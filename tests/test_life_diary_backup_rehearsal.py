from base64 import b64encode
from unittest import TestCase
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.modules.life_diary.backup_rehearsal import rehearsal_router


class BackupRehearsalTest(TestCase):
    def setUp(self):
        self.owner, self.other = uuid4(), uuid4()
        self.sessions = {'Bearer owner-test': self.owner, 'Bearer other-test': self.other}
        self.enabled = {self.owner, self.other}

        def authenticate(request):
            owner = self.sessions.get(request.headers.get('Authorization'))
            if owner is None:
                raise HTTPException(401, 'Authentication required')
            return owner

        app = FastAPI()
        app.include_router(rehearsal_router(authenticate, self.enabled.__contains__))
        self.client = self.enterContext(TestClient(app))
        self.path = f'/api/v1/mobile/life-diary/backup/entries/{uuid4()}'
        self.headers = {'Authorization': 'Bearer owner-test'}
        self.payload = {'format_version': 1, 'ciphertext': b64encode(bytes(range(32))).decode()}

    def save(self, payload=None):
        return self.client.put(self.path, headers=self.headers,
                               json=self.payload if payload is None else payload)

    def test_owner_can_store_and_read(self):
        self.assertEqual(self.save().status_code, 201)
        read = self.client.get(self.path, headers=self.headers)
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.headers['Cache-Control'], 'no-store')
        self.assertEqual(read.json(), self.payload)

    def test_other_account_cannot_read(self):
        self.assertEqual(self.save().status_code, 201)
        read = self.client.get(self.path, headers={'Authorization': 'Bearer other-test'})
        self.assertEqual(read.status_code, 404)

    def test_identical_retry_returns_existing_success(self):
        self.assertEqual(self.save().status_code, 201)
        result = self.save()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), self.payload)

    def test_conflicting_retry_preserves_original(self):
        self.assertEqual(self.save().status_code, 201)
        self.assertEqual(self.save(self.payload | {'ciphertext': 'QUJDRA=='}).status_code, 409)
        self.assertEqual(self.client.get(self.path, headers=self.headers).json(), self.payload)

    def test_backup_requires_opt_in(self):
        self.enabled.remove(self.owner)
        self.assertEqual(self.save().status_code, 403)

    def test_revoked_session_cannot_upload_or_read(self):
        self.assertEqual(self.save().status_code, 201)
        self.sessions.clear()
        self.assertEqual(self.save().status_code, 401)
        self.assertEqual(self.client.get(self.path, headers=self.headers).status_code, 401)

    def test_invalid_encoding_and_extra_fields_rejected(self):
        self.assertEqual(self.save(self.payload | {'ciphertext': '!!!?'}).status_code, 422)
        rejected = self.save(self.payload | {'owner_id': str(self.other)})
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json(), {'detail': 'Invalid request'})
        self.assertEqual(self.save().status_code, 201)
