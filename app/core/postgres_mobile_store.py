"""PostgreSQL persistence for the isolated Life Diary authentication service."""
from contextlib import contextmanager

from fastapi import HTTPException
import psycopg
from psycopg.rows import dict_row

from .mobile_store import MobileCoreStore
from .postgres import PostgresConnectionError
from .postgres_settings import PostgresConfigurationError


class PostgresMobileStore(MobileCoreStore):
    integrity_error = psycopg.errors.UniqueViolation
    retryable_write_error = (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure)

    @staticmethod
    def is_write_conflict(error):
        return True

    @contextmanager
    def transaction(self):
        try:
            with self._connect() as db:
                db.row_factory = dict_row
                db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                db.execute('SET LOCAL search_path TO jl_ld_auth, pg_catalog, pg_temp')
                if db.execute('SELECT version FROM core_schema_version ORDER BY version').fetchall() != [{'version': 1}]:
                    raise HTTPException(503, 'Authentication unavailable')
                yield db
            return
        except (PostgresConnectionError, PostgresConfigurationError, psycopg.Error):
            pass
        raise HTTPException(503, 'Authentication unavailable')
