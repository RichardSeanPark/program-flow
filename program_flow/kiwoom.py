"""Kiwoom ka90008 read-only market data client (KRW millions -> KRW)."""
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation
import time
import logging
import re
import httpx

BASE = 'https://api.kiwoom.com'
logger = logging.getLogger(__name__)


class KiwoomError(RuntimeError):
    pass


class KiwoomAuthError(KiwoomError):
    """An upstream authentication rejection that can be retried with a fresh token."""


class KiwoomRateLimitError(KiwoomError):
    pass


def check_payload(payload, api):
    if not isinstance(payload, dict):
        raise KiwoomError(f'{api} 응답 형식 오류')
    try:
        code = str(int(payload.get('return_code')))
    except (ValueError, TypeError):
        code = ''
    if code == '0':
        return
    message = str(payload.get('return_msg', 'unknown'))[:120]
    embedded = {part for pair in re.findall(r'\[(\d+):|CODE=(\d+)', message) for part in pair if part}
    if code in {'8003','8005','8006','8009','8015','8016'} or embedded & {'8003','8005','8006','8009','8015','8016'}:
        raise KiwoomAuthError(f'{api} 인증 토큰 오류: {message}')
    if code in {'1700','1701','1702'} or embedded & {'1700','1701','1702'}:
        raise KiwoomRateLimitError(f'{api} 요청 제한: {message}')
    raise KiwoomError(f'{api} 오류: {message}')


def request_page(client, url, body, headers, api):
    """Retry the same read-only continuation page; never discard earlier pages on a transient reset."""
    for attempt in range(3):
        status = None
        try:
            response = client.post(url, json=body, headers=headers, timeout=15)
            status = getattr(response, 'status_code', 200)
            if status in (401, 403):
                raise KiwoomAuthError('키움 인증이 거부되었습니다. 토큰을 다시 발급합니다.')
            response.raise_for_status()
            payload = response.json()
            check_payload(payload, api)
            return payload, response.headers
        except KiwoomRateLimitError:
            logger.warning('API rate limited; api=%s attempt=%d/3', api, attempt+1)
            if attempt == 2:
                raise
        except (httpx.HTTPError, ValueError) as exc:
            retryable = not isinstance(exc, httpx.HTTPStatusError) or status in (429,500,502,503,504)
            logger.warning('API page request failed; api=%s attempt=%d/3 error_type=%s http_status=%s retry=%s',
                           api, attempt+1, type(exc).__name__, status, retryable and attempt<2)
            if not retryable or attempt == 2:
                raise KiwoomError(f'{api} 연결 또는 응답 오류: 자동 재시도 후에도 응답을 받지 못했습니다') from exc
        time.sleep(0.6 * 2**attempt)


def parse_amount(value):
    text = str(value).strip().replace(',', '').replace(' ', '')
    while text.startswith('--'):
        text = text[1:]
    try:
        value = Decimal(text)
        if not value.is_finite(): raise ValueError('non-finite')
        return int(value * 1_000_000)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('invalid Kiwoom amount') from exc


def access_token(app_key, app_secret):
    try:
        response = httpx.post(f'{BASE}/oauth2/token', json={
            'grant_type': 'client_credentials', 'appkey': app_key, 'secretkey': app_secret,
        }, timeout=12)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise KiwoomError('토큰 연결 또는 응답 오류') from exc
    if not isinstance(payload, dict):
        raise KiwoomError('토큰 응답 형식 오류')
    token = payload.get('token') or payload.get('access_token')
    if not token or payload.get('return_code', 0) not in (0, '0'):
        raise KiwoomError('키움 토큰 발급 실패: 키, 등록 IP, 권한을 확인하세요')
    # Kiwoom returns a Seoul-local wall-clock expiration, not a duration.
    try:
        expiry = datetime.strptime(payload['expires_dt'], '%Y%m%d%H%M%S').replace(
            tzinfo=ZoneInfo('Asia/Seoul')).timestamp()
    except (KeyError, TypeError, ValueError) as exc:
        raise KiwoomError('키움 토큰 만료일 응답 오류') from exc
    if expiry <= time.time():
        raise KiwoomError('키움 토큰이 이미 만료되었습니다')
    return token, expiry


def fetch_stock_list(token, market, max_pages=40):
    """Read complete KOSPI/KOSDAQ name-code listings via official ka10099."""
    if market not in ('0', '10'):
        raise ValueError('invalid stock market')
    continuation, next_key = 'N', ''
    seen_keys, stocks = set(), []
    with httpx.Client() as client:
        for _ in range(max_pages):
            headers = {'api-id': 'ka10099', 'authorization': f'Bearer {token}',
                       'cont-yn': continuation, 'next-key': next_key,
                       'Content-Type': 'application/json;charset=UTF-8'}
            payload, response_headers = request_page(client, f'{BASE}/api/dostk/stkinfo', {'mrkt_tp':market}, headers, 'ka10099')
            records = payload.get('list')
            if not isinstance(records, list):
                raise KiwoomError('ka10099 종목 목록 형식 오류')
            for row in records:
                if isinstance(row, dict):
                    code, name = row.get('code', ''), row.get('name', '')
                elif isinstance(row, (list, tuple)) and len(row) >= 2:
                    code, name = row[:2]
                else:
                    continue
                code, name = str(code).strip(), str(name).strip()
                if len(code) == 6 and code.isdigit() and name:
                    stocks.append((code, name))
            continuation = response_headers.get('cont-yn', 'N')
            if continuation != 'Y':
                return stocks
            next_key = response_headers.get('next-key', '')
            if not next_key or next_key in seen_keys:
                raise KiwoomError('ka10099 연속조회 키 오류')
            seen_keys.add(next_key)
            time.sleep(0.22)
        raise KiwoomError('ka10099 페이지 한도 초과: 목록 일부만으로 종목을 선택하지 않습니다')


def fetch_market_rows(token, code, date, market, max_pages=200):
    if market not in ('KRX', 'NXT') or len(code) != 6 or not code.isdigit():
        raise ValueError('invalid market or stock code')
    if len(date) != 8 or not date.isdigit():
        raise ValueError('invalid date')
    body = {'amt_qty_tp': '1', 'stk_cd': code + ('_NX' if market == 'NXT' else ''), 'date': date}
    continuation, next_key = 'N', ''
    seen_keys, result = set(), []
    with httpx.Client() as client:
        for page in range(max_pages):
            headers = {'api-id': 'ka90008', 'authorization': f'Bearer {token}',
                       'cont-yn': continuation, 'next-key': next_key,
                       'Content-Type': 'application/json;charset=UTF-8'}
            payload, response_headers = request_page(client, f'{BASE}/api/dostk/mrkcond', body, headers, 'ka90008')
            records = payload.get('stk_tm_prm_trde_trnsn') or []
            if not isinstance(records, list): raise KiwoomError('ka90008 응답 형식 오류')
            for row in records:
                if not isinstance(row, dict) or str(row.get('stex_tp', '')).upper() != market:
                    continue
                tm = str(row.get('tm', ''))
                if len(tm) != 6 or not tm.isdigit() or int(tm[:2]) > 23 or int(tm[2:4]) > 59:
                    continue
                try:
                    result.append({'tm': tm,
                        'buy_amt': parse_amount(row['prm_buy_amt']),
                        'sell_amt': parse_amount(row['prm_sell_amt']),
                        'net_amt': parse_amount(row['prm_netprps_amt'])})
                except (KeyError, ValueError) as exc:
                    raise KiwoomError('ka90008 금액 필드 오류') from exc
            if (page+1) % 10 == 0:
                logger.info('Collection pages; code=%s date=%s market=%s pages=%d raw_rows=%d', code, date, market, page+1, len(result))
            continuation = response_headers.get('cont-yn', 'N')
            if continuation != 'Y': return sorted(result, key=lambda r: r['tm'])
            next_key = response_headers.get('next-key', '')
            if not next_key or next_key in seen_keys: raise KiwoomError('ka90008 연속조회 키 오류')
            seen_keys.add(next_key)
            time.sleep(0.22)
        raise KiwoomError('ka90008 페이지 한도 초과: 일부 데이터는 저장하지 않았습니다')
