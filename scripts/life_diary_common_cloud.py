"""Opt-in Life Diary development login against common Supabase PostgreSQL."""
import argparse
import base64
from dataclasses import replace
from getpass import getpass
import json
from pathlib import Path
import secrets
import ssl
import time
from types import SimpleNamespace

from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from psycopg import sql
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.auth0_provider import Auth0Provider
from app.core.common_mobile_auth import CommonMobileAuthStore, MobileRegistration, PROFILES, install_common_mobile
from scripts.common_auth_cloud import connector
from scripts.common_auth_cloud_settings import (
    ROOT, SETTINGS as COMMON_SETTINGS, ENABLED, CALLBACK, validate,
)

DIRECTORY = ROOT / '.env.life-diary-common-cloud'
SETTINGS = DIRECTORY / 'settings.env'
APP_ID = 'life_diary'
MOBILE_CALLBACK = PROFILES[APP_ID][1]


def validate_settings(values):
    if (values.get('APP_ID') != APP_ID
            or values.get('AUTH0_APPLICATION') != 'jl-life-diary-dev'
            or values.get('AUTH0_CALLBACK_URL') != MOBILE_CALLBACK
            or not values.get('BROKER_BROWSER_CLIENT_ID')
            or values.get('AUTH0_CLIENT_ID') == values.get('BROKER_BROWSER_CLIENT_ID')):
        raise ValueError('Dedicated Life Diary registration required')
    # Reuse the common endpoint/key validation. Only the two already checked,
    # server-owned app/callback values are normalized for that browser validator.
    config = validate(values | {'APP_ID':'churchos','AUTH0_CALLBACK_URL':CALLBACK})
    if any(c.isspace() for c in next(iter(config.policy.client_ids))):
        raise ValueError('Invalid dedicated client registration')
    return replace(config, app_id=APP_ID)


def write_new(path, content):
    from scripts.local_mysql import protect  # ACL utility; no MySQL operation
    DIRECTORY.mkdir(exist_ok=True)
    protect(DIRECTORY)
    with path.open('x', encoding='utf-8') as output:
        protect(path)
        output.write(content)


def prepare():
    common = dotenv_values(COMMON_SETTINGS, interpolate=False)
    validate(common)
    values = {ENABLED:'0', 'APP_ID':APP_ID, 'AUTH0_APPLICATION':'jl-life-diary-dev',
        'AUTH0_CALLBACK_URL':MOBILE_CALLBACK, 'AUTH0_CLIENT_ID':'', 'AUTH0_CLIENT_SECRET':'',
        'BROKER_BROWSER_CLIENT_ID':common['AUTH0_CLIENT_ID'],
        'COMMON_TOKEN_HMAC_KEY':base64.b64encode(secrets.token_bytes(32)).decode(),
        'COMMON_TOKEN_ENCRYPTION_KEY':base64.b64encode(secrets.token_bytes(32)).decode()}
    for key in ('AUTH0_ISSUER','AUTH0_AUDIENCE','PROJECT_NAME','POOLER_HOST','PROJECT_REF','SSLROOTCERT'):
        values[key] = common[key]
    write_new(SETTINGS, ''.join(k+'='+json.dumps(v, ensure_ascii=False)+'\n' for k,v in values.items()))


def build_plan(config):
    if config.app_id != APP_ID:
        raise ValueError('Dedicated Life Diary configuration required')
    head = '''BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='10s';
DO $guard$ BEGIN
 IF current_user<>'postgres' OR NOT EXISTS
  (SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolbypassrls)
  OR NOT pg_has_role(current_user,'jl_migration_owner','MEMBER') THEN
  RAISE EXCEPTION 'Verified development administrator required'; END IF;
 IF to_regnamespace('jl_core_auth') IS NULL OR NOT EXISTS
  (SELECT 1 FROM pg_roles WHERE rolname='jl_core_auth_runtime') THEN
  RAISE EXCEPTION 'Common authentication must be provisioned first'; END IF;
 IF to_regclass('jl_core_auth.mobile_logins') IS NOT NULL OR
    to_regclass('jl_core_auth.common_mobile_schema_version') IS NOT NULL THEN
  RAISE EXCEPTION 'Mobile schema already exists; review before applying'; END IF;
END $guard$;
'''
    schema = (ROOT / 'migrations/postgres/candidates/common_mobile_auth.sql').read_text(encoding='utf-8')
    binding = sql.SQL('INSERT INTO jl_core_auth.app_bindings VALUES ({},{},{});').format(
        sql.Literal(APP_ID.encode()), sql.Literal(next(iter(config.policy.client_ids)).encode()),
        sql.Literal(MOBILE_CALLBACK.encode())).as_string()
    return head + schema + '\nSET LOCAL ROLE jl_migration_owner;\n' + binding + '''
RESET ROLE;
COMMIT;
SELECT 'LIFE_DIARY_COMMON_MOBILE_SCHEMA_READY' AS result;
'''


def probe(store, config):
    with store.transaction() as db, db.cursor() as cursor:
        store.ready(cursor)
        if db.execute('SELECT identity_copy_verified FROM jl_core_auth.development_readiness '
                      'WHERE id=1').fetchone() != {'identity_copy_verified':True}:
            raise ValueError('Common identity copy readiness missing')
        row = db.execute('SELECT count(*) AS total FROM jl_core_auth.app_bindings '
            'WHERE app_id=%s AND client_id=%s AND redirect_uri=%s',
            (APP_ID.encode(),next(iter(config.policy.client_ids)).encode(),MOBILE_CALLBACK.encode())).fetchone()
        if row != {'total':1}:
            raise ValueError('Dedicated Life Diary binding missing')
        row = db.execute("SELECT count(*) AS total, bool_and(c.relrowsecurity AND c.relforcerowsecurity) AS forced "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='jl_core_auth' AND c.relname IN "
            "('mobile_logins','common_mobile_schema_version')").fetchone()
        if row != {'total':2,'forced':True}:
            raise ValueError('Common mobile RLS unavailable')


def create_app(config, store, *, provider=None, clock=time.time, backup_store=None):
    if not config.enabled or config.app_id != APP_ID or not isinstance(store, CommonMobileAuthStore):
        raise ValueError('Explicit enabled common Life Diary runtime required')
    runtime = SimpleNamespace(config=config,store=store,provider=provider or Auth0Provider(config),
                              now=lambda:int(clock()))
    app = FastAPI(title='Life Diary common cloud development authentication',
                  docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','testserver'])

    @app.middleware('http')
    async def protect(request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse({'detail':'Common mobile authentication unavailable'},status_code=503)
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
            'X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    @app.get('/health')
    def health():
        return {'status':'ok','app_id':APP_ID,'authentication_store':'COMMON_POSTGRES','development_only':True}

    owners = install_common_mobile(app,(MobileRegistration(APP_ID,next(iter(config.policy.client_ids)),runtime,True),))
    if backup_store is not None:
        from app.modules.life_diary.completed_backup_store import CompletedBackupStore
        from app.modules.life_diary.completed_backup_router import completed_backup_router
        if not isinstance(backup_store, CompletedBackupStore):
            raise ValueError('Explicit completed-backup store required')
        app.include_router(completed_backup_router(
            authenticated_owner=owners[APP_ID],
            store=backup_store, enabled=True,
        ))
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','check','build-plan','probe','serve'))
    args = parser.parse_args()
    stage = 'SETTINGS'
    try:
        if args.action == 'prepare':
            prepare()
            print('PASS: protected Life Diary common cloud settings prepared; disabled; no DB connection')
            return
        values = dotenv_values(SETTINGS,interpolate=False)
        missing = [key for key in ('AUTH0_CLIENT_ID','AUTH0_CLIENT_SECRET') if not values.get(key)]
        if missing:
            print('NOT_READY: missing setting names: '+','.join(missing))
            raise SystemExit(1)
        config = validate_settings(values)
        ssl.create_default_context(cafile=str(config.certificate))
        if args.action == 'check':
            print('PASS: dedicated Life Diary settings/CA format; enabled='+str(config.enabled)+'; no DB connection')
            return
        if args.action == 'build-plan':
            stage = 'PLAN_BUILD'
            content = build_plan(config)
            stage = 'PLAN_WRITE'
            write_new(DIRECTORY / 'provision-mobile.sql', content)
            print('PASS: protected provision-mobile.sql prepared; NOT_EXECUTED')
            return
        if not config.enabled:
            print('BLOCKED: LIFE_DIARY_COMMON_CLOUD_DISABLED; no password requested or DB connection')
            raise SystemExit(2)
        stage = 'PASSWORD'
        password = getpass('jl_core_auth_runtime password (hidden): ')
        store = CommonMobileAuthStore(config.encryption_key,config.hmac_key,
                                       connector=connector(config,password),app_id=APP_ID)
        stage = 'COMMON_MOBILE_READINESS'
        probe(store,config)
        print('PASS: common PostgreSQL Life Diary role/schema/app binding/RLS checks')
        if args.action == 'serve':
            stage = 'SERVER_START'
            import uvicorn
            uvicorn.run(create_app(config,store),host='127.0.0.1',port=8000,
                        access_log=False,proxy_headers=False,log_level='critical')
    except FileExistsError:
        print('NOT_CHANGED: protected output already exists; never overwritten')
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print('STOPPED: Life Diary common cloud verification')
    except Exception:
        print('BLOCKED: stage='+stage+'; details suppressed; no MySQL fallback')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
