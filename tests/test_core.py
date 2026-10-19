import os
import httpx
import tempfile
import unittest
from unittest.mock import patch

from program_flow.kiwoom import parse_amount, fetch_market_rows, fetch_stock_list, access_token, KiwoomError, KiwoomAuthError
from program_flow.store import Store
from program_flow.series import build_sessions


class KiwoomTests(unittest.TestCase):
    def test_access_token_uses_official_expiry_and_rejects_missing_expiry(self):
        class Response:
            def __init__(self, payload): self.payload = payload
            def raise_for_status(self): pass
            def json(self): return self.payload
        from datetime import datetime
        from zoneinfo import ZoneInfo
        expiry_time = datetime.now(ZoneInfo('Asia/Seoul')).replace(microsecond=0)
        from datetime import timedelta
        expiry_time += timedelta(hours=2)
        expiry = expiry_time.timestamp()
        with patch('program_flow.kiwoom.httpx.post', return_value=Response({
            'return_code': 0, 'token': 'temporary-token', 'expires_dt': expiry_time.strftime('%Y%m%d%H%M%S')
        })):
            self.assertEqual(access_token('fake-app', 'fake-secret'), ('temporary-token', expiry))
        with patch('program_flow.kiwoom.httpx.post', return_value=Response({
            'return_code': 0, 'token': 'temporary-token'
        })):
            with self.assertRaises(KiwoomError): access_token('fake-app', 'fake-secret')

    def test_stock_list_follows_official_pagination_and_preserves_exact_names(self):
        calls = []
        class Response:
            def __init__(self, records, more=False):
                self.headers = {'cont-yn': 'Y' if more else 'N', 'next-key': 'next-page' if more else ''}
                self.records = records
            def raise_for_status(self): pass
            def json(self): return {'return_code': 0, 'list': self.records}
        def post(url, **kw):
            calls.append((url, kw))
            if len(calls) == 1:
                return Response([{'code': '005930', 'name': '삼성전자'}], more=True)
            return Response([{'code': '000660', 'name': 'SK하이닉스'}])
        with patch('program_flow.kiwoom.httpx.Client.post', side_effect=post):
            result = fetch_stock_list('fake-token', '0')
        self.assertEqual(result, [('005930', '삼성전자'), ('000660', 'SK하이닉스')])
        self.assertEqual(calls[0][0], 'https://api.kiwoom.com/api/dostk/stkinfo')
        self.assertEqual(calls[0][1]['headers']['api-id'], 'ka10099')
        self.assertEqual(calls[0][1]['json'], {'mrkt_tp': '0'})
        self.assertEqual(calls[1][1]['headers']['next-key'], 'next-page')

    def test_stock_list_accepts_positional_records_from_official_example(self):
        class Response:
            headers = {'cont-yn': 'N'}
            def raise_for_status(self): pass
            def json(self): return {'return_code': 0, 'list': [['005930', '삼성전자']]}
        with patch('program_flow.kiwoom.httpx.Client.post', return_value=Response()):
            self.assertEqual(fetch_stock_list('fake-token', '0'), [('005930', '삼성전자')])

    def test_stock_list_rejects_non_object_api_response(self):
        class Response:
            headers = {}
            def raise_for_status(self): pass
            def json(self): return ['unexpected']
        with patch('program_flow.kiwoom.httpx.Client.post', return_value=Response()):
            with self.assertRaises(KiwoomError):
                fetch_stock_list('fake-token', '0')

    def test_signed_amount_and_bad_input(self):
        self.assertEqual(parse_amount('--3472'), -3472000000)
        self.assertEqual(parse_amount('+17'), 17000000)
        with self.assertRaises(ValueError): parse_amount('garbage')

    def test_nxt_code_pagination_and_market_filter(self):
        calls = []
        class Response:
            status_code = 200
            def __init__(self, rows, more=False):
                self._rows = rows
                self.headers = {'cont-yn': 'Y' if more else 'N', 'next-key': 'page2' if more else ''}
            def json(self): return {'return_code': 0, 'stk_tm_prm_trde_trnsn': self._rows}
            def raise_for_status(self): pass
        def post(url, **kw):
            calls.append(kw)
            row = {'tm': '153001', 'stex_tp': 'NXT', 'prm_buy_amt': '20', 'prm_sell_amt': '5', 'prm_netprps_amt': '+15'}
            return Response([row], True) if len(calls) == 1 else Response([{**row, 'tm': '153101'}, {**row, 'stex_tp': 'KRX'}])
        with patch('program_flow.kiwoom.httpx.Client.post', side_effect=post):
            rows = fetch_market_rows('token', '039490', '20261015', 'NXT')
        self.assertEqual([r['tm'] for r in rows], ['153001', '153101'])
        self.assertEqual(calls[0]['json']['stk_cd'], '039490_NX')
        self.assertEqual(calls[1]['headers']['next-key'], 'page2')

    def test_incomplete_pagination_is_error(self):
        class Response:
            headers = {'cont-yn': 'Y', 'next-key': 'page2'}
            def json(self): return {'return_code': 0, 'stk_tm_prm_trde_trnsn': []}
            def raise_for_status(self): pass
        with patch('program_flow.kiwoom.httpx.Client.post', return_value=Response()):
            with self.assertRaises(KiwoomError): fetch_market_rows('token', '039490', '20261015', 'NXT', max_pages=1)

    def test_nxt_snapshot_can_span_more_than_thirty_pages(self):
        pages = []
        class Response:
            status_code = 200
            def __init__(self, page):
                self.headers = {'cont-yn':'Y' if page < 81 else 'N', 'next-key':str(page+1)}
            def raise_for_status(self): pass
            def json(self):
                return {'return_code':0, 'stk_tm_prm_trde_trnsn':[{
                    'tm':'080001','stex_tp':'NXT','prm_buy_amt':'2','prm_sell_amt':'1','prm_netprps_amt':'1'}]}
        def post(*args, **kwargs):
            pages.append(kwargs['headers']['next-key'])
            return Response(len(pages)-1)
        with patch('program_flow.kiwoom.httpx.Client.post', side_effect=post), \
             patch('program_flow.kiwoom.time.sleep'):
            rows = fetch_market_rows('synthetic-token','009150','20261019','NXT')
        self.assertEqual(len(rows),82)
        self.assertEqual(len(set(pages)),82)

    def test_embedded_token_rejection_is_distinguished_from_data_errors(self):
        class Response:
            status_code = 200
            headers = {}
            def raise_for_status(self): pass
            def json(self): return {'return_code':3,'return_msg':'인증에 실패했습니다[8005:Token이 유효하지 않습니다]'}
        with patch('program_flow.kiwoom.httpx.Client.post', return_value=Response()):
            with self.assertRaises(KiwoomAuthError):
                fetch_market_rows('synthetic-token','009150','20261019','NXT')

    def test_transport_reset_retries_only_the_failed_continuation_page(self):
        class Response:
            status_code=200
            def __init__(self,more):
                self.headers={'cont-yn':'Y' if more else 'N','next-key':'page-2'}
            def raise_for_status(self):pass
            def json(self):return {'return_code':0,'stk_tm_prm_trde_trnsn':[]}
        with patch('program_flow.kiwoom.httpx.Client.post',side_effect=[Response(True),httpx.ReadError('synthetic reset'),Response(False)]) as request, \
             patch('program_flow.kiwoom.time.sleep'):
            self.assertEqual(fetch_market_rows('synthetic','009150','20261019','NXT'),[])
        self.assertEqual([c.kwargs['headers']['next-key'] for c in request.call_args_list],['','page-2','page-2'])

    def test_rate_limit_response_is_retried_without_changing_page(self):
        class Response:
            status_code=200
            headers={}
            def __init__(self,limited):self.limited=limited
            def raise_for_status(self):pass
            def json(self):return {'return_code':1700,'return_msg':'요청 제한'} if self.limited else {'return_code':0,'stk_tm_prm_trde_trnsn':[]}
        with patch('program_flow.kiwoom.httpx.Client.post',side_effect=[Response(True),Response(False)]) as request, \
             patch('program_flow.kiwoom.time.sleep'):
            self.assertEqual(fetch_market_rows('synthetic','009150','20261019','NXT'),[])
        self.assertEqual(request.call_count,2)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, 'test.db'))
    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    def test_tenants_are_isolated_and_latest_snapshot_wins_per_minute(self):
        self.store.create_profile('a')
        self.store.create_profile('b')
        self.store.save_rows('a', '039490', '20261015', 'NXT', [
            {'tm': '153001', 'buy_amt': 20, 'sell_amt': 5, 'net_amt': 15},
            {'tm': '153059', 'buy_amt': 24, 'sell_amt': 5, 'net_amt': 19},
        ])
        self.assertEqual(self.store.rows('b', '039490', '20261015'), [])
        self.assertEqual(self.store.rows('a', '039490', '20261015')[0]['net_amt'], 19)

    def test_afternoon_without_baseline_is_unknown_not_zero(self):
        rows = [{'market': 'NXT', 'tm': '153000', 'net_amt': 260}, {'market': 'NXT', 'tm': '160000', 'net_amt': 280}]
        series = build_sessions(rows)
        self.assertIsNone(series['NXT_PM']['latest'])
        self.assertEqual(series['NXT_PM']['reason'], '15:30 이전 기준값 없음')

    def test_afternoon_subtracts_latest_before_1530(self):
        rows = [
            {'market': 'NXT', 'tm': '085900', 'net_amt': 100},
            {'market': 'NXT', 'tm': '152900', 'net_amt': 250},
            {'market': 'NXT', 'tm': '153000', 'net_amt': 260},
            {'market': 'NXT', 'tm': '160000', 'net_amt': 280},
        ]
        sessions = build_sessions(rows)
        self.assertEqual(sessions['NXT_AM']['latest'], 100)
        self.assertEqual(sessions['NXT_PM']['latest'], 30)
        self.assertEqual(sessions['NXT_PM']['points'][0]['net_amt'], 10)


if __name__ == '__main__': unittest.main()
