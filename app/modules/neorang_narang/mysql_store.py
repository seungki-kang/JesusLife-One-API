"""Owner locks serialize commands across processes; one connection per transaction."""
from contextlib import contextmanager
from datetime import timezone
from threading import local
from uuid import UUID

import pymysql
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.database import connect
from .schemas import CompletionRecordMetadata
from .store import StoredCompletion


class MySQLCompletionStore:
    def __init__(self, connector=connect):
        self._connect = connector
        self._local = local()

    @contextmanager
    def transaction(self, owner):
        connection = None
        try:
            connection = self._connect()
            self._local.connection = connection
            self._local.owner = owner
            with connection.cursor() as cursor:
                # Schema read must not freeze a REPEATABLE READ snapshot before the owner lock.
                cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            connection.begin()
            with connection.cursor() as cursor:
                cursor.execute('SELECT version FROM nn_schema_version ORDER BY version')
                if cursor.fetchall() != [{'version': 1}]:
                    raise HTTPException(503, 'Storage unavailable')
                cursor.execute('INSERT INTO nn_completion_owners (owner_sub) VALUES (%s) '
                               'ON DUPLICATE KEY UPDATE owner_sub=owner_sub', (str(owner),))
                cursor.execute('SELECT owner_sub FROM nn_completion_owners WHERE owner_sub=%s FOR UPDATE',
                               (str(owner),))
                cursor.fetchone()
            yield
            connection.commit()
        except (pymysql.MySQLError, ValidationError, ValueError, OverflowError):
            raise HTTPException(503, 'Storage unavailable') from None
        finally:
            if connection is not None:
                try:
                    connection.rollback()
                except pymysql.MySQLError:
                    pass
                try:
                    connection.close()
                except pymysql.MySQLError:
                    pass
            self._local.connection = None
            self._local.owner = None

    def _cursor(self, owner):
        if self._local.owner != owner:
            raise RuntimeError('Invalid store transaction')
        return self._local.connection.cursor()

    @staticmethod
    def _record(row):
        if row is None:
            return None
        def utc(value):
            return None if value is None else value.replace(tzinfo=timezone.utc)
        metadata = CompletionRecordMetadata(
            id=row['record_id'], course_number=row['course_number'],
            participation_mode=row['participation_mode'], completed_at=utc(row['completed_at']),
            revision=row['revision'], deleted_at=utc(row['deleted_at']))
        return StoredCompletion(UUID(row['owner_sub']), metadata, utc(row['updated_at']), row['delete_base'])

    def get(self, owner, record_id):
        with self._cursor(owner) as cursor:
            cursor.execute('SELECT * FROM nn_completion_records WHERE owner_sub=%s AND record_id=%s',
                           (str(owner), str(record_id)))
            return self._record(cursor.fetchone())

    def list_for_owner(self, owner):
        with self._cursor(owner) as cursor:
            cursor.execute('SELECT * FROM nn_completion_records WHERE owner_sub=%s', (str(owner),))
            return [self._record(row) for row in cursor.fetchall()]

    def save(self, record):
        m = record.metadata
        def naive(value):
            return None if value is None else value.astimezone(timezone.utc).replace(tzinfo=None)
        with self._cursor(record.owner_sub) as cursor:
            cursor.execute('INSERT INTO nn_completion_records '
                           '(owner_sub,record_id,course_number,participation_mode,completed_at,revision,deleted_at,updated_at,delete_base) '
                           'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) AS incoming '
                           'ON DUPLICATE KEY UPDATE course_number=incoming.course_number, '
                           'participation_mode=incoming.participation_mode, revision=incoming.revision, '
                           'deleted_at=incoming.deleted_at, updated_at=incoming.updated_at, delete_base=incoming.delete_base',
                           (str(record.owner_sub), str(m.id), int(m.course_number), str(m.participation_mode),
                            naive(m.completed_at), m.revision, naive(m.deleted_at), naive(record.updated_at), record.delete_base))
