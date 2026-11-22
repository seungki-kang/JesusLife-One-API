"""Synthetic guards; no external services or credentials."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import UUID

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth0_pc import create_app
from app.core.auth import AuthContext
from app.core.postgres import PostgresConnectionError
from scripts.churchos_supabase_dev import ENABLED, membership_connector
from scripts.churchos_supabase_http import install_verification


class SupabaseDevTest(TestCase):
    def test_explicit_tls_role_and_environment_guards(self):
        with TemporaryDirectory() as folder:
            cert = Path(folder) / 'ca.crt'
            cert.touch()
            values = {ENABLED: '1', 'PROJECT_NAME': 'jesuslife-api-dev',
                      'POOLER_HOST': 'aws-0-ap-northeast-2.pooler.supabase.com',
                      'PROJECT_REF': 'a' * 20, 'SSLROOTCERT': str(cert)}
            driver = MagicMock()
            driver.return_value.execute.return_value.fetchone.return_value = (True,) * 6
            connect = membership_connector(values, 'synthetic', driver=driver)
            driver.assert_not_called()
            with patch.dict(os.environ, {}, clear=True):
                connect()
            self.assertEqual(driver.call_args.kwargs['sslmode'], 'verify-full')
            self.assertEqual(driver.call_args.kwargs['port'], 5432)
            self.assertEqual(driver.call_args.kwargs['user'], 'jl_churchos_dev_login.' + 'a' * 20)
            with patch.dict(os.environ, {'PGSERVICE': 'untrusted'}, clear=True):
                with self.assertRaises(PostgresConnectionError):
                    connect()
            for changes in ({ENABLED: 'true'}, {'PROJECT_NAME': 'production'},
                            {'POOLER_HOST': '127.0.0.1'}, {'PROJECT_REF': ''},
                            {'SSLROOTCERT': str(cert) + '.absent'}):
                with self.assertRaises(ValueError):
                    membership_connector(values | changes, 'synthetic', driver=driver)
            driver.return_value.execute.return_value.fetchone.return_value = (True,) * 5 + (False,)
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(PostgresConnectionError):
                    connect()
            driver.return_value.close.assert_called_once()

    def test_verified_account_and_cookie_scope_observations(self):
        def identity(request, *, product=False, required_scope=None):
            cookie = request.cookies.get('jl_pc_session')
            if not cookie:
                raise HTTPException(401)
            if required_scope and cookie in ('basic', 'basic_relogin'):
                raise HTTPException(403)
            return AuthContext(sub=UUID(int=2 if cookie == 'foreign' else 1))

        runtime = MagicMock()
        runtime.identity.side_effect = identity
        db = MagicMock()
        db.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (False,)
        app = create_app(runtime, church_membership_connect=db)
        with TemporaryDirectory() as folder, \
                patch('scripts.churchos_supabase_http.DIRECTORY', Path(folder)), \
                patch('scripts.local_mysql.protect'), \
                patch('scripts.churchos_supabase_http.uuid4', side_effect=[UUID(int=10), UUID(int=20)]):
            install_verification(app, runtime)
            own = '/api/v1/churches/' + str(UUID(int=10)) + '/membership'
            other = '/api/v1/churches/' + str(UUID(int=20)) + '/membership'
            with TestClient(app) as client:
                self.assertEqual(client.get(own).status_code, 401)
                client.cookies.set('jl_pc_session', 'basic')
                self.assertEqual(client.post('/dev/churchos/confirm-test-account').status_code, 200)
                client.cookies.set('jl_pc_session', 'basic_relogin')
                self.assertEqual(client.get(own).status_code, 403)
                status = client.get('/dev/churchos/results').json()['http_status']
                self.assertEqual(status.get('basic_login'), 403)
                db.assert_not_called()
                client.cookies.set('jl_pc_session', 'foreign')
                client.get(own)
                self.assertNotIn('own_membership', client.get('/dev/churchos/results').json()['http_status'])
                client.cookies.set('jl_pc_session', 'scoped')
                self.assertEqual(client.get(own).status_code, 200)
                db.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = None
                self.assertEqual(client.get(other).status_code, 403)
                result = client.get('/dev/churchos/results').json()
                self.assertTrue(result['http_pass'])
                self.assertNotIn(str(UUID(int=1)), str(result))
            insert = (Path(folder) / 'insert.sql').read_text()
            cleanup = (Path(folder) / 'cleanup.sql').read_text()
            self.assertIn('rolbypassrls', insert)
            self.assertNotIn('CREATE POLICY', insert)
            self.assertIn('synthetic_rows_absent', cleanup)
            with self.assertRaises(ValueError):
                install_verification(create_app(runtime), runtime)
