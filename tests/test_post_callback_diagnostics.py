"""Post-callback failures remain closed and diagnostics contain no input values."""
import unittest
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient
import pymysql

from app.auth0_pc import ORIGIN, PcRuntime, create_app
from app.core.auth0_poc import AppSession, VerifiedAccess
from app.core.core_store import CoreStore, digest, utc
from scripts.auth0_pc_settings import validate
from tests.auth_contract_fixtures import NOW
from tests import test_auth0_pc_settings as settings_fixtures


class PostCallbackDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.config = validate(settings_fixtures.PcSettingsTest().settings())
        self.provider, self.store = Mock(), Mock()
        self.token = VerifiedAccess(self.config.policy.issuer, 'private-subject',
            next(iter(self.config.policy.client_ids)), b'f' * 32, NOW + 600, frozenset())
        self.provider.verify_access.return_value = self.token
        self.store.cookie_token.return_value = ('private-token', {})
        self.store.lookup.return_value = AppSession(uuid4(), uuid4(), self.token.issuer,
            self.token.subject, self.token.client_id, NOW + 600, consent_active=False)
        self.runtime = PcRuntime(self.config, provider=self.provider, store=self.store, clock=lambda: NOW)

    def request(self, *, cookie=True, csrf=True, path='/auth/poc/acceptance/start-a'):
        with TestClient(create_app(self.runtime), base_url=ORIGIN) as client:
            if cookie:
                client.cookies.set('jl_pc_session', 'private-cookie')
            headers = {'Origin': ORIGIN}
            if csrf:
                headers['X-CSRF-Token'] = 'private-csrf'
            with self.assertLogs('uvicorn.error', level='INFO') as captured:
                response = client.post(path, headers=headers)
        logs = '\n'.join(captured.output)
        for value in ('private-token', 'private-cookie', 'private-csrf', 'private-subject',
                      str(self.store.lookup.return_value.account_id), 'private-exception'):
            self.assertNotIn(value, logs)
        return response, logs

    def test_a_registration_uses_verified_identity_without_product_consent(self):
        response, logs = self.request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'A_registered': True})
        for name in ('cookie_present', 'cookie_token', 'access_verify', 'session_lookup', 'session_binding', 'register_a'):
            self.assertIn(f'stage={name} result=PASS', logs)
        self.assertIn('route=register_a status=200', logs)

    def test_missing_cookie_and_csrf_stop_before_token_processing(self):
        response, logs = self.request(cookie=False)
        self.assertEqual(response.status_code, 401)
        self.assertIn('stage=cookie_present result=FAIL', logs)
        self.provider.verify_access.assert_not_called()
        response, logs = self.request(csrf=False)
        self.assertEqual(response.status_code, 403)
        self.assertIn('stage=csrf result=FAIL', logs)
        self.store.cookie_token.assert_not_called()

    def test_crypto_and_storage_exceptions_are_distinct_and_sanitized(self):
        self.store.cookie_token.side_effect = ValueError('private-exception')
        response, logs = self.request()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'Authentication unavailable'})
        self.assertIn('stage=cookie_token result=FAIL', logs)
        self.assertNotIn('stage=register_a', logs)
        self.store.cookie_token.side_effect = None
        self.store.lookup.side_effect = RuntimeError('private-exception')
        response, logs = self.request()
        self.assertEqual(response.status_code, 503)
        self.assertIn('stage=session_lookup result=FAIL', logs)

    def test_revoked_binding_still_denies_registration(self):
        from dataclasses import replace
        self.store.lookup.return_value = replace(self.store.lookup.return_value, revoked=True)
        response, logs = self.request()
        self.assertEqual(response.status_code, 401)
        self.assertIn('stage=session_binding result=FAIL', logs)
        self.assertNotIn('stage=register_a', logs)

    def test_real_store_cipher_and_db_failure_stages(self):
        connection, cursor = Mock(), Mock()
        connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
        connection.cursor.return_value.__exit__ = Mock(return_value=False)
        cursor.fetchall.return_value = [{'version': 1}]
        store = CoreStore(self.config.encryption_key, self.config.hmac_key, connector=lambda: connection)
        row = dict(revoked_at=None, expires_at=utc(NOW+600), csrf_hash=digest('private-csrf'),
                   fingerprint=b'f'*32, jwt_ciphertext=store.encrypt('private-token', b'f'*32))
        cursor.fetchone.return_value = row
        with self.assertLogs('uvicorn.error', level='INFO') as captured:
            self.assertEqual(store.cookie_token('private-cookie', now=NOW, csrf='private-csrf')[0], 'private-token')
        self.assertIn('stage=token_decrypt result=PASS', '\n'.join(captured.output))
        row['jwt_ciphertext'] = b'broken'
        with self.assertLogs('uvicorn.error', level='INFO') as captured, self.assertRaises(Exception):
            store.cookie_token('private-cookie', now=NOW)
        self.assertIn('stage=token_decrypt result=FAIL', '\n'.join(captured.output))
        store._connect = Mock(side_effect=pymysql.OperationalError(2003, 'private-exception'))
        with self.assertLogs('uvicorn.error', level='INFO') as captured, self.assertRaises(Exception):
            store.cookie_token('private-cookie', now=NOW)
        logs = '\n'.join(captured.output)
        self.assertIn('auth_database stage=connect result=FAIL', logs)
        self.assertNotIn('private-exception', logs)
