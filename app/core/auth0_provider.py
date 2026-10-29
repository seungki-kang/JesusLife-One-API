"""Fixed-origin Auth0 code/ID/access validation for the local PC PoC."""
import base64
import hashlib
import hmac
import json
import re
from threading import RLock
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException
import httpx

from .auth_diagnostics import stage
from .auth0_poc import OfflineAccessVerifier, _decode, _object, _invalid_constant, denied


class Auth0Provider:
    def __init__(self, config, *, transport=None):
        host = urlsplit(config.policy.issuer).hostname or ''
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.auth0\.com', host):
            raise ValueError('Auth0 public tenant domain required')
        if urlsplit(config.policy.issuer).port not in (None, 443):
            raise ValueError('Invalid Auth0 endpoint')
        self.config, self.transport = config, transport
        self._keys, self._loaded, self._lock = {}, -1000, RLock()

    def _request(self, method, suffix, **kwargs):
        try:
            with httpx.Client(transport=self.transport, timeout=10, follow_redirects=False, trust_env=False) as client:
                response = client.request(method, self.config.policy.issuer + suffix, **kwargs)
            if len(response.content) > 131072:
                raise HTTPException(503, 'Authentication unavailable')
            if response.status_code != 200:
                if suffix == 'oauth/token' and response.status_code in (400, 401, 403):
                    raise denied()
                raise HTTPException(503, 'Authentication unavailable')
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, 'Authentication unavailable') from None

    def keys_for(self, raw, now):
        try:
            if len(raw) > 16384:
                raise denied()
            header = json.loads(_decode(raw.split('.')[0]), object_pairs_hook=_object,
                                parse_constant=_invalid_constant)
            if not isinstance(header,dict) or header.get('alg') != 'RS256':
                raise denied()
            kid = header['kid']
            if not isinstance(kid, str) or len(kid) > 256:
                raise denied()
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
            raise denied() from None
        with self._lock:
            if now - self._loaded >= 300 or (kid not in self._keys and now - self._loaded >= 30):
                with stage('jwks_fetch'):
                    payload = self._request('GET', '.well-known/jwks.json')
                try:
                    keys = {}
                    for jwk in payload['keys']:
                        if jwk.get('kty') != 'RSA' or jwk.get('use', 'sig') != 'sig' or jwk.get('alg', 'RS256') != 'RS256':
                            continue
                        key = rsa.RSAPublicNumbers(int.from_bytes(_decode(jwk['e']), 'big'),
                                                  int.from_bytes(_decode(jwk['n']), 'big')).public_key()
                        if key.key_size < 2048 or jwk['kid'] in keys:
                            raise ValueError('Invalid JWKS')
                        keys[jwk['kid']] = key
                    if not keys:
                        raise ValueError('Empty JWKS')
                except (ValueError, KeyError, TypeError):
                    raise HTTPException(503, 'Authentication unavailable') from None
                self._keys, self._loaded = keys, now
            if kid not in self._keys:
                raise denied()
            return dict(self._keys)

    def verify_access(self, raw, *, now):
        return OfflineAccessVerifier(self.config.policy, self.keys_for(raw, now), self.config.hmac_key).verify(raw, now=now)

    def exchange(self, *, code, verifier, nonce_hash, now):
        with stage('token_exchange_pkce'):
            payload = self._request('POST', 'oauth/token', data={
                'grant_type': 'authorization_code', 'client_id': next(iter(self.config.policy.client_ids)),
                'client_secret': self.config.client_secret, 'code': code, 'code_verifier': verifier,
                'redirect_uri': 'http://127.0.0.1:8000/api/v1/auth/callback/web'})
        try:
            with stage('token_response'):
                if not isinstance(payload, dict) or not isinstance(payload.get('token_type'), str):
                    raise denied()
                if payload['token_type'].lower() != 'bearer' or 'refresh_token' in payload:
                    raise denied()
                raw, id_token = payload['access_token'], payload['id_token']
                if not isinstance(raw, str) or not isinstance(id_token, str):
                    raise denied()
            with stage('access_jwt'):
                access = self.verify_access(raw, now=now)
            with stage('id_jwt_nonce'):
                self._verify_id(id_token, access, raw, nonce_hash, now)
            return raw, access
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise denied() from None

    def _verify_id(self, raw, access, access_raw, nonce_hash, now):
        try:
            if not isinstance(raw, str) or len(raw) > 16384:
                raise denied()
            head, body, signature = raw.split('.')
            header = json.loads(_decode(head), object_pairs_hook=_object, parse_constant=_invalid_constant)
            claims = json.loads(_decode(body), object_pairs_hook=_object, parse_constant=_invalid_constant)
            if not isinstance(header, dict) or not isinstance(claims, dict):
                raise denied()
            if (header.get('alg') != 'RS256' or header.get('typ') != 'JWT'
                    or any(k in header for k in ('crit', 'jku', 'x5u', 'jwk', 'b64'))):
                raise denied()
            with stage('id_signature'):
                self.keys_for(raw, now)[header['kid']].verify(_decode(signature), (head + '.' + body).encode('ascii'),
                                                          padding.PKCS1v15(), hashes.SHA256())
            audience = claims.get('aud')
            audience = [audience] if isinstance(audience, str) else audience
            client = access.client_id
            if (not isinstance(audience, list) or client not in audience or not audience
                    or any(not isinstance(a,str) for a in audience)
                    or (len(audience) > 1 and claims.get('azp') != client)
                    or ('azp' in claims and claims['azp'] != client)
                    or claims.get('iss') != access.issuer or claims.get('sub') != access.subject
                    or type(claims.get('exp')) is not int or type(claims.get('iat')) is not int
                    or claims['exp'] <= now or claims['iat'] < 0 or claims['iat'] > now + 30 or claims['exp'] <= claims['iat']):
                raise denied()
            with stage('nonce'):
                if (not isinstance(claims.get('nonce'), str)
                        or not hmac.compare_digest(hashlib.sha256(claims['nonce'].encode()).digest(), nonce_hash)):
                    raise denied()
            if 'at_hash' in claims:
                expected = base64.urlsafe_b64encode(hashlib.sha256(access_raw.encode('ascii')).digest()[:16]).rstrip(b'=').decode()
                if not isinstance(claims['at_hash'], str) or not hmac.compare_digest(expected, claims['at_hash']):
                    raise denied()
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError, InvalidSignature):
            raise denied() from None
