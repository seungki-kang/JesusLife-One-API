"""Offline checks for the explicit cloud backup server."""
from contextlib import contextmanager
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import life_diary_backup_cloud_server as server


class CloudBackupServerTests(unittest.TestCase):
    def test_password_input(self):
        result = server.read_passwords(BytesIO(
            b'{"auth_password":"synthetic-auth","backup_password":"synthetic-backup"}\n'))
        self.assertEqual(set(result), {'auth_password', 'backup_password'})

    def test_invalid_password_input(self):
        invalid = (
            b'', b'not-json', b'[]', b'{}',
            b'{"auth_password":"x","backup_password":""}',
            b'{"auth_password":7,"backup_password":"x"}',
            b'{"auth_password":"x","backup_password":"y","extra":"z"}',
            b'x' * 16385,
        )
        for supplied in invalid:
            with self.subTest(length=len(supplied)):
                with self.assertRaises((ValueError, UnicodeError)):
                    server.read_passwords(BytesIO(supplied))

    def test_settings_same_project(self):
        auth = SimpleNamespace(enabled=True, pooler_host='same',
                               project_ref='same', certificate=Path('synthetic-ca'))
        backup = SimpleNamespace(enabled=True, pooler_host='same',
                                 project_ref='same')
        with patch.object(server, 'dotenv_values', return_value={}), \
             patch.object(server, 'validate_settings', return_value=auth), \
             patch.object(server, 'validate_backup', return_value=backup), \
             patch.object(server.ssl, 'create_default_context') as tls:
            self.assertEqual(server.load_settings(Path('auth'), Path('backup')),
                             (auth, backup))
            tls.assert_called_once_with(cafile='synthetic-ca')

    def test_settings_reject_disabled_or_different_target(self):
        for enabled, host, project in (
                (False, 'same', 'same'),
                (True, 'different', 'same'),
                (True, 'same', 'different')):
            auth = SimpleNamespace(enabled=True, pooler_host='same',
                                   project_ref='same', certificate=Path('synthetic-ca'))
            backup = SimpleNamespace(enabled=enabled, pooler_host=host,
                                     project_ref=project)
            with self.subTest(enabled=enabled, host=host, project=project), \
                 patch.object(server, 'dotenv_values', return_value={}), \
                 patch.object(server, 'validate_settings', return_value=auth), \
                 patch.object(server, 'validate_backup', return_value=backup), \
                 patch.object(server.ssl, 'create_default_context'):
                with self.assertRaises(ValueError):
                    server.load_settings(Path('auth'), Path('backup'))

    def test_backup_probe_is_read_only(self):
        calls = []

        class Database:
            def execute(self, query):
                calls.append(query)
                return self

            def fetchone(self):
                return {'total': 3, 'forced': True}

        @contextmanager
        def transactions(account):
            self.assertEqual(account.version, 4)
            yield Database()

        server.probe_backup(transactions)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith('SELECT '))
        self.assertNotIn('INSERT', calls[0])

    def test_backup_probe_rejects_missing_rls(self):
        class Database:
            def execute(self, query):
                return self

            def fetchone(self):
                return {'total': 3, 'forced': False}

        @contextmanager
        def transactions(account):
            yield Database()

        with self.assertRaises(ValueError):
            server.probe_backup(transactions)

    def test_check_never_requests_password_or_connects(self):
        args = [
            'cloud-server', 'check', '--auth-settings', 'synthetic-auth',
            '--backup-settings', 'synthetic-backup', '--allow-cloud-backup',
        ]
        with patch.object(server.sys, 'argv', args), \
             patch.dict(server.os.environ, {}, clear=True), \
             patch.object(server, 'load_settings', return_value=(object(), object())), \
             patch.object(server, 'read_passwords') as passwords, \
             patch.object(server, 'auth_connector') as auth, \
             patch.object(server, 'backup_connector') as backup, \
             patch.object(server.uvicorn, 'run') as run, \
             patch('sys.stdout', new_callable=StringIO):
            server.main()
            passwords.assert_not_called()
            auth.assert_not_called()
            backup.assert_not_called()
            run.assert_not_called()

    def test_explicit_enablement_and_pg_environment_guards(self):
        base = [
            'cloud-server', 'probe', '--auth-settings', 'synthetic-auth',
            '--backup-settings', 'synthetic-backup',
        ]
        for argv, environment in (
                (base, {}),
                (base + ['--allow-cloud-backup'], {'PGHOST': 'synthetic'})):
            with self.subTest(environment=environment), \
                 patch.object(server.sys, 'argv', argv), \
                 patch.dict(server.os.environ, environment, clear=True), \
                 patch.object(server, 'load_settings') as settings, \
                 patch.object(server, 'read_passwords') as passwords:
                with self.assertRaises(SystemExit) as caught:
                    server.main()
                self.assertEqual(str(caught.exception),
                                 'BLOCKED: stage=INPUT; details suppressed; no fallback')
                settings.assert_not_called()
                passwords.assert_not_called()


if __name__ == '__main__':
    unittest.main()