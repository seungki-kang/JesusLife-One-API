"""Actual server-factory composition tests; no DB or external Auth0."""
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.common_mobile_auth import CommonMobileAuthStore
from app.modules.life_diary.completed_backup_store import CompletedBackupStore
from scripts.life_diary_common_cloud import create_app

PREFIX = '/api/v1/mobile/life-diary/backup'


class BackupCompositionTests(unittest.TestCase):
    def setUp(self):
        self.account = uuid4()
        self.session_id = uuid4()
        self.config = SimpleNamespace(
            enabled=True, app_id='life_diary',
            policy=SimpleNamespace(client_ids=frozenset({'synthetic-client'})))
        self.auth = MagicMock(spec=CommonMobileAuthStore)
        self.auth._app_id = 'life_diary'
        self.row = {
            'app_id': b'life_diary',
            'client_id': b'synthetic-client',
            'session_id': str(self.session_id),
        }
        self.auth.cookie_token.return_value = ('synthetic-token', self.row)
        self.auth.lookup.return_value = SimpleNamespace(
            account_id=self.account, session_id=self.session_id, version=1)
        self.provider = MagicMock()
        self.provider.verify_access.return_value = SimpleNamespace(
            fingerprint='synthetic-fingerprint', scopes=frozenset({'openid'}))
        self.backup = MagicMock(spec=CompletedBackupStore)
        self.backup.grant.return_value = 1
        self.binding_patch = patch(
            'app.core.common_mobile_auth.validate_binding_candidate')
        self.binding_patch.start()
        self.addCleanup(self.binding_patch.stop)

    def client(self, enabled=False):
        options = {'backup_store': self.backup} if enabled else {}
        app = create_app(
            self.config, self.auth, provider=self.provider,
            clock=lambda: 1800000000, **options)
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def test_default_has_no_backup_routes_or_auth_store_access(self):
        client = self.client()
        backup_id = uuid4()
        responses = [
            client.post(PREFIX + '/consent'),
            client.get(f'{PREFIX}/entries/1/{backup_id}'),
            client.delete(PREFIX + '/consent/1'),
        ]
        self.assertEqual([r.status_code for r in responses], [404] * 3)
        self.assertEqual(self.auth.mock_calls, [])
        self.assertEqual(self.backup.mock_calls, [])

    def test_opt_in_rejects_unauthenticated_request(self):
        response = self.client(True).post(PREFIX + '/consent')
        self.assertEqual(response.status_code, 401)
        self.backup.grant.assert_not_called()
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_opt_in_uses_verified_account(self):
        response = self.client(True).post(
            PREFIX + '/consent',
            headers={'Authorization': 'Bearer synthetic-credential'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'generation': 1})
        self.backup.grant.assert_called_once_with(self.account)
        self.auth.mobile_status.assert_not_called()

    def test_neorang_session_cannot_grant_life_diary_backup(self):
        self.row['app_id'] = b'neorang_narang'
        response = self.client(True).post(
            PREFIX + '/consent',
            headers={'Authorization': 'Bearer synthetic-credential'})
        self.assertEqual(response.status_code, 401)
        self.backup.grant.assert_not_called()

    def test_unexpected_store_failure_is_sanitized(self):
        self.backup.grant.side_effect = RuntimeError('synthetic-private-detail')
        response = self.client(True).post(
            PREFIX + '/consent',
            headers={'Authorization': 'Bearer synthetic-credential'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('synthetic-private-detail', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_untyped_backup_store_is_rejected(self):
        with self.assertRaises(ValueError):
            create_app(
                self.config, self.auth, provider=self.provider,
                backup_store=object())


if __name__ == '__main__':
    unittest.main()
