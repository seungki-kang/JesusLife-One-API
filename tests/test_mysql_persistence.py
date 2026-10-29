"""Opt-in integration tests. All identities and records are freshly generated synthetic data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pymysql

from app.core.auth import AuthContext, get_current_user
from app.core.database import connect, settings
from app.main import app
from app.modules.neorang_narang.mysql_store import MySQLCompletionStore
from app.modules.neorang_narang.schemas import CompletionRecordMetadata
from app.modules.neorang_narang.service import CompletionService
from app.modules.neorang_narang.store import get_completion_store

PATH = '/api/v1/neorang-narang/completions'


@unittest.skipUnless(os.environ.get('RUN_MYSQL_TESTS') == '1', 'Opt-in local synthetic MySQL tests')
class MySQLPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.owner = uuid4()
        self.other = uuid4()
        self.store = MySQLCompletionStore()
        self.service = CompletionService(self.store, AuthContext(sub=self.owner))
        self.metadata = CompletionRecordMetadata(
            id=uuid4(), course_number=1, participation_mode='solo',
            completed_at='2026-10-01T09:00:00.123456+09:00', revision=1)
        self.addCleanup(app.dependency_overrides.clear)

    def assert_status(self, status, operation):
        with self.assertRaises(HTTPException) as caught:
            operation()
        self.assertEqual(caught.exception.status_code, status)

    def test_roundtrip_reconnect_create_replay_and_microseconds(self):
        result, created = self.service.create(self.metadata)
        self.assertTrue(created)
        fresh = CompletionService(MySQLCompletionStore(), AuthContext(sub=self.owner))
        self.assertEqual(fresh.get(self.metadata.id), self.metadata)
        retry, created = fresh.create(self.metadata)
        self.assertFalse(created)
        self.assertTrue(retry.replayed)
        self.assertEqual(retry.updated_at, result.updated_at)
        self.assert_status(409, lambda: fresh.create(self.metadata.model_copy(update={'course_number': 2})))

    def test_api_timestamp_range_preserved(self):
        for timestamp in ('0001-01-01T00:00:00Z', '9999-12-31T23:59:59.999999Z'):
            record = CompletionRecordMetadata.model_validate(self.metadata.model_dump() | {
                'id': uuid4(), 'completed_at': timestamp})
            self.service.create(record)
            self.assertEqual(self.service.get(record.id), record)

    def test_concurrent_create_and_update_across_connections(self):
        barrier = Barrier(2)
        def create(_):
            svc = CompletionService(MySQLCompletionStore(), AuthContext(sub=self.owner))
            barrier.wait(timeout=10)
            return svc.create(self.metadata)[1]
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(create, range(2))), [False, True])
        def update(course):
            svc = CompletionService(MySQLCompletionStore(), AuthContext(sub=self.owner))
            barrier.wait(timeout=10)
            try:
                svc.update(self.metadata.id, 1, self.metadata.model_copy(update={'revision': 2, 'course_number': course}))
                return 200
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(update, (1, 2))), [200, 409])
        self.assertEqual(self.service.get(self.metadata.id).revision, 2)

    def test_owner_isolation_and_same_id_independent(self):
        self.service.create(self.metadata)
        other = CompletionService(MySQLCompletionStore(), AuthContext(sub=self.other))
        self.assertEqual(other.list(20), [])
        self.assert_status(404, lambda: other.get(self.metadata.id))
        self.assert_status(404, lambda: other.delete(self.metadata.id, 1, 2))
        self.assert_status(404, lambda: other.update(self.metadata.id, 1, self.metadata.model_copy(update={'revision': 2})))
        other.create(self.metadata.model_copy(update={'course_number': 2}))
        self.assertEqual(self.service.get(self.metadata.id).course_number, 1)
        self.assertEqual(other.get(self.metadata.id).course_number, 2)

    def test_tombstone_reconnect_retry_and_no_resurrection(self):
        self.service.create(self.metadata)
        first = self.service.delete(self.metadata.id, 1, 2)
        fresh = CompletionService(MySQLCompletionStore(), AuthContext(sub=self.owner))
        retry = fresh.delete(self.metadata.id, 1, 2)
        self.assertTrue(retry.replayed)
        self.assertEqual(first.metadata, retry.metadata)
        self.assertEqual(fresh.list(20), [])
        self.assert_status(404, lambda: fresh.get(self.metadata.id))
        self.assert_status(409, lambda: fresh.create(self.metadata))
        self.assert_status(409, lambda: fresh.delete(self.metadata.id, 2, 3))

    def test_transaction_rollback_and_connection_failure_safe_503(self):
        from app.modules.neorang_narang.store import StoredCompletion
        with self.assertRaises(RuntimeError):
            with self.store.transaction(self.owner):
                self.store.save(StoredCompletion(self.owner, self.metadata, datetime.now(timezone.utc)))
                raise RuntimeError('Synthetic rollback')
        self.assert_status(404, lambda: self.service.get(self.metadata.id))
        def broken():
            raise pymysql.OperationalError(2003, 'SYNTHETIC_PRIVATE')
        app.dependency_overrides[get_current_user] = lambda: AuthContext(sub=self.owner)
        app.dependency_overrides[get_completion_store] = lambda: MySQLCompletionStore(broken)
        response = TestClient(app).get(PATH)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'Storage unavailable'})

    def test_database_and_ddl_privilege_isolation(self):
        config = settings()
        for database, user, password, forbidden in (
            ('neorang_narang', 'nn_app', config['NN_DB_PASSWORD'], 'life_diary'),
            ('life_diary', 'life_diary_app', config['LIFE_DIARY_DB_PASSWORD'], 'neorang_narang'),
        ):
            with connect(database=database, user=user, password=password) as connection:
                with connection.cursor() as cursor:
                    with self.assertRaises(pymysql.MySQLError):
                        cursor.execute(f'USE {forbidden}')
                    with self.assertRaises(pymysql.MySQLError):
                        cursor.execute(f'CREATE TABLE {database}.synthetic_forbidden (id INT)')
                    if database == 'neorang_narang':
                        with self.assertRaises(pymysql.MySQLError):
                            cursor.execute('DELETE FROM nn_completion_records WHERE 1=0')
            with self.assertRaises(pymysql.MySQLError):
                connect(database=forbidden, user=user, password=password)
        with connect(admin=True, database='life_diary') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SHOW TABLES')
                self.assertEqual(cursor.fetchall(), ())

    def test_actual_auth_stays_closed_and_test_only_http_crud(self):
        with TestClient(app) as client:
            for method, url, body in (
                ('POST', PATH, self.metadata.model_dump(mode='json')),
                ('GET', PATH, None), ('GET', PATH+'/'+str(self.metadata.id), None),
                ('PUT', PATH+'/'+str(self.metadata.id), {}), ('DELETE', PATH+'/'+str(self.metadata.id), {}),
            ):
                self.assertEqual(client.request(method, url, json=body).status_code, 401)
            app.dependency_overrides[get_current_user] = lambda: AuthContext(sub=self.owner)
            # Uses actual configured MySQL dependency. No production bypass is added.
            self.assertEqual(client.post(PATH, json=self.metadata.model_dump(mode='json')).status_code, 201)
            self.assertEqual(client.get(PATH+'/'+str(self.metadata.id)).status_code, 200)
            changed = CompletionRecordMetadata.model_validate(self.metadata.model_dump() | {'revision': 2, 'course_number': 2})
            self.assertEqual(client.put(PATH+'/'+str(self.metadata.id), json={
                'base_revision': 1, 'metadata': changed.model_dump(mode='json')}).status_code, 200)
            self.assertEqual(client.request('DELETE', PATH+'/'+str(self.metadata.id), json={
                'base_revision': 2, 'revision': 3}).status_code, 200)
            self.assertEqual(client.get(PATH+'/'+str(self.metadata.id)).status_code, 404)

    def test_schema_gate_and_commit_failure(self):
        from unittest.mock import MagicMock
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        store = MySQLCompletionStore(lambda: connection)
        self.assert_status(503, lambda: CompletionService(store, AuthContext(sub=self.owner)).list(10))
        connection.close.assert_called_once()
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [{'version': 1}]
        connection.commit.side_effect = pymysql.OperationalError(2013, 'SYNTHETIC_PRIVATE')
        store = MySQLCompletionStore(lambda: connection)
        with self.assertRaises(HTTPException) as caught:
            with store.transaction(self.owner):
                pass
        self.assertEqual(caught.exception.detail, 'Storage unavailable')
        connection.rollback.assert_called_once()


if __name__ == '__main__':
    unittest.main()
