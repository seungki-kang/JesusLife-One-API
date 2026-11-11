from contextlib import contextmanager
from types import SimpleNamespace
import sqlite3

import pytest
from fastapi import HTTPException

from app.core.mobile_backup_store import access_backup, erase_backups


class Cursor:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, args=()):
        if 'information_schema.tables' in sql:
            sql = "SELECT 1 FROM sqlite_master WHERE name='nn_mobile_backups'"
        self.result = self.db.execute(sql.replace(' FOR UPDATE', '').replace('%s', '?'), args)

    def fetchone(self):
        return self.result.fetchone()


class Store:
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE mobile_consents(account_id TEXT PRIMARY KEY,
                generation INTEGER, active INTEGER, deletion_through INTEGER);
            INSERT INTO mobile_consents VALUES ('a',1,1,0), ('b',1,1,0);
            CREATE TABLE nn_mobile_backups(account_id TEXT, generation INTEGER,
                revision INTEGER, envelope BLOB, PRIMARY KEY(account_id,generation));
        """)

    @contextmanager
    def transaction(self):
        @contextmanager
        def cursor():
            yield Cursor(self.db)

        with self.db:
            yield SimpleNamespace(cursor=cursor)

    def ready(self, cursor):
        pass


def upload(generation=1, revision=0, envelope='A' * 80):
    return SimpleNamespace(generation=generation, base_revision=revision, envelope=envelope)


def test_owner_isolation_and_retry_revision():
    store = Store()
    assert access_backup(store, 'a', update=upload())['revision'] == 1
    assert access_backup(store, 'a', update=upload())['revision'] == 1
    with pytest.raises(HTTPException) as missing:
        access_backup(store, 'b')
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as conflict:
        access_backup(store, 'a', update=upload(envelope='B' * 80))
    assert conflict.value.status_code == 409
    assert access_backup(store, 'a')['envelope'] == 'A' * 80
    assert access_backup(store, 'a', update=upload(revision=1, envelope='B' * 80))['revision'] == 2


def test_revoke_erases_old_backup_and_regrant_rejects_old_upload():
    store = Store()
    access_backup(store, 'a', update=upload())
    access_backup(store, 'b', update=upload())
    with store.transaction() as connection, connection.cursor() as cursor:
        erase_backups(cursor, 'a', 1)
        cursor.execute("UPDATE mobile_consents SET generation=2,deletion_through=1 WHERE account_id='a'")
    assert access_backup(store, 'b')['revision'] == 1
    with pytest.raises(HTTPException) as missing:
        access_backup(store, 'a')
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as expired:
        access_backup(store, 'a', update=upload())
    assert expired.value.status_code == 409
    assert store.db.execute("SELECT COUNT(*) FROM nn_mobile_backups WHERE account_id='a'").fetchone()[0] == 0


def test_disabled_consent_and_missing_migration_fail_closed():
    store = Store()
    with pytest.raises(HTTPException) as denied:
        access_backup(store, 'unknown', update=upload())
    assert denied.value.status_code == 403
    store.db.execute('DROP TABLE nn_mobile_backups')
    with pytest.raises(HTTPException) as unavailable:
        access_backup(store, 'a', update=upload())
    assert unavailable.value.status_code == 503
