"""Backup target validation with synthetic certificates; no live configuration."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import life_diary_backup_cloud_settings as settings
from tests.test_common_cloud_runtime import certificate


class BackupCloudSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cert = Path(self.temp.name) / 'synthetic-ca.crt'
        certificate(self.cert)
        self.values = {
            settings.ENABLED: '0',
            'PROJECT_NAME': settings.PROJECT_NAME,
            'PROJECT_REF': settings.PROJECT_REF,
            'POOLER_HOST': settings.POOLER_HOST,
            'SSLROOTCERT': str(self.cert),
        }

    def test_default_profile_is_disabled(self):
        config = settings.validate(self.values)
        self.assertFalse(config.enabled)
        self.assertEqual(config.pooler_host, settings.POOLER_HOST)
        self.assertEqual(config.project_ref, settings.PROJECT_REF)

    def test_explicit_enablement(self):
        config = settings.validate(self.values | {settings.ENABLED: '1'})
        self.assertTrue(config.enabled)

    def test_missing_or_invalid_enablement_rejected(self):
        for value in (None, '', 'true', 'yes', True, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings.validate(self.values | {settings.ENABLED: value})

    def test_other_targets_rejected(self):
        changes = (
            {'PROJECT_NAME': 'other-project'},
            {'PROJECT_REF': 'a' * 20},
            {'POOLER_HOST': '127.0.0.1'},
            {'POOLER_HOST': 'other.pooler.supabase.com'},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                settings.validate(self.values | change)

    def test_extra_credentials_and_endpoint_overrides_rejected(self):
        for key in (
            'DB_PASSWORD', 'DATABASE_URL', 'PGHOST', 'PGPASSWORD',
            'JESUSLIFE_POSTGRES_RUNTIME_DSN', 'AUTH0_CLIENT_SECRET',
            'COMMON_TOKEN_HMAC_KEY', 'PORT', 'DB_USER',
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                settings.validate(self.values | {key: 'synthetic-private-value'})

    def test_missing_fields_rejected(self):
        for key in settings.KEYS:
            values = self.values.copy()
            del values[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                settings.validate(values)

    def test_invalid_certificate_paths_rejected(self):
        for value in ('relative.crt', str(self.cert) + ' ', None,
                      str(self.cert.parent / 'missing.crt')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings.validate(self.values | {'SSLROOTCERT': value})

    def test_invalid_certificate_content_rejected(self):
        self.cert.write_text('synthetic invalid certificate', encoding='utf-8')
        with self.assertRaises(ValueError) as caught:
            settings.validate(self.values)
        self.assertEqual(
            str(caught.exception), 'Invalid dedicated Life Diary backup settings')
        self.assertIsNone(caught.exception.__context__)

    def test_settings_repr_does_not_expose_configuration(self):
        config = settings.validate(self.values)
        self.assertNotIn(str(self.cert), repr(config))
        self.assertNotIn(settings.PROJECT_REF, repr(config))


if __name__ == '__main__':
    unittest.main()
