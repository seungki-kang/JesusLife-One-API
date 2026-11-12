"""Opt-in local ChurchOS wiring for the existing PC development settings file."""
from functools import partial
import os
from urllib.parse import unquote, urlsplit

import psycopg

from app.core.postgres import PostgresConnectionError, connect_runtime
from app.core.postgres_settings import RUNTIME_DSN, load_postgres_runtime_settings

ENABLED = 'JESUSLIFE_PC_CHURCHOS_ENABLED'


def membership_connector(values):
    """Validate without connecting. Only the literal '1' enables the route."""
    if values.get(ENABLED) != '1':
        return None
    settings = load_postgres_runtime_settings(values)
    uri = urlsplit(settings.dsn)
    if uri.hostname != '127.0.0.1' or unquote(uri.username) != 'jl_api_runtime':
        raise ValueError('ChurchOS PC requires local PostgreSQL runtime credentials')
    config = {RUNTIME_DSN: settings.dsn}

    def connect():
        # libpq service/host overrides must never redirect this local rehearsal.
        if any(key.upper().startswith('PG') for key in os.environ):
            raise PostgresConnectionError('Local PostgreSQL environment is not isolated')
        return connect_runtime(config, connector=partial(
            psycopg.connect, host='127.0.0.1', hostaddr='127.0.0.1',
            port=uri.port or 5432,
        ))

    return connect
