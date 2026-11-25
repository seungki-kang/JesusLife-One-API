"""Authentication hook tests using synthetic stores and provider responses."""
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.core.common_mobile_auth import (
    CommonMobileAuthStore, MobileRegistration, install_common_mobile,
)


class OwnerHookTests(unittest.TestCase):
    def setUp(self):
        self.account = uuid4()
        self.session_id = uuid4()
        self.row = {
            'app_id': b'life_diary',
            'client_id': b'synthetic-client',
            'session_id': str(self.session_id),
        }
        self.session = SimpleNamespace(
            account_id=self.account, session_id=self.session_id, version=1)
        self.token = SimpleNamespace(
            fingerprint='synthetic-fingerprint', scopes=frozenset({'openid'}))
        self.store = MagicMock(spec=CommonMobileAuthStore)
        self.store._app_id = 'life_diary'
        self.store.cookie_token.return_value = ('synthetic-provider-token', self.row)
        self.store.lookup.return_value = self.session
        self.provider = MagicMock()
        self.provider.verify_access.return_value = self.token
        runtime = SimpleNamespace(
            store=self.store, provider=self.provider,
            config=SimpleNamespace(
                policy=SimpleNamespace(client_ids=frozenset({'synthetic-client'}))),
            now=lambda: 1800000000,
        )
        self.app = FastAPI()
        owners = install_common_mobile(self.app, (
            MobileRegistration('life_diary', 'synthetic-client', runtime, True),
        ))
        self.assertEqual(set(owners), {'life_diary'})
        owner = owners['life_diary']

        @self.app.get('/__test_owner')
        def test_owner(request: Request):
            return {'owner': str(owner(request))}

        self.binding_patch = patch(
            'app.core.common_mobile_auth.validate_binding_candidate')
        self.validate_binding = self.binding_patch.start()
        self.addCleanup(self.binding_patch.stop)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def call(self):
        return self.client.get(
            '/__test_owner',
            headers={'Authorization': 'Bearer synthetic-credential'})

    def test_missing_bearer_stops_before_store(self):
        self.assertEqual(self.client.get('/__test_owner').status_code, 401)
        self.store.cookie_token.assert_not_called()

    def test_valid_identity_returns_verified_account_only(self):
        response = self.call()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'owner': str(self.account)})
        self.store.cookie_token.assert_called_once_with(
            'synthetic-credential', now=1800000000)
        self.validate_binding.assert_called_once_with(
            self.token, self.session, expected_version=1, now=1800000000)
        self.store.mobile_status.assert_not_called()
        self.assertFalse(any('/backup' in path for path in self.app.openapi()['paths']))

    def test_other_app_session_is_rejected(self):
        self.row['app_id'] = b'neorang_narang'
        self.assertEqual(self.call().status_code, 401)
        self.provider.verify_access.assert_not_called()

    def test_other_client_session_is_rejected(self):
        self.row['client_id'] = b'other-client'
        self.assertEqual(self.call().status_code, 401)
        self.provider.verify_access.assert_not_called()

    def test_missing_or_mismatched_session_is_rejected(self):
        for value in (None, SimpleNamespace(session_id=uuid4())):
            with self.subTest(value=value):
                self.store.lookup.return_value = value
                self.assertEqual(self.call().status_code, 401)

    def test_store_rejection_is_preserved(self):
        self.store.cookie_token.side_effect = HTTPException(401, 'Denied')
        self.assertEqual(self.call().status_code, 401)
        self.provider.verify_access.assert_not_called()

    def test_provider_rejection_is_preserved(self):
        self.provider.verify_access.side_effect = HTTPException(401, 'Denied')
        self.assertEqual(self.call().status_code, 401)
        self.store.lookup.assert_not_called()

    def test_binding_validator_rejection_is_preserved(self):
        self.validate_binding.side_effect = HTTPException(401, 'Denied')
        self.assertEqual(self.call().status_code, 401)

    def test_missing_openid_scope_is_rejected(self):
        self.token.scopes = frozenset()
        self.assertEqual(self.call().status_code, 401)


if __name__ == '__main__':
    unittest.main()
