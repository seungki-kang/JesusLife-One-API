"""Explicit, non-pooled PostgreSQL connections; no startup or import I/O.

Returned connections belong to the caller: close them and manage transactions.
Only adapter operations translate errors; callers must also protect their own
query/transaction boundaries against leaking driver exceptions.
"""
import psycopg

from app.core.postgres_settings import (
    load_postgres_migration_settings,
    load_postgres_runtime_settings,
)


class PostgresConnectionError(RuntimeError):
    """Fixed safe error, without the driver exception or connection details."""


def _connect(settings, connector):
    try:
        return connector(
            settings.dsn,
            connect_timeout=5,
            application_name=f'jesuslife_{settings.purpose}',
            options='-c timezone=UTC',
        )
    except Exception:
        pass
    # Outside the handler so __context__ cannot expose driver credentials.
    raise PostgresConnectionError('PostgreSQL connection failed')


def connect_runtime(environ=None, *, connector=None):
    """Validate runtime credentials and open one caller-owned connection.

    No retries; psycopg's default autocommit=False is preserved.
    """
    settings = load_postgres_runtime_settings(environ)
    return _connect(settings, psycopg.connect if connector is None else connector)


def connect_migration(environ=None, *, connector=None):
    """Separate migration-only entry point; does not execute migration SQL."""
    settings = load_postgres_migration_settings(environ)
    return _connect(settings, psycopg.connect if connector is None else connector)


def probe_runtime(environ=None, *, connector=None):
    """Explicit SELECT 1 probe; always attempt cursor and connection cleanup.

    The probe never commits. Closing discards its read-only transaction.
    Cleanup failure is a safe failure, even when the query succeeded.
    """
    connection = connect_runtime(environ, connector=connector)
    cursor = None
    failed = False
    try:
        cursor = connection.cursor()
        cursor.execute('SELECT 1')
        failed = cursor.fetchone() != (1,)
    except Exception:
        failed = True
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                failed = True
        try:
            connection.close()
        except Exception:
            failed = True
    if failed:
        raise PostgresConnectionError('PostgreSQL probe failed')
    return True
