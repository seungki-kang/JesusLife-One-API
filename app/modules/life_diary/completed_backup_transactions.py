"""Dedicated backup transactions; no default connector or startup connection."""
from contextlib import contextmanager
from uuid import UUID

from fastapi import HTTPException
import psycopg
from psycopg.rows import dict_row

from app.core.postgres import PostgresConnectionError
from app.core.postgres_settings import PostgresConfigurationError


class CompletedBackupTransactions:
    def __init__(self, *, connector):
        # Connector must separately enforce the reviewed target and TLS settings.
        if not callable(connector):
            raise ValueError('Explicit dedicated backup connector required')
        self._connector = connector

    @contextmanager
    def __call__(self, account):
        account = UUID(str(account))
        failed = False
        try:
            with self._connector() as db:
                if db.autocommit:
                    raise PostgresConnectionError('Backup transaction required')
                db.row_factory = dict_row
                db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                db.execute('SET LOCAL search_path TO pg_catalog, jl_ld_backup, pg_temp')
                role = db.execute(
                    "SELECT current_user = 'jl_ld_backup_runtime' AS expected_role, "
                    "NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb "
                    "AND NOT rolcreaterole AND NOT rolreplication AND NOT rolinherit "
                    "AND NOT pg_has_role(current_user, 'jl_migration_owner', 'MEMBER') "
                    "AS restricted FROM pg_roles WHERE rolname=current_user"
                ).fetchone()
                if role != {'expected_role': True, 'restricted': True}:
                    raise PostgresConnectionError('Backup role rejected')
                db.execute(
                    "SELECT set_config('jesuslife.backup_app_id', %s, true)",
                    ('life_diary',),
                )
                db.execute(
                    "SELECT set_config('jesuslife.backup_account_id', %s, true)",
                    (str(account),),
                )
                versions = db.execute(
                    'SELECT version FROM jl_ld_backup.schema_version ORDER BY version'
                ).fetchall()
                if versions != [{'version': 1}]:
                    raise PostgresConnectionError('Backup schema unavailable')
                yield db
        except (PostgresConnectionError, PostgresConfigurationError, psycopg.Error):
            failed = True
        if failed:
            raise HTTPException(503, 'Backup storage unavailable')
