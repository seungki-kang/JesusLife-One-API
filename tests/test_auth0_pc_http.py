"""Configuration-free HTTP regressions; no database or external authentication."""
import unittest
from unittest.mock import Mock

from fastapi import HTTPException

from fastapi.testclient import TestClient

from app.auth0_pc import create_app


class UnconfiguredPcHttpTest(unittest.TestCase):
    def test_page_displays_only_server_verified_status(self):
        runtime = Mock()
        with TestClient(create_app(runtime), base_url='http://127.0.0.1:8000') as client:
            for error, login, session in (
                (None, '로그인됨', '유효'),
                (HTTPException(401, 'synthetic-private-detail'), '로그인되지 않음', '유효하지 않음'),
                (HTTPException(503, 'synthetic-private-detail'), '확인 불가', '확인 불가'),
                (RuntimeError('synthetic-private-detail'), '확인 불가', '확인 불가'),
            ):
                runtime.identity.side_effect = error
                for path in ('/auth/poc/', '/auth/poc/signed-out'):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('id="login-state">' + login, response.text)
                    self.assertIn('id="session-state">' + session, response.text)
                    self.assertNotIn('synthetic-private-detail', response.text)
                    self.assertEqual(response.headers['cache-control'], 'no-store')
                    self.assertFalse(runtime.identity.call_args.kwargs['product'])

    def test_missing_runtime_is_not_a_login_or_header_bypass(self):
        with TestClient(create_app(),base_url='http://127.0.0.1:8000') as client:
            self.assertEqual(client.get('/auth/poc/login').status_code,503)
            response = client.get('/api/v1/neorang-narang/completions',headers={
                'Authorization':'Bearer synthetic-unverified','X-Session-ID':'synthetic-session'})
            self.assertEqual(response.status_code,401)
            self.assertEqual(response.json(),{'detail':'Authentication required'})

    def test_redirect_host_injection_is_rejected(self):
        with TestClient(create_app(),base_url='http://untrusted.example.invalid') as client:
            self.assertEqual(client.get('/auth/poc/login').status_code,400)
