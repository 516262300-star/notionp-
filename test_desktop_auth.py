import unittest
from unittest.mock import patch
import httpx
from erp_client import ErpClient, ErpLoginRequired
from erp_desktop_auth import DesktopLoginRequired

class WeeklyDesktopTests(unittest.TestCase):
    def test_constructor_does_not_restore_old_session(self):
        with patch('erp_client.get_client_cookies') as get:
            with ErpClient() as client:
                self.assertEqual(len(client.client.cookies), 0)
            get.assert_not_called()

    def test_client_missing_blocks_requests(self):
        with patch('erp_client.get_client_cookies', side_effect=DesktopLoginRequired('login needed')):
            with ErpClient() as client, patch.object(client.client, 'get') as get:
                with self.assertRaises(ErpLoginRequired):
                    client._get_authenticated('https://ldswj.net/data')
                get.assert_not_called()

    def test_expiry_refreshes_cookies_and_retries_get_once(self):
        req = httpx.Request('GET', 'https://ldswj.net/data')
        responses = [httpx.Response(200, text='<input name="password">', request=req), httpx.Response(200, text='data', request=req)]
        cookies = [{'name': 'session', 'value': 'synthetic', 'domain': 'ldswj.net', 'path': '/'}]
        with patch('erp_client.get_client_cookies', return_value=cookies) as get_cookies:
            with ErpClient() as client, patch.object(client.client, 'get', side_effect=responses), patch.object(client.client, 'post') as post:
                self.assertEqual(client._get_authenticated(str(req.url)).text, 'data')
                self.assertEqual([c.kwargs['force'] for c in get_cookies.call_args_list], [False, True])
                post.assert_not_called()

if __name__ == '__main__':
    unittest.main()
