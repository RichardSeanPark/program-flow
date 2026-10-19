import tempfile
import unittest
from unittest.mock import patch
import time
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from program_flow.app import create_app, today_kst
from program_flow.kiwoom import KiwoomError, KiwoomAuthError


class WebFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.master = Fernet.generate_key()
        self.app = create_app(self.tmp.name, master_key=self.master)
        self.extra_stores = []
        self.client = TestClient(self.app)
        self.client.headers.update({'Origin': 'http://testserver'})

    def tearDown(self):
        self.client.close()
        for store in self.extra_stores:
            store.conn.close()
        self.app.state.store.conn.close()
        self.tmp.cleanup()

    def test_browser_starts_without_account_login(self):
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        response = self.client.post('/api/session')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['has_keys'])
        self.assertIn('httponly', response.headers['set-cookie'].lower())
        self.assertIn('samesite=strict', response.headers['set-cookie'].lower())
        self.assertEqual(self.client.get('/api/me').json()['has_keys'], False)
        self.assertEqual(self.client.post('/api/session').status_code, 200)
        self.assertEqual(self.client.post('/api/register', json={}).status_code, 404)
        self.assertEqual(self.client.post('/api/login', json={}).status_code, 404)
        self.assertEqual(self.client.post('/api/logout').status_code, 404)

    def test_browser_cookie_recovers_saved_key_after_server_restart(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('token', time.time() + 3600)):
            self.assertEqual(self.client.post('/api/keys', json={'app_key': 'a'*32, 'app_secret': 'b'*32}).status_code, 200)
        restarted = create_app(self.tmp.name, master_key=self.master)
        self.extra_stores.append(restarted.state.store)
        with patch('program_flow.app.access_token', return_value=('renewed', time.time() + 3600)) as issue:
            with TestClient(restarted) as browser:
                browser.cookies.update(self.client.cookies)
                browser.headers.update({'Origin': 'http://testserver'})
                self.assertTrue(browser.post('/api/session').json()['has_keys'])
                self.assertTrue(browser.get('/api/me').json()['has_keys'])
            issue.assert_called_once()

    def test_browser_session_renews_without_creating_another_profile(self):
        self.client.post('/api/session')
        cookie = self.client.cookies.get('program_browser')
        store = self.app.state.store
        initial = store.conn.execute('SELECT expires FROM sessions').fetchone()[0]
        with patch('program_flow.store.time.time', return_value=initial - 100):
            refreshed = self.client.post('/api/session')
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(self.client.cookies.get('program_browser'), cookie)
        self.assertIn('max-age=31536000', refreshed.headers['set-cookie'].lower())
        self.assertGreater(store.conn.execute('SELECT expires FROM sessions').fetchone()[0], initial)
        self.assertEqual(store.conn.execute('SELECT count(*) FROM profiles').fetchone()[0], 1)

    def test_sync_only_owner_and_no_fake_missing_minutes(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('token', time.time() + 3600)), patch('program_flow.app.fetch_market_rows') as fetch:
            self.assertEqual(self.client.post('/api/keys', json={'app_key': 'a'*32, 'app_secret': 'b'*32}).status_code, 200)
            fetch.side_effect = [
                [{'tm': '090001', 'buy_amt': 20, 'sell_amt': 5, 'net_amt': 15}],
                [{'tm': '153001', 'buy_amt': 30, 'sell_amt': 10, 'net_amt': 20}],
            ]
            response = self.client.post('/api/sync', json={'code': '039490', 'date': '20261015'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(fetch.call_count, 2)
        data = self.client.get('/api/data?code=039490&date=20261015').json()
        self.assertEqual(len(data['rows']), 2)
        self.assertIsNone(data['sessions']['NXT_PM']['latest'])
        with patch('program_flow.app.fetch_market_rows', return_value=[]), TestClient(self.app) as other:
            other.headers.update({'Origin': 'http://testserver'})
            self.assertEqual(other.post('/api/session').status_code, 200)
            self.assertEqual(other.get('/api/data?code=039490&date=20261015').json()['rows'], [])
            self.assertFalse(other.get('/api/me').json()['has_keys'])

    def test_stock_name_resolves_to_official_code_before_data_lookup(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('fake-token', time.time()+3600)):
            self.assertEqual(self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32}).status_code, 200)
        with patch('program_flow.app.fetch_stock_list', side_effect=[
            [('005930', '삼성전자')], [('000660', 'SK하이닉스')]
        ]) as listing:
            match = self.client.get('/api/stocks/resolve', params={'name':'삼성전자'})
            self.assertEqual(match.status_code, 200, match.text)
            self.assertEqual(match.json(), {'code':'005930', 'name':'삼성전자'})
            self.assertEqual(listing.call_args_list[0].args, ('fake-token', '0'))
            self.assertEqual(listing.call_args_list[1].args, ('fake-token', '10'))
            self.assertEqual(self.client.get('/api/stocks/resolve', params={'name':'삼성전자'}).json(), match.json())
            self.assertEqual(listing.call_count, 2)

    def test_stock_lookup_does_not_guess_missing_or_ambiguous_names(self):
        self.assertEqual(self.client.get('/api/stocks/resolve', params={'name':'삼성전자'}).status_code, 401)
        self.client.post('/api/session')
        self.assertEqual(self.client.get('/api/stocks/resolve', params={'name':'삼성전자'}).status_code, 409)
        with patch('program_flow.app.access_token', return_value=('fake-token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.fetch_stock_list', side_effect=[
            [('111111','동명이종목')], [('222222','동명이종목')]
        ]):
            ambiguous = self.client.get('/api/stocks/resolve', params={'name':'동명이종목'})
            self.assertEqual(ambiguous.status_code, 409)
            self.assertEqual(self.client.get('/api/stocks/resolve', params={'name':'없는종목'}).status_code, 404)
            self.assertNotIn('fake-token', ambiguous.text)

    def test_stock_search_returns_substring_suggestions_for_click_selection(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('fake-token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.fetch_stock_list', side_effect=[
            [('005930','삼성전자'),('005935','삼성전자우')], [('123456','우리삼성전자')]
        ]) as listing:
            response = self.client.get('/api/stocks/search', params={'q':'성전자'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['items'], [
                {'code':'005930','name':'삼성전자'},
                {'code':'005935','name':'삼성전자우'},
                {'code':'123456','name':'우리삼성전자'},
            ])
            self.assertFalse(response.json()['has_more'])
            self.assertEqual(self.client.get('/api/stocks/search', params={'q':'삼성전자'}).status_code, 200)
            self.assertEqual(listing.call_count, 2)
            self.assertNotIn('fake-token', response.text)

    def test_stock_search_requires_auth_and_limits_candidates(self):
        self.assertEqual(self.client.get('/api/stocks/search', params={'q':'삼'}).status_code, 401)
        self.client.post('/api/session')
        self.assertEqual(self.client.get('/api/stocks/search', params={'q':'  '}).status_code, 400)
        self.assertEqual(self.client.get('/api/stocks/search', params={'q':'삼'}).status_code, 409)
        with patch('program_flow.app.access_token', return_value=('fake-token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.fetch_stock_list', side_effect=[
            [(f'{i:06d}',f'SK{i:03d}') for i in range(25)], []
        ]):
            result = self.client.get('/api/stocks/search', params={'q':'sk'})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(len(result.json()['items']), 20)
            self.assertTrue(result.json()['has_more'])
            self.assertEqual(result.json()['items'][0], {'code':'000000','name':'SK000'})

    def test_boot_renews_expiring_token_once_and_sync_uses_it(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', side_effect=[
            ('initial', time.time() + 60), ('renewed', time.time() + 3600)
        ]) as issue, patch('program_flow.app.fetch_market_rows', return_value=[]) as fetch:
            self.assertEqual(self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32}).status_code, 200)
            self.assertIsNone(self.client.post('/api/session').json()['token_error'])
            self.assertIsNone(self.client.post('/api/session').json()['token_error'])
            self.assertEqual(self.client.post('/api/sync', json={'code':'039490','date':'20261015'}).status_code, 200)
            self.assertEqual(issue.call_count, 2)
            self.assertEqual(fetch.call_args_list[0].args[0], 'renewed')

    def test_startup_failure_surfaces_without_exposing_keys_and_can_retry(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('old', time.time() + 3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        restarted = create_app(self.tmp.name, master_key=self.master)
        self.extra_stores.append(restarted.state.store)
        with patch('program_flow.app.access_token', side_effect=KiwoomError('키움 토큰 발급 실패: 키, 등록 IP, 권한을 확인하세요')):
            with TestClient(restarted) as browser:
                browser.cookies.update(self.client.cookies)
                browser.headers.update({'Origin': 'http://testserver'})
                response = browser.post('/api/session')
                self.assertTrue(response.json()['has_keys'])
                self.assertIn('키', response.json()['token_error'])
                self.assertNotIn('a'*32, response.text)
                self.assertNotIn('b'*32, response.text)
                self.assertEqual(browser.post('/api/sync', json={'code':'039490','date':'20261015'}).status_code, 502)
                with patch('program_flow.app.access_token', return_value=('new', time.time() + 3600)):
                    self.assertIsNone(browser.post('/api/session').json()['token_error'])

    def test_cross_origin_bootstrap_is_rejected(self):
        self.client.headers['Origin'] = 'https://attacker.example'
        self.assertEqual(self.client.post('/api/session').status_code, 403)
        self.assertEqual(self.client.get('/api/me').status_code, 401)

    def test_watch_requires_session_keys_and_official_stock(self):
        target = {'code': '005930', 'name': '삼성전자'}
        self.assertEqual(self.client.post('/api/watch', json=target).status_code, 401)
        self.client.post('/api/session')
        self.assertEqual(self.client.post('/api/watch', json=target).status_code, 409)
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32, 'app_secret':'b'*32})
        with patch('program_flow.app.fetch_stock_list', side_effect=[
            [('005930','삼성전자')], []
        ]), patch('program_flow.app.fetch_market_rows', return_value=[]):
            self.assertEqual(self.client.post('/api/watch', json={'code':'999999','name':'삼성전자'}).status_code, 400)
            self.assertEqual(self.client.post('/api/watch', json={'code':'005930','name':'가짜이름'}).status_code, 400)
            result = self.client.post('/api/watch', json=target)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get('/api/watch').json()['watch'], target)
        with patch('program_flow.app.fetch_market_rows', return_value=[]), TestClient(self.app) as other:
            other.headers.update({'Origin':'http://testserver'})
            other.post('/api/session')
            self.assertIsNone(other.get('/api/watch').json()['watch'])

    def test_background_collects_without_browser_and_recovers_after_restart(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.fetch_stock_list', side_effect=[
            [('005930','삼성전자')], []
        ]), patch('program_flow.app.fetch_market_rows', return_value=[
            {'tm':'090001','buy_amt':20,'sell_amt':5,'net_amt':15}
        ]) as fetch:
            self.assertEqual(self.client.post('/api/watch', json={'code':'005930','name':'삼성전자'}).status_code, 200)
            self.assertEqual(fetch.call_count, 2)
        # Restart with no browser request; the stored target must be collected by lifespan.
        restarted = create_app(self.tmp.name, master_key=self.master, collect_interval=0.05)
        self.extra_stores.append(restarted.state.store)
        with patch('program_flow.app.access_token', return_value=('again', time.time()+3600)), \
             patch('program_flow.app.fetch_market_rows', return_value=[
                 {'tm':'090101','buy_amt':25,'sell_amt':5,'net_amt':20}
             ]) as fetch, patch.object(restarted.state.store, 'last_sync', return_value=None):
            with TestClient(restarted):
                deadline = time.monotonic()+4
                while fetch.call_count < 2 and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertGreaterEqual(fetch.call_count, 2, 'server did not collect without a browser')
        saved = self.app.state.store.conn.execute(
            "SELECT count(*) FROM minute_rows WHERE stock_code='005930' AND tm='090101'").fetchone()[0]
        self.assertGreater(saved, 0)

    def test_background_skips_profiles_without_keys_after_deletion(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.fetch_stock_list', side_effect=[[('005930','삼성전자')], []]), \
             patch('program_flow.app.fetch_market_rows', return_value=[]):
            self.client.post('/api/watch', json={'code':'005930','name':'삼성전자'})
        self.client.delete('/api/keys')
        restarted = create_app(self.tmp.name, master_key=self.master, collect_interval=0.05)
        self.extra_stores.append(restarted.state.store)
        with patch('program_flow.app.fetch_market_rows') as fetch:
            with TestClient(restarted):
                time.sleep(0.2)
            fetch.assert_not_called()

    def test_background_runs_again_on_next_tick_without_a_browser(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.fetch_stock_list', side_effect=[[('005930','삼성전자')], []]), \
             patch('program_flow.app.fetch_market_rows', return_value=[]):
            self.assertEqual(self.client.post('/api/watch', json={'code':'005930','name':'삼성전자'}).status_code, 200)
        # Make old sync timestamps eligible, and let the worker retry on its own.
        store = self.app.state.store
        with store.lock, store.conn:
            store.conn.execute('UPDATE sync_state SET synced_at=0')
        restarted = create_app(self.tmp.name, master_key=self.master, collect_interval=0.12)
        self.extra_stores.append(restarted.state.store)
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)), \
             patch('program_flow.app.fetch_market_rows', return_value=[]) as fetch:
            with TestClient(restarted):
                deadline = time.monotonic()+4
                while fetch.call_count < 2 and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertEqual(fetch.call_count, 2)
                while (restarted.state.store.last_sync(
                        restarted.state.store.active_watches()[0][0], '005930',
                        today_kst().strftime('%Y%m%d'),
                        'NXT') == 0 and time.monotonic() < deadline):
                    time.sleep(0.02)
                with restarted.state.store.lock, restarted.state.store.conn:
                    restarted.state.store.conn.execute('UPDATE sync_state SET synced_at=0')
                deadline = time.monotonic()+4
                while fetch.call_count < 4 and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertGreaterEqual(fetch.call_count, 4, 'next server tick did not collect')

    def test_collect_interval_is_measured_from_start_not_end(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.fetch_stock_list', side_effect=[[('005930','삼성전자')], []]), \
             patch('program_flow.app.fetch_market_rows', return_value=[]):
            self.client.post('/api/watch', json={'code':'005930','name':'삼성전자'})
        app = create_app(self.tmp.name, master_key=self.master, collect_interval=0.8)
        self.extra_stores.append(app.state.store)
        calls = []
        def fetch(*_):
            calls.append(time.monotonic())
            return []
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)), \
             patch('program_flow.app.fetch_market_rows', side_effect=fetch), \
             patch.object(app.state.store, 'last_sync', return_value=None):
            with TestClient(app):
                deadline = time.monotonic()+3
                while len(calls) < 3 and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertGreaterEqual(len(calls), 3)
                self.assertLess(calls[2]-calls[0], 1.1, 'request duration added to 60-second period')

    def test_same_app_can_restart_its_collector(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.fetch_stock_list', side_effect=[[('005930','삼성전자')], []]), \
             patch('program_flow.app.fetch_market_rows', return_value=[]):
            self.client.post('/api/watch', json={'code':'005930','name':'삼성전자'})
        app = create_app(self.tmp.name, master_key=self.master, collect_interval=0.1)
        self.extra_stores.append(app.state.store)
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)), \
             patch('program_flow.app.fetch_market_rows', return_value=[]) as fetch, \
             patch.object(app.state.store, 'last_sync', return_value=None):
            for attempt in range(2):
                with TestClient(app):
                    deadline = time.monotonic()+3
                    while fetch.call_count < 2*(attempt+1) and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertGreaterEqual(fetch.call_count, 2*(attempt+1), f'restart #{attempt+1} failed')

    def test_watch_registration_survives_initial_provider_failure(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.fetch_stock_list', side_effect=[[('005930','삼성전자')], []]), \
             patch('program_flow.app.fetch_market_rows', side_effect=KiwoomError('일시적으로 응답 없음')):
            response = self.client.post('/api/watch', json={'code':'005930','name':'삼성전자'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['watch'], {'code':'005930','name':'삼성전자'})
        self.assertIn('응답 없음', response.json()['last_error'])
        self.assertEqual(self.client.get('/api/watch').json()['watch']['code'], '005930')

    def test_both_markets_are_eligible_each_roughly_minute_tick(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('token', time.time()+3600)):
            self.client.post('/api/keys', json={'app_key':'a'*32,'app_secret':'b'*32})
        # The second market is queried later in each round. It must not get
        # skipped for a whole extra minute due to sub-second clock skew.
        with patch.object(self.app.state.store, 'last_sync', return_value=time.time()-59.5), \
             patch('program_flow.app.fetch_market_rows', return_value=[]) as fetch:
            result = self.client.post('/api/sync', json={
                'code':'005930','date':today_kst().strftime('%Y%m%d')})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(fetch.call_count, 2)

    def test_rejected_unexpired_token_is_renewed_and_the_same_query_retried(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token', return_value=('old-token',time.time()+3600)):
            self.client.post('/api/keys',json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.access_token', return_value=('renewed-token',time.time()+3600)) as renew, \
             patch('program_flow.app.fetch_market_rows',side_effect=[KiwoomAuthError('8005'),[],[]]) as fetch:
            result=self.client.post('/api/sync',json={'code':'009150','date':'20261019'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual([call.args[0] for call in fetch.call_args_list],['old-token','renewed-token','renewed-token'])
        self.assertEqual(renew.call_count,1)

    def test_reconnect_renews_cached_token_and_rejects_another_origin(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token',return_value=('old',time.time()+3600)):
            self.client.post('/api/keys',json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.access_token',return_value=('new',time.time()+3600)) as renew:
            self.assertEqual(self.client.post('/api/reconnect').status_code,200)
            renew.assert_called_once()
            self.assertEqual(self.client.post('/api/reconnect',headers={'Origin':'https://other.example'}).status_code,403)
            self.assertEqual(renew.call_count,1)

    def test_one_market_failure_does_not_prevent_the_other_market_being_saved(self):
        self.client.post('/api/session')
        with patch('program_flow.app.access_token',return_value=('valid',time.time()+3600)):
            self.client.post('/api/keys',json={'app_key':'a'*32,'app_secret':'b'*32})
        with patch('program_flow.app.fetch_market_rows',side_effect=[KiwoomError('KRX temporary failure'),[
            {'tm':'080001','buy_amt':20,'sell_amt':5,'net_amt':15}]]) as fetch:
            result=self.client.post('/api/sync',json={'code':'009150','date':'20261019'})
        self.assertEqual(result.status_code,502)
        self.assertEqual(fetch.call_count,2)
        data=self.client.get('/api/data?code=009150&date=20261019').json()
        self.assertEqual(data['rows'][0]['market'],'NXT')
        self.assertEqual(data['sessions']['NXT_AM']['latest'],15)


if __name__ == '__main__': unittest.main()
