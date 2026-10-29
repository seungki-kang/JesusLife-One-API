"""Offline PoC primitives. Not wired to get_current_user or any HTTP route.

No network, environment defaults, database creation, login bypass, or token minting.
Real OIDC code/ID-token validation and a durable Core registry are still required.
"""
import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
from typing import Mapping, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException

from .auth_diagnostics import stage
from .auth import AuthContext


def denied():
    return HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})


def pkce_challenge(verifier: str) -> str:
    """RFC 7636 S256; callers generate a new high-entropy verifier per flow."""
    if not isinstance(verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
        raise ValueError('Invalid PKCE verifier')
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')


def matches_pkce(verifier: str, challenge: str) -> bool:
    try:
        return isinstance(challenge, str) and hmac.compare_digest(pkce_challenge(verifier), challenge)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True, repr=False)
class PocTokenPolicy:
    issuer: str
    audience: str
    client_ids: frozenset[str]
    max_lifetime: int = 600
    clock_skew: int = 30

    def __post_init__(self):
        url = urlsplit(self.issuer)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.path != '/' or url.query or url.fragment
                or not self.audience or not self.client_ids
                or self.audience in self.client_ids or self.audience == self.issuer
                or any(not isinstance(c, str) or not c for c in self.client_ids)
                or type(self.max_lifetime) is not int or not 1 <= self.max_lifetime <= 600
                or type(self.clock_skew) is not int or not 0 <= self.clock_skew <= 30):
            raise ValueError('Invalid PoC token policy')


@dataclass(frozen=True, repr=False)
class VerifiedAccess:
    issuer: str
    subject: str
    client_id: str
    fingerprint: bytes = field(repr=False)
    expires_at: int
    scopes: frozenset[str]


def _decode(segment: str) -> bytes:
    if not re.fullmatch(r'[A-Za-z0-9_-]+', segment):
        raise ValueError('Invalid JWT encoding')
    raw = base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))
    if base64.urlsafe_b64encode(raw).rstrip(b'=').decode() != segment:
        raise ValueError('Noncanonical JWT encoding')
    return raw


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JWT field')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Invalid JSON constant')


class OfflineAccessVerifier:
    """RS256/RFC9068 testable verifier with explicitly supplied trusted RSA keys.

    This intentionally has no discovery/JWKS fetching; callers must obtain keys
    from the configured issuer. HTTP activation is forbidden until that exists.
    """
    def __init__(self, policy: PocTokenPolicy, keys: Mapping[str, rsa.RSAPublicKey],
                 fingerprint_key: bytes):
        if not isinstance(fingerprint_key, bytes) or len(fingerprint_key) < 32:
            raise ValueError('Fingerprint key required')
        if not keys or any(not isinstance(k, rsa.RSAPublicKey) or k.key_size < 2048 for k in keys.values()):
            raise ValueError('Trusted RSA keys required')
        self.policy, self._keys, self._fingerprint_key = policy, dict(keys), fingerprint_key

    def verify(self, token: str, *, now: int) -> VerifiedAccess:
        try:
            if not isinstance(token, str) or len(token) > 16384 or type(now) is not int:
                raise ValueError('Invalid input')
            head, payload, signature = token.split('.')
            header = json.loads(_decode(head), object_pairs_hook=_object, parse_constant=_invalid_constant)
            claims = json.loads(_decode(payload), object_pairs_hook=_object, parse_constant=_invalid_constant)
            if not isinstance(header, dict) or not isinstance(claims, dict):
                raise ValueError('Invalid JWT objects')
            with stage('access_profile'):
                if (header.get('alg') != 'RS256' or header.get('typ') != 'at+jwt'
                        or any(k in header for k in ('crit', 'jku', 'x5u', 'jwk', 'b64'))):
                    raise ValueError('Unsupported JWT profile')
            with stage('access_signature'):
                key = self._keys[header['kid']]
                key.verify(_decode(signature), (head + '.' + payload).encode('ascii'),
                           padding.PKCS1v15(), hashes.SHA256())
            with stage('access_claims'):
                policy = self.policy
                audience = claims.get('aud')
                audiences = [audience] if isinstance(audience, str) else audience
                if (not isinstance(audiences, list) or not audiences
                        or any(not isinstance(a, str) or not a for a in audiences)
                        or policy.audience not in audiences or claims.get('iss') != policy.issuer
                        or claims.get('client_id') not in policy.client_ids
                        or not isinstance(claims.get('sub'), str) or not claims['sub'].strip()
                        or not isinstance(claims.get('jti'), str) or not claims['jti']
                        or claims.get('gty') == 'client-credentials'
                        or claims['sub'] == claims['client_id']
                        or claims.get('token_use', 'access') != 'access'):
                    raise ValueError('Invalid JWT claims')
            with stage('access_time'):
                exp, iat = claims['exp'], claims['iat']
                nbf = claims.get('nbf', iat)
                if (any(type(t) is not int for t in (exp, iat, nbf)) or iat < 0
                        or exp <= iat or exp - iat > policy.max_lifetime
                        or exp <= now - policy.clock_skew
                        or iat > now + policy.clock_skew or nbf > now + policy.clock_skew):
                    raise ValueError('Invalid JWT time')
            scope = claims.get('scope', '')
            if not isinstance(scope, str):
                raise ValueError('Invalid scope')
            fingerprint = hmac.digest(self._fingerprint_key, token.encode('ascii'), 'sha256')
            return VerifiedAccess(policy.issuer, claims['sub'], claims['client_id'],
                                  fingerprint, exp, frozenset(scope.split()))
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, InvalidSignature):
            raise denied() from None


@dataclass(frozen=True, repr=False)
class AppSession:
    session_id: UUID
    account_id: UUID
    issuer: str
    subject: str
    client_id: str
    expires_at: int
    version: int = 0
    revoked: bool = False
    account_active: bool = True
    consent_active: bool = True


def validate_binding_candidate(token: VerifiedAccess, session: AppSession,
                               *, expected_version: int, now: int) -> None:
    """Run INSIDE registry commit/CAS after trusted code/refresh proof.

    This is not login proof and cannot register a bearer by itself. A durable
    repository must consume the proof and enforce global fingerprint uniqueness.
    """
    if (session.revoked or not session.account_active or session.expires_at <= now
            or session.version != expected_version or token.expires_at <= now
            or (session.issuer, session.subject, session.client_id)
            != (token.issuer, token.subject, token.client_id)):
        raise denied()


class SessionStoreUnavailable(Exception):
    pass


class SessionRegistry(Protocol):
    def lookup(self, fingerprint: bytes) -> AppSession | None:
        """Authoritative current session/account/consent; never a stale positive cache."""
        ...


class OfflineSessionGate:
    def __init__(self, verifier: OfflineAccessVerifier, registry: SessionRegistry):
        self.verifier, self.registry = verifier, registry

    def authorize(self, token: str, *, required_scope: str, now: int) -> AuthContext:
        verified = self.verifier.verify(token, now=now)
        try:
            session = self.registry.lookup(verified.fingerprint)
        except SessionStoreUnavailable:
            raise HTTPException(503, 'Authentication unavailable') from None
        if session is None:
            raise denied()
        validate_binding_candidate(verified, session, expected_version=session.version, now=now)
        if required_scope not in verified.scopes or not session.consent_active:
            raise HTTPException(403, 'Access denied')
        return AuthContext(sub=session.account_id)
