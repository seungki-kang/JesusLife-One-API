"""Synthetic settings and SQLite only; invoked by scripts.test_offline."""
import unittest
import base64
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from scripts.life_diary_dev import build_app, main, CALLBACK
from tests.test_life_diary_login import LifeDiaryLoginTest as Fixture
from app.core.life_diary_login import PREFIX


class DevelopmentEntrypointTest(unittest.TestCase):
    setUp = Fixture.setUp
    enable_fixture = Fixture.enable
    start = Fixture.start
    login_nn = Fixture.login

    def prepare(self):
        self.enable_fixture()
        self.values = {
            'LD_AUTH0_APPLICATION': 'jl-life-diary-dev',
            'LD_AUTH0_CLIENT_ID': self.fields['client_id'],
            'LD_AUTH0_CLIENT_SECRET': 'synthetic-secret-only',
            'LD_AUTH0_CALLBACK_URL': CALLBACK,
            'NN_AUTH0_CLIENT_ID': 'synthetic-nn-client',
        }
        self.runtime.life_diary_runtime = None
        self.runtime.life_diary_registration = None

    def test_reject_missing_wrong_and_duplicate_settings(self):
        self.prepare()
        for key in self.values:
            values = dict(self.values)
            del values[key]
            with self.assertRaises(ValueError):
                build_app(values, self.runtime)
        for key, value in [
            ('LD_AUTH0_APPLICATION', 'other'),
            ('LD_AUTH0_CLIENT_ID', next(iter(self.config.policy.client_ids))),
            ('LD_AUTH0_CLIENT_ID', self.values['NN_AUTH0_CLIENT_ID']),
            *[('LD_AUTH0_CALLBACK_URL', uri) for uri in (
                CALLBACK+'/', CALLBACK+'?x=1', CALLBACK+'#fragment',
                CALLBACK.replace('https:', 'http:'),
                CALLBACK.replace('ngrok-free.dev', 'ngrok-free.dev.evil.invalid'))],
        ]:
            with self.assertRaises(ValueError):
                build_app(self.values | {key: value}, self.runtime)
        self.assertIsNone(self.runtime.life_diary_runtime)

    def test_exact_callback_and_shared_store(self):
        self.prepare()
        app = build_app(self.values, self.runtime, provider=self.ld.provider)
        self.assertIs(self.runtime.life_diary_runtime.store, self.store)
        with TestClient(app, base_url='http://127.0.0.1:8000') as client:
            response = client.post(PREFIX+'/login-transactions', json=self.fields | {'challenge': 'a'*43})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['authorize_url'].startswith('http://127.0.0.1:8000/'))
            response = client.get(response.json()['authorize_url'], follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(parse_qs(urlsplit(response.headers['location']).query)['redirect_uri'], [CALLBACK])
            code, state = self.ld.issue(response.headers['location'], 'auth0|synthetic-a')
            response = client.get(CALLBACK, params={'state': state, 'code': code}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertNotIn(code, response.headers['location'])
            self.assertEqual(client.get(response.headers['location'], follow_redirects=False).status_code, 303)
            self.assertEqual(client.get('/health', headers={'host': 'evil.invalid'}).status_code, 403)

    def start_relay(self):
        self.prepare()
        app = build_app(self.values, self.runtime, provider=self.ld.provider)
        client = TestClient(app, base_url='http://127.0.0.1:8000')
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        response = client.post(PREFIX+'/login-transactions', json=self.fields | {'challenge': 'a'*43})
        authorize = client.get(response.json()['authorize_url'], follow_redirects=False)
        code, state = self.ld.issue(authorize.headers['location'], 'auth0|synthetic-a')
        return app, client, code, state

    def test_relay_wrong_browser_unknown_state_and_reuse(self):
        app, client, code, state = self.start_relay()
        with patch.object(self.ld.provider, 'exchange', wraps=self.ld.provider.exchange) as exchange:
            self.assertEqual(client.get(CALLBACK, params={'state': 'z'*43, 'code': code}).status_code, 401)
            response = client.get(CALLBACK, params={'state': state, 'code': code}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            location = response.headers['location']
            exchange.assert_not_called()
            self.assertEqual(client.get(CALLBACK, params={'state': state, 'code': code}).status_code, 401)
            with TestClient(app, base_url='http://127.0.0.1:8000') as other:
                self.assertEqual(other.get(location).status_code, 401)
                other.cookies.set('jl_ld_login', 'x'*43)
                self.assertEqual(other.get(location).status_code, 401)
            exchange.assert_not_called()
            self.assertEqual(client.get(location, follow_redirects=False).status_code, 303)
            self.assertEqual(exchange.call_count, 1)
            self.assertEqual(client.get(location).status_code, 401)
            self.assertEqual(client.get(CALLBACK, params={'state': state, 'code': code}).status_code, 401)

    def test_relay_expired_and_public_routes_denied(self):
        app, client, code, state = self.start_relay()
        public = CALLBACK.split('/api/')[0]
        for path in ('/health', PREFIX+'/authorize?state='+state,
                     '/api/v1/auth/callback/life-diary/android/complete?ticket='+'a'*43):
            self.assertEqual(client.get(public+path).status_code, 403)
        response = client.get(CALLBACK, params={'state': state, 'code': code}, follow_redirects=False)
        self.now += 61
        with patch.object(self.ld.provider, 'exchange') as exchange:
            self.assertEqual(client.get(response.headers['location']).status_code, 401)
            exchange.assert_not_called()

    def test_relay_expired_state_before_public_callback(self):
        _, client, code, state = self.start_relay()
        self.now += 301
        self.assertEqual(client.get(CALLBACK, params={'state': state, 'code': code}).status_code, 401)

    def test_pc_and_nn_login_still_work_on_relay_app(self):
        _, client, _, _ = self.start_relay()
        self.client = client
        nn, headers = self.login_nn()
        self.assertEqual(client.get('/api/v1/mobile/life-diary/session', headers=headers).status_code, 401)
        response = client.get('/auth/poc/login', follow_redirects=False)
        code, state = self.idp.issue(response.headers['location'], 'auth0|synthetic-a')
        response = client.get('/api/v1/auth/callback/web', params={'state': state, 'code': code},
                              follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(client.get('/api/v1/me').json()['sub'], nn['sub'])

    def test_relay_ticket_concurrent_claim_is_single_use(self):
        from concurrent.futures import ThreadPoolExecutor
        from fastapi import HTTPException
        from app.core.life_diary_dev_relay import DevelopmentRelay
        relay = DevelopmentRelay()
        relay.begin('s'*43, 'b'*43, 100)
        ticket = relay.receive('s'*43, 'synthetic-auth-code', 100)
        def claim(_):
            try:
                relay.consume(ticket, 'b'*43, 101)
                return True
            except HTTPException:
                return False
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(claim, range(2))), [False, True])

    def test_callback_and_relay_values_are_not_logged(self):
        import logging
        from app.core.auth_diagnostics import CallbackQueryFilter
        _, client, code, state = self.start_relay()
        browser = client.cookies.get('jl_ld_login')
        with self.assertLogs('uvicorn.error', level='INFO') as logs:
            response = client.get(CALLBACK, params={'state': state, 'code': code}, follow_redirects=False)
            location = response.headers['location']
            ticket = parse_qs(urlsplit(location).query)['ticket'][0]
            result = client.get(location, follow_redirects=False)
            self.assertEqual(result.status_code, 303)
        handoff = parse_qs(urlsplit(result.headers['location']).query)['code'][0]
        for secret in (code, state, ticket, browser, handoff,
                       self.values['LD_AUTH0_CLIENT_SECRET'], *self.ld.issued.values()):
            self.assertNotIn(secret, '\n'.join(logs.output))
        for target in (urlsplit(CALLBACK).path+'?state='+state+'&code='+code,
                       urlsplit(location).path+'?ticket='+ticket):
            record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s %s %s %s %s',
                                       ('client', 'GET', target, '1.1', 303), None)
            CallbackQueryFilter().filter(record)
            self.assertNotIn('?', record.getMessage())

    def test_cli_requires_opt_in_before_reading_settings(self):
        with patch('dotenv.dotenv_values', side_effect=AssertionError('must not read')):
            with self.assertRaises(SystemExit):
                main(['--settings', 'unused'])

    def test_cli_fixed_bind_and_no_access_log(self):
        with patch('dotenv.dotenv_values', return_value={}), \
                patch('scripts.auth0_pc_settings.validate', return_value=self.config), \
                patch('scripts.life_diary_dev.build_app', return_value='synthetic-app'), \
                patch('uvicorn.run') as run:
            self.assertEqual(main(['--enable', '--settings', 'synthetic-settings']), 0)
        run.assert_called_once_with('synthetic-app', host='127.0.0.1', port=8000,
                                    access_log=False, proxy_headers=False)

    def test_explicit_pc_settings_files_and_connector(self):
        self.prepare()
        pc_values = {
            'AUTH0_ISSUER': self.config.policy.issuer,
            'AUTH0_CLIENT_ID': next(iter(self.config.policy.client_ids)),
            'AUTH0_CLIENT_SECRET': 'synthetic-pc-secret',
            'AUTH0_AUDIENCE': self.config.policy.audience,
            'AUTH0_CALLBACK_URL': 'http://127.0.0.1:8000/api/v1/auth/callback/web',
            'CORE_DB_HOST': '127.0.0.1', 'CORE_DB_PORT': '3307',
            'CORE_DB_NAME': 'platform_core', 'CORE_DB_USER': 'platform_core_app',
            'CORE_DB_PASSWORD': 'synthetic-db-password',
            'CORE_TOKEN_HMAC_KEY': base64.b64encode(self.config.hmac_key).decode(),
            'CORE_TOKEN_ENCRYPTION_KEY': base64.b64encode(self.config.encryption_key).decode(),
        }
        # Use .conf names because the offline runner forbids all .env file opens.
        from dotenv.main import DotEnv
        with tempfile.TemporaryDirectory() as directory:
            pc = Path(directory) / 'pc.conf'
            ld = Path(directory) / 'ld.conf'
            for path, values in ((pc, pc_values), (ld, self.values)):
                path.write_text(''.join(k+'='+v+'\n' for k, v in values.items()), encoding='utf-8')
            reads = []
            def read_selected(path, **kwargs):
                self.assertIn(Path(path), (pc, ld))
                reads.append(Path(path))
                return DotEnv(path, interpolate=False).dict()
            output = StringIO()
            with patch('dotenv.dotenv_values', side_effect=read_selected), \
                    patch('uvicorn.run') as run, \
                    patch('app.core.database.connect') as connect, redirect_stdout(output):
                self.assertEqual(main(['--enable', '--settings', str(ld), '--pc-settings', str(pc)]), 0)
                runtime = run.call_args.args[0].state.auth_runtime
                runtime.store._connect()
                connect.assert_called_once_with(database='platform_core', user='platform_core_app',
                                                password='synthetic-db-password')
            self.assertEqual(reads, [ld, pc])
            self.assertEqual(output.getvalue(), '')
            with patch('dotenv.dotenv_values', side_effect=read_selected), \
                    patch('uvicorn.run') as run, redirect_stdout(StringIO()):
                pc.write_text('AUTH0_CLIENT_ID=synthetic-incomplete\n', encoding='utf-8')
                self.assertEqual(main(['--enable', '--settings', str(ld), '--pc-settings', str(pc)]), 1)
                run.assert_not_called()

    def test_omitted_pc_settings_keeps_default_path(self):
        from scripts.auth0_pc_settings import PATH
        with patch('dotenv.dotenv_values', return_value={}) as read, \
                patch('scripts.auth0_pc_settings.validate', return_value=self.config), \
                patch('scripts.life_diary_dev.build_app', return_value='synthetic-app'), \
                patch('uvicorn.run'):
            self.assertEqual(main(['--enable', '--settings', 'synthetic-settings']), 0)
        self.assertEqual(read.call_args_list[-1].args, (PATH,))


del Fixture
