"""Opt-in synthetic Core/MySQL and mocked Auth0 wire tests; no real IdP calls."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from threading import Barrier
from urllib.parse import parse_qs, urlsplit
import unittest
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pymysql

from app.auth0_pc import PcRuntime, create_app, ORIGIN
from app.core.auth0_provider import Auth0Provider
from app.core.auth0_poc import pkce_challenge
from app.core.core_store import CoreStore, digest
from app.core.database import ROOT, connect
from scripts.auth0_pc_settings import validate
from scripts.core_mysql import (TABLES, MANIFEST, local_config, core_connect, migrate,
                                core_snapshot, bootstrap)
from scripts.local_mysql import protect
from tests.auth_contract_fixtures import SyntheticJWTs, NOW, b64url


class SyntheticAuth0:
    def __init__(self, config):
        self.jwt, self.codes, self.config = SyntheticJWTs(), {}, config
        self.transport = httpx.MockTransport(self.handle)
        self.provider = Auth0Provider(config, transport=self.transport)
        self.issued = {}

    def issue(self, location, subject, *, wrong_nonce=False):
        query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
        code = secrets.token_urlsafe(32)
        self.codes[code] = query | {'sub': subject, 'wrong_nonce': wrong_nonce}
        return code, query['state']

    def handle(self, request):
        if request.url.path == '/.well-known/jwks.json':
            key = self.jwt.public_key.public_numbers()
            return httpx.Response(200, json={'keys': [{'kid': 'synthetic-key', 'kty': 'RSA', 'alg': 'RS256',
                'use': 'sig', 'n': b64url(key.n.to_bytes((key.n.bit_length()+7)//8, 'big')),
                'e': b64url(key.e.to_bytes((key.e.bit_length()+7)//8, 'big'))}]})
        if request.url.path != '/oauth/token':
            return httpx.Response(404)
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        query = self.codes.pop(form.get('code'), None)
        if not query or pkce_challenge(form['code_verifier']) != query['code_challenge']:
            return httpx.Response(400, json={'error': 'invalid_grant'})
        common = {'iss': self.config.policy.issuer, 'sub': query['sub'], 'iat': NOW, 'exp': NOW+600}
        raw = self.jwt.signed(claims=common | {'aud': self.config.policy.audience,
                              'client_id': form['client_id'], 'jti': str(uuid4())}, omit=('azp', 'token_use'))
        id_token = self.jwt.signed(header={'typ': 'JWT'}, claims=common | {'aud': form['client_id'],
                                   'nonce': 'wrong' if query['wrong_nonce'] else query['nonce'],
                                   'at_hash': b64url(hashlib.sha256(raw.encode()).digest()[:16])}, omit=('azp',))
        self.issued[query['sub']] = raw
        return httpx.Response(200, json={'access_token': raw, 'id_token': id_token, 'token_type': 'Bearer'})


@unittest.skipUnless(os.environ.get('RUN_CORE_TESTS') == '1', 'Opt-in synthetic local Core tests')
class CorePersistenceTest(unittest.TestCase):
    def setUp(self):
        cfg = local_config() | {'AUTH0_ISSUER': 'https://synthetic.auth0.com/',
                                'AUTH0_CLIENT_ID': 'synthetic-pc-client', 'AUTH0_CLIENT_SECRET': 'synthetic-only'}
        self.config = validate(cfg)
        self.store = CoreStore(self.config.encryption_key, self.config.hmac_key)
        self.idp = SyntheticAuth0(self.config)
        self.runtime = PcRuntime(self.config, store=self.store, provider=self.idp.provider, clock=lambda: NOW)
        self.client = self.new_client()
        self.subject = 'auth0|synthetic-' + str(uuid4())

    def new_client(self, runtime=None):
        client = TestClient(create_app(runtime or self.runtime), base_url=ORIGIN)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def login(self, client=None, subject=None, **kwargs):
        client, subject = client or self.client, subject or self.subject
        start = client.get('/auth/poc/login', follow_redirects=False)
        self.assertEqual(start.status_code, 303)
        code, state = self.idp.issue(start.headers['location'], subject, **kwargs)
        callback = client.get('/api/v1/auth/callback/web', params={'state': state, 'code': code}, follow_redirects=False)
        return callback, code, state

    def csrf(self, client=None):
        client = client or self.client
        return {'Origin': ORIGIN, 'X-CSRF-Token': client.cookies.get('jl_pc_csrf')}

    def consent(self, client=None):
        client = client or self.client
        self.assertEqual(client.post('/api/v1/me/consents/neorang-narang-sync', headers=self.csrf(client)).status_code, 200)

    def test_real_db_callback_uuid_stable_and_no_token_response(self):
        response, _, _ = self.login()
        self.assertEqual(response.status_code, 303)
        first = self.client.get('/api/v1/me').json()['sub']
        other = self.new_client()
        self.assertEqual(self.login(other)[0].status_code, 303)
        self.assertEqual(other.get('/api/v1/me').json()['sub'], first)
        self.assertNotIn(self.idp.issued[self.subject], response.text)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_ab_acceptance_real_mysql_synthetic_provider(self):
        self.assertEqual(self.login()[0].status_code, 303)
        def action(name, status=200):
            response = self.client.post('/auth/poc/acceptance/'+name, headers=self.csrf())
            self.assertEqual(response.status_code, status)
            return response.json()
        action('start-a')
        action('compare', 409)  # Same session is not reauthentication evidence.
        action('check', 409)
        old_csrf = self.csrf()
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers=old_csrf).status_code, 204)
        self.assertEqual(self.client.post('/auth/poc/acceptance/compare', headers=old_csrf).status_code, 401)
        self.assertEqual(self.login()[0].status_code, 303)
        self.assertEqual(action('compare'), {'same_account': True, 'distinct_b': False})
        action('check', 409)  # Prior product consent does not consent to this run.
        action('consent')
        self.assertNotIn('FAIL', action('check')['checks'].values())
        # Automatic SSO to A must remain A, never B.
        self.assertEqual(self.login()[0].status_code, 303)
        self.assertFalse(action('compare')['distinct_b'])
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers=self.csrf()).status_code, 204)
        subject_b = 'auth0|synthetic-b-'+str(uuid4())
        self.assertEqual(self.login(subject=subject_b)[0].status_code, 303)
        self.assertEqual(action('compare'), {'same_account': False, 'distinct_b': True})
        action('check', 409)
        action('consent')
        result = action('check')
        self.assertNotIn('FAIL', result['checks'].values())
        self.assertEqual(result['checks']['foreign_get'], 'PASS')
        # Revisit A to prove B's denied writes left A intact and reverse isolation.
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers=self.csrf()).status_code, 204)
        self.assertEqual(self.login()[0].status_code, 303)
        action('compare')
        result = action('check')
        self.assertNotIn('FAIL', result['checks'].values())
        self.assertEqual(result['checks']['foreign_delete_retry_1'], 'PASS')
        self.assertEqual(action('results')['acceptance'], 'NOT_RUN')
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers=self.csrf()).status_code, 204)
        self.assertEqual(self.login(subject=subject_b)[0].status_code, 303)
        action('compare')
        self.assertNotIn('FAIL', action('check')['checks'].values())
        self.assertEqual(action('results')['acceptance'], 'PASS')
        self.assertEqual(self.client.post('/auth/poc/acceptance/check', headers=self.csrf() |
            {'Origin': 'https://other.example.invalid'}).status_code, 403)

    def test_wrong_nonce_state_cookie_and_replayed_callback_rejected(self):
        self.assertEqual(self.login(wrong_nonce=True)[0].status_code, 401)
        response, code, state = self.login()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get('/api/v1/auth/callback/web', params={'code': code,'state': state}).status_code, 401)
        other = self.new_client()
        start = self.client.get('/auth/poc/login', follow_redirects=False)
        code, state = self.idp.issue(start.headers['location'], self.subject)
        self.assertEqual(other.get('/api/v1/auth/callback/web', params={'code': code,'state': state}).status_code, 401)

    def test_issuer_and_case_sensitive_subjects_do_not_auto_merge(self):
        subject = 'auth0|Case-' + str(uuid4())
        self.assertEqual(self.login(subject=subject)[0].status_code, 303)
        first = self.client.get('/api/v1/me').json()['sub']
        lower = self.new_client()
        self.assertEqual(self.login(lower, subject.lower())[0].status_code, 303)
        self.assertNotEqual(first, lower.get('/api/v1/me').json()['sub'])
        config = validate(local_config() | {'AUTH0_ISSUER':'https://other-synthetic.auth0.com/',
                    'AUTH0_CLIENT_ID':'synthetic-pc-client','AUTH0_CLIENT_SECRET':'synthetic-only'})
        idp = SyntheticAuth0(config)
        other = self.new_client(PcRuntime(config,store=self.store,provider=idp.provider,clock=lambda:NOW))
        start = other.get('/auth/poc/login',follow_redirects=False)
        code,state = idp.issue(start.headers['location'],subject)
        self.assertEqual(other.get('/api/v1/auth/callback/web',params={'code':code,'state':state},follow_redirects=False).status_code,303)
        self.assertNotEqual(first,other.get('/api/v1/me').json()['sub'])

    def test_duplicate_query_and_external_origin_mutation_rejected(self):
        start = self.client.get('/auth/poc/login',follow_redirects=False)
        code,state = self.idp.issue(start.headers['location'],self.subject)
        response = self.client.get('/api/v1/auth/callback/web',params=[('code',code),('state',state),('state',state)])
        self.assertEqual(response.status_code,401)
        self.assertEqual(self.client.get('/api/v1/auth/callback/web',params={'code':code,'state':state},follow_redirects=False).status_code,303)
        self.assertEqual(self.client.post('/api/v1/auth/logout',headers=self.csrf() | {'Origin':'https://other.example.invalid'}).status_code,403)

    def test_revoked_token_cannot_bind_new_login_or_rollback_into_new_account(self):
        self.assertEqual(self.login()[0].status_code,303)
        raw = self.idp.issued[self.subject]
        old = self.idp.provider.verify_access(raw,now=NOW)
        self.assertEqual(self.client.post('/api/v1/auth/logout',headers=self.csrf()).status_code,204)
        state,browser,nonce,verifier = [secrets.token_urlsafe(32) for _ in range(4)]
        self.store.begin_login(state=state,browser=browser,nonce=nonce,verifier=verifier,
                              client_id=old.client_id,redirect_uri='http://127.0.0.1:8000/api/v1/auth/callback/web',now=NOW)
        self.store.claim_login(state=state,browser=browser,now=NOW)
        with self.assertRaises(HTTPException) as caught:
            self.store.complete_login(state=state,browser=browser,token=old,raw_token=raw,now=NOW)
        self.assertEqual(caught.exception.status_code,401)
        self.assertTrue(self.store.lookup(old.fingerprint).revoked)

    def test_expired_transaction_and_bad_nonce_do_not_create_identity(self):
        state,browser,nonce,verifier = [secrets.token_urlsafe(32) for _ in range(4)]
        self.store.begin_login(state=state,browser=browser,nonce=nonce,verifier=verifier,
                              client_id='synthetic-pc-client',redirect_uri='http://127.0.0.1:8000/api/v1/auth/callback/web',now=NOW-301)
        with self.assertRaises(HTTPException) as caught:
            self.store.claim_login(state=state,browser=browser,now=NOW)
        self.assertEqual(caught.exception.status_code,401)
        self.assertEqual(self.login(wrong_nonce=True)[0].status_code,401)
        with core_connect() as conn,conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM external_identities WHERE issuer=%s AND provider_subject=%s',
                           (self.config.policy.issuer.encode(),self.subject.encode()))
            self.assertEqual(cursor.fetchone()['n'],0)

    def test_a_b_product_isolation_csrf_and_revoked_bearer(self):
        self.assertEqual(self.login()[0].status_code, 303)
        raw_a = self.idp.issued[self.subject]
        self.assertEqual(self.client.get('/api/v1/neorang-narang/completions').status_code, 403)
        self.assertEqual(self.client.post('/api/v1/me/consents/neorang-narang-sync').status_code, 403)
        self.consent()
        path = '/api/v1/neorang-narang/completions'
        value = {'id': str(uuid4()), 'course_number': 1, 'participation_mode': 'solo',
                 'completed_at': '2026-10-01T00:00:00Z', 'revision': 1}
        self.assertEqual(self.client.post(path, json=value, headers=self.csrf()).status_code, 201)
        b = self.new_client()
        self.assertEqual(self.login(b, 'auth0|synthetic-' + str(uuid4()))[0].status_code, 303)
        self.consent(b)
        self.assertNotEqual(self.client.get('/api/v1/me').json(), b.get('/api/v1/me').json())
        self.assertEqual(b.get(path + '/' + value['id']).status_code, 404)
        self.assertEqual(b.put(path + '/' + value['id'], json={'base_revision': 1, 'metadata': value | {'revision':2}}, headers=self.csrf(b)).status_code, 404)
        self.assertEqual(b.request('DELETE', path + '/' + value['id'], json={'base_revision':1, 'revision':2}, headers=self.csrf(b)).status_code, 404)
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers=self.csrf()).status_code, 204)
        self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer '+raw_a}).status_code, 401)
        self.assertEqual(b.get(path).status_code, 200)
        restarted = self.new_client(PcRuntime(self.config, store=CoreStore(self.config.encryption_key, self.config.hmac_key),
                                              provider=self.idp.provider, clock=lambda: NOW))
        self.assertEqual(restarted.get(path, headers={'Authorization':'Bearer '+raw_a}).status_code, 401)

    def test_concurrent_initial_logins_one_mapping_no_orphan_accounts(self):
        clients = [self.new_client(), self.new_client()]
        callbacks = []
        with core_connect() as conn, conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM accounts')
            before = cursor.fetchone()['n']
        for client in clients:
            start = client.get('/auth/poc/login', follow_redirects=False)
            callbacks.append(self.idp.issue(start.headers['location'], self.subject))
        barrier = Barrier(2)
        def finish(index):
            code, state = callbacks[index]
            barrier.wait(timeout=5)
            response = clients[index].get('/api/v1/auth/callback/web', params={'code':code,'state':state}, follow_redirects=False)
            return response.status_code
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(list(pool.map(finish, range(2))), [303, 303])
        self.assertEqual(clients[0].get('/api/v1/me').json(), clients[1].get('/api/v1/me').json())
        with core_connect() as conn, conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM accounts')
            self.assertEqual(cursor.fetchone()['n'], before+1)
            cursor.execute('SELECT COUNT(*) AS n FROM external_identities WHERE issuer=%s AND provider_subject=%s',
                           (self.config.policy.issuer.encode(), self.subject.encode()))
            self.assertEqual(cursor.fetchone()['n'], 1)

    def test_transaction_rollback_and_core_product_privilege_isolation(self):
        account = str(uuid4())
        with self.assertRaises(RuntimeError):
            with self.store.transaction() as conn, conn.cursor() as cursor:
                cursor.execute('INSERT INTO accounts (account_id,created_at) VALUES (%s,UTC_TIMESTAMP(6))', (account,))
                raise RuntimeError('Synthetic rollback')
        with core_connect() as conn, conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM accounts WHERE account_id=%s', (account,))
            self.assertEqual(cursor.fetchone()['n'], 0)
            for sql in ('DELETE FROM accounts WHERE 1=0', 'UPDATE core_schema_version SET version=version WHERE 1=0',
                        'CREATE TABLE forbidden_synthetic (id INT)', 'USE neorang_narang', 'USE life_diary'):
                with self.assertRaises(pymysql.MySQLError):
                    cursor.execute(sql)
        with core_connect(migrator=True) as conn, conn.cursor() as cursor:
            for sql in ('UPDATE accounts SET status=status WHERE 1=0', 'SELECT * FROM accounts LIMIT 0',
                        'INSERT INTO accounts (account_id,created_at) SELECT UUID(),UTC_TIMESTAMP(6) WHERE FALSE',
                        'USE neorang_narang', 'USE life_diary'):
                with self.assertRaises(pymysql.MySQLError):
                    cursor.execute(sql)
        from app.core.database import settings
        cfg = settings()
        for user, password in (('nn_app',cfg['NN_DB_PASSWORD']),('life_diary_app',cfg['LIFE_DIARY_DB_PASSWORD'])):
            with self.assertRaises(pymysql.MySQLError):
                connect(database='platform_core', user=user, password=password)

    def test_migration_replay_collision_and_partial_failure_safety(self):
        expected = json.loads(MANIFEST.read_text(encoding='utf-8'))
        with core_connect() as data:
            before = core_snapshot(data)
        with core_connect(migrator=True) as conn:
            migrate(conn, expected)
        with core_connect() as data:
            self.assertEqual(core_snapshot(data), before)
        with redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            bootstrap()
        target = 'core_check_' + secrets.token_hex(6)
        with connect(admin=True) as root, root.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{target}` CHARACTER SET utf8mb4')
            cursor.execute(f'USE `{target}`')
            cursor.execute(expected['accounts'])
            migrate(root, expected)
            first = core_snapshot(root)
            migrate(root, expected)
            self.assertEqual(core_snapshot(root), first)
            cursor.execute('INSERT INTO core_schema_version VALUES (2,UTC_TIMESTAMP(6))')
            root.commit()
            before = core_snapshot(root)
            with self.assertRaises(RuntimeError):
                migrate(root, expected)
            self.assertEqual(core_snapshot(root), before)

    def test_mismatched_existing_schema_is_not_overwritten(self):
        expected = json.loads(MANIFEST.read_text(encoding='utf-8'))
        target = 'core_check_' + secrets.token_hex(6)
        with connect(admin=True) as root,root.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{target}` CHARACTER SET utf8mb4')
            cursor.execute(f'USE `{target}`')
            cursor.execute(expected['accounts'])
            cursor.execute('ALTER TABLE accounts ADD COLUMN synthetic_extra INT NULL')
            from scripts.core_mysql import shape
            before = shape(root,'accounts')
            with self.assertRaises(RuntimeError):
                migrate(root,expected)
            self.assertEqual(shape(root,'accounts'),before)

    def test_revoked_and_active_state_survive_new_python_process(self):
        self.assertEqual(self.login()[0].status_code, 303)
        for _ in range(2):
            page = self.client.get('/auth/poc/')
            self.assertIn('id="login-state">로그인됨', page.text)
            self.assertIn('id="session-state">유효', page.text)
            for private in (self.idp.issued[self.subject], self.subject,
                            self.client.cookies.get('jl_pc_session'),
                            self.client.cookies.get('jl_pc_csrf')):
                self.assertNotIn(private, page.text)
        revoked_cookie = self.client.cookies.get('jl_pc_session')
        self.consent()
        revoked = self.idp.issued[self.subject]
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers=self.csrf()).status_code, 204)
        self.assertIn('id="login-state">로그인되지 않음', self.client.get('/auth/poc/signed-out').text)
        replay = self.new_client()
        replay.cookies.set('jl_pc_session', revoked_cookie)
        self.assertEqual(replay.get('/api/v1/me').status_code, 401)
        self.assertIn('id="session-state">유효하지 않음', replay.get('/auth/poc/').text)
        other = self.new_client()
        self.assertEqual(self.login(other)[0].status_code, 303)
        active = self.idp.issued[self.subject]
        self.consent(other)
        directory = Path(tempfile.mkdtemp(prefix='core-restart-proof-'))
        protect(directory)
        proof = directory / 'proof.json'
        public = self.idp.jwt.public_key.public_bytes(serialization.Encoding.PEM,
                                                     serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        with proof.open('x', encoding='utf-8') as output:
            protect(proof)
            json.dump({'public':public, 'now':NOW,
                       'revoked_cookie':base64.b64encode(self.store.encrypt(revoked_cookie,b'restart-proof')).decode(),
                       'active_cookie':base64.b64encode(self.store.encrypt(other.cookies.get('jl_pc_session'),b'restart-proof')).decode(),
                       'revoked':base64.b64encode(self.store.encrypt(revoked,b'restart-proof')).decode(),
                       'active':base64.b64encode(self.store.encrypt(active,b'restart-proof')).decode()},output)
        result = subprocess.run([sys.executable,'-B','-m','scripts.verify_core','restart-check',str(proof)],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode,0, 'Restart proof failed; details suppressed')
        self.assertIn('PASS',result.stdout)
