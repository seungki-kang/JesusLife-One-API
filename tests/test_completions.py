import unittest
from uuid import UUID

from fastapi.testclient import TestClient
from app.main import app
from app.core.auth import AuthContext, get_current_user
from app.modules.neorang_narang.store import InMemoryCompletionStore, get_completion_store

PATH = '/api/v1/neorang-narang/completions'
OWNER = UUID('00000000-0000-4000-8000-000000000001')
OTHER = UUID('00000000-0000-4000-8000-000000000002')


def metadata(number=1, **changes):
    value = dict(id=f'10000000-0000-4000-8000-{number:012d}', course_number=1,
                 participation_mode='solo', completed_at='2026-10-01T00:00:00Z',
                 revision=1, deleted_at=None)
    return value | changes


class CompletionApiTest(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryCompletionStore()
        app.dependency_overrides[get_completion_store] = lambda: self.store
        self.login(OWNER)
        self.client = TestClient(app)
        self.addCleanup(app.dependency_overrides.clear)

    def login(self, sub):
        app.dependency_overrides[get_current_user] = lambda: AuthContext(sub=sub)

    def create(self, value=None):
        return self.client.post(PATH, json=value or metadata())

    def test_authentication_all_operations(self):
        app.dependency_overrides.pop(get_current_user)
        for method, url, body in [('POST', PATH, metadata()), ('GET', PATH, None),
                                 ('GET', PATH+'/'+metadata()['id'], None),
                                 ('PUT', PATH+'/'+metadata()['id'], {}),
                                 ('DELETE', PATH+'/'+metadata()['id'], {})]:
            with self.subTest(method=method):
                self.assertEqual(self.client.request(method, url, json=body).status_code, 401)

    def test_create_and_retry(self):
        first = self.create()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()['metadata'], metadata())
        retry = self.create(metadata(completed_at='2026-10-01T09:00:00+09:00'))
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()['replayed'])
        self.assertEqual(len(self.client.get(PATH).json()), 1)
        self.assertNotIn('owner_sub', first.text)
        self.assertEqual(self.create(metadata(course_number=2)).status_code, 409)

    def test_reject_extra_fields_without_reflection(self):
        for key in ('owner_sub', 'user_id', 'owner_id', 'name', 'partner_name',
                    'grace_reflection', 'signature', 'SYNTHETIC_FIELD'):
            response = self.create(metadata(**{key: 'SYNTHETIC_PRIVATE'}))
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(key, response.text)
            self.assertNotIn('SYNTHETIC_PRIVATE', response.text)

    def test_initial_revision_and_tombstone(self):
        self.assertEqual(self.create(metadata(revision=2)).status_code, 409)
        self.assertEqual(self.create(metadata(deleted_at='2026-10-02T00:00:00Z')).status_code, 422)

    def test_owner_isolation_and_same_uuid(self):
        self.create()
        url = PATH+'/'+metadata()['id']
        self.assertEqual(self.client.get(url).json()['revision'], 1)
        self.login(OTHER)
        missing = self.client.get(url)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), self.client.get(PATH+'/'+metadata(99)['id']).json())
        self.assertEqual(self.client.get(PATH).json(), [])
        self.assertEqual(self.client.put(url, json={'base_revision': 1, 'metadata': metadata(revision=2)}).status_code, 404)
        self.assertEqual(self.client.request('DELETE', url, json={'base_revision': 1, 'revision': 2}).status_code, 404)
        self.assertEqual(self.create(metadata(course_number=2)).status_code, 201)
        self.login(OWNER)
        self.assertEqual(self.client.get(url).json()['course_number'], 1)

    def test_sort_and_limits(self):
        for number in range(1, 24):
            self.create(metadata(number, completed_at='2026-10-02T00:00:00Z' if number==23 else '2026-10-01T00:00:00Z'))
        result = self.client.get(PATH).json()
        self.assertEqual(len(result), 10)
        self.assertEqual([row['id'] for row in result[:3]], [metadata(n)['id'] for n in (23, 1, 2)])
        self.assertEqual(len(self.client.get(PATH+'?limit=20').json()), 20)
        for limit in ('0', '21', 'bad'):
            self.assertEqual(self.client.get(PATH+'?limit='+limit).status_code, 422)

    def test_update_conflicts_and_immutable_fields(self):
        self.create()
        url = PATH+'/'+metadata()['id']
        command = {'base_revision': 1, 'metadata': metadata(revision=2, course_number=2)}
        response = self.client.put(url, json=command)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['metadata']['revision'], 2)
        self.assertEqual(self.client.put(url, json=command).status_code, 409)
        for change, code in (({'revision': 4}, 409), ({'completed_at': '2026-10-03T00:00:00Z'}, 422),
                             ({'id': metadata(2)['id']}, 422), ({'deleted_at': '2026-10-03T00:00:00Z'}, 422)):
            candidate = metadata(revision=3) | change
            response = self.client.put(url, json={'base_revision': 2, 'metadata': candidate})
            self.assertEqual(response.status_code, code)

    def test_delete_and_safe_retry(self):
        self.create()
        url = PATH+'/'+metadata()['id']
        command = {'base_revision': 1, 'revision': 2}
        self.assertEqual(self.client.request('DELETE', url, json={'base_revision': 0, 'revision': 1}).status_code, 409)
        first = self.client.request('DELETE', url, json=command)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['metadata']['revision'], 2)
        self.assertIsNotNone(first.json()['metadata']['deleted_at'])
        retry = self.client.request('DELETE', url, json=command)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()['metadata'], first.json()['metadata'])
        self.assertTrue(retry.json()['replayed'])
        self.assertEqual(self.client.get(url).json(), {'detail': 'Not Found'})
        self.assertEqual(self.client.get(PATH).json(), [])
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.client.put(url, json={'base_revision': 2, 'metadata': metadata(revision=3)}).status_code, 404)
        self.assertEqual(self.client.request('DELETE', url, json={'base_revision': 2, 'revision': 3}).status_code, 409)

    def test_store_instances_are_isolated(self):
        self.create()
        app.dependency_overrides[get_completion_store] = lambda: InMemoryCompletionStore()
        self.assertEqual(self.client.get(PATH).json(), [])


    def test_concurrent_updates_compare_and_save_atomically(self):
        from concurrent.futures import ThreadPoolExecutor
        from fastapi import HTTPException
        from app.modules.neorang_narang.service import CompletionService
        from app.modules.neorang_narang.schemas import CompletionRecordMetadata
        service = CompletionService(self.store, AuthContext(sub=OWNER))
        service.create(CompletionRecordMetadata(**metadata()))

        def write(course):
            try:
                service.update(UUID(metadata()['id']), 1,
                               CompletionRecordMetadata(**metadata(revision=2, course_number=course)))
                return 200
            except HTTPException as error:
                return error.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(write, (1, 2))), [200, 409])
        self.assertEqual(self.client.get(PATH+'/'+metadata()['id']).json()['revision'], 2)

    def test_defensive_guard_and_default_store(self):
        from dataclasses import replace
        from app.modules.neorang_narang.service import CompletionService
        from app.modules.neorang_narang.schemas import CompletionRecordMetadata
        from unittest.mock import patch
        from fastapi import HTTPException
        service = CompletionService(self.store, AuthContext(sub=OWNER))
        service.create(CompletionRecordMetadata(**metadata()))
        record = self.store.get(OWNER, UUID(metadata()['id']))
        with patch.object(self.store, 'get', return_value=replace(record, owner_sub=OTHER)):
            with self.assertRaises(HTTPException) as caught:
                service.get(UUID(metadata()['id']))
            self.assertEqual(caught.exception.status_code, 404)
        app.dependency_overrides.pop(get_completion_store)
        import os
        with patch.dict(os.environ, {'COMPLETION_STORE': 'memory'}):
            self.assertEqual(self.client.get(PATH).json(), [])

    def test_validation_on_commands_and_paths_is_safe(self):
        self.create()
        url = PATH+'/'+metadata()['id']
        for method, target, body in (
            ('PUT', url, {'base_revision': True, 'metadata': metadata(revision=2)}),
            ('DELETE', url, {'base_revision': 1, 'revision': 2, 'SYNTHETIC_FIELD': 'SYNTHETIC_PRIVATE'}),
            ('GET', PATH+'/SYNTHETIC_PRIVATE', None),
        ):
            response = self.client.request(method, target, json=body)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json(), {'detail': 'Invalid request'})
