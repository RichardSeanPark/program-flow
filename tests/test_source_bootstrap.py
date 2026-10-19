import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SourceBootstrapTests(unittest.TestCase):
    def test_launches_source_beside_entry_and_observes_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'windows_main.py').write_bytes((ROOT / 'windows_main.py').read_bytes())
            package = root / 'program_flow'
            package.mkdir()
            (package / 'static').mkdir()
            for name in ['__init__.py', 'app.py', 'kiwoom.py', 'store.py', 'series.py',
                         'static/index.html', 'static/app.js']:
                (package / name).write_text('', encoding='utf-8')
            for value in (37, 42):
                (package / 'windows_launcher.py').write_text(
                    f'def main():\n    return {value}\n', encoding='utf-8')
                # Same-length edits within a second must not use cached bytecode.
                run = subprocess.run([sys.executable, '-B', str(root / 'windows_main.py')],
                                     capture_output=True, timeout=10)
                self.assertEqual(run.returncode, value, run.stderr)

    def test_missing_source_fails_without_using_installed_package(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / 'windows_main.py'
            entry.write_bytes((ROOT / 'windows_main.py').read_bytes())
            run = subprocess.run([sys.executable, str(entry)], capture_output=True, timeout=10)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn(b'RuntimeError', run.stderr)


if __name__ == '__main__':
    unittest.main()
