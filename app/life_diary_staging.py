"""Explicit HTTPS staging entry point for synthetic Life Diary checks."""

import base64
from contextlib import closing
from dataclasses import dataclass, replace
import os
from urllib.parse import parse_qs, urlsplit

from app.core.postgres_settings import (
    RUNTIME_DSN,
    load_postgres_runtime_settings,
)


@dataclass(frozen=True, repr=False)
class AuthConfiguration:
    policy: object
    client_secret: str
    hmac_key: bytes
    encryption_key: bytes


def _key(values, name):
    try:
        key = base64.b64decode(values[name], validate=True)
        if len(key) == 32:
            return key
    except (KeyError, ValueError, TypeError):
        pass
    raise ValueError(f'Invalid staging setting: {name}')


def _database_environment(values):
    settings = load_postgres_runtime_settings(values)
    target = urlsplit(settings.dsn)
    if (target.hostname in {'localhost', '127.0.0.1', '::1'}
            or parse_qs(target.query).get('sslmode') != ['verify-full']):
        raise ValueError('Life Diary staging requires remote PostgreSQL with verify-full TLS')
    return {RUNTIME_DSN: settings.dsn}


def create_app(environ=None):
    values = os.environ if environ is None else environ
    if values.get('LIFE_DIARY_STAGING_ENABLED') != '1':
        raise ValueError('Life Diary staging is disabled')

    def required(name):
        value = values.get(name, '')
        if not value or any(char.isspace() for char in value):
            raise ValueError(f'Missing or invalid staging setting: {name}')
        return value

    origin = required('LIFE_DIARY_PUBLIC_ORIGIN')
    parent_id = required('AUTH0_CORE_CLIENT_ID')
    diary_id = required('LD_AUTH0_CLIENT_ID')
    if parent_id == diary_id:
        raise ValueError('Life Diary requires its own Auth0 application')
    hmac_key = _key(values, 'CORE_TOKEN_HMAC_KEY')
    encryption_key = _key(values, 'CORE_TOKEN_ENCRYPTION_KEY')
    if hmac_key == encryption_key:
        raise ValueError('Staging token keys must be distinct')
    postgres_environment = _database_environment(values)

    from fastapi import HTTPException, Response
    from psycopg import Error as PostgresDriverError
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    from app.auth0_pc import PcRuntime
    from app.core.auth0_poc import PocTokenPolicy
    from app.core.life_diary_login import Registration, cloud_callback
    from app.core.postgres import PostgresConnectionError, connect_runtime
    from app.core.postgres_mobile_store import PostgresMobileStore
    from app.main import create_app as create_one_api

    callback = cloud_callback(origin)
    policy = PocTokenPolicy(
        required('AUTH0_ISSUER'), required('AUTH0_AUDIENCE'), frozenset({parent_id})
    )
    parent_config = AuthConfiguration(policy, '', hmac_key, encryption_key)
    diary_config = replace(
        parent_config,
        policy=replace(policy, client_ids=frozenset({diary_id})),
        client_secret=required('LD_AUTH0_CLIENT_SECRET'),
    )

    def connect():
        connection = connect_runtime(postgres_environment)
        if connection.info.user != 'jl_ld_auth_runtime':
            connection.close()
            raise PostgresConnectionError('Unexpected Life Diary runtime role')
        return connection

    def connect_backup():
        try:
            return connect()
        except PostgresConnectionError:
            pass
        raise HTTPException(503, 'Backup storage unavailable')

    store = PostgresMobileStore(encryption_key, hmac_key, connector=connect)
    parent = PcRuntime(parent_config, store=store)
    parent.life_diary_registration = Registration(diary_id, enabled=True, callback_uri=callback)
    parent.life_diary_runtime = PcRuntime(diary_config, store=store, clock=parent.clock)
    api = create_one_api(
        life_diary_runtime=parent,
        life_diary_public_origin=origin,
        life_diary_backup_connect=connect_backup,
    )
    @api.get('/ready', status_code=204)
    def readiness():
        try:
            with closing(connect()) as connection:
                connection.execute('SET TRANSACTION READ ONLY')
                core = connection.execute(
                    'SELECT version FROM jl_ld_auth.core_schema_version ORDER BY version'
                ).fetchall()
                mobile = connection.execute(
                    'SELECT version FROM jl_ld_auth.mobile_schema_version ORDER BY version'
                ).fetchall()
                if core != [(1,)] or mobile != [(1,)]:
                    raise PostgresConnectionError('Unexpected Life Diary schema version')
                connection.execute(
                    'SELECT owner_id, generation, active FROM ld_backup_race.backup_consent LIMIT 0'
                )
                connection.execute(
                    'SELECT owner_id, generation, entry_id, ciphertext '
                    'FROM ld_backup_race.backup_entries LIMIT 0'
                )
                signatures = (
                    'ld_backup_race.grant_backup(uuid)',
                    'ld_backup_race.save_backup(uuid,bigint,uuid,bytea)',
                    'ld_backup_race.withdraw_backup(uuid,bigint)',
                )
                for signature in signatures:
                    allowed = connection.execute(
                        "SELECT has_function_privilege(to_regprocedure(%s), 'EXECUTE')",
                        (signature,),
                    ).fetchone()
                    if allowed != (True,):
                        raise PostgresConnectionError('Life Diary backup function unavailable')
        except (PostgresConnectionError, PostgresDriverError):
            raise HTTPException(503, 'Life Diary storage unavailable') from None
        return Response(status_code=204)

    api.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(origin).hostname])
    return api
