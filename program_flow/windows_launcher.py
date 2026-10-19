"""Windows entry point: a packaged local server with a notification-area icon.

The release installer bundles Python. No interpreter, WSL, or command prompt is
needed on the computer running Program Flow. Keys and data stay in LocalAppData.
"""
import argparse
import contextlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
import webbrowser


HOST = '127.0.0.1'


def data_directory(environ=None):
    env = os.environ if environ is None else environ
    local = env.get('LOCALAPPDATA')
    if not local:
        raise RuntimeError('Windows 사용자 데이터 폴더(LOCALAPPDATA)를 찾지 못했습니다.')
    return Path(local) / 'ProgramFlow'


def close_logging():
    logger = logging.getLogger('program_flow')
    for handler in logger.handlers[:]:
        if getattr(handler, '_program_flow', False):
            logger.removeHandler(handler)
            handler.close()


def configure_logging(data_dir):
    close_logging()
    folder = Path(data_dir) / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / 'program-flow.log', maxBytes=2_000_000,
                                  backupCount=3, encoding='utf-8')
    handler._program_flow = True
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logger = logging.getLogger('program_flow')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    logger.info('Program Flow starting; version=0.2.6; source=%s', __file__)


def start_server(data_dir, application=None):
    # app.py constructs the application when imported. Set its data location FIRST.
    os.environ['PROGRAM_FLOW_DATA_DIR'] = str(data_dir)
    configure_logging(data_dir)
    if application is None:
        from .app import app as application
    import uvicorn

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    port_path = Path(data_dir) / 'server-port.json'
    preferred = 0
    try:
        preferred = int(json.loads(port_path.read_text(encoding='utf-8'))['port'])
        if not 1 <= preferred <= 65535: preferred = 0
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        listener.bind((HOST, preferred))
    except OSError:
        if not preferred: raise
        logging.getLogger('program_flow').warning('Previous port unavailable; choosing another port')
        listener.bind((HOST, 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    config = uvicorn.Config(application, host=HOST, port=port, loop='asyncio', http='h11',
                            lifespan='on', log_level='warning', access_log=False,
                            log_config=None)
    server = uvicorn.Server(config)
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]},
                              name='program-flow-local-server', daemon=True)
    worker.start()
    for _ in range(100):
        if server.started:
            port_path.write_text(json.dumps({'port':port}), encoding='utf-8')
            logging.getLogger('program_flow').info('Local server ready; port=%d', port)
            return server, worker, listener, f'http://{HOST}:{port}'
        if not worker.is_alive():
            listener.close()
            raise RuntimeError('화면 서버를 시작하지 못했습니다.')
        time.sleep(0.1)
    server.should_exit = True
    worker.join(timeout=5)
    listener.close()
    raise RuntimeError('화면 서버 시작 시간이 초과되었습니다.')


def stop_server(server, worker, listener):
    server.should_exit = True
    worker.join(timeout=8)
    listener.close()
    logging.getLogger('program_flow').info('Local server stopped')
    close_logging()


def smoke_test(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    server, worker, listener, url = start_server(data_dir)
    try:
        with urllib.request.urlopen(url + '/api/health', timeout=5) as response:
            health = response.status
        with urllib.request.urlopen(url + '/', timeout=5) as response:
            html = response.read().decode('utf-8')
        with urllib.request.urlopen(url + '/static/app.js', timeout=5) as response:
            script = response.read().decode('utf-8')
        session_request = urllib.request.Request(url + '/api/session', data=b'',
                                                  method='POST', headers={'Origin': url})
        with urllib.request.urlopen(session_request, timeout=5) as response:
            session = json.load(response)
        tray_loaded = None
        if sys.platform == 'win32':
            from pystray import Icon
            from PIL import Image
            tray_loaded = callable(Icon) and callable(Image.open)
        result = {'health': health, 'source_file': str(Path(__file__).resolve()),
                'app_source_file': str(Path(sys.modules['program_flow.app'].__file__).resolve()),
                'stock_search_ui': 'id="stock-suggestions"' in html and
                '/api/stocks/search?q=' in script, 'new_profile_has_keys': session['has_keys'],
                'manual_buttons_removed': 'id="load-btn"' not in html and 'id="refresh-btn"' not in html,
                'background_worker_running': any(thread.name == 'program-flow-collector' and
                                                 thread.is_alive() for thread in threading.enumerate()),
                'bound_host': HOST, 'tray_loaded': tray_loaded, 'launcher_window': False}
        (data_dir / 'smoke-result.json').write_text(json.dumps(result), encoding='utf-8')
        return result
    finally:
        stop_server(server, worker, listener)

def collector_smoke_test(data_dir, collect_interval=0.25):
    """Only with --collector-smoke-test and an EMPTY data dir. No Kiwoom network calls."""
    from unittest.mock import patch

    data_dir.mkdir(parents=True, exist_ok=True)
    # app.py creates a global app on import: isolate it before importing.
    os.environ['PROGRAM_FLOW_DATA_DIR'] = str(data_dir)
    from . import app as app_module
    sequence = {'count': 0, 'events': []}

    def fake_market(_token, _code, _date, market):
        sequence['count'] += 1
        sequence['events'].append({'market': market, 'at': time.monotonic()})
        minute = min(sequence['count'], 59)
        return [{'tm': f'09{minute:02d}00', 'buy_amt': minute,
                 'sell_amt': 0, 'net_amt': minute}]

    def request(url, path, body=None, cookie=''):
        headers = {'Origin': url, 'Content-Type': 'application/json'}
        if cookie: headers['Cookie'] = cookie
        req = urllib.request.Request(url + path,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     method='POST' if body is not None else 'GET', headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            return json.load(response), response.headers.get('Set-Cookie', '').split(';', 1)[0]

    # The real HTTP server, database, encryption, and Windows EXE run as usual;
    # only remote Kiwoom responses and the 60-second throttle are synthetic.
    with patch.object(app_module, 'access_token', return_value=('synthetic', time.time()+3600)), \
         patch.object(app_module, 'fetch_stock_list',
                      side_effect=lambda _token, market: [('005930','삼성전자')] if market == '0' else []), \
         patch.object(app_module, 'fetch_market_rows', side_effect=fake_market):
        first = app_module.create_app(data_dir, collect_interval=collect_interval)
        server = None
        try:
            with patch.object(first.state.store, 'last_sync', return_value=None) if collect_interval < 1 else contextlib.nullcontext():
                server, worker, listener, url = start_server(data_dir, first)
                _, cookie = request(url, '/api/session', {})
                request(url, '/api/keys', {'app_key': 'x'*32, 'app_secret': 'y'*32}, cookie)
                request(url, '/api/watch', {'code': '005930', 'name': '삼성전자'}, cookie)
                # Do not make ANY further browser/API requests while waiting.
                after_close = sequence['count']
                deadline = time.monotonic() + max(6, collect_interval * 2 + 20)
                while sequence['count'] < after_close + 4 and time.monotonic() < deadline:
                    time.sleep(0.05)
                continued = sequence['count'] >= after_close + 4
        finally:
            if server is not None:
                stop_server(server, worker, listener)
            first.state.store.conn.close()

        before_restart = sequence['count']
        closed_events = sequence['events'][after_close:before_restart]
        krx_times = [event['at'] for event in closed_events if event['market'] == 'KRX']
        minute_gaps = [round(b - a, 3) for a, b in zip(krx_times, krx_times[1:])]
        minute_verified = any(55 <= gap <= 75 for gap in minute_gaps) if collect_interval >= 1 else None
        second = app_module.create_app(data_dir, collect_interval=collect_interval)
        server = None
        try:
            with patch.object(second.state.store, 'last_sync', return_value=None) if collect_interval < 1 else contextlib.nullcontext():
                server, worker, listener, _ = start_server(data_dir, second)
                deadline = time.monotonic() + max(6, collect_interval + 15)
                while sequence['count'] < before_restart + 2 and time.monotonic() < deadline:
                    time.sleep(0.05)
                resumed = sequence['count'] >= before_restart + 2
                saved = second.state.store.conn.execute(
                    "SELECT count(*) FROM minute_rows WHERE stock_code='005930'").fetchone()[0]
        finally:
            if server is not None:
                stop_server(server, worker, listener)
            second.state.store.conn.close()

    result = {'synthetic_only': True, 'collected_after_browser_closed': continued,
              'collected_after_restart': resumed, 'stored_rows': saved,
              'collector_interval_seconds': collect_interval,
              'closed_browser_krx_gaps_seconds': minute_gaps,
              'minute_interval_verified': minute_verified}
    (data_dir / 'collector-result.json').write_text(json.dumps(result), encoding='utf-8')
    if not continued or not resumed or saved < 4 or (collect_interval >= 1 and not minute_verified):
        raise RuntimeError('synthetic background collection did not persist across browser close/restart')
    return result


def message(text):
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, 'Program Flow', 0x00000010)


def run_tray(url, ui_smoke=False):
    """Keep collection running without a launcher window; offer open/exit in the tray."""
    from PIL import Image
    import pystray

    def open_browser(_icon=None, _item=None):
        webbrowser.open(url)

    def exit_app(icon, _item):
        icon.stop()

    def ready(icon):
        icon.visible = True
        if ui_smoke:
            timer = threading.Timer(1.2, icon.stop)
            timer.daemon = True
            timer.start()
        else:
            open_browser()

    image_path = Path(__file__).resolve().parent / 'static' / 'icon-192.png'
    with Image.open(image_path) as image:
        icon = pystray.Icon('ProgramFlow', image.copy(), 'Program Flow', menu=pystray.Menu(
            pystray.MenuItem('프로그램 화면 열기', open_browser, default=True),
            pystray.MenuItem('종료', exit_app),
        ))
    try:
        icon.run(setup=ready)
    finally:
        icon.stop()


def run_desktop(ui_smoke=False):
    # Avoid a second background server for a double-clicked shortcut.
    import msvcrt
    data_dir = data_directory()
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / 'instance.lock'
    # Windows denies reads of bytes locked by another process. Acquire the
    # lock before touching its contents, including when reopening the app.
    with lock_path.open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            try:
                state = json.loads((data_dir / 'instance.json').read_text(encoding='utf-8'))
                port = int(state['port'])
                if not 1 <= port <= 65535:
                    raise ValueError('invalid port')
                url = f'http://{HOST}:{port}'
                with urllib.request.urlopen(url + '/api/health', timeout=2) as response:
                    if response.status != 200:
                        raise ValueError('not running')
                webbrowser.open(url)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                message('이미 실행 중입니다. 잠시 후 바로가기를 다시 실행하거나 작업표시줄 알림 영역의 Program Flow 아이콘을 확인해 주세요.')
            return
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b'1')
            lock.flush()
        state_path = data_dir / 'instance.json'
        server = worker = listener = None
        try:
            server, worker, listener, url = start_server(data_dir)
            state_path.write_text(json.dumps({'port': listener.getsockname()[1]}),
                                  encoding='utf-8')
            run_tray(url, ui_smoke=ui_smoke)
        finally:
            if server is not None:
                stop_server(server, worker, listener)
            state_path.unlink(missing_ok=True)
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Program Flow Windows launcher')
    parser.add_argument('--smoke-test', action='store_true', help='run isolated local check and exit')
    parser.add_argument('--collector-smoke-test', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--collector-minute-test', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--ui-smoke-test', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--data-dir', type=Path, help='test-only empty data directory')
    args = parser.parse_args(argv)
    if sum((args.smoke_test, args.ui_smoke_test, args.collector_smoke_test, args.collector_minute_test)) > 1:
        parser.error('choose one smoke test')
    if args.data_dir and not (args.smoke_test or args.collector_smoke_test or args.collector_minute_test):
        parser.error('--data-dir is only supported with isolated smoke tests')
    if (args.collector_smoke_test or args.collector_minute_test) and args.data_dir is None:
        parser.error('collector tests require an explicit empty --data-dir')
    if args.smoke_test or args.collector_smoke_test or args.collector_minute_test:
        data_dir = args.data_dir or data_directory()
        if data_dir.exists() and any(data_dir.iterdir()):
            parser.error('smoke-test data directory must be empty')
        result = (collector_smoke_test(data_dir, collect_interval=60) if args.collector_minute_test else
                  collector_smoke_test(data_dir) if args.collector_smoke_test else smoke_test(data_dir))
        if sys.stdout is not None:
            print(json.dumps(result))
        return 0
    if sys.platform != 'win32':
        parser.error('desktop mode requires Windows')
    try:
        run_desktop(ui_smoke=args.ui_smoke_test)
    except Exception:
        if not logging.getLogger('program_flow').handlers:
            configure_logging(data_directory())
        logging.getLogger('program_flow').exception('Launcher failed')
        message('실행에 실패했습니다. 설치 상태와 사용 권한을 확인해 주세요.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
