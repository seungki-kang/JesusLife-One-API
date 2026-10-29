"""Pre-provider fail-closed boundary tests, NOT token-verifier conformance.

Valid signed synthetic tokens must also fail until a provider and Core session
adapter are implemented. All requests use the real auth dependency; no overrides.
"""
import base64
import unittest
from unittest.mock import patch

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient

from app.main import app
from tests.auth_contract_fixtures import ACCOUNT_A, ACCOUNT_B, SyntheticJWTs


class AuthContractPreparationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = SyntheticJWTs()
        cls.cases = cls.tokens.cases()

    def setUp(self):
        # Never clear/mutate another test's overrides to force a passing result.
        self.assertFalse(app.dependency_overrides)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_vectors_include_real_signatures_and_an_untrusted_key(self):
        for name in ('active_a', 'active_b', 'wrong_signature'):
            case = next(c for c in self.cases if c.name == name)
            head, payload, encoded = case.token.split('.')
            signature = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
            def verify():
                self.tokens.public_key.verify(signature, (head + '.' + payload).encode(),
                                              padding.PKCS1v15(), hashes.SHA256())
            if name == 'wrong_signature':
                with self.assertRaises(InvalidSignature):
                    verify()
            else:
                verify()

    def test_no_token_fixture_can_enable_unconfigured_authentication(self):
        path = '/api/v1/neorang-narang/completions'
        record = '10000000-0000-4000-8000-000000000001'
        operations = [('GET', path), ('POST', path), ('GET', path + '/' + record),
                      ('PUT', path + '/' + record), ('DELETE', path + '/' + record)]
        with patch('app.core.database.pymysql.connect') as database:
            for case in self.cases:
                for method, url in operations:
                    with self.subTest(case=case.name, method=method):
                        response = self.client.request(method, url, json={}, headers={
                            'Authorization': 'Bearer ' + case.token})
                        self.assertEqual(response.status_code, 401)
                        self.assertEqual(response.json(), {'detail': 'Authentication required'})
                        self.assertEqual(response.headers['www-authenticate'], 'Bearer')
                        self.assertNotIn(case.token, response.text)
            database.assert_not_called()

    def test_account_and_session_claims_in_request_never_establish_identity(self):
        with patch('app.core.database.pymysql.connect') as database:
            for account in (ACCOUNT_A, ACCOUNT_B):
                response = self.client.post(
                    '/api/v1/neorang-narang/completions?sub=' + str(account),
                    headers={'X-User-ID': str(account), 'X-Session-ID': 'synthetic-session',
                             'Authorization': 'Bearer ' + self.cases[0].token},
                    json={'owner_sub': str(account), 'session_id': 'synthetic-session'})
                self.assertEqual(response.status_code, 401)
                self.assertNotIn(str(account), response.text)
                self.assertNotIn('synthetic-session', response.text)
            database.assert_not_called()

    def test_unimplemented_contract_paths_are_not_authentication_shortcuts(self):
        # Candidate paths are documentation, not active endpoints.
        for path in ('login-transactions', 'session-exchange', 'refresh', 'logout',
                     'logout-all', 'idp-logout'):
            with self.subTest(path=path):
                self.assertEqual(self.client.post('/api/v1/auth/' + path, json={}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
