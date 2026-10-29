"""Offline cryptographic/gate tests; reference registry is test-only, not a DB.

Session CAS scenarios specify durable Core repository acceptance conditions.
They do not prove SQL atomicity, Auth0 code exchange, JWKS fetching or device SSO.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import secrets
from threading import Barrier, RLock
import unittest
from uuid import uuid4

from fastapi import HTTPException

from app.core.auth0_poc import (AppSession, OfflineAccessVerifier, OfflineSessionGate,
                               PocTokenPolicy, SessionStoreUnavailable, matches_pkce,
                               pkce_challenge, validate_binding_candidate)
from app.modules.neorang_narang.schemas import CompletionRecordMetadata
from app.modules.neorang_narang.service import CompletionService
from app.modules.neorang_narang.store import InMemoryCompletionStore
from tests.auth_contract_fixtures import (ACCOUNT_A, ACCOUNT_B, AUDIENCE, CLIENT,
                                          ISSUER, NOW, SyntheticJWTs)


class ReferenceRegistry:
    """Test model only: no app imports it and no HTTP route uses it.

    A receipt models a previously verified code exchange or a serialized refresh
    result. No receipt can be obtained by presenting an arbitrary bearer token.
    """
    def __init__(self):
        self.lock, self.sessions, self.bindings, self.receipts = RLock(), {}, {}, {}

    def lookup(self, fingerprint):
        with self.lock:
            sid = self.bindings.get(fingerprint)
            return self.sessions.get(sid)

    def receipt(self, sid):
        with self.lock:
            receipt = secrets.token_bytes(32)
            self.receipts[receipt] = (sid, self.sessions[sid].version)
            return receipt

    def commit(self, receipt, token):
        with self.lock:
            binding = self.receipts.get(receipt)
            if binding is None or token.fingerprint in self.bindings:
                raise HTTPException(401, 'Authentication required')
            sid, version = binding
            session = self.sessions[sid]
            validate_binding_candidate(token, session, expected_version=version, now=NOW)
            self.bindings[token.fingerprint] = sid
            self.sessions[sid] = replace(session, version=version + 1)
            del self.receipts[receipt]

    def logout(self, sid):
        with self.lock:
            session = self.sessions[sid]
            if not session.revoked:
                self.sessions[sid] = replace(session, revoked=True, version=session.version + 1)
            # Bindings/tombstones retained, not unregistered or reassigned.


class Auth0PocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jwt = SyntheticJWTs()

    def setUp(self):
        self.verifier = OfflineAccessVerifier(
            PocTokenPolicy(ISSUER, AUDIENCE, frozenset({CLIENT})),
            {'synthetic-key': self.jwt.public_key}, secrets.token_bytes(32))
        self.registry = ReferenceRegistry()
        self.gate = OfflineSessionGate(self.verifier, self.registry)

    def token(self, subject='synthetic-provider-a', **changes):
        claims = {'sub': subject, 'client_id': CLIENT, 'jti': str(uuid4()), **changes}
        return self.jwt.signed(claims=claims, omit=('azp', 'token_use'))

    def session(self, account=ACCOUNT_A, subject='synthetic-provider-a'):
        session = AppSession(uuid4(), account, ISSUER, subject, CLIENT, NOW + 3600)
        self.registry.sessions[session.session_id] = session
        return session.session_id

    def bind(self, sid, raw):
        self.registry.commit(self.registry.receipt(sid), self.verifier.verify(raw, now=NOW))

    def allow(self, raw):
        return self.gate.authorize(raw, required_scope='neorang-narang:read', now=NOW)

    def reject(self, status, operation):
        with self.assertRaises(HTTPException) as caught:
            operation()
        self.assertEqual(caught.exception.status_code, status)

    def test_pkce_rfc7636_vector_and_wrong_verifier(self):
        verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
        challenge = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'
        self.assertEqual(pkce_challenge(verifier), challenge)
        self.assertTrue(matches_pkce(verifier, challenge))
        for invalid in ('short', ' ' * 43, 'a' * 129, '\uac00' * 43):
            self.assertFalse(matches_pkce(invalid, challenge))
        self.assertFalse(matches_pkce('a' * 43, challenge))

    def test_signed_unregistered_token_rejected_and_a_b_map_to_core_ids(self):
        a, b = self.token(), self.token('synthetic-provider-b')
        self.reject(401, lambda: self.allow(a))
        self.bind(self.session(), a)
        self.bind(self.session(ACCOUNT_B, 'synthetic-provider-b'), b)
        self.assertEqual(self.allow(a).sub, ACCOUNT_A)
        self.assertEqual(self.allow(b).sub, ACCOUNT_B)

    def test_rfc9068_bad_signature_and_claim_cases(self):
        for changes in ({'iss': 'https://wrong.example.invalid/'}, {'aud': 'wrong'},
                        {'client_id': 'wrong'}, {'sub': ''}, {'jti': ''},
                        {'exp': None}, {'exp': True}, {'iat': NOW + 3600},
                        {'nbf': NOW + 3600}, {'iat': NOW - 1200, 'exp': NOW - 600},
                        {'exp': NOW + 601}, {'scope': ['bad']}, {'sub': CLIENT}):
            with self.subTest(fields=sorted(changes)):
                self.reject(401, lambda: self.verifier.verify(self.token(**changes), now=NOW))
        for raw in ('not-a-jwt', self.jwt.signed(other_key=True),
                    self.jwt.signed(header={'alg': 'none'}),
                    self.jwt.signed(header={'alg': 'HS256'}),
                    self.jwt.signed(header={'typ': 'JWT'}),
                    self.jwt.signed(header={'kid': 'unknown'})):
            self.reject(401, lambda: self.verifier.verify(raw, now=NOW))

    def test_audience_array_and_non_uuid_provider_subject(self):
        raw = self.token('auth0|synthetic-account', aud=['urn:other', AUDIENCE])
        self.bind(self.session(subject='auth0|synthetic-account'), raw)
        self.assertEqual(self.allow(raw).sub, ACCOUNT_A)

    def test_verified_context_preserves_record_owner_isolation(self):
        a, b = self.token(), self.token('synthetic-provider-b')
        self.bind(self.session(), a)
        self.bind(self.session(ACCOUNT_B, 'synthetic-provider-b'), b)
        store = InMemoryCompletionStore()
        owner = CompletionService(store, self.allow(a))
        other = CompletionService(store, self.allow(b))
        metadata = CompletionRecordMetadata(id=uuid4(), course_number=1, participation_mode='solo',
                                            completed_at='2026-10-01T00:00:00Z', revision=1)
        owner.create(metadata)
        self.assertEqual(other.list(20), [])
        self.reject(404, lambda: other.get(metadata.id))
        self.reject(404, lambda: other.update(metadata.id, 1, metadata.model_copy(update={'revision': 2})))
        self.reject(404, lambda: other.delete(metadata.id, 1, 2))
        self.assertEqual(owner.get(metadata.id), metadata)

    def test_embedded_key_locations_are_not_trusted_and_errors_are_fixed(self):
        for header in ({'jku': 'https://untrusted.example.invalid/keys'},
                       {'x5u': 'https://untrusted.example.invalid/cert'},
                       {'jwk': {}}, {'crit': ['synthetic']}):
            raw = self.jwt.signed(header=header)
            with self.assertRaises(HTTPException) as caught:
                self.verifier.verify(raw, now=NOW)
            self.assertEqual(caught.exception.detail, 'Authentication required')
            self.assertNotIn(raw, str(caught.exception))

    def test_logout_blocks_original_and_refreshed_tokens_only_for_current_session(self):
        a1, a2, b1 = self.session(), self.session(), self.session(ACCOUNT_B, 'synthetic-provider-b')
        old, refreshed, other, b = self.token(), self.token(), self.token(), self.token('synthetic-provider-b')
        for sid, raw in ((a1, old), (a1, refreshed), (a2, other), (b1, b)):
            self.bind(sid, raw)
        self.registry.logout(a1)
        self.registry.logout(a1)
        for raw in (old, refreshed):
            self.reject(401, lambda: self.allow(raw))
        self.assertEqual(self.allow(other).sub, ACCOUNT_A)
        self.assertEqual(self.allow(b).sub, ACCOUNT_B)

    def test_logged_out_token_cannot_rebind_even_after_same_account_relogin(self):
        first, raw = self.session(), self.token()
        self.bind(first, raw)
        self.registry.logout(first)
        second, fresh = self.session(), self.token()
        self.reject(401, lambda: self.bind(second, raw))
        self.reject(401, lambda: self.allow(raw))
        self.bind(second, fresh)
        self.assertEqual(self.allow(fresh).sub, ACCOUNT_A)

    def test_wrong_identity_or_client_cannot_bind_to_a_session(self):
        sid = self.session(ACCOUNT_B, 'synthetic-provider-b')
        self.reject(401, lambda: self.bind(sid, self.token()))
        session = self.registry.sessions[sid]
        self.registry.sessions[sid] = replace(session, client_id='different-app')
        self.reject(401, lambda: self.bind(sid, self.token('synthetic-provider-b')))

    def test_consumed_receipt_cannot_replay_or_accept_arbitrary_bearer(self):
        sid, raw = self.session(), self.token()
        verified = self.verifier.verify(raw, now=NOW)
        receipt = self.registry.receipt(sid)
        self.registry.commit(receipt, verified)
        self.reject(401, lambda: self.registry.commit(receipt, self.verifier.verify(self.token(), now=NOW)))
        self.reject(401, lambda: self.registry.commit(b'untrusted-session-id', verified))

    def test_logout_during_refresh_rejects_late_response(self):
        sid = self.session()
        pending = self.registry.receipt(sid)
        self.registry.logout(sid)
        raw = self.token()
        self.reject(401, lambda: self.registry.commit(pending, self.verifier.verify(raw, now=NOW)))
        self.reject(401, lambda: self.allow(raw))

    def test_parallel_requests_after_logout_do_not_use_a_positive_cache(self):
        sid, raw = self.session(), self.token()
        self.bind(sid, raw)
        self.assertEqual(self.allow(raw).sub, ACCOUNT_A)
        self.registry.logout(sid)
        def request(_):
            try:
                self.allow(raw)
                return 200
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(4) as pool:
            self.assertEqual(list(pool.map(request, range(16))), [401] * 16)

    def test_concurrent_refresh_cas_allows_only_one_commit(self):
        sid, barrier = self.session(), Barrier(2)
        receipts = [self.registry.receipt(sid), self.registry.receipt(sid)]
        tokens = [self.token(), self.token()]
        def finish(index):
            verified = self.verifier.verify(tokens[index], now=NOW)
            barrier.wait(timeout=5)
            try:
                self.registry.commit(receipts[index], verified)
                return 200
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(finish, range(2))), [200, 401])

    def test_scope_consent_disabled_account_and_store_outage(self):
        sid, raw = self.session(), self.token()
        self.bind(sid, raw)
        base = self.registry.sessions[sid]
        for changes, status in (({'consent_active': False}, 403), ({'account_active': False}, 401),
                                ({'expires_at': NOW}, 401)):
            self.registry.sessions[sid] = replace(base, **changes)
            self.reject(status, lambda: self.allow(raw))
        self.registry.sessions[sid] = base
        self.reject(403, lambda: self.gate.authorize(raw, required_scope='ungranted', now=NOW))
        class DownRegistry:
            def lookup(self, fingerprint):
                raise SessionStoreUnavailable()
        self.reject(503, lambda: OfflineSessionGate(self.verifier, DownRegistry()).authorize(
            raw, required_scope='neorang-narang:read', now=NOW))


if __name__ == '__main__':
    unittest.main()
