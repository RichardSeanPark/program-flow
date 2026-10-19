import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from program_flow import windows_launcher


class WindowsLauncherTests(unittest.TestCase):
    def test_data_directory_is_per_user_and_not_under_install_tree(self):
        with tempfile.TemporaryDirectory() as root:
            env = {'LOCALAPPDATA': root}
            self.assertEqual(windows_launcher.data_directory(env), Path(root) / 'ProgramFlow')
            self.assertNotEqual(windows_launcher.data_directory(env), Path.cwd())

    def test_smoke_starts_local_server_and_serves_bundled_ui_without_api_key(self):
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run(
                [sys.executable, '-m', 'program_flow.windows_launcher', '--smoke-test', '--data-dir', root],
                capture_output=True, text=True, timeout=35, env=os.environ.copy())
            self.assertEqual(result.returncode, 0, result.stderr)
            outcome = json.loads(result.stdout)
            self.assertEqual(json.loads((Path(root) / 'smoke-result.json').read_text(encoding='utf-8')), outcome)
            self.assertEqual(outcome['health'], 200)
            self.assertTrue(outcome['stock_search_ui'])
            self.assertTrue(outcome['background_worker_running'])
            self.assertTrue(outcome['manual_buttons_removed'])
            self.assertEqual(outcome['new_profile_has_keys'], False)
            self.assertEqual(outcome['bound_host'], '127.0.0.1')
            self.assertTrue((Path(root) / 'program.db').is_file())
            self.assertTrue((Path(root) / 'master.key').is_file())
            log=(Path(root)/'logs'/'program-flow.log').read_text(encoding='utf-8')
            self.assertIn('Local server ready',log)
            self.assertIn('Local server stopped',log)
            self.assertNotIn('app_secret',log)

    def test_windowless_smoke_still_returns_success_without_stdout(self):
        with tempfile.TemporaryDirectory() as root:
            code = ('import sys; sys.stdout=None; from program_flow.windows_launcher import main; '
                    'raise SystemExit(main(["--smoke-test", "--data-dir", sys.argv[1]]))')
            result = subprocess.run([sys.executable, '-c', code, root], capture_output=True,
                                    text=True, timeout=35, env=os.environ.copy())
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_packaged_collector_smoke_uses_synthetic_market_and_no_browser(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / 'collection'
            env = os.environ.copy()
            env['LOCALAPPDATA'] = str(Path(root) / 'other-local-data')
            env.pop('PROGRAM_FLOW_DATA_DIR', None)
            run = subprocess.run([sys.executable, '-m', 'program_flow.windows_launcher',
                                  '--collector-smoke-test', '--data-dir', str(data)],
                                 env=env, capture_output=True, text=True, timeout=35)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertTrue(result['synthetic_only'])
            self.assertTrue(result['collected_after_browser_closed'])
            self.assertTrue(result['collected_after_restart'])
            self.assertGreaterEqual(result['stored_rows'], 4)
            self.assertTrue((data / 'collector-result.json').is_file())
            self.assertFalse((Path(root) / 'other-local-data' / 'ProgramFlow').exists())

    def test_collector_smoke_refuses_implicit_user_data_directory(self):
        with tempfile.TemporaryDirectory() as root:
            env = os.environ.copy()
            env['LOCALAPPDATA'] = root
            run = subprocess.run([sys.executable, '-m', 'program_flow.windows_launcher',
                                  '--collector-smoke-test'], env=env, capture_output=True,
                                 text=True, timeout=10)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((Path(root) / 'ProgramFlow').exists())

    def test_collector_minute_test_runs_with_real_interval_only_in_isolated_dir(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / 'empty'
            with patch.object(windows_launcher, 'collector_smoke_test', return_value={}), \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(windows_launcher.main(['--collector-minute-test', '--data-dir', str(data)]), 0)
                windows_launcher.collector_smoke_test.assert_called_once_with(data, collect_interval=60)
                self.assertEqual(json.loads(output.getvalue()), {})
            with self.assertRaises(SystemExit):
                windows_launcher.main(['--collector-minute-test'])

    def test_collector_smoke_closes_second_database_on_server_start_failure(self):
        from program_flow import app as app_module
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ):
            created = []
            real_create, real_start = app_module.create_app, windows_launcher.start_server
            starts = []
            def create(*args, **kwargs):
                app = real_create(*args, **kwargs)
                created.append(app)
                return app
            def start(*args, **kwargs):
                starts.append(1)
                if len(starts) == 2:
                    raise OSError('synthetic second start failure')
                return real_start(*args, **kwargs)
            with patch.object(app_module, 'create_app', side_effect=create), \
                 patch.object(windows_launcher, 'start_server', side_effect=start):
                with self.assertRaisesRegex(OSError, 'synthetic second start failure'):
                    windows_launcher.collector_smoke_test(Path(root))
            self.assertEqual(len(created), 2)
            with self.assertRaises(Exception):
                created[-1].state.store.conn.execute('SELECT 1')

    def test_tray_opens_browser_and_exit_menu_stops_without_launcher_window(self):
        from types import SimpleNamespace
        events = []
        class Image:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def copy(self): return self
        class Icon:
            def __init__(self, _name, _image, _title, menu):
                self.menu = menu
            def run(self, setup):
                setup(self)
                self.menu[0][1](self, None)
                self.menu[1][1](self, None)
            def stop(self): events.append('stop')
        fake_tray = SimpleNamespace(Icon=Icon, Menu=lambda *items:items,
                                   MenuItem=lambda label, action, **_: (label, action))
        fake_pil = SimpleNamespace(Image=SimpleNamespace(open=lambda _:Image()))
        with patch.dict(sys.modules, {'pystray':fake_tray, 'PIL':fake_pil}), \
             patch.object(windows_launcher.webbrowser, 'open') as browser:
            windows_launcher.run_tray('http://127.0.0.1:12345')
            self.assertEqual(browser.call_count, 2)
            browser.assert_called_with('http://127.0.0.1:12345')
        self.assertEqual(events, ['stop', 'stop'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows byte-range locks')
    def test_reopen_while_running_opens_existing_server_without_reading_locked_byte(self):
        with tempfile.TemporaryDirectory() as root:
            env = os.environ.copy()
            env['LOCALAPPDATA'] = root
            env['PYTHONUTF8'] = '1'
            ready, stop = Path(root) / 'ready', Path(root) / 'stop'
            code = ("import time; from pathlib import Path; "
                    "from program_flow import windows_launcher as w; "
                    f"ready=Path({str(ready)!r}); stop=Path({str(stop)!r}); "
                    "exec('def tray(url, **kwargs):\\n ready.write_text(url)\\n while not stop.exists(): time.sleep(0.02)'); "
                    "w.run_tray=tray; raise SystemExit(w.main([]))")
            first = subprocess.Popen([sys.executable, '-c', code], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 15
                while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), 'first server failed to start')
                original_state = (Path(root) / 'ProgramFlow' / 'instance.json').read_bytes()
                code = ("from program_flow import windows_launcher as w; "
                        "w.webbrowser.open=lambda url: print('REOPENED',url); "
                        "w.message=lambda text: print('ERROR_DIALOG',text); "
                        "raise SystemExit(w.main([]))")
                second = subprocess.run([sys.executable, '-c', code], env=env,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
                self.assertIn('REOPENED ' + ready.read_text(), second.stdout)
                self.assertNotIn('ERROR_DIALOG', second.stdout)
                self.assertIsNone(first.poll())
                self.assertEqual((Path(root) / 'ProgramFlow' / 'instance.json').read_bytes(), original_state)
            finally:
                stop.touch()
                try:
                    first.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    first.kill()
                    first.communicate()
            self.assertEqual(first.returncode, 0)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows tray lifecycle')
    def test_tray_exit_closes_server_and_keeps_user_data_for_restart(self):
        with tempfile.TemporaryDirectory() as root:
            env = os.environ.copy()
            env['LOCALAPPDATA'] = root
            data_dir = Path(root) / 'ProgramFlow'
            for attempt in range(2):
                result = subprocess.run([sys.executable, '-m', 'program_flow.windows_launcher',
                                         '--ui-smoke-test'], env=env, capture_output=True,
                                        text=True, timeout=35)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((data_dir / 'program.db').is_file())
                self.assertFalse((data_dir / 'instance.json').exists())
                key = (data_dir / 'master.key').read_bytes()
                if attempt:
                    self.assertEqual(key, previous_key)
                previous_key = key


if __name__ == '__main__':
    unittest.main()
