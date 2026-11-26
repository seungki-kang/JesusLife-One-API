"""Cloud launcher composition tests; no network or real credentials."""
from contextlib import ExitStack
from io import BytesIO, StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import life_diary_backup_cloud_server as cli


class CloudLauncherRuntimeTests(unittest.TestCase):
    def invoke(self, action, *, failure=None):
        argv = [
            'launcher', action,
            '--auth-settings', 'synthetic-auth-settings',
            '--backup-settings', 'synthetic-backup-settings',
            '--allow-cloud-backup',
        ]
        with ExitStack() as stack:
            stack.enter_context(patch('sys.argv', argv))
            stack.enter_context(patch.dict(cli.os.environ, {}, clear=True))
            stack.enter_context(patch(
                'sys.stdin', SimpleNamespace(buffer=BytesIO(
                    b'{"auth_password":"synthetic-auth",'
                    b'"backup_password":"synthetic-backup"}\n'))))
            output = stack.enter_context(patch('sys.stdout', new_callable=StringIO))
            mocks = {}
            for name in (
                'socket.socket', 'load_settings',
                'auth_connector', 'backup_connector',
                'CompletedBackupTransactions', 'probe_backup',
                'CommonMobileAuthStore', 'probe',
                'CompletedBackupStore', 'create_app', 'uvicorn.run',
            ):
                mocks[name] = stack.enter_context(
                    patch('scripts.life_diary_backup_cloud_server.' + name))
            auth = SimpleNamespace(
                encryption_key=b'e' * 32, hmac_key=b'h' * 32)
            backup = SimpleNamespace()
            mocks['load_settings'].return_value = (auth, backup)

            if failure == 'port':
                listener = mocks['socket.socket'].return_value.__enter__.return_value
                listener.bind.side_effect = OSError('synthetic-private-detail')
            elif failure == 'backup':
                mocks['probe_backup'].side_effect = ValueError('synthetic-private-detail')
            elif failure == 'auth':
                mocks['probe'].side_effect = ValueError('synthetic-private-detail')

            error = None
            try:
                cli.main()
            except SystemExit as caught:
                error = str(caught)
            return error, mocks, output.getvalue(), auth, backup

    def test_probe_checks_both_stores_without_starting_server(self):
        error, mocks, output, auth, backup = self.invoke('probe')
        self.assertIsNone(error)
        mocks['backup_connector'].assert_called_once_with(
            backup, 'synthetic-backup')
        mocks['auth_connector'].assert_called_once_with(
            auth, 'synthetic-auth')
        mocks['CompletedBackupTransactions'].assert_called_once_with(
            connector=mocks['backup_connector'].return_value)
        mocks['CommonMobileAuthStore'].assert_called_once_with(
            auth.encryption_key, auth.hmac_key,
            connector=mocks['auth_connector'].return_value,
            app_id=cli.APP_ID)
        mocks['probe_backup'].assert_called_once_with(
            mocks['CompletedBackupTransactions'].return_value)
        mocks['probe'].assert_called_once_with(
            mocks['CommonMobileAuthStore'].return_value, auth)
        mocks['socket.socket'].assert_not_called()
        mocks['create_app'].assert_not_called()
        mocks['uvicorn.run'].assert_not_called()
        self.assertNotIn('synthetic-auth', output)
        self.assertNotIn('synthetic-backup', output)

    def test_serve_composes_cloud_stores_and_loopback_server(self):
        error, mocks, output, auth, backup = self.invoke('serve')
        self.assertIsNone(error)
        mocks['socket.socket'].return_value.__enter__.return_value.bind.assert_called_once_with(
            ('127.0.0.1', 8000))
        transactions = mocks['CompletedBackupTransactions'].return_value
        mocks['CompletedBackupStore'].assert_called_once_with(
            transaction=transactions)
        mocks['create_app'].assert_called_once_with(
            auth, mocks['CommonMobileAuthStore'].return_value,
            backup_store=mocks['CompletedBackupStore'].return_value)
        mocks['uvicorn.run'].assert_called_once_with(
            mocks['create_app'].return_value,
            host='127.0.0.1', port=8000, access_log=False,
            proxy_headers=False, log_level='critical')
        self.assertNotIn('synthetic-auth', output)
        self.assertNotIn('synthetic-backup', output)

    def test_port_conflict_prevents_database_work(self):
        error, mocks, _, _, _ = self.invoke('serve', failure='port')
        self.assertIn('stage=PORT', error)
        self.assertNotIn('synthetic-private-detail', error)
        mocks['backup_connector'].assert_not_called()
        mocks['auth_connector'].assert_not_called()
        mocks['uvicorn.run'].assert_not_called()

    def test_backup_failure_prevents_auth_connection_and_server(self):
        error, mocks, _, _, _ = self.invoke('serve', failure='backup')
        self.assertIn('stage=BACKUP_READINESS', error)
        self.assertNotIn('synthetic-private-detail', error)
        mocks['auth_connector'].assert_not_called()
        mocks['create_app'].assert_not_called()
        mocks['uvicorn.run'].assert_not_called()

    def test_auth_failure_prevents_server(self):
        error, mocks, _, _, _ = self.invoke('serve', failure='auth')
        self.assertIn('stage=AUTH_READINESS', error)
        self.assertNotIn('synthetic-private-detail', error)
        mocks['create_app'].assert_not_called()
        mocks['uvicorn.run'].assert_not_called()


if __name__ == '__main__':
    unittest.main()