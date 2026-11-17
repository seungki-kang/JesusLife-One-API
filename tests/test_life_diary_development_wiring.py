"""Applied development wiring: synthetic SQLite and mock provider only."""
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient

# Configured entrypoints must not read local environment files during import.
with patch('dotenv.dotenv_values', return_value={}):
    from app.auth0_mobile import create_development_app
    from tests.test_life_diary_login import LifeDiaryLoginTest as LoginFixture

from app.core.life_diary_login import PREFIX


class LifeDiaryDevelopmentWiringTest(LoginFixture):
    """Run existing HTTP login/isolation regressions against the applied module."""

    def enable(self):
        super().enable()
        config = self.runtime.life_diary_runtime.config
        provider = self.ld.provider
        self.runtime.life_diary_registration = None
        self.runtime.life_diary_runtime = None
        app = create_development_app(self.runtime, life_diary_config=config,
                                     enabled=True, provider=provider)
        self.client = TestClient(app, base_url='http://127.0.0.1:8000')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.assertIs(self.runtime.life_diary_runtime.store, self.runtime.store)
        self.assertIs(self.runtime.life_diary_runtime.clock, self.runtime.clock)
        self.assertIs(self.runtime.life_diary_runtime.provider, provider)

    def test_default_disabled_even_with_config_and_after_opt_in(self):
        self.enable()
        config = self.runtime.life_diary_runtime.config
        create_development_app(self.runtime, life_diary_config=config)
        self.assertIsNone(self.runtime.life_diary_runtime)
        self.assertIsNone(self.runtime.life_diary_registration)
        response = self.client.post(PREFIX+'/login-transactions', json=self.fields | {
            'challenge': 'a'*43})
        self.assertEqual(response.status_code, 503)

    def test_invalid_development_config_is_rejected_before_wiring(self):
        self.enable()
        config = self.runtime.life_diary_runtime.config
        parent = self.runtime
        parent.life_diary_registration = None
        parent.life_diary_runtime = None
        wrong = [None, self.config,
                 replace(config, policy=replace(config.policy, client_ids=frozenset({'a', 'b'}))),
                 replace(config, policy=replace(config.policy, issuer='https://other.auth0.com/')),
                 replace(config, policy=replace(config.policy, audience='https://other.invalid/')),
                 replace(config, client_secret=''),
                 replace(config, encryption_key=b'x'*32),
                 replace(config, hmac_key=b'x'*32)]
        for candidate in wrong:
            with self.subTest(candidate=wrong.index(candidate)):
                with self.assertRaises(ValueError):
                    create_development_app(parent, life_diary_config=candidate, enabled=True)
                self.assertIsNone(parent.life_diary_runtime)
                self.assertIsNone(parent.life_diary_registration)
        with self.assertRaises(ValueError):
            create_development_app(None, life_diary_config=config, enabled=True)

    def test_wrong_app_and_client_rejected_at_start(self):
        self.enable()
        for field, value in [('app_id', 'neorang_narang'),
                             ('client_id', next(iter(self.config.policy.client_ids)))]:
            response = self.client.post(PREFIX+'/login-transactions', json=self.fields | {
                'challenge': 'a'*43, field: value})
            self.assertEqual(response.status_code, 401)


del LoginFixture  # Avoid collecting the imported base class a second time.
