"""Synthetic configuration and login regressions; no provider or database I/O."""
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from app.auth0_pc import PcRuntime, configured_app, create_app
from app.core.postgres import PostgresConnectionError
from app.core.postgres_settings import RUNTIME_DSN
from scripts.churchos_pc_settings import ENABLED, membership_connector
from tests import test_auth0_pc_settings
from scripts.auth0_pc_settings import validate

DSN = 'postgresql://jl_api_runtime:synthetic_only@127.0.0.1:55432/postgres'
PATH = '/api/v1/churches/00000000-0000-0000-0000-000000000004/membership'


class ChurchosPcConfigurationTest(TestCase):
    def settings(self):
        return test_auth0_pc_settings.PcSettingsTest().settings() | {
            'AUTH0_ISSUER': 'https://synthetic-test.us.auth0.com/',
        }

    def test_only_explicit_enable_registers_routes_without_connecting(self):
        for flag in (None, '', '0', 'true', '1'):
            values = self.settings() | {ENABLED: flag, RUNTIME_DSN: DSN}
            with patch('app.auth0_pc.dotenv_values', return_value=values), \
                    patch('scripts.churchos_pc_settings.psycopg.connect') as db:
                app = configured_app()
                with TestClient(app) as client:
                    self.assertEqual(client.get(PATH).status_code, 401 if flag == '1' else 404)
                    paths = app.openapi()['paths']
                    self.assertEqual('/auth/poc/login/churchos' in paths, flag == '1')
                db.assert_not_called()

    def test_invalid_optional_settings_preserve_auth_runtime(self):
        for dsn in (None, 'synthetic-private-invalid', DSN.replace('127.0.0.1', 'remote.invalid'),
                    DSN.replace('jl_api_runtime', 'jl_migration_owner')):
            values = self.settings() | {ENABLED: '1', RUNTIME_DSN: dsn}
            with patch('app.auth0_pc.dotenv_values', return_value=values):
                app = configured_app()
            self.assertIsNotNone(app.state.auth_runtime)
            self.assertNotIn('/auth/poc/login/churchos', app.openapi()['paths'])

    def test_scope_is_requested_only_on_separate_enabled_login(self):
        for enabled in (False, True):
            store = Mock()
            runtime = PcRuntime(validate(self.settings()), store=store, provider=Mock())
            app = create_app(runtime, church_membership_connect=Mock() if enabled else None)
            with TestClient(app) as client:
                for path in ('/auth/poc/login', '/auth/poc/login?scope=churchos:membership:read',
                             '/auth/poc/login/churchos'):
                    response = client.get(path, follow_redirects=False)
                    if path.endswith('/churchos') and not enabled:
                        self.assertEqual(response.status_code, 404)
                        continue
                    self.assertEqual(response.status_code, 303)
                    query = parse_qs(urlsplit(response.headers['location']).query)
                    scopes = query['scope'][0].split()
                    self.assertEqual('churchos:membership:read' in scopes, path.endswith('/churchos'))
                    self.assertTrue({'openid', 'neorang-narang:read', 'neorang-narang:write'} <= set(scopes))
                    self.assertEqual(query['code_challenge_method'], ['S256'])
                    self.assertEqual(query['prompt'], ['login'])
                    self.assertIn('HttpOnly', response.headers['set-cookie'])
                # Each login persists a fresh state, browser binding and verifier.
                calls = store.begin_login.call_args_list
                self.assertEqual(len({call.kwargs['state'] for call in calls}), len(calls))

    def test_connection_is_lazy_and_rejects_libpq_environment(self):
        with patch.dict('os.environ', {}, clear=True), \
                patch('scripts.churchos_pc_settings.psycopg.connect') as db:
            connect = membership_connector({ENABLED: '1', RUNTIME_DSN: DSN})
            db.assert_not_called()
            connect()
            self.assertEqual(db.call_args.kwargs['hostaddr'], '127.0.0.1')
            self.assertEqual(db.call_args.kwargs['port'], 55432)
            with patch.dict('os.environ', {'PGHOSTADDR': '192.0.2.1'}):
                with self.assertRaises(PostgresConnectionError):
                    connect()
            self.assertEqual(db.call_count, 1)
