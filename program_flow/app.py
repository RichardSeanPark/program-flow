"""Browser-isolated, read-only program-flow app without account login."""
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import logging
import mimetypes
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .kiwoom import KiwoomAuthError, KiwoomError, access_token, fetch_market_rows, fetch_stock_list
from .series import build_sessions
from .store import Store

logger = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / 'static'
mimetypes.add_type('image/webp', '.webp')
CODE_RE = re.compile(r'^\d{6}$')
KST = ZoneInfo('Asia/Seoul')


def today_kst():
    return datetime.now(KST).date()


def secret_file(directory, name, make):
    path = directory / name
    if not path.exists():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as file:
                file.write(make())
        except FileExistsError:
            pass
    return path.read_bytes().strip()


def create_app(data_dir=None, master_key=None, collect_interval=60):
    root = Path(data_dir or os.environ.get('PROGRAM_FLOW_DATA_DIR') or
                Path.home() / '.local/share/program-flow-web').expanduser()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt' and root.stat().st_mode & 0o077:
        root.chmod(0o700)
        if root.stat().st_mode & 0o077:
            raise RuntimeError('private data directory must have permissions 0700 (use WSL ext4)')
    key = master_key or secret_file(root, 'master.key', Fernet.generate_key)
    cipher = Fernet(key)
    store = Store(str(root / 'program.db'))

    @asynccontextmanager
    async def lifespan(_app):
        logger.info('Application starting; saved_profiles=%d', len(store.keyed_profiles()))
        previous = getattr(app.state, 'collector_thread', None)
        if previous is not None and previous.is_alive():
            raise RuntimeError('이전 자동 수집 작업이 아직 종료되지 않았습니다')
        stopping.clear()
        wake.clear()
        worker = threading.Thread(target=background_collect, name='program-flow-collector', daemon=True)
        app.state.collector_thread = worker
        worker.start()
        try:
            yield
        finally:
            stopping.set()
            wake.set()
            worker.join(timeout=30)
            logger.info('Application collector stopped; alive=%s', worker.is_alive())

    app = FastAPI(title='Program Flow', docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.store = store
    app.mount('/static', StaticFiles(directory=STATIC), name='static')

    @app.middleware('http')
    async def security_headers(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            logger.exception('Unhandled HTTP error; method=%s path=%s', request.method, request.url.path)
            raise
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    tokens = {}
    catalogs = {}
    locks = {}
    locks_guard = threading.Lock()
    stopping = threading.Event()
    wake = threading.Event()
    collection_errors = {}
    collection_progress = {}

    def user_lock(user):
        with locks_guard:
            return locks.setdefault(('token', user), threading.RLock())

    def token_for_user(user):
        # The official expires_dt is checked before every use; one thread renews per profile.
        with user_lock(user):
            cached = tokens.get(user)
            if cached and cached[1] > time.time() + 300:
                return cached[0]
            record = store.user(user)
            if not record or not record['app_key'] or not record['app_secret']:
                raise KiwoomError('키움 API 키를 먼저 등록하세요')
            try:
                app_key = cipher.decrypt(record['app_key']).decode()
                app_secret = cipher.decrypt(record['app_secret']).decode()
            except (InvalidToken, UnicodeDecodeError) as exc:
                raise KiwoomError('저장된 키를 읽을 수 없습니다. 다시 등록하세요') from exc
            # Never keep an expired token after a failed renewal.
            tokens.pop(user, None)
            try:
                tokens[user] = access_token(app_key, app_secret)
            except KiwoomError as exc:
                logger.warning('Token renewal failed: %s', exc)
                raise
            logger.info('Token renewed successfully')
            return tokens[user][0]

    def call_with_token(user, operation, *args):
        for attempt in range(2):
            token = token_for_user(user)
            try:
                return operation(token, *args)
            except KiwoomAuthError:
                logger.warning('Upstream rejected token; operation=%s attempt=%d', getattr(operation, '__name__', 'kiwoom'), attempt + 1)
                with user_lock(user):
                    cached = tokens.get(user)
                    if cached and cached[0] == token:
                        tokens.pop(user, None)
                if attempt:
                    raise

    class Keys(BaseModel):
        app_key: str
        app_secret: str

    class Target(BaseModel):
        code: str
        date: str
        force: bool = False

    class Watch(BaseModel):
        code: str
        name: str

    def check_origin(request: Request):
        origin = request.headers.get('origin', '')
        parsed = urlsplit(origin)
        if not origin or parsed.netloc.lower() != request.headers.get('host', '').lower() or parsed.scheme not in ('https', 'http'):
            raise HTTPException(403, '다른 출처의 요청은 허용하지 않습니다')
        if request.headers.get('sec-fetch-site', 'same-origin') not in ('same-origin', 'none'):
            raise HTTPException(403, '다른 사이트의 요청은 허용하지 않습니다')

    def auth(request: Request):
        token = request.cookies.get('program_browser', '')
        user = store.session_user(hashlib.sha256(token.encode()).hexdigest()) if token else None
        if not user: raise HTTPException(401, '브라우저 연결이 필요합니다')
        return user

    def cookie(response, user, request, token=None):
        if token is None:
            token = secrets.token_urlsafe(40)
            store.create_session(hashlib.sha256(token.encode()).hexdigest(), user)
        else:
            store.renew_session(hashlib.sha256(token.encode()).hexdigest())
        secure = os.environ.get('PROGRAM_FLOW_SECURE_COOKIE') == '1' or request.url.scheme == 'https'
        response.set_cookie('program_browser', token, max_age=31536000, httponly=True,
                            secure=secure, samesite='strict', path='/')

    def validate_target(code, date):
        if not CODE_RE.fullmatch(code): raise HTTPException(400, '6자리 종목코드가 필요합니다')
        try:
            day = datetime.strptime(date, '%Y%m%d').date()
        except ValueError:
            raise HTTPException(400, '날짜는 YYYYMMDD 형식이어야 합니다')
        if day > today_kst(): raise HTTPException(400, '미래 날짜는 조회할 수 없습니다')

    @app.get('/')
    def index(): return FileResponse(STATIC / 'index.html')

    @app.get('/manifest.webmanifest')
    def manifest(): return FileResponse(STATIC / 'manifest.webmanifest', media_type='application/manifest+json')

    @app.get('/service-worker.js')
    def sw(): return FileResponse(STATIC / 'service-worker.js', media_type='application/javascript')

    @app.get('/api/health')
    def health(): return {'ok': True}

    @app.post('/api/session')
    def browser_session(response: Response, request: Request):
        check_origin(request)
        token = request.cookies.get('program_browser', '')
        user = store.session_user(hashlib.sha256(token.encode()).hexdigest()) if token else None
        if not user:
            user = secrets.token_urlsafe(24)
            store.create_profile(user)
            cookie(response, user, request)
        else:
            cookie(response, user, request, token)
        has_keys = bool(store.user(user)['app_key'])
        token_error = None
        if has_keys:
            try:
                token_for_user(user)
            except KiwoomError as exc:
                token_error = str(exc)
        return {'has_keys': has_keys, 'token_error': token_error}

    @app.post('/api/reconnect')
    def reconnect(request: Request, user=Depends(auth)):
        check_origin(request)
        logger.info('Browser requested connection renewal')
        try:
            with user_lock(user):
                tokens.pop(user, None)
                token_for_user(user)
        except KiwoomError as exc:
            raise HTTPException(502, str(exc))
        wake.set()
        return {'ok': True}

    @app.get('/api/me')
    def me(user=Depends(auth)):
        return {'has_keys': bool(store.user(user)['app_key'])}

    @app.post('/api/keys')
    def set_keys(data: Keys, request: Request, user=Depends(auth)):
        check_origin(request)
        if not (8 <= len(data.app_key) <= 256 and 8 <= len(data.app_secret) <= 256):
            raise HTTPException(400, '키 형식을 확인하세요')
        with user_lock(user):
            try:
                token = access_token(data.app_key, data.app_secret)
            except KiwoomError as exc:
                logger.warning('API key verification failed: %s', exc)
                raise HTTPException(502, str(exc))
            store.set_keys(user, cipher.encrypt(data.app_key.encode()), cipher.encrypt(data.app_secret.encode()))
            tokens[user] = token
            catalogs.pop(user, None)
        return {'ok': True}

    @app.delete('/api/keys')
    def delete_keys(request: Request, user=Depends(auth)):
        check_origin(request)
        with user_lock(user):
            store.clear_keys(user)
            tokens.pop(user, None)
            catalogs.pop(user, None)
            collection_errors.pop(user, None)
        return {'ok': True}

    def stock_catalog(user):
        if not store.user(user)['app_key']:
            raise HTTPException(409, '키움 API 키를 먼저 등록하세요')
        try:
            with user_lock(user):
                token = token_for_user(user)
                cached = catalogs.get(user)
                if cached and time.time() - cached[0] < 21600:
                    return cached[1]
                listings = []
                for market in ('0', '10'):
                    listings.extend(call_with_token(user, fetch_stock_list, market))
                    time.sleep(0.22)
                catalogs[user] = (time.time(), listings)
                return listings
        except KiwoomError as exc:
            raise HTTPException(502, str(exc))

    @app.get('/api/stocks/search')
    def search_stocks(q: str, user=Depends(auth)):
        query = q.strip()
        if not 1 <= len(query) <= 80:
            raise HTTPException(400, '검색어를 1~80자로 입력하세요')
        needle = query.casefold()
        matches = {code: official for code, official in stock_catalog(user)
                   if needle in official.casefold()}
        ordered = sorted(matches.items(), key=lambda pair: (
            pair[1].casefold() != needle,
            not pair[1].casefold().startswith(needle),
            pair[1].casefold(), pair[0]))
        return {'items': [{'code': code, 'name': official} for code, official in ordered[:20]],
                'has_more': len(ordered) > 20}

    @app.get('/api/stocks/resolve')
    def resolve_stock(name: str, user=Depends(auth)):
        query = name.strip()
        if not 1 <= len(query) <= 80:
            raise HTTPException(400, '종목명을 1~80자로 입력하세요')
        matches = {code: official for code, official in stock_catalog(user)
                   if official.casefold() == query.casefold()}
        if not matches:
            raise HTTPException(404, '일치하는 종목명이 없습니다. 한국거래소 상장 종목명을 확인하세요')
        if len(matches) != 1:
            raise HTTPException(409, '같은 이름의 종목이 여러 개입니다. 종목명을 더 구체적으로 확인하세요')
        code, official = next(iter(matches.items()))
        return {'code': code, 'name': official}

    @app.get('/api/watch')
    def get_watch(user=Depends(auth)):
        return {'watch': store.watch(user), 'last_error': collection_errors.get(user),
                'progress': collection_progress.get(user)}

    @app.post('/api/watch')
    def set_watch(target: Watch, request: Request, user=Depends(auth)):
        check_origin(request)
        validate_target(target.code, today_kst().strftime('%Y%m%d'))
        if not 1 <= len(target.name) <= 80:
            raise HTTPException(400, '종목명을 확인하세요')
        if not any(code == target.code and name == target.name for code, name in stock_catalog(user)):
            raise HTTPException(400, '종목코드와 공식 종목명이 일치하지 않습니다')
        logger.info('Watch selected; code=%s', target.code)
        store.set_watch(user, target.code, target.name)
        wake.set()
        date = today_kst().strftime('%Y%m%d')
        try:
            result = sync_target(user, target.code, date)
        except HTTPException as exc:
            # The selection succeeded; keep it for the next background retry.
            collection_errors[user] = str(exc.detail)
            result = {'updated': [], 'data': data(target.code, date, user)}
        return {'watch': store.watch(user), 'result': result,
                'last_error': collection_errors.get(user)}

    @app.get('/api/data')
    def data(code: str, date: str, user=Depends(auth)):
        validate_target(code, date)
        rows = store.rows(user, code, date)
        return {'code': code, 'date': date, 'rows': rows, 'sessions': build_sessions(rows),
                'synced_at': {market: store.last_sync(user, code, date, market) for market in ('KRX','NXT')}}

    @app.post('/api/sync')
    def sync(target: Target, request: Request, user=Depends(auth)):
        check_origin(request)
        validate_target(target.code, target.date)
        return sync_target(user, target.code, target.date, target.force)

    def sync_target(user, code, date, force=False):
        record = store.user(user)
        if not record['app_key']: raise HTTPException(409, '키움 API 키를 먼저 등록하세요')
        with locks_guard:
            lock = locks.setdefault((user,code,date), threading.Lock())
        if not lock.acquire(blocking=False):
            return {'updated': [], 'data': data(code, date, user)}
        try:
            token = token_for_user(user)
            updated = []
            errors = []
            for market in ('KRX', 'NXT'):
                last = store.last_sync(user, code, date, market)
                current = date == today_kst().strftime('%Y%m%d')
                # A market sampled later in the previous round can otherwise
                # miss every other 60-second tick due to timestamp rounding.
                if not force and last and (not current or time.time()-last < 59):
                    continue
                try:
                    started = time.monotonic()
                    collection_progress[user] = {'code':code, 'date':date, 'market':market, 'state':'collecting'}
                    logger.info('Collection started; code=%s date=%s market=%s', code, date, market)
                    rows = call_with_token(user, fetch_market_rows, code, date, market)
                    store.save_rows(user, code, date, market, rows)
                    updated.append(market)
                    logger.info('Collection saved; code=%s date=%s market=%s raw_rows=%d seconds=%.2f', code, date, market, len(rows), time.monotonic()-started)
                except KiwoomError as exc:
                    logger.warning('Collection failed; code=%s date=%s market=%s error=%s', code, date, market, exc)
                    errors.append(f'{market} 수집 실패: {exc}')
                time.sleep(0.22)
            if errors:
                collection_progress[user] = {'code':code, 'date':date, 'state':'error'}
                raise HTTPException(502, ' / '.join(errors))
            collection_progress[user] = {'code':code, 'date':date, 'state':'ready'}
            collection_errors.pop(user, None)
            return {'updated': updated, 'data': data(code, date, user)}
        except KiwoomError as exc:
            raise HTTPException(502, str(exc))
        finally:
            lock.release()

    def background_collect():
        # Network authentication must not block local server startup.
        for user in store.keyed_profiles():
            if stopping.is_set():
                return
            try:
                token_for_user(user)
            except KiwoomError:
                pass  # Retry at the next collection or browser reconnect.
        first_pass = True
        while not stopping.is_set():
            started = time.monotonic()
            wake.clear()
            date = today_kst().strftime('%Y%m%d')
            for user, code in store.active_watches():
                if stopping.is_set(): break
                try:
                    sync_target(user, code, date, force=first_pass)
                except HTTPException as exc:
                    collection_errors[user] = str(exc.detail)
                except Exception:
                    logger.exception('Unexpected background collection error; code=%s date=%s', code, date)
                    # Do not kill the collector because one account or network call failed.
                    collection_errors[user] = '자동 수집에 실패했습니다. 연결 상태를 확인하세요.'
            first_pass = False
            wake.wait(max(0, collect_interval-(time.monotonic()-started)))

    return app


app = create_app()
