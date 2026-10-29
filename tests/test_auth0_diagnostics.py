"""Synthetic wire regressions; no local credentials, database or real Auth0."""
import logging
from unittest.mock import Mock
from urllib.parse import urlencode
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth0_pc import ORIGIN, PcRuntime, create_app
from app.core.auth_diagnostics import CallbackQueryFilter, stage
from app.core.core_store import digest
from scripts.auth0_pc_settings import CALLBACK, validate
from tests.test_auth0_pc_settings import PcSettingsTest
from tests.test_core_persistence import SyntheticAuth0
from tests.auth_contract_fixtures import NOW


class CallbackDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.config = validate(PcSettingsTest().settings() | {'AUTH0_ISSUER': 'https://synthetic.auth0.com/'})
        self.idp = SyntheticAuth0(self.config)
        self.store = Mock()
        self.runtime = PcRuntime(self.config, store=self.store, provider=self.idp.provider, clock=lambda: NOW)

    def callback(self, *, wrong_nonce=False, profile=None, claim_failure=False, core_failure=False):
        verifier, nonce = 'v' * 43, 'synthetic-nonce'
        from app.core.auth0_poc import pkce_challenge
        location = 'https://synthetic.auth0.com/authorize?' + urlencode({
            'state': 'synthetic-state', 'nonce': nonce, 'code_challenge': pkce_challenge(verifier)})
        code, state_value = self.idp.issue(location, 'synthetic-subject', wrong_nonce=wrong_nonce)
        self.store.claim_login.return_value = dict(client_id=b'synthetic-client', redirect_uri=CALLBACK.encode(),
                                                   verifier=verifier, nonce_hash=digest(nonce))
        if claim_failure:
            self.store.claim_login.side_effect = HTTPException(401, 'Authentication required')
        if core_failure:
            self.store.complete_login.side_effect = HTTPException(503, 'Authentication unavailable')
        else:
            self.store.complete_login.return_value = ('synthetic-cookie', 'synthetic-csrf', None)
        if profile:
            original = self.idp.jwt.signed
            def signed(**kwargs):
                if 'header' not in kwargs:
                    kwargs['header'] = {'typ': profile}
                return original(**kwargs)
            self.idp.jwt.signed = signed
        with TestClient(create_app(self.runtime), base_url=ORIGIN) as client:
            client.cookies.set('jl_pc_login', 'synthetic-browser')
            with self.assertLogs('uvicorn.error', level='INFO') as captured:
                response = client.get(CALLBACK, params={'code': code, 'state': state_value}, follow_redirects=False)
        logs = '\n'.join(captured.output)
        for secret in (code, state_value, verifier, nonce, 'synthetic-browser', 'synthetic-cookie', 'synthetic-subject'):
            self.assertNotIn(secret, logs)
        return response, logs

    def test_success_validates_exchange_jwts_and_creates_session(self):
        response, logs = self.callback()
        self.assertEqual(response.status_code, 303)
        for name in ('callback_input', 'state_browser_pkce', 'token_exchange_pkce', 'access_profile',
                     'access_signature', 'access_claims', 'access_time', 'id_jwt_nonce', 'core_session'):
            self.assertIn(f'stage={name} result=PASS', logs)
        self.store.complete_login.assert_called_once()

    def test_state_failure_never_exchanges_or_creates_session(self):
        response, logs = self.callback(claim_failure=True)
        self.assertEqual(response.status_code, 401)
        self.assertIn('stage=state_browser_pkce result=FAIL', logs)
        self.assertNotIn('stage=token_exchange_pkce', logs)
        self.store.complete_login.assert_not_called()

    def test_default_profile_is_rejected_before_session(self):
        response, logs = self.callback(profile='JWT')
        self.assertEqual(response.status_code, 401)
        self.assertIn('stage=token_exchange_pkce result=PASS', logs)
        self.assertIn('stage=access_profile result=FAIL', logs)
        self.store.complete_login.assert_not_called()

    def test_nonce_failure_never_creates_session(self):
        response, logs = self.callback(wrong_nonce=True)
        self.assertEqual(response.status_code, 401)
        self.assertIn('stage=access_jwt result=PASS', logs)
        self.assertIn('stage=id_jwt_nonce result=FAIL', logs)
        self.store.complete_login.assert_not_called()

    def test_exchange_failure_never_verifies_or_creates_session(self):
        original = self.idp.handle
        import httpx
        def reject_exchange(request):
            if request.url.path == '/oauth/token':
                return httpx.Response(400, json={'error': 'invalid_grant'})
            return original(request)
        self.idp.provider.transport = httpx.MockTransport(reject_exchange)
        response, logs = self.callback()
        self.assertEqual(response.status_code, 401)
        self.assertIn('stage=token_exchange_pkce result=FAIL', logs)
        self.assertNotIn('stage=access_jwt', logs)
        self.store.complete_login.assert_not_called()

    def test_core_failure_is_distinct_from_jwt(self):
        response, logs = self.callback(core_failure=True)
        self.assertEqual(response.status_code, 503)
        self.assertIn('stage=id_jwt_nonce result=PASS', logs)
        self.assertIn('stage=core_session result=FAIL', logs)

    def test_access_log_omits_entire_callback_query(self):
        record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0,
                                  '%s - "%s %s HTTP/%s" %d',
                                  ('127.0.0.1', 'GET', '/api/v1/auth/callback/web?code=PRIVATE&state=PRIVATE', '1.1', 401), None)
        CallbackQueryFilter().filter(record)
        self.assertNotIn('PRIVATE', record.getMessage())
        self.assertNotIn('?', record.getMessage())

    def test_exception_details_are_never_logged(self):
        with self.assertLogs('uvicorn.error', level='INFO') as logs:
            with self.assertRaises(ValueError):
                with stage('core_session'):
                    raise ValueError('SYNTHETIC_SECRET')
        self.assertNotIn('SYNTHETIC_SECRET', str(logs.output))
