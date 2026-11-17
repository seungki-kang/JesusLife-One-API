"""Local rehearsal helpers; never used by the API PostgreSQL adapter."""
import os

import psycopg


def isolated_environment(environ):
    """Use the same allowlist for Python workers and PostgreSQL utilities."""
    return {key: value for key, value in environ.items()
            if key.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP',
                               'LANG', 'COMSPEC'}}


def local_connect(*args, port, **kwargs):
    """Fail closed outside an isolated worker and pin the TCP endpoint."""
    if any(key.upper().startswith('PG') for key in os.environ):
        raise RuntimeError('Local PostgreSQL worker inherited PG environment')
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('Temporary cluster port required')
    kwargs.update(host='127.0.0.1', hostaddr='127.0.0.1', port=port)
    return psycopg.connect(*args, **kwargs)
