"""Candidate common authentication broker; explicit connector, no DB fallback.

Not a product data repository. No mobile handoff or cloud entrypoint is installed.
Reuses the existing cryptographic/login contract, not the legacy connector.
"""
from contextlib import contextmanager

from fastapi import HTTPException
import psycopg
from psycopg.rows import dict_row

from .core_store import CoreStore, utc
from .postgres import PostgresConnectionError
from .postgres_settings import PostgresConfigurationError


APP_IDS = frozenset({
    'neorang_narang', 'life_diary', 'jl_bible', 'jl_prayer',
    'jesuslife_academy', 'churchos',
})


class PostgresCommonAuthStore(CoreStore):
    """One trusted server app context per store; never accept it from a header."""

    integrity_error = psycopg.errors.UniqueViolation
    retryable_write_error = (
        psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure,
    )

    def __init__(self, encryption_key, hmac_key, *, connector, app_id):
        if app_id not in APP_IDS or not callable(connector):
            raise ValueError('Explicit common authentication connector and app required')
        super().__init__(encryption_key, hmac_key, connector=connector)
        self._app_id = app_id

    @staticmethod
    def is_write_conflict(error):
        return isinstance(error, PostgresCommonAuthStore.retryable_write_error)

    @contextmanager
    def transaction(self):
        failed = False
        try:
            # A fresh caller-owned psycopg connection is required. Its context
            # commits on success, rolls back on any exception, and closes it.
            with self._connect() as db:
                if db.autocommit:
                    raise PostgresConnectionError('Common authentication transaction required')
                db.row_factory = dict_row
                db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                db.execute('SET LOCAL search_path TO pg_catalog, jl_core_auth, pg_temp')
                role = db.execute(
                    "SELECT current_user = 'jl_core_auth_runtime' AS expected_role, "
                    "NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb "
                    "AND NOT rolcreaterole AND NOT rolreplication AND NOT rolinherit "
                    "AND NOT pg_has_role(current_user, 'jl_migration_owner', 'MEMBER') AS restricted "
                    "FROM pg_roles WHERE rolname=current_user"
                ).fetchone()
                if role != {'expected_role': True, 'restricted': True}:
                    raise PostgresConnectionError('Common authentication role rejected')
                db.execute("SELECT set_config('jesuslife.auth_app_id', %s, true)",
                           (self._app_id,))
                if db.execute(
                    'SELECT version FROM jl_core_auth.core_schema_version ORDER BY version'
                ).fetchall() != [{'version': 1}]:
                    raise PostgresConnectionError('Common authentication schema unavailable')
                yield db
        except (PostgresConnectionError, PostgresConfigurationError, psycopg.Error):
            failed = True
        if failed:
            # Outside the except block: never retain credential-bearing drivers.
            raise HTTPException(503, 'Common PostgreSQL authentication unavailable')

    def complete_login(self, *, app_id=None, **kwargs):
        if app_id is not None and app_id != self._app_id:
            raise HTTPException(401, 'Access denied')
        return super().complete_login(app_id=self._app_id, **kwargs)

    def grant_consent(self, account, *, now):
        # Compatibility only for the old explicit metadata consent. It is NOT
        # permission to back up originals or use personal CHGO input.
        if self._app_id != 'neorang_narang':
            raise HTTPException(403, 'Consent purpose unavailable')
        with self.transaction() as db:
            db.execute(
                'INSERT INTO product_consents '
                '(account_id,product,purpose,policy_version,generation,granted_at) '
                'VALUES (%s,%s,%s,%s,1,%s) '
                'ON CONFLICT (account_id,product,purpose) DO UPDATE SET '
                'policy_version=EXCLUDED.policy_version,generation=product_consents.generation+1,'
                'granted_at=EXCLUDED.granted_at,revoked_at=NULL',
                (str(account), b'neorang_narang', b'completion-metadata', b'pc-poc-v1', utc(now)),
            )
