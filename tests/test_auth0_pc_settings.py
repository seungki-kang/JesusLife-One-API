import base64
import unittest

from scripts.auth0_pc_settings import AUDIENCE, CALLBACK, validate


class PcSettingsTest(unittest.TestCase):
    def settings(self):
        return dict(AUTH0_ISSUER='https://synthetic.example.invalid/',
                    AUTH0_CLIENT_ID='synthetic-client', AUTH0_CLIENT_SECRET='synthetic-secret',
                    AUTH0_AUDIENCE=AUDIENCE, AUTH0_CALLBACK_URL=CALLBACK,
                    CORE_DB_HOST='127.0.0.1', CORE_DB_PORT='3307', CORE_DB_NAME='platform_core',
                    CORE_DB_USER='platform_core_app', CORE_DB_PASSWORD='synthetic-db-secret',
                    CORE_TOKEN_HMAC_KEY=base64.b64encode(b'a' * 32).decode(),
                    CORE_TOKEN_ENCRYPTION_KEY=base64.b64encode(b'b' * 32).decode())

    def test_settings_validate_without_returning_secrets_in_repr(self):
        config = validate(self.settings())
        self.assertNotIn('synthetic-secret', repr(config))
        self.assertNotIn('synthetic-db-secret', repr(config))

    def test_missing_settings_do_not_invent_identity_or_keys(self):
        with self.assertRaises(ValueError):
            validate({})

    def test_wrong_callback_product_database_or_mariadb_rejected(self):
        for change in ({'AUTH0_CALLBACK_URL': 'jesuslife-poc://auth/complete/web'},
                       {'CORE_DB_NAME': 'neorang_narang'}, {'CORE_DB_PORT': '3306'},
                       {'CORE_DB_HOST': '192.0.2.1'}, {'CORE_DB_USER': 'nn_app'}):
            with self.subTest(names=list(change)), self.assertRaises(ValueError):
                validate(self.settings() | change)

    def test_invalid_key_is_not_reflected_in_errors(self):
        with self.assertRaises(ValueError) as caught:
            validate(self.settings() | {'CORE_TOKEN_ENCRYPTION_KEY': 'SYNTHETIC_PRIVATE_INVALID'})
        self.assertNotIn('SYNTHETIC_PRIVATE_INVALID', str(caught.exception))
