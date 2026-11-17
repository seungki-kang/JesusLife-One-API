"""Synthetic adapter tests: libpq and Python network entry points are denied."""
import importlib
import traceback
import unittest
from unittest.mock import Mock, patch

from app.core import postgres
from app.core.postgres_settings import (
    MIGRATION_DSN, RUNTIME_DSN, PostgresConfigurationError,
)


RUNTIME = 'postgresql://synthetic_runtime:synthetic_password@db.example.invalid/synthetic?sslmode=require'
MIGRATION = RUNTIME.replace('synthetic_runtime', 'synthetic_migration')
CONFIG = {RUNTIME_DSN: RUNTIME, MIGRATION_DSN: MIGRATION}


class PostgresAdapterTest(unittest.TestCase):
    def setUp(self):
        self.driver = self.enterContext(patch('psycopg.connect', side_effect=AssertionError('DB denied')))
        self.socket = self.enterContext(patch('socket.socket.connect', side_effect=AssertionError('Network denied')))
        self.dns = self.enterContext(patch('socket.getaddrinfo', side_effect=AssertionError('DNS denied')))
        self.connection = Mock()
        self.cursor = self.connection.cursor.return_value
        self.cursor.fetchone.return_value = (1,)
        self.connector = Mock(return_value=self.connection)

    def tearDown(self):
        self.driver.assert_not_called()
        self.socket.assert_not_called()
        self.dns.assert_not_called()

    def assert_safe(self, operation):
        try:
            operation()
        except postgres.PostgresConnectionError as error:
            output = str(error) + repr(error) + traceback.format_exc()
            self.assertIsNone(error.__context__)
            self.assertIsNone(error.__cause__)
            for secret in (RUNTIME, 'synthetic_password', 'db.example.invalid'):
                self.assertNotIn(secret, output)
        else:
            self.fail('Expected safe application error')

    def test_runtime_and_migration_are_separate(self):
        for entry, dsn, purpose in (
            (postgres.connect_runtime, RUNTIME, 'runtime'),
            (postgres.connect_migration, MIGRATION, 'migration'),
        ):
            self.connector.reset_mock()
            result = entry(CONFIG, connector=self.connector)
            self.assertIs(result, self.connection)
            self.connector.assert_called_once_with(
                dsn, connect_timeout=5, application_name=f'jesuslife_{purpose}',
                options='-c timezone=UTC',
            )
            self.connection.close.assert_not_called()
            self.connection.commit.assert_not_called()
            self.assertNotIn('autocommit', self.connector.call_args.kwargs)

    def test_default_connector_is_resolved_only_on_call(self):
        # Replace the deny guard temporarily with a fake; never call libpq.
        with patch('psycopg.connect', self.connector):
            self.assertIs(postgres.connect_runtime(CONFIG), self.connection)
        self.connector.assert_called_once()

    def test_import_and_app_creation_do_not_connect(self):
        importlib.reload(postgres)
        import app.main
        importlib.reload(app.main)

    def test_existing_configuration_validation_runs_before_connector(self):
        for entry in (postgres.connect_runtime, postgres.connect_migration):
            for config in ({}, {RUNTIME_DSN: RUNTIME, MIGRATION_DSN: RUNTIME},
                           {RUNTIME_DSN: 'invalid', MIGRATION_DSN: 'invalid'}):
                with self.assertRaises(PostgresConfigurationError):
                    entry(config, connector=self.connector)
        self.connector.assert_not_called()

    def test_probe_success_closes_resources_without_commit(self):
        self.assertTrue(postgres.probe_runtime(CONFIG, connector=self.connector))
        self.cursor.execute.assert_called_once_with('SELECT 1')
        self.cursor.close.assert_called_once_with()
        self.connection.close.assert_called_once_with()
        self.connection.commit.assert_not_called()

    def test_connect_errors_are_safe_for_both_entry_points_and_probe(self):
        self.connector.side_effect = RuntimeError(RUNTIME)
        for entry in (postgres.connect_runtime, postgres.connect_migration, postgres.probe_runtime):
            self.assert_safe(lambda: entry(CONFIG, connector=self.connector))
        self.connection.close.assert_not_called()

    def test_query_fetch_and_cleanup_failures_are_safe_and_close_both(self):
        for target in (self.cursor.execute, self.cursor.fetchone,
                       self.cursor.close, self.connection.close):
            with self.subTest(operation=target._mock_name):
                self.cursor.reset_mock()
                self.connection.close.reset_mock()
                target.side_effect = RuntimeError(RUNTIME)
                self.assert_safe(lambda: postgres.probe_runtime(CONFIG, connector=self.connector))
                self.cursor.close.assert_called_once_with()
                self.connection.close.assert_called_once_with()
                target.side_effect = None

    def test_cursor_creation_failure_still_closes_connection(self):
        self.connection.cursor.side_effect = RuntimeError(RUNTIME)
        self.assert_safe(lambda: postgres.probe_runtime(CONFIG, connector=self.connector))
        self.connection.close.assert_called_once_with()

    def test_unexpected_probe_result_is_safe_failure(self):
        self.cursor.fetchone.return_value = (0,)
        self.assert_safe(lambda: postgres.probe_runtime(CONFIG, connector=self.connector))
        self.cursor.close.assert_called_once_with()
        self.connection.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
