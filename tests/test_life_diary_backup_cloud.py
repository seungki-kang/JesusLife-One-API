"""Dedicated backup connector tests; no network or live credentials."""
from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from app.core.postgres import PostgresConnectionError
from scripts import life_diary_backup_cloud as cli
from scripts import life_diary_backup_cloud_settings as settings
from tests.test_common_cloud_runtime import certificate


class BackupConnectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cert = Path(self.temp.name) / 'synthetic-ca.crt'
        certificate(self.cert)
        self.config = settings.validate({
            settings.ENABLED: '1',
            'PROJECT_NAME': settings.PROJECT_NAME,
            'PROJECT_REF': settings.PROJECT_REF,
            'POOLER_HOST': settings.POOLER_HOST,
            'SSLROOTCERT': str(self.cert),
        })
        self.driver = MagicMock()

    def test_construction_never_connects(self):
        cli.connector(self.config, 'synthetic-password', driver=self.driver)
        self.driver.assert_not_called()

    def test_strict_target_role_tls_and_raw_password(self):
        password = 'synthetic:@not-uri-encoded'
        connect = cli.connector(self.config, password, driver=self.driver)
        with patch.dict(os.environ, {}, clear=True):
            result = connect()
        self.assertIs(result, self.driver.return_value)
        self.driver.assert_called_once_with(
            host=settings.POOLER_HOST, port=5432, dbname='postgres',
            user=settings.ROLE + '.' + settings.PROJECT_REF,
            password=password, sslmode='verify-full',
            sslrootcert=str(self.cert), connect_timeout=5,
            application_name='jesuslife_ld_backup_dev',
            prepare_threshold=None,
            options='-c timezone=UTC -c statement_timeout=10000 -c lock_timeout=5000',
        )

    def test_disabled_or_forged_target_rejected(self):
        candidates = (
            replace(self.config, enabled=False),
            replace(self.config, pooler_host='127.0.0.1'),
            replace(self.config, project_ref='a' * 20),
            object(),
        )
        for config in candidates:
            with self.subTest(config_type=type(config).__name__):
                with self.assertRaises(ValueError):
                    cli.connector(config, 'synthetic', driver=self.driver)
        self.driver.assert_not_called()

    def test_missing_password_rejected(self):
        for password in (None, '', 123):
            with self.subTest(password_type=type(password).__name__):
                with self.assertRaises(ValueError):
                    cli.connector(self.config, password, driver=self.driver)
        self.driver.assert_not_called()

    def test_inherited_pg_options_block_driver(self):
        connect = cli.connector(self.config, 'synthetic', driver=self.driver)
        for key in ('PGHOST', 'PGPASSWORD', 'PGSERVICE', 'PGOPTIONS', 'pgport'):
            with self.subTest(key=key), patch.dict(
                    os.environ, {key: 'synthetic'}, clear=True):
                with self.assertRaises(PostgresConnectionError):
                    connect()
        self.driver.assert_not_called()

    def test_removed_certificate_blocks_driver(self):
        connect = cli.connector(self.config, 'synthetic', driver=self.driver)
        self.cert.unlink()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PostgresConnectionError):
                connect()
        self.driver.assert_not_called()

    def test_invalid_certificate_blocks_driver(self):
        connect = cli.connector(self.config, 'synthetic', driver=self.driver)
        self.cert.write_text('synthetic invalid certificate', encoding='utf-8')
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PostgresConnectionError):
                connect()
        self.driver.assert_not_called()

    def test_driver_failure_is_sanitized_and_not_retried(self):
        self.driver.side_effect = RuntimeError('synthetic-private-driver-detail')
        connect = cli.connector(self.config, 'synthetic', driver=self.driver)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PostgresConnectionError) as caught:
                connect()
        self.assertEqual(
            str(caught.exception), 'Dedicated backup PostgreSQL connection failed')
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(self.driver.call_count, 1)


if __name__ == '__main__':
    unittest.main()
