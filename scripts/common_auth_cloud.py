"""Explicit common cloud dev authentication. No MySQL or automatic migration."""
import argparse
import base64
from getpass import getpass
import json
import os
import secrets
import ssl
from uuid import uuid4

from dotenv import dotenv_values
import psycopg
from psycopg import sql

from app.core.postgres import PostgresConnectionError
from app.core.postgres_common_auth import PostgresCommonAuthStore
from scripts.common_auth_cloud_settings import (
    ROOT, DIRECTORY, SETTINGS, ENABLED, CALLBACK, AUDIENCE, validate,
)


def connector(config, password, *, driver=None):
    if not config.enabled or not isinstance(password, str) or not password:
        raise ValueError('Explicit common cloud enablement and password required')
    connect_driver = driver or psycopg.connect
    def connect():
        if any(k.upper().startswith('PG') for k in os.environ):
            raise PostgresConnectionError('PostgreSQL environment is not isolated')
        failed = False
        try:
            return connect_driver(host=config.pooler_host, port=5432, dbname='postgres',
                user='jl_core_auth_runtime.' + config.project_ref, password=password,
                sslmode='verify-full', sslrootcert=str(config.certificate), connect_timeout=5,
                application_name='jesuslife_common_auth_dev', prepare_threshold=None,
                options='-c timezone=UTC -c statement_timeout=5000')
        except Exception:
            failed = True
        if failed:
            raise PostgresConnectionError('Common cloud PostgreSQL connection failed')
    return connect


def prepare(*, reuse_dev_settings=False):
    from scripts.local_mysql import protect  # filesystem ACL utility only; no DB call
    DIRECTORY.mkdir(exist_ok=True)
    protect(DIRECTORY)
    values = {ENABLED: '0', 'APP_ID': 'churchos', 'PROJECT_NAME': 'jesuslife-api-dev',
        'POOLER_HOST': '', 'PROJECT_REF': '', 'SSLROOTCERT': '',
        'AUTH0_ISSUER': '', 'AUTH0_CLIENT_ID': '', 'AUTH0_CLIENT_SECRET': '',
        'AUTH0_AUDIENCE': AUDIENCE, 'AUTH0_CALLBACK_URL': CALLBACK,
        'COMMON_TOKEN_HMAC_KEY': base64.b64encode(secrets.token_bytes(32)).decode(),
        'COMMON_TOKEN_ENCRYPTION_KEY': base64.b64encode(secrets.token_bytes(32)).decode()}
    if reuse_dev_settings:
        # Explicit credential migration, allowlist only. Never import legacy DB
        # host/password, consent settings, keys or persistence selection.
        old_auth = dotenv_values(ROOT / '.env.auth0-pc', interpolate=False)
        old_pg = dotenv_values(ROOT / '.env.churchos-supabase-dev/settings.env', interpolate=False)
        for name in ('AUTH0_ISSUER', 'AUTH0_CLIENT_ID', 'AUTH0_CLIENT_SECRET'):
            values[name] = old_auth.get(name) or ''
        for name in ('POOLER_HOST', 'PROJECT_REF'):
            values[name] = old_pg.get(name) or ''
        values['SSLROOTCERT'] = old_pg.get('SSLROOTCERT') or str(
            ROOT / '.env.churchos-supabase-dev/project-ca.crt')
    with SETTINGS.open('x', encoding='utf-8') as output:
        protect(SETTINGS)
        for name, value in values.items():
            output.write(name + '=' + json.dumps(value, ensure_ascii=False) + '\n')


def build_plan(config):
    # Configuration is validated, but enablement is intentionally still OFF.
    # NOLOGIN keeps the new role inaccessible until a later explicit password
    # setup and runtime readiness check. No credentials enter generated SQL.
    head = '''BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='10s';
DO $guard$ BEGIN
 IF current_user <> 'postgres' OR NOT EXISTS
  (SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolbypassrls)
  OR NOT pg_has_role(current_user,'jl_migration_owner','MEMBER') THEN
  RAISE EXCEPTION 'Verified development administrator required'; END IF;
 IF to_regnamespace('jl_core_auth') IS NOT NULL OR EXISTS
  (SELECT 1 FROM pg_roles WHERE rolname='jl_core_auth_runtime') THEN
  RAISE EXCEPTION 'Common authentication already exists; do not overwrite'; END IF;
END $guard$;
CREATE ROLE jl_core_auth_runtime NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB
 NOCREATEROLE NOREPLICATION NOBYPASSRLS;
'''
    schema = (ROOT / 'migrations/postgres/candidates/common_auth.sql').read_text()
    copy = (ROOT / 'migrations/postgres/candidates/common_auth_identity_copy.sql').read_text()
    binding = sql.SQL('INSERT INTO jl_core_auth.app_bindings VALUES ({},{},{});').format(
        sql.Literal(config.app_id.encode()),
        sql.Literal(next(iter(config.policy.client_ids)).encode()), sql.Literal(CALLBACK.encode()),
    ).as_string()
    tail = '''
SET LOCAL ROLE jl_migration_owner;
''' + binding + '''
CREATE TABLE jl_core_auth.development_readiness (
 id SMALLINT PRIMARY KEY CHECK (id=1), identity_copy_verified BOOLEAN NOT NULL
);
INSERT INTO jl_core_auth.development_readiness VALUES (1,true);
REVOKE ALL ON jl_core_auth.development_readiness FROM PUBLIC;
GRANT SELECT ON jl_core_auth.development_readiness TO jl_core_auth_runtime;
ALTER TABLE jl_core_auth.development_readiness ENABLE ROW LEVEL SECURITY;
ALTER TABLE jl_core_auth.development_readiness FORCE ROW LEVEL SECURITY;
CREATE POLICY common_auth_readiness_read ON jl_core_auth.development_readiness
 FOR SELECT TO jl_core_auth_runtime USING (id=1);
RESET ROLE;
COMMIT;
SELECT 'COMMON_AUTH_PROVISIONED_ROLE_STILL_NOLOGIN' AS result;
'''
    return head + schema + '\n' + copy + tail


def probe(store, config):
    with store.transaction() as db:
        marker = db.execute('SELECT identity_copy_verified FROM jl_core_auth.development_readiness '
                            'WHERE id=1').fetchone()
        if marker != {'identity_copy_verified': True}:
            raise ValueError('Verified identity copy required')
        binding = db.execute('SELECT count(*) AS total FROM jl_core_auth.app_bindings '
            'WHERE app_id=%s AND client_id=%s AND redirect_uri=%s',
            (config.app_id.encode(), next(iter(config.policy.client_ids)).encode(), CALLBACK.encode())).fetchone()
        if binding != {'total': 1}:
            raise ValueError('Application binding unavailable')
        row = db.execute("SELECT count(*) AS total, bool_and(c.relrowsecurity AND c.relforcerowsecurity) AS forced "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='jl_core_auth' AND c.relname IN "
            "('accounts','external_identities','login_transactions','app_sessions','session_access_tokens','product_consents')").fetchone()
        if row != {'total': 6, 'forced': True}:
            raise ValueError('Common authentication RLS unavailable')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'check', 'build-plan', 'refresh-plan', 'probe', 'serve'))
    parser.add_argument('--reuse-dev-settings', action='store_true')
    args = parser.parse_args()
    if args.reuse_dev_settings and args.action != 'prepare':
        parser.error('--reuse-dev-settings is valid only with prepare')
    stage = 'SETTINGS'
    try:
        if args.action == 'prepare':
            prepare(reuse_dev_settings=args.reuse_dev_settings)
            print('PASS: protected common cloud settings prepared; disabled; no DB connection')
            return
        config = validate(dotenv_values(SETTINGS, interpolate=False))
        ssl.create_default_context(cafile=str(config.certificate))
        if args.action == 'check':
            print('PASS: cloud settings and CA format only; enabled=' + str(config.enabled)
                  + '; authentication=COMMON_POSTGRES; no DB connection')
            return
        if args.action in ('build-plan', 'refresh-plan'):
            from scripts.local_mysql import protect
            stage = 'PLAN_BUILD'
            content = build_plan(config)
            if args.action == 'refresh-plan':
                path = DIRECTORY / 'provision.sql'
                actual = path.read_text(encoding='utf-8')
                if actual == content:
                    print('PASS: provision.sql already current; NOT_EXECUTED')
                    return
                rls = (
                    'ALTER TABLE jl_core_auth.development_readiness ENABLE ROW LEVEL SECURITY;\n'
                    'ALTER TABLE jl_core_auth.development_readiness FORCE ROW LEVEL SECURITY;\n'
                    'CREATE POLICY common_auth_readiness_read ON jl_core_auth.development_readiness\n'
                    ' FOR SELECT TO jl_core_auth_runtime USING (id=1);\n'
                )
                accepted = {content.replace(rls, '')}
                old_copy_path = ROOT / 'tests/fixtures/common_auth_identity_copy_before_grants.sql'
                if old_copy_path.is_file():
                    current_copy = (ROOT / 'migrations/postgres/candidates/common_auth_identity_copy.sql').read_text(encoding='utf-8')
                    old_copy = old_copy_path.read_text(encoding='utf-8')
                    if content.count(current_copy) != 1:
                        raise ValueError('Unexpected identity copy composition')
                    previous = content.replace(current_copy, old_copy)
                    accepted.update((previous, previous.replace(rls, '')))
                if content.count(rls) != 1 or actual not in accepted:
                    raise ValueError('Unexpected existing plan preserved')
                path.rename(DIRECTORY / ('provision-before-readiness-rls-' + uuid4().hex + '.sql'))
            stage = 'PLAN_WRITE'
            with (DIRECTORY / 'provision.sql').open('x', encoding='utf-8') as output:
                protect(DIRECTORY / 'provision.sql')
                output.write(content)
            print('PASS: protected provision.sql prepared; NOT_EXECUTED; role remains NOLOGIN')
            return
        if not config.enabled:
            print('BLOCKED: COMMON_CLOUD_DISABLED; no password requested or DB connection')
            raise SystemExit(2)
        stage = 'PASSWORD'
        password = getpass('jl_core_auth_runtime password (hidden; not membership account): ')
        store = PostgresCommonAuthStore(config.encryption_key, config.hmac_key,
            connector=connector(config, password), app_id=config.app_id)
        stage = 'COMMON_POSTGRES_READINESS'
        probe(store, config)
        print('PASS: common PostgreSQL TLS/role/schema/app binding/identity-copy marker checks')
        if args.action == 'serve':
            stage = 'SERVER_START'
            from app.core.common_cloud_app import create_cloud_app
            import uvicorn
            uvicorn.run(create_cloud_app(config, store=store), host='127.0.0.1', port=8000,
                        access_log=False, log_level='critical')
    except FileExistsError:
        print('NOT_CHANGED: protected output already exists; never overwritten')
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print('STOPPED: common cloud verification')
    except Exception:
        print('BLOCKED: stage=' + stage + '; details suppressed; no MySQL fallback')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
