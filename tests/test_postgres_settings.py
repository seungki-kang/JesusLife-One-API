import traceback
import unittest
from unittest.mock import patch

from app.core.postgres_settings import (
    MIGRATION_DSN, RUNTIME_DSN, PostgresConfigurationError,
    load_postgres_migration_settings, load_postgres_runtime_settings,
)


RUNTIME = 'postgresql://synthetic_runtime:synthetic_password@db.example.invalid/synthetic_db?sslmode=require'
MIGRATION = 'postgres://synthetic_migration:synthetic_other_password@db.example.invalid/synthetic_db?sslmode=require'


class PostgresSettingsTest(unittest.TestCase):
    def test_missing_settings(self):
        for loader in (load_postgres_runtime_settings, load_postgres_migration_settings):
            for value in (None, ''):
                with self.subTest(loader=loader.__name__, value=value):
                    with self.assertRaises(PostgresConfigurationError):
                        loader({RUNTIME_DSN: value, MIGRATION_DSN: value})

    def test_separate_synthetic_settings(self):
        config = {RUNTIME_DSN: RUNTIME, MIGRATION_DSN: MIGRATION}
        runtime = load_postgres_runtime_settings(config)
        migration = load_postgres_migration_settings(config)
        self.assertEqual((runtime.purpose, runtime.dsn), ('runtime', RUNTIME))
        self.assertEqual((migration.purpose, migration.dsn), ('migration', MIGRATION))

    def test_each_purpose_can_be_provisioned_alone(self):
        self.assertEqual(load_postgres_runtime_settings({RUNTIME_DSN: RUNTIME}).dsn, RUNTIME)
        self.assertEqual(load_postgres_migration_settings({MIGRATION_DSN: MIGRATION}).dsn, MIGRATION)
        with patch('app.core.postgres_settings.os.environ', {RUNTIME_DSN: RUNTIME}):
            self.assertEqual(load_postgres_runtime_settings().dsn, RUNTIME)

    def test_invalid_scheme_tls_and_uri(self):
        values = [
            RUNTIME.replace('postgresql:', 'mysql:'),
            RUNTIME.split('?')[0],
            RUNTIME.replace('require', 'prefer'),
            RUNTIME + '&sslmode=disable',
            RUNTIME + '&host=localhost',
            RUNTIME + '&sslmode=',
            RUNTIME + '#synthetic_fragment',
            RUNTIME.replace('db.example.invalid', '[invalid'),
            RUNTIME.replace('db.example.invalid', 'db.example.invalid:bad'),
            RUNTIME.replace('db.example.invalid', 'db.example.invalid:0'),
            RUNTIME.replace('synthetic_password', ''),
            RUNTIME + '\n',
        ]
        for value in values:
            with self.subTest(case=values.index(value)):
                with self.assertRaises(PostgresConfigurationError):
                    load_postgres_runtime_settings({RUNTIME_DSN: value})

    def test_tls_verification_modes_and_loopback(self):
        for mode in ('require', 'verify-ca', 'verify-full'):
            load_postgres_runtime_settings({RUNTIME_DSN: RUNTIME.replace('require', mode)})
        for host in ('localhost', '127.0.0.1', '[::1]'):
            load_postgres_runtime_settings({RUNTIME_DSN: RUNTIME.split('?')[0].replace('db.example.invalid', host)})

    def test_same_credentials_rejected_in_both_loaders(self):
        for other in (RUNTIME, RUNTIME.replace('postgresql:', 'postgres:')
                      .replace('db.example.invalid', 'DB.EXAMPLE.INVALID:5432'),
                      RUNTIME.replace('synthetic_runtime', '%73ynthetic_runtime')
                      .replace('synthetic_password', 'synthetic_rotated_password')):
            for loader in (load_postgres_runtime_settings, load_postgres_migration_settings):
                with self.assertRaises(PostgresConfigurationError):
                    loader({RUNTIME_DSN: RUNTIME, MIGRATION_DSN: other})

    def test_repr_str_and_errors_redact_secrets(self):
        settings = load_postgres_runtime_settings({RUNTIME_DSN: RUNTIME})
        outputs = [str(settings), repr(settings)]
        for value in (RUNTIME.replace('require', 'disable'),
                      RUNTIME.replace('db.example.invalid', '[synthetic_password')):
            try:
                load_postgres_runtime_settings({RUNTIME_DSN: value})
            except PostgresConfigurationError as error:
                outputs.extend((str(error), repr(error), traceback.format_exc()))
                self.assertIsNone(error.__context__)
            else:
                self.fail('Expected configuration rejection')
        for output in outputs:
            for secret in (RUNTIME, 'synthetic_password', 'db.example.invalid', 'synthetic_runtime'):
                self.assertNotIn(secret, output)
