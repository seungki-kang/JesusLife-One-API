"""Dedicated LD profile; no live service on ordinary discovery."""
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from dotenv import dotenv_values
from fastapi.testclient import TestClient
import psycopg

from app.core.common_mobile_auth import CommonMobileAuthStore
from scripts import life_diary_common_cloud as cli
from scripts.common_auth_cloud_settings import validate, ENABLED, ORIGIN
from tests.test_common_cloud_runtime import certificate, values
from tools.chgo_server.mock_oidc import LocalOIDC

ADMIN_CONNECT = RUNTIME_CONNECT = None
CLIENT = 'synthetic-mobile-life_diary'
NOW = 1_800_000_000


class LifeDiaryCloudSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cert = self.root / 'ca.crt'
        certificate(self.cert)
        self.values = values(self.cert) | {'APP_ID':'life_diary',
            'AUTH0_APPLICATION':'jl-life-diary-dev','AUTH0_CALLBACK_URL':cli.MOBILE_CALLBACK,
            'BROKER_BROWSER_CLIENT_ID':'synthetic-browser','AUTH0_CLIENT_ID':CLIENT}

    def test_dedicated_registration_and_callback_required(self):
        self.assertEqual(cli.validate_settings(self.values).app_id,'life_diary')
        for changes in ({'APP_ID':'jl_bible'}, {'AUTH0_APPLICATION':'jl-core-poc-pc'},
                        {'AUTH0_CALLBACK_URL':'https://untrusted.invalid/'},
                        {'AUTH0_CLIENT_ID':'synthetic-browser'}, {'BROKER_BROWSER_CLIENT_ID':''}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                cli.validate_settings(self.values | changes)

    def test_prepare_copies_no_browser_secret_or_keys_and_never_overwrites(self):
        common = self.root / 'common.env'
        import json
        source = values(self.cert) | {'AUTH0_CLIENT_SECRET':'browser-secret-do-not-copy'}
        common.write_text(''.join(k+'='+json.dumps(v)+'\n' for k,v in source.items()),encoding='utf-8')
        target_dir = self.root / 'profile'
        target = target_dir / 'settings.env'
        with patch.object(cli,'COMMON_SETTINGS',common),patch.object(cli,'DIRECTORY',target_dir), \
                patch.object(cli,'SETTINGS',target), patch.object(cli,'dotenv_values',return_value=source), patch('pymysql.connect') as mysql:
            cli.prepare()
            config = {key: json.loads(value) for key, value in (line.split('=', 1) for line in target.read_text(encoding='utf-8').splitlines() if line)}
            self.assertEqual(config[ENABLED],'0')
            self.assertEqual(config['AUTH0_CLIENT_ID'],'')
            self.assertEqual(config['AUTH0_CLIENT_SECRET'],'')
            self.assertNotIn('browser-secret-do-not-copy',target.read_text())
            self.assertNotEqual(config['COMMON_TOKEN_HMAC_KEY'],source['COMMON_TOKEN_HMAC_KEY'])
            before = target.read_bytes()
            with self.assertRaises(FileExistsError):
                cli.prepare()
            self.assertEqual(target.read_bytes(),before)
            mysql.assert_not_called()

    def test_disabled_profile_does_not_request_password(self):
        for action in ('probe','serve'):
            with patch('sys.argv',['ld',action]),patch.object(cli,'dotenv_values',return_value=self.values), \
                    patch.object(cli,'getpass') as password,patch.object(cli,'connector') as connector, \
                    redirect_stdout(StringIO()):
                with self.assertRaises(SystemExit) as result:
                    cli.main()
                self.assertEqual(result.exception.code,2)
                password.assert_not_called()
                connector.assert_not_called()

    def test_missing_credentials_report_names_only(self):
        with patch('sys.argv',['ld','check']), \
                patch.object(cli,'dotenv_values',return_value=self.values|{'AUTH0_CLIENT_SECRET':''}), \
                redirect_stdout(StringIO()) as output:
            with self.assertRaises(SystemExit):
                cli.main()
        self.assertIn('AUTH0_CLIENT_SECRET',output.getvalue())
        self.assertNotIn('synthetic-only',output.getvalue())

    def test_plan_adds_only_ld_registration_and_never_replaces_accounts(self):
        plan = cli.build_plan(cli.validate_settings(self.values))
        self.assertTrue(plan.startswith('BEGIN;'))
        self.assertIn('LIFE_DIARY_COMMON_MOBILE_SCHEMA_READY',plan)
        self.assertNotIn('INSERT INTO jl_core_auth.accounts',plan)
        self.assertNotIn('CREATE ROLE',plan)
        self.assertNotIn('jl_bible',plan)
        self.assertNotIn('synthetic-only',plan)


class LifeDiaryCloudPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ADMIN_CONNECT is None or RUNTIME_CONNECT is None:
            raise unittest.SkipTest('Disposable dedicated LD profile harness required')

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        cert = Path(self.temp.name) / 'ca.crt'
        certificate(cert)
        data = values(cert) | {ENABLED:'1','APP_ID':'life_diary',
            'AUTH0_APPLICATION':'jl-life-diary-dev','AUTH0_CALLBACK_URL':cli.MOBILE_CALLBACK,
            'BROKER_BROWSER_CLIENT_ID':'synthetic-browser','AUTH0_CLIENT_ID':CLIENT}
        self.config = cli.validate_settings(data)
        self.store = CommonMobileAuthStore(self.config.encryption_key,self.config.hmac_key,
                                            connector=RUNTIME_CONNECT,app_id='life_diary')

    def test_actual_factory_has_only_ld_and_performs_callback_exchange_logout(self):
        from app.core.auth0_poc import pkce_challenge
        import secrets
        provider = LocalOIDC(self.config)
        app = cli.create_app(self.config,self.store,provider=provider.provider,clock=lambda:NOW)
        prefix = '/api/v1/mobile/life-diary'
        verifier = secrets.token_urlsafe(32)
        body = {'app_id':'life_diary','client_id':CLIENT,
                'return_uri':'jesuslife-life-diary-poc://auth/complete/android'}
        with TestClient(app,base_url=ORIGIN) as client,patch('pymysql.connect') as mysql:
            for path in ('/auth/poc/login','/auth/cloud/login',
                         '/api/v1/mobile/neorang-narang/login-transactions','/api/v1/mobile/jl-bible/login-transactions'):
                self.assertEqual(client.get(path).status_code,404)
            start = client.post(prefix+'/login-transactions',json=body|{'challenge':pkce_challenge(verifier)})
            self.assertEqual(start.status_code,200)
            authorize = client.get(start.json()['authorize_url'],follow_redirects=False)
            code,state = provider.issue(authorize.headers['location'],str(uuid4()))
            callback = client.get(urlsplit(cli.MOBILE_CALLBACK).path,params={'code':code,'state':state},follow_redirects=False)
            self.assertEqual(callback.status_code,303)
            handoff = parse_qs(urlsplit(callback.headers['location']).query)
            result = client.post(prefix+'/session-exchange',json=body|{
                'transaction':handoff['transaction'][0],'code':handoff['code'][0],'verifier':verifier})
            self.assertEqual(result.status_code,200)
            headers = {'Authorization':'Bearer '+result.json()['access_token']}
            self.assertEqual(client.get(prefix+'/session',headers=headers).status_code,200)
            self.assertEqual(client.post(prefix+'/logout',headers=headers).status_code,204)
            self.assertEqual(client.get(prefix+'/session',headers=headers).status_code,401)
            mysql.assert_not_called()

    def test_probe_checks_dedicated_binding_and_rls_without_writes(self):
        with ADMIN_CONNECT() as db:
            db.execute('CREATE TABLE jl_core_auth.development_readiness '
                '(id SMALLINT PRIMARY KEY,identity_copy_verified BOOLEAN NOT NULL)')
            db.execute('INSERT INTO jl_core_auth.development_readiness VALUES (1,true)')
            db.execute('GRANT SELECT ON jl_core_auth.development_readiness TO jl_core_auth_runtime')
            before = db.execute('SELECT count(*) FROM jl_core_auth.accounts').fetchone()
        try:
            cli.probe(self.store,self.config)
            wrong = replace(self.config,policy=replace(self.config.policy,client_ids=frozenset({'unregistered'})))
            with self.assertRaises(ValueError):
                cli.probe(self.store,wrong)
            with ADMIN_CONNECT() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM jl_core_auth.accounts').fetchone(),before)
        finally:
            with ADMIN_CONNECT() as db:
                db.execute('DROP TABLE jl_core_auth.development_readiness')

    def test_z_full_mobile_plan_preserves_accounts_and_role_flags(self):
        from psycopg import sql
        with ADMIN_CONNECT() as db:
            host,port = db.info.host,db.info.port
            self.assertEqual(host,'127.0.0.1')
            accounts = db.execute('SELECT * FROM jl_core_auth.accounts ORDER BY account_id').fetchall()
            flags = db.execute("SELECT rolcanlogin,rolsuper,rolbypassrls FROM pg_roles WHERE rolname='jl_core_auth_runtime'").fetchone()
            db.execute('DROP TABLE jl_core_auth.mobile_logins, jl_core_auth.common_mobile_schema_version')
            db.execute('CREATE ROLE postgres LOGIN NOINHERIT NOSUPERUSER BYPASSRLS')
            db.execute(sql.SQL('ALTER ROLE postgres PASSWORD {}').format(sql.Literal('synthetic-isolated-only')))
            db.execute('GRANT jl_migration_owner TO postgres')
            db.execute('GRANT USAGE ON SCHEMA jl_core_auth TO postgres')
        config = replace(self.config,policy=replace(self.config.policy,client_ids=frozenset({CLIENT+'-new'})))
        try:
            with psycopg.connect(host=host,port=port,dbname='postgres',user='postgres',
                password='synthetic-isolated-only',sslmode='disable') as db:
                db.execute(cli.build_plan(config),prepare=False)
            with ADMIN_CONNECT() as db:
                self.assertEqual(db.execute('SELECT * FROM jl_core_auth.accounts ORDER BY account_id').fetchall(),accounts)
                self.assertEqual(db.execute("SELECT rolcanlogin,rolsuper,rolbypassrls FROM pg_roles WHERE rolname='jl_core_auth_runtime'").fetchone(),flags)
                self.assertEqual(db.execute("SELECT bool_and(relrowsecurity AND relforcerowsecurity) FROM pg_class "
                    "WHERE oid IN ('jl_core_auth.mobile_logins'::regclass,'jl_core_auth.common_mobile_schema_version'::regclass)").fetchone(),(True,))
        finally:
            with ADMIN_CONNECT() as db:
                db.execute('REVOKE USAGE ON SCHEMA jl_core_auth FROM postgres')
                db.execute('DROP ROLE postgres')
