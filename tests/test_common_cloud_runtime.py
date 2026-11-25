"""Synthetic settings/TLS tests and opt-in actual PostgreSQL cloud app tests."""
import base64
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from scripts import common_auth_cloud as cli
from scripts.common_auth_cloud_settings import validate, ENABLED, CALLBACK, AUDIENCE, ORIGIN
from app.core.common_cloud_app import create_cloud_app
from app.core.postgres_common_auth import PostgresCommonAuthStore
from app.core.postgres import PostgresConnectionError

ADMIN_CONNECT = RUNTIME_CONNECT = None
NOW = 1_800_000_000
CLIENT = 'synthetic-common-app'


def values(cert):
    return {ENABLED: '0', 'APP_ID': 'churchos', 'PROJECT_NAME': 'jesuslife-api-dev',
        'POOLER_HOST': 'aws-0-ap-northeast-2.pooler.supabase.com', 'PROJECT_REF': 'a' * 20,
        'SSLROOTCERT': str(cert), 'AUTH0_ISSUER': 'https://synthetic-common.auth0.com/',
        'AUTH0_CLIENT_ID': CLIENT, 'AUTH0_CLIENT_SECRET': 'synthetic-only',
        'AUTH0_AUDIENCE': AUDIENCE, 'AUTH0_CALLBACK_URL': CALLBACK,
        'COMMON_TOKEN_HMAC_KEY': base64.b64encode(b'a' * 32).decode(),
        'COMMON_TOKEN_ENCRYPTION_KEY': base64.b64encode(b'b' * 32).decode()}


def certificate(path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic CA')])
    cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
    cert = cert.serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(days=1))
    cert = cert.not_valid_after(datetime.now(timezone.utc)+timedelta(days=1))
    cert = cert.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256())
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


class CloudSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cert = self.root / 'ca.crt'
        certificate(self.cert)
        self.values = values(self.cert)

    def test_legacy_db_settings_and_insecure_targets_rejected(self):
        for extra in ({'CORE_DB_PASSWORD': 'synthetic'}, {'MYSQL_HOST': '127.0.0.1'},
                      {'PGSERVICE': 'anything'}, {'DATABASE_URL': 'anything'},
                      {'POOLER_HOST': 'localhost'}, {'AUTH0_CALLBACK_URL': 'https://untrusted.invalid/'},
                      {'APP_ID': 'unregistered'}, {'SSLROOTCERT': 'relative.crt'}):
            with self.subTest(extra=list(extra)):
                with self.assertRaises(ValueError):
                    validate(self.values | extra)

    def test_disabled_server_and_probe_do_not_request_password_or_connect(self):
        for action in ('probe', 'serve'):
            with patch('sys.argv', ['cloud', action]), patch.object(cli, 'dotenv_values', return_value=self.values), \
                    patch.object(cli, 'getpass') as password, patch.object(cli, 'connector') as connect, \
                    redirect_stdout(StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli.main()
                self.assertEqual(error.exception.code, 2)
                password.assert_not_called()
                connect.assert_not_called()

    def test_strict_tls_runtime_role_raw_password_and_no_inherited_pg_options(self):
        config = replace(validate(self.values), enabled=True)
        driver = MagicMock()
        connect = cli.connector(config, 'synthetic:@not-uri-encoded', driver=driver)
        with patch.dict(os.environ, {}, clear=True):
            connect()
        kwargs = driver.call_args.kwargs
        self.assertEqual(kwargs['sslmode'], 'verify-full')
        self.assertEqual(kwargs['sslrootcert'], str(self.cert))
        self.assertEqual(kwargs['user'], 'jl_core_auth_runtime.' + 'a' * 20)
        self.assertEqual(kwargs['password'], 'synthetic:@not-uri-encoded')
        self.assertEqual(kwargs['port'], 5432)
        with patch.dict(os.environ, {'PGPASSWORD': 'must-not-use'}, clear=True):
            with self.assertRaises(PostgresConnectionError):
                connect()
        self.assertEqual(driver.call_count, 1)

    def test_driver_failure_does_not_expose_details_or_fallback(self):
        config = replace(validate(self.values), enabled=True)
        driver = MagicMock(side_effect=RuntimeError('synthetic-secret'))
        with patch.dict(os.environ, {}, clear=True), patch('pymysql.connect') as mysql:
            with self.assertRaises(PostgresConnectionError) as error:
                cli.connector(config, 'synthetic', driver=driver)()
        mysql.assert_not_called()
        self.assertNotIn('synthetic-secret', str(error.exception))
        self.assertIsNone(error.exception.__context__)


    def test_prepare_reuses_only_auth_and_pooler_allowlist_and_never_overwrites(self):
        import json

        old_auth = {
            key: value for key, value in self.values.items()
            if key.startswith('AUTH0_')
        }
        old_auth['CORE_DB_PASSWORD'] = 'legacy-db-secret-not-to-copy'
        old_pg = {
            key: self.values[key]
            for key in ('POOLER_HOST', 'PROJECT_REF', 'SSLROOTCERT')
        }
        old_pg['CORE_DB_PASSWORD'] = 'legacy-db-secret-not-to-copy'
        directory = self.root / 'synthetic-common-profile'
        target = directory / 'settings.env'

        def synthetic_values(path, *, interpolate):
            self.assertFalse(interpolate)
            if path == self.root / '.env.auth0-pc':
                return old_auth.copy()
            if path == self.root / '.env.churchos-supabase-dev/settings.env':
                return old_pg.copy()
            raise AssertionError('Unexpected configuration source')

        with patch.object(cli, 'ROOT', self.root), \
                patch.object(cli, 'DIRECTORY', directory), \
                patch.object(cli, 'SETTINGS', target), \
                patch.object(cli, 'dotenv_values', side_effect=synthetic_values), \
                patch('pymysql.connect') as mysql:
            cli.prepare(reuse_dev_settings=True)
            data = target.read_text(encoding='utf-8')
            parsed = {
                key: json.loads(value)
                for key, value in (
                    line.split('=', 1) for line in data.splitlines() if line
                )
            }
            self.assertFalse(validate(parsed).enabled)
            for key in ('AUTH0_ISSUER', 'AUTH0_CLIENT_ID', 'AUTH0_CLIENT_SECRET'):
                self.assertEqual(parsed[key], old_auth[key])
            for key in ('POOLER_HOST', 'PROJECT_REF', 'SSLROOTCERT'):
                self.assertEqual(parsed[key], old_pg[key])
            self.assertNotIn('legacy-db-secret-not-to-copy', data)
            self.assertNotIn('CORE_DB_', data)
            before = target.read_bytes()
            with self.assertRaises(FileExistsError):
                cli.prepare(reuse_dev_settings=True)
            self.assertEqual(before, target.read_bytes())
            mysql.assert_not_called()

    def test_plan_is_transactional_no_login_and_contains_no_secret(self):
        plan = cli.build_plan(validate(self.values))
        self.assertTrue(plan.startswith('BEGIN;'))
        self.assertIn('CREATE ROLE jl_core_auth_runtime NOLOGIN', plan)
        self.assertIn('IDENTITY_COPY_VERIFIED_RELOGIN_REQUIRED', plan)
        self.assertIn('COMMIT;', plan)
        self.assertNotIn('synthetic-only', plan)
        self.assertNotIn(self.values['COMMON_TOKEN_HMAC_KEY'], plan)
        self.assertIn('ALTER TABLE jl_core_auth.development_readiness ENABLE ROW LEVEL SECURITY', plan)
        self.assertIn('ALTER TABLE jl_core_auth.development_readiness FORCE ROW LEVEL SECURITY', plan)
        self.assertIn('FOR SELECT TO jl_core_auth_runtime USING (id=1)', plan)

    def test_generation_failure_does_not_create_empty_provision_file(self):
        with patch('sys.argv', ['cloud', 'build-plan']), \
                patch.object(cli, 'dotenv_values', return_value=self.values), \
                patch.object(cli, 'DIRECTORY', self.root), \
                patch.object(cli, 'build_plan', side_effect=FileNotFoundError()), \
                redirect_stdout(StringIO()) as output:
            with self.assertRaises(SystemExit):
                cli.main()
        self.assertIn('stage=PLAN_BUILD', output.getvalue())
        self.assertFalse((self.root / 'provision.sql').exists())

    def test_refresh_archives_only_exact_old_plan(self):
        content = cli.build_plan(validate(self.values))
        start = content.index('ALTER TABLE jl_core_auth.development_readiness ENABLE')
        end = content.index('RESET ROLE;', start)
        old = content[:start] + content[end:]
        path = self.root / 'provision.sql'
        path.write_text(old, encoding='utf-8')
        with patch('sys.argv', ['cloud', 'refresh-plan']), \
                patch.object(cli, 'dotenv_values', return_value=self.values), \
                patch.object(cli, 'DIRECTORY', self.root), redirect_stdout(StringIO()):
            cli.main()
        self.assertEqual(path.read_text(encoding='utf-8'), content)
        archived = list(self.root.glob('provision-before-readiness-rls-*.sql'))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_text(encoding='utf-8'), old)

    def test_refresh_preserves_unexpected_existing_plan(self):
        path = self.root / 'provision.sql'
        path.write_text('different plan', encoding='utf-8')
        with patch('sys.argv', ['cloud', 'refresh-plan']), \
                patch.object(cli, 'dotenv_values', return_value=self.values), \
                patch.object(cli, 'DIRECTORY', self.root), redirect_stdout(StringIO()):
            with self.assertRaises(SystemExit):
                cli.main()
        self.assertEqual(path.read_text(encoding='utf-8'), 'different plan')

    def test_refresh_known_old_grant_plan_preserves_backup(self):
        content = cli.build_plan(validate(self.values))
        current = (cli.ROOT / 'migrations/postgres/candidates/common_auth_identity_copy.sql').read_text(encoding='utf-8')
        old = (cli.ROOT / 'tests/fixtures/common_auth_identity_copy_before_grants.sql').read_text(encoding='utf-8')
        previous = content.replace(current, old)
        self.assertNotEqual(content, previous)
        path = self.root / 'provision.sql'
        path.write_text(previous, encoding='utf-8')
        with patch('sys.argv', ['cloud', 'refresh-plan']), \
                patch.object(cli, 'dotenv_values', return_value=self.values), \
                patch.object(cli, 'DIRECTORY', self.root), redirect_stdout(StringIO()):
            cli.main()
        self.assertEqual(path.read_text(encoding='utf-8'), content)
        archived = list(self.root.glob('provision-before-readiness-rls-*.sql'))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_text(encoding='utf-8'), previous)


class CloudAppPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ADMIN_CONNECT is None or RUNTIME_CONNECT is None:
            raise unittest.SkipTest('Disposable cloud application harness required')

    def setUp(self):
        from scripts.common_auth_cloud_settings import CloudSettings
        from app.core.auth0_poc import PocTokenPolicy
        from tools.chgo_server.mock_oidc import LocalOIDC
        self.config = CloudSettings(True,
            PocTokenPolicy('https://synthetic-common.auth0.com/', AUDIENCE, frozenset({CLIENT})),
            'synthetic-only', secrets.token_bytes(32), secrets.token_bytes(32),
            'aws-0-ap-northeast-2.pooler.supabase.com', 'a'*20, Path('/unused-test-ca'))
        self.store = PostgresCommonAuthStore(self.config.encryption_key, self.config.hmac_key,
                                            connector=RUNTIME_CONNECT, app_id='churchos')
        self.idp = LocalOIDC(self.config)
        self.app = create_cloud_app(self.config, store=self.store, provider=self.idp.provider, clock=lambda: NOW)

    def login(self, client, subject, wrong_nonce=False):
        start = client.get('/auth/cloud/login', follow_redirects=False)
        self.assertEqual(start.status_code, 303)
        code, state = self.idp.issue(start.headers['location'], subject, wrong_nonce=wrong_nonce)
        result = client.get('/api/v1/auth/callback/web', params={'code':code,'state':state}, follow_redirects=False)
        return result, code, state

    def test_cloud_login_status_logout_replay_and_no_legacy_business_routes(self):
        with patch('pymysql.connect', side_effect=AssertionError('MySQL accessed')), \
                patch('app.core.core_store.dotenv_values', side_effect=AssertionError('Legacy settings accessed')), \
                TestClient(self.app, base_url=ORIGIN) as client:
            self.assertEqual(client.get('/api/v1/auth/cloud-status').status_code, 401)
            result, code, state = self.login(client, str(uuid4()))
            self.assertEqual(result.status_code, 303)
            self.assertEqual(result.headers['location'], '/auth/cloud/')
            status = client.get('/api/v1/auth/cloud-status')
            self.assertEqual(status.status_code, 200)
            self.assertNotIn('sub', status.json())
            self.assertEqual(client.get('/api/v1/auth/callback/web',
                params={'code':code,'state':state}, follow_redirects=False).status_code, 401)
            for path in ('/auth/poc/login','/api/v1/me','/api/v1/neorang-narang/completions'):
                self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(client.post('/api/v1/auth/cloud-logout').status_code, 403)
            headers = {'Origin':ORIGIN,'X-CSRF-Token':client.cookies.get('jl_cloud_csrf')}
            self.assertEqual(client.post('/api/v1/auth/cloud-logout', headers=headers).status_code, 204)
            self.assertEqual(client.get('/api/v1/auth/cloud-status').status_code, 401)

    def test_wrong_nonce_duplicate_callback_and_disabled_factory_rejected(self):
        with TestClient(self.app, base_url=ORIGIN) as client:
            result, _, _ = self.login(client, str(uuid4()), wrong_nonce=True)
            self.assertEqual(result.status_code, 401)
            self.assertIsNone(client.cookies.get('jl_cloud_session'))
            self.assertEqual(client.get('/api/v1/auth/callback/web?state=a&state=b&code=c').status_code, 401)
        with self.assertRaises(ValueError):
            create_cloud_app(replace(self.config, enabled=False), store=self.store)

    def test_readiness_requires_copy_marker_then_succeeds(self):
        with self.assertRaises(Exception):
            cli.probe(self.store, self.config)
        with ADMIN_CONNECT() as db:
            db.execute('CREATE TABLE jl_core_auth.development_readiness '
                       '(id SMALLINT PRIMARY KEY, identity_copy_verified BOOLEAN NOT NULL)')
            db.execute('INSERT INTO jl_core_auth.development_readiness VALUES (1,true)')
            db.execute('GRANT SELECT ON jl_core_auth.development_readiness TO jl_core_auth_runtime')
        try:
            cli.probe(self.store, self.config)
        finally:
            with ADMIN_CONNECT() as db:
                db.execute('DROP TABLE jl_core_auth.development_readiness')
