"""Backup HTTP contract tests with synthetic authentication and mocked storage."""
import base64
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.modules.life_diary.completed_backup_router import completed_backup_router

PREFIX = '/api/v1/mobile/life-diary/backup'


class BackupRouterTests(unittest.TestCase):
    def setUp(self):
        self.owner = uuid4()
        self.backup_id = uuid4()
        self.raw = b'x' * 29
        self.payload = {
            'format_version': 1,
            'ciphertext': base64.b64encode(self.raw).decode('ascii'),
        }
        self.store = MagicMock()

        def authenticate(request):
            if request.headers.get('authorization') != 'Bearer synthetic':
                raise HTTPException(401, 'Access denied')
            return self.owner

        app = FastAPI()
        app.include_router(completed_backup_router(
            authenticated_owner=authenticate, store=self.store, enabled=True))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {'Authorization': 'Bearer synthetic'}
        self.path = f'{PREFIX}/entries/1/{self.backup_id}'

    def test_default_router_is_disabled(self):
        app = FastAPI()
        app.include_router(completed_backup_router())
        with TestClient(app) as client:
            self.assertEqual(client.post(PREFIX + '/consent').status_code, 404)

    def test_missing_authentication_never_calls_store(self):
        responses = [
            self.client.post(PREFIX + '/consent'),
            self.client.put(self.path, json=self.payload),
            self.client.get(self.path),
            self.client.delete(PREFIX + '/consent/1'),
        ]
        self.assertEqual([r.status_code for r in responses], [401] * 4)
        self.assertEqual(self.store.mock_calls, [])

    def test_consent_uses_verified_owner(self):
        self.store.grant.return_value = 1
        response = self.client.post(PREFIX + '/consent', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'generation': 1})
        self.store.grant.assert_called_once_with(self.owner)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_upload_and_replay_contract(self):
        for result, expected in (('created', 201), ('replay', 200)):
            self.store.save.return_value = result
            response = self.client.put(
                self.path, json=self.payload, headers=self.headers)
            self.assertEqual(response.status_code, expected)
            self.assertEqual(response.json(), {'result': result})
            self.assertEqual(response.headers['cache-control'], 'no-store')
        self.store.save.assert_called_with(
            self.owner, 1, self.backup_id, self.raw)

    def test_invalid_payload_never_reaches_store(self):
        invalid = [
            self.payload | {'format_version': True},
            self.payload | {'format_version': 2},
            self.payload | {'owner_id': str(uuid4())},
            self.payload | {'ciphertext': '!' * 40},
            self.payload | {'ciphertext': 'x' * 65537},
            self.payload | {'ciphertext': base64.b64encode(b'x' * 28).decode()},
        ]
        for payload in invalid:
            with self.subTest(payload_type=list(payload)):
                response = self.client.put(
                    self.path, json=payload, headers=self.headers)
                self.assertEqual(response.status_code, 422)
        self.store.save.assert_not_called()

    def test_invalid_generation_and_backup_id(self):
        for path in (
            f'{PREFIX}/entries/0/{self.backup_id}',
            f'{PREFIX}/entries/9223372036854775808/{self.backup_id}',
            f'{PREFIX}/entries/1/00000000-0000-0000-0000-000000000000',
        ):
            self.assertEqual(
                self.client.get(path, headers=self.headers).status_code, 422)
        self.store.load.assert_not_called()

    def test_download_contract(self):
        self.store.load.return_value = {
            'format_version': 1, 'ciphertext': self.raw}
        response = self.client.get(self.path, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.payload)
        self.store.load.assert_called_once_with(self.owner, 1, self.backup_id)

    def test_withdrawal_has_empty_204_response(self):
        response = self.client.delete(
            PREFIX + '/consent/1', headers=self.headers)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        self.store.withdraw.assert_called_once_with(self.owner, 1)

    def test_inactive_consent_is_preserved_as_403(self):
        self.store.save.side_effect = HTTPException(403, 'Backup denied')
        response = self.client.put(
            self.path, json=self.payload, headers=self.headers)
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
