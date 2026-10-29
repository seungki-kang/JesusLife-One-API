"""Synthetic local checks with failure details suppressed (no row/credential output)."""
import argparse
import hashlib
import io
import json
import os
import secrets
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from uuid import UUID, uuid4

from app.core.auth import AuthContext, get_current_user
from app.core.database import ROOT, connect
from app.main import app
from app.modules.neorang_narang.mysql_store import MySQLCompletionStore
from app.modules.neorang_narang.service import CompletionService
from app.modules.neorang_narang.schemas import CompletionRecordMetadata
from scripts.local_mysql import migrate, snapshot


def run_tests():
    os.environ['RUN_MYSQL_TESTS'] = '1'
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=2).run(suite)
    for case, _ in result.failures + result.errors:
        print('FAIL:', case.id())
    print(f'Tests: {result.testsRun}; failures: {len(result.failures)}; errors: {len(result.errors)}; skipped: {len(result.skipped)}')
    if not result.wasSuccessful():
        raise RuntimeError('Tests failed')


def database_snapshot():
    with connect(admin=True, database='neorang_narang') as connection:
        return snapshot(connection)


def digest(value):
    return hashlib.sha256(repr(value).encode('utf-8')).hexdigest()


def checkpoint():
    value = database_snapshot()
    assert value['nn_completion_records'], 'Missing synthetic fixtures'
    assert any(row['deleted_at'] for row in value['nn_completion_records']), 'Missing tombstone'
    (ROOT / '.env.verification').write_text(json.dumps({'digest': digest(value)}), encoding='utf-8')


def verify_checkpoint():
    expected = json.loads((ROOT / '.env.verification').read_text(encoding='utf-8'))
    value = database_snapshot()
    assert expected['digest'] == digest(value)
    # New Python process, new stores/connections; verify the application projection too.
    for row in value['nn_completion_records']:
        owner, record_id = UUID(row['owner_sub']), UUID(row['record_id'])
        svc = CompletionService(MySQLCompletionStore(), AuthContext(sub=owner))
        if row['deleted_at'] is None:
            metadata = svc.get(record_id)
            assert metadata.revision == row['revision']
            assert metadata.completed_at.replace(tzinfo=None) == row['completed_at']
        else:
            try:
                svc.get(record_id)
            except HTTPException as error:
                assert error.status_code == 404
            else:
                raise AssertionError('Tombstone became visible')


def outage():
    # Dependency replacement exists only inside this isolated verification process.
    app.dependency_overrides[get_current_user] = lambda: AuthContext(sub=uuid4())
    try:
        with TestClient(app) as client:
            response = client.get('/api/v1/neorang-narang/completions')
            assert response.status_code == 503
            assert response.json() == {'detail': 'Storage unavailable'}
            assert client.get('/health').status_code == 200
    finally:
        app.dependency_overrides.clear()


def migration_retry():
    database = 'nn_migration_check_' + secrets.token_hex(6)
    with connect(admin=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4')
            cursor.execute(f'USE `{database}`')
            # Simulate DDL interruption before completion-record table/version receipt.
            parts = (ROOT / 'migrations/neorang_narang/001_initial.sql').read_text(encoding='utf-8').split(';')
            for statement in parts[:2]:
                cursor.execute(statement)
        migrate(connection)
        before = snapshot(connection)
        migrate(connection)
        assert snapshot(connection) == before
        with connection.cursor() as cursor:
            cursor.execute('SELECT version FROM nn_schema_version')
            assert cursor.fetchall() == [{'version': 1}]
            cursor.execute('INSERT INTO nn_schema_version VALUES (2, UTC_TIMESTAMP(6))')
        connection.commit()
        future = snapshot(connection)
        try:
            migrate(connection)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Future version accepted')
        assert snapshot(connection) == future
    # Retain synthetic check DB; no destructive rollback or DROP.


def rollback_mode():
    before = digest(database_snapshot())
    with patch.dict(os.environ, {'COMPLETION_STORE': 'memory'}):
        with TestClient(app) as client:
            assert client.get('/api/v1/neorang-narang/completions').status_code == 401
            app.dependency_overrides[get_current_user] = lambda: AuthContext(sub=uuid4())
            try:
                record = CompletionRecordMetadata(id=uuid4(), course_number=1, participation_mode='solo',
                                                  completed_at='2026-10-01T00:00:00Z', revision=1)
                assert client.post('/api/v1/neorang-narang/completions', json=record.model_dump(mode='json')).status_code == 201
            finally:
                app.dependency_overrides.clear()
    assert digest(database_snapshot()) == before


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('tests', 'checkpoint', 'verify-checkpoint', 'outage', 'migration-retry', 'rollback-mode'))
    action = parser.parse_args().action
    try:
        {'tests': run_tests, 'checkpoint': checkpoint, 'verify-checkpoint': verify_checkpoint,
         'outage': outage, 'migration-retry': migration_retry, 'rollback-mode': rollback_mode}[action]()
        print('PASS:', action)
    except Exception:
        print('FAIL:', action, '(details suppressed)')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
