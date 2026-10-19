import unittest
from fastapi.testclient import TestClient
from program_flow.app import app


class UiTests(unittest.TestCase):
    def test_frontend_assets_are_served_without_exposing_api_data(self):
        with TestClient(app) as client:
            page = client.get('/')
            self.assertEqual(page.status_code, 200)
            for text in ('Program Flow', 'NXT 오전', 'NXT 오후', 'KRX 정규장', 'id="chart"', 'id="keys-form"'):
                self.assertIn(text, page.text)
            self.assertNotIn('id="login-form"', page.text)
            self.assertNotIn('id="logout-btn"', page.text)
            self.assertEqual(client.get('/static/app.js').status_code, 200)
            self.assertEqual(client.get('/manifest.webmanifest').status_code, 200)
            self.assertEqual(client.get('/api/data?code=039490&date=20261015').status_code, 401)

    def test_chart_only_displays_cumulative_net_buy(self):
        with TestClient(app) as client:
            page = client.get('/').text
            chart_header = page.split('<section class="panel chart-panel">', 1)[1].split('<div id="chart"', 1)[0]
            self.assertIn('순매수</span>', chart_header)
            self.assertEqual(chart_header.count('class="swatch'), 1)
            self.assertNotIn('매도 (음수)', chart_header)
            script = client.get('/static/app.js').text
            self.assertIn("path('net')", script)
            self.assertNotIn("path('buy')", script)
            self.assertNotIn("path('sell')", script)
            self.assertNotIn('매수 ${amount', script)
            self.assertNotIn('매도 ${amount', script)

    def test_stock_name_input_resolves_code_before_loading(self):
        with TestClient(app) as client:
            page = client.get('/').text
            self.assertIn('id="stock-name"', page)
            self.assertNotIn('id="stock-code"', page)
            script = client.get('/static/app.js').text
            self.assertIn('/api/stocks/resolve?name=', script)
            self.assertIn('const query = name(), date = ymd();', script)
            self.assertIn('encodeURIComponent(query)', script)

    def test_stock_name_has_clickable_suggestion_list(self):
        with TestClient(app) as client:
            page = client.get('/').text
            self.assertIn('id="stock-suggestions"', page)
            self.assertIn('aria-controls="stock-suggestions"', page)
            script = client.get('/static/app.js').text
            self.assertIn('/api/stocks/search?q=', script)
            self.assertIn("$('stock-name').addEventListener('input'", script)
            self.assertIn('chooseSuggestion(', script)

    def test_auto_collection_has_no_manual_buttons_and_refreshes_saved_data(self):
        with TestClient(app) as client:
            page = client.get('/').text
            script = client.get('/static/app.js').text
            self.assertNotIn('id="load-btn"', page)
            self.assertNotIn('id="refresh-btn"', page)
            self.assertIn('/api/watch', script)
            self.assertIn('setInterval(', script)
            self.assertIn('/api/data?code=', script)
            self.assertIn('visibilitychange', script)
            self.assertNotIn('!document.hidden)load(false)', script)

    def test_child_friendly_guide_is_linked_and_illustrated(self):
        with TestClient(app) as client:
            self.assertIn('/static/kiwoom-rest-guide.html', client.get('/').text)
            guide = client.get('/static/kiwoom-rest-guide.html')
            self.assertEqual(guide.status_code, 200)
            self.assertIn('키움 REST API', guide.text)
            self.assertIn('https://openapi.kiwoom.com/intro/serviceInfo', guide.text)
            for image in ('official-portal.webp', 'official-apply.webp', 'official-ip.webp',
                          'official-download.webp', 'program-flow-settings.webp'):
                result = client.get('/static/guide/' + image)
                self.assertEqual(result.status_code, 200, image)
                self.assertEqual(result.headers['content-type'], 'image/webp')
            pdf = client.get('/static/kiwoom-rest-guide.pdf')
            self.assertEqual(pdf.status_code, 200)
            self.assertEqual(pdf.headers['content-type'], 'application/pdf')
            self.assertTrue(pdf.content.startswith(b'%PDF-'))

    def test_security_headers_prevent_cached_private_responses(self):
        with TestClient(app) as client:
            home = client.get('/')
            self.assertIn("default-src 'self'", home.headers['content-security-policy'])
            self.assertEqual(home.headers['x-content-type-options'], 'nosniff')
            self.assertEqual(client.get('/api/me').headers['cache-control'], 'no-store')


if __name__ == '__main__': unittest.main()
