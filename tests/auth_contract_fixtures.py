"""Synthetic inputs for future verifier conformance; never imported by app code.

No verifier, trusted production issuer, session implementation, or persisted key.
The RS256 test profile is a fixture choice, not an approved provider profile.
"""
import base64
from dataclasses import dataclass, field
import json
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ISSUER = 'https://identity.example.invalid/'
AUDIENCE = 'urn:jesuslife:synthetic-api'
CLIENT = 'synthetic-app'
NOW = 1_800_000_000
ACCOUNT_A = UUID('00000000-0000-4000-8000-000000000001')
ACCOUNT_B = UUID('00000000-0000-4000-8000-000000000002')


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


@dataclass(frozen=True)
class TokenCase:
    name: str
    token: str = field(repr=False)
    # Expected only AFTER an adapter is configured with this fixture's key,
    # issuer, profile and active Core session/consent. Not a live test result.
    future_expectation: str


class SyntheticJWTs:
    def __init__(self):
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self._key.public_key()

    def signed(self, *, claims=None, header=None, other_key=False, omit=()):
        payload = dict(iss=ISSUER, aud=AUDIENCE, sub='synthetic-provider-a',
                       azp=CLIENT, token_use='access', iat=NOW, exp=NOW + 600,
                       scope='neorang-narang:read neorang-narang:write')
        payload.update(claims or {})
        for name in omit:
            payload.pop(name, None)
        protected = {'alg': 'RS256', 'kid': 'synthetic-key', 'typ': 'at+jwt'}
        protected.update(header or {})
        parts = [b64url(json.dumps(value, separators=(',', ':')).encode())
                 for value in (protected, payload)]
        message = '.'.join(parts).encode('ascii')
        key = self._other_key if other_key else self._key
        signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        return message.decode('ascii') + '.' + b64url(signature)

    def cases(self):
        valid = self.signed()
        _, payload, _ = valid.split('.')
        unsigned = b64url(b'{"alg":"none"}') + '.' + payload + '.'
        wrong_algorithm = b64url(b'{"alg":"HS256","kid":"synthetic-key"}')
        return (
            TokenCase('active_a', valid, 'allow_account_a'),
            TokenCase('active_b', self.signed(claims={'sub': 'synthetic-provider-b'}), 'allow_account_b'),
            TokenCase('wrong_signature', self.signed(other_key=True), 'reject_401'),
            TokenCase('unsigned', unsigned, 'reject_401'),
            TokenCase('algorithm_confusion', wrong_algorithm + '.' + payload + '.c3ludGhldGlj', 'reject_401'),
            TokenCase('wrong_issuer', self.signed(claims={'iss': 'https://other.example.invalid/'}), 'reject_401'),
            TokenCase('wrong_audience', self.signed(claims={'aud': 'urn:other:api'}), 'reject_401'),
            TokenCase('audience_array', self.signed(claims={'aud': ['urn:other:api', AUDIENCE]}), 'allow_account_a'),
            TokenCase('id_token', self.signed(header={'typ': 'JWT'}, claims={'token_use': 'id'}), 'reject_401'),
            TokenCase('expired', self.signed(claims={'iat': NOW - 1200, 'exp': NOW - 600}), 'reject_401'),
            TokenCase('future_nbf', self.signed(claims={'nbf': NOW + 3600}), 'reject_401'),
            TokenCase('future_iat', self.signed(claims={'iat': NOW + 3600, 'exp': NOW + 4200}), 'reject_401'),
            TokenCase('empty_subject', self.signed(claims={'sub': ''}), 'reject_401'),
            TokenCase('missing_subject', self.signed(omit=('sub',)), 'reject_401'),
            TokenCase('missing_expiry', self.signed(omit=('exp',)), 'reject_401'),
            TokenCase('null_expiry', self.signed(claims={'exp': None}), 'reject_401'),
            TokenCase('unknown_key', self.signed(header={'kid': 'unknown-synthetic-key'}), 'reject_401'),
            TokenCase('malformed', 'synthetic-not-a-jwt', 'reject_401'),
        )
