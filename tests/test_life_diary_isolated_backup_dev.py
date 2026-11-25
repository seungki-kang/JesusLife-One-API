"""Isolated launcher tests; all sockets, DB access and server startup are mocked."""
from contextlib import ExitStack
from io import BytesIO, StringIO
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from scripts import life_diary_isolated_backup_dev as cli


class IsolatedLauncherTests(unittest.TestCase):
    def setUp(self):
        self.argv = [
            'launcher', '--auth-settings', 'synthetic-settings',
            '--backup-port', '10625', '--allow-isolated-backup',
        ]
        self.payload = {
            'auth_password': 'synthetic-auth',
            'backup_password': 'synthetic-backup',
        }

    def invoke(self, *, argv=None, raw=None, environ=None, setup=None):
        with ExitStack() as stack:
            stack.enter_context(patch('sys.argv', argv or self.argv))
            stack.enter_context(patch.dict(
                cli.os.environ, environ or {}, clear=True))
            stack.enter_context(patch(
                'sys.stdin', SimpleNamespace(buffer=BytesIO(
                    raw if raw is not None else
                    (json.dumps(self.payload) + '\n').encode()))))
            output = stack.enter_context(patch('sys.stdout', new_callable=StringIO))
            mocks = {}
            for name in (
                'socket.socket', 'dotenv_values', 'validate_settings',
                'ssl.create_default_context', 'CompletedBackupTransactions',
                'CommonMobileAuthStore', 'connector', 'probe',
                'create_app', 'uvicorn.run',
            ):
                mocks[name] = stack.enter_context(patch.object(
                    cli, name) if '.' not in name else
                    patch('scripts.life_diary_isolated_backup_dev.' + name))
            mocks['validate_settings'].return_value = SimpleNamespace(
                enabled=True, certificate='synthetic-ca',
                encryption_key=b'e' * 32, hmac_key=b'h' * 32)
            db = (
                mocks['CompletedBackupTransactions'].return_value
                .return_value.__enter__.return_value
            )
            db.execute.return_value.fetchone.return_value = {
                'total': 3, 'forced': True}
            if setup:
                setup(mocks)
            error = None
            try:
                cli.main()
            except SystemExit as caught:
                error = str(caught)
            return error, mocks, output.getvalue()

    def test_explicit_opt_in_required(self):
        error, mocks, _ = self.invoke(argv=self.argv[:-1])
        self.assertIn('stage=INPUT', error)
        mocks['socket.socket'].assert_not_called()
        mocks['connector'].assert_not_called()

    def test_inherited_pg_settings_rejected(self):
        error, mocks, _ = self.invoke(environ={'PGHOST': 'synthetic'})
        self.assertIn('stage=INPUT', error)
        mocks['socket.socket'].assert_not_called()

    def test_port_conflict_stops_before_configuration(self):
        def setup(mocks):
            mocks['socket.socket'].return_value.__enter__.return_value.bind.side_effect = (
                OSError('synthetic-private-detail'))
        error, mocks, _ = self.invoke(setup=setup)
        self.assertIn('stage=INPUT', error)
        self.assertNotIn('synthetic-private-detail', error)
        mocks['dotenv_values'].assert_not_called()

    def test_malformed_and_oversized_input_rejected(self):
        for raw in (b'not-json\n', b'x' * 16385, b'{}\n'):
            with self.subTest(size=len(raw)):
                error, mocks, _ = self.invoke(raw=raw)
                self.assertIn('stage=INPUT', error)
                mocks['dotenv_values'].assert_not_called()

    def test_disabled_auth_configuration_rejected(self):
        def setup(mocks):
            mocks['validate_settings'].return_value.enabled = False
        error, mocks, _ = self.invoke(setup=setup)
        self.assertIn('stage=AUTH_SETTINGS', error)
        mocks['CompletedBackupTransactions'].assert_not_called()

    def test_rls_readiness_failure_stops_auth_connection(self):
        def setup(mocks):
            db = (mocks['CompletedBackupTransactions'].return_value
                  .return_value.__enter__.return_value)
            db.execute.return_value.fetchone.return_value = {
                'total': 3, 'forced': False}
        error, mocks, _ = self.invoke(setup=setup)
        self.assertIn('stage=BACKUP_READINESS', error)
        mocks['connector'].assert_not_called()
        mocks['uvicorn.run'].assert_not_called()

    def test_explicit_composition_starts_only_after_readiness(self):
        error, mocks, output = self.invoke()
        self.assertIsNone(error)
        mocks['probe'].assert_called_once()
        self.assertIn('backup_store', mocks['create_app'].call_args.kwargs)
        options = mocks['uvicorn.run'].call_args.kwargs
        self.assertEqual((options['host'], options['port']), ('127.0.0.1', 8000))
        self.assertFalse(options['access_log'])
        self.assertFalse(options['proxy_headers'])
        self.assertNotIn('synthetic-auth', output)
        self.assertNotIn('synthetic-backup', output)


if __name__ == '__main__':
    unittest.main()
