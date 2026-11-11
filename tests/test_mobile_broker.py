"""Offline HTTP/crypto/state-machine tests on isolated SQLite transactions.

Exercises production store methods via a dialect adapter. Does NOT certify
MySQL DDL, privileges or MySQL lock semantics; those remain opt-in NOT_RUN.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, closing
from datetime import datetime
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth0_pc import PcRuntime, create_app
from app.core.auth0_poc import pkce_challenge
from app.core.core_store import digest
from app.core.mobile_routes import CALLBACK, RETURN_URI, PREFIX
from app.core.mobile_store import MobileCoreStore
from app.modules.neorang_narang.mobile_store import MobileProjectionStore
from scripts.auth0_pc_settings import validate, AUDIENCE, CALLBACK as PC_CALLBACK
from tests.auth_contract_fixtures import NOW
from tests.test_core_persistence import SyntheticAuth0


class Cursor:
    def __init__(self, db):
        self.raw = db.cursor()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.raw.close()
    def execute(self, sql, args=()):
        if 'information_schema.tables' in sql:
            sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nn_mobile_backups'"
        sql = sql.replace(' FOR UPDATE', '').replace('%s', '?').replace('neorang_narang.', '')
        if 'ON DUPLICATE KEY UPDATE account_id=account_id' in sql:
            sql = sql.split(' ON DUPLICATE')[0].replace('INSERT INTO', 'INSERT OR IGNORE INTO')
        self.raw.execute(sql, tuple(v.isoformat(' ') if isinstance(v, datetime) else v for v in args))
    @property
    def rowcount(self):
        return self.raw.rowcount
    def _row(self, row):
        if row is None:
            return None
        result = dict(row)
        for key in ('expires_at', 'created_at', 'consumed_at', 'revoked_at'):
            if isinstance(result.get(key), str):
                result[key] = datetime.fromisoformat(result[key])
        return result
    def fetchone(self):
        return self._row(self.raw.fetchone())
    def fetchall(self):
        return [self._row(row) for row in self.raw.fetchall()]


class Connection:
    def __init__(self, db):
        self.db = db
    def cursor(self):
        return Cursor(self.db)


class SQLiteMobile(MobileCoreStore):
    def __init__(self, path, encryption, hmac):
        super().__init__(encryption, hmac)
        self.path = path
    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield Connection(db)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


DDL = '''
CREATE TABLE mobile_schema_version(version INTEGER); INSERT INTO mobile_schema_version VALUES(1);
CREATE TABLE mobile_logins(state_hash BLOB PRIMARY KEY, transaction_id TEXT UNIQUE, challenge BLOB,
 return_uri BLOB, browser_ciphertext BLOB, handoff_hash BLOB UNIQUE, credential_ciphertext BLOB,
 account_id TEXT, expires_at TEXT, consumed_at TEXT);
CREATE TABLE mobile_consents(account_id TEXT PRIMARY KEY, generation INTEGER DEFAULT 0,
 active INTEGER DEFAULT 0, deletion_through INTEGER DEFAULT 0, deletion_status TEXT DEFAULT 'none');
CREATE TABLE nn_mobile_synthetic(sync_id TEXT PRIMARY KEY, owner_sub TEXT, generation INTEGER,
 metadata TEXT, erased INTEGER DEFAULT 0, UNIQUE(owner_sub,generation));
CREATE TABLE login_transactions(state_hash BLOB PRIMARY KEY, browser_binding_hash BLOB,
 nonce_hash BLOB, verifier_ciphertext BLOB, key_version INTEGER, client_id BLOB, redirect_uri BLOB,
 created_at TEXT, expires_at TEXT, consumed_at TEXT, status TEXT DEFAULT 'pending');
CREATE TABLE accounts(account_id TEXT PRIMARY KEY, created_at TEXT, status TEXT DEFAULT 'active',security_version INTEGER DEFAULT 0);
CREATE TABLE external_identities(issuer BLOB,provider_subject BLOB,account_id TEXT,created_at TEXT, PRIMARY KEY(issuer,provider_subject));
CREATE TABLE app_sessions(session_id TEXT PRIMARY KEY,account_id TEXT,issuer BLOB,provider_subject BLOB,client_id BLOB,
 cookie_hash BLOB UNIQUE,csrf_hash BLOB,account_security_version INTEGER,created_at TEXT,expires_at TEXT,
 revoked_at TEXT,version INTEGER DEFAULT 0);
CREATE TABLE session_access_tokens(fingerprint BLOB PRIMARY KEY,fingerprint_key_version INTEGER,session_id TEXT,
 jwt_ciphertext BLOB,encryption_key_version INTEGER,issued_at TEXT,expires_at TEXT);
CREATE TABLE product_consents(account_id TEXT,product BLOB,purpose BLOB,policy_version BLOB,revoked_at TEXT);
'''


class MobileBrokerTest(unittest.TestCase):
    def setUp(self):
        import base64
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name)/'synthetic.db')
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(DDL)
        self.config = validate({'AUTH0_ISSUER': 'https://synthetic.auth0.com/',
            'AUTH0_CLIENT_ID': 'synthetic-pc-client', 'AUTH0_CLIENT_SECRET': 'synthetic-only',
            'AUTH0_AUDIENCE': AUDIENCE, 'AUTH0_CALLBACK_URL': PC_CALLBACK,
            'CORE_DB_HOST': '127.0.0.1', 'CORE_DB_PORT': '3307', 'CORE_DB_NAME': 'platform_core',
            'CORE_DB_USER': 'platform_core_app', 'CORE_DB_PASSWORD': 'synthetic-only',
            'CORE_TOKEN_HMAC_KEY': base64.b64encode(b'h'*32).decode(),
            'CORE_TOKEN_ENCRYPTION_KEY': base64.b64encode(b'e'*32).decode()})
        self.store = SQLiteMobile(self.path, self.config.encryption_key, self.config.hmac_key)
        self.idp = SyntheticAuth0(self.config)
        self.now = NOW
        self.runtime = PcRuntime(self.config, store=self.store, provider=self.idp.provider, clock=lambda: self.now)
        self.client = TestClient(create_app(self.runtime), base_url='http://127.0.0.1:8000')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def start(self, subject='auth0|synthetic-a', wrong_nonce=False):
        verifier = secrets.token_urlsafe(32)
        start = self.client.post(PREFIX+'/login-transactions', json={'challenge': pkce_challenge(verifier), 'return_uri': RETURN_URI})
        self.assertEqual(start.status_code, 200)
        data = start.json()
        auth = self.client.get(data['authorize_url'], follow_redirects=False)
        self.assertEqual(auth.status_code, 303)
        upstream = parse_qs(urlsplit(auth.headers['location']).query)
        self.assertEqual(upstream['redirect_uri'], [CALLBACK])
        self.assertNotIn('offline_access', upstream['scope'][0])
        code, state = self.idp.issue(auth.headers['location'], subject, wrong_nonce=wrong_nonce)
        response = self.client.get(CALLBACK, params={'code': code, 'state': state}, follow_redirects=False)
        if wrong_nonce:
            return response
        self.assertEqual(response.status_code, 303, response.text)
        query = parse_qs(urlsplit(response.headers['location']).query)
        self.assertEqual(set(query), {'code', 'transaction'})
        self.assertNotIn(self.idp.issued[subject], response.headers['location'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        return {'transaction': data['transaction'], 'code': query['code'][0],
                'verifier': verifier, 'return_uri': RETURN_URI}

    def login(self, subject='auth0|synthetic-a'):
        response = self.client.post(PREFIX+'/session-exchange', json=self.start(subject))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), {'Authorization': 'Bearer '+response.json()['access_token']}

    def grant(self, headers):
        response = self.client.post(PREFIX+'/consent', headers=headers)
        self.assertEqual(response.status_code, 200)
        return response.json()['generation']

    def metadata(self, generation=1):
        return {'sync_id': str(uuid4()), 'generation': generation, 'course_number': 1,
                'participation_mode': 'solo', 'completed_at': '2026-10-30T00:00:00Z', 'synthetic': True}

    def test_handoff_binding_consumption_and_expiry(self):
        command = self.start()
        for change in ({'verifier': 'x'*43}, {'transaction': str(uuid4())},
                       {'return_uri': 'jesuslife-poc://auth/other'}, {'code': 'x'*43}):
            self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command|change).status_code, 401)
        self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command).status_code, 200)
        self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command).status_code, 401)
        command = self.start()
        self.now += 61
        self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command).status_code, 401)

    def test_bad_nonce_missing_browser_and_callback_replay(self):
        self.assertEqual(self.start(wrong_nonce=True).status_code, 401)
        self.assertEqual(self.client.get(CALLBACK, params={'state': 'x'*43, 'code': 'bad'}).status_code, 401)
        self.assertEqual(self.client.get(CALLBACK, params={'state': ['a','b'], 'code':'bad'}).status_code, 401)
        self.assertEqual(self.client.post(PREFIX+'/login-transactions', json={
            'challenge': 'x'*43,'return_uri': RETURN_URI+'/evil'}).status_code, 401)

    def test_duplicate_account_isolation_and_allowlist(self):
        a, ha = self.login()
        b, hb = self.login('auth0|synthetic-b')
        self.assertNotEqual(a['sub'], b['sub'])
        ga, gb = self.grant(ha), self.grant(hb)
        command = self.metadata(ga)
        path = PREFIX+'/synthetic-completion'
        first = self.client.post(path, json=command, headers=ha)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()['replayed'])
        self.assertTrue(self.client.post(path, json=command, headers=ha).json()['replayed'])
        changed = command | {'course_number': 2 if command['course_number'] == 1 else 1}
        self.assertEqual(self.client.post(path, json=changed, headers=ha).status_code, 409)
        self.assertEqual(self.client.post(path, json=command|{'generation':gb}, headers=hb).status_code, 409)
        self.assertEqual(self.client.post(PREFIX+'/consent/revoke', json={'generation':gb}, headers=hb).status_code, 200)
        self.assertTrue(self.client.get(PREFIX+'/consent', headers=ha).json()['active'])
        self.assertEqual(self.client.post(path, json=command, headers=ha).json(),
                         {'status': 'stored', 'replayed': True})
        self.assertEqual(self.client.post(path, json=self.metadata(ga), headers=ha).status_code, 409)
        response = self.client.post(path, json=command|{'name':'synthetic-private'}, headers=ha)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('synthetic-private', response.text)
        # Opaque mobile bearer cannot authenticate against the PC product API.
        self.assertEqual(self.client.get('/api/v1/neorang-narang/completions', headers=ha).status_code, 401)
        self.assertEqual(self.client.post(path, json=command).status_code, 401)

    def test_revoke_lost_response_restart_and_old_generation(self):
        a, headers = self.login()
        generation = self.grant(headers)
        command = self.metadata(generation)
        self.assertEqual(self.client.post(PREFIX+'/synthetic-completion', json=command, headers=headers).status_code, 200)
        response = self.client.post(PREFIX+'/consent/revoke', json={'generation':generation}, headers=headers)
        self.assertEqual(response.json()['deletion_status'], 'complete')
        self.assertEqual(response.json()['deletion_through'], generation)
        self.assertTrue(response.json()['current_generation_deletion_complete'])
        self.runtime.store = SQLiteMobile(self.path, self.config.encryption_key, self.config.hmac_key)
        replay = self.client.post(PREFIX+'/consent/revoke', json={'generation':generation}, headers=headers)
        self.assertEqual(replay.json(), response.json())
        self.assertEqual(self.client.post(PREFIX+'/synthetic-completion', json=command, headers=headers).status_code, 410)
        self.assertEqual(self.grant(headers), generation+1)
        status = self.client.get(PREFIX+'/consent', headers=headers).json()
        self.assertEqual(status['deletion_status'], 'complete')
        self.assertEqual(status['deletion_through'], generation)
        self.assertFalse(status['current_generation_deletion_complete'])
        self.assertEqual(self.client.post(PREFIX+'/synthetic-completion', json=command, headers=headers).status_code, 410)
        new_command = self.metadata(generation+1)
        self.assertEqual(self.client.post(PREFIX+'/synthetic-completion', json=new_command, headers=headers).status_code, 200)
        replay = self.client.post(PREFIX+'/consent/revoke', json={'generation':generation}, headers=headers)
        self.assertTrue(replay.json()['active'])
        self.assertFalse(replay.json()['current_generation_deletion_complete'])
        self.assertEqual(self.client.post(PREFIX+'/synthetic-completion', json=new_command, headers=headers).json(),
                         {'status': 'stored', 'replayed': True})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT metadata,erased FROM nn_mobile_synthetic WHERE generation=?',
                                        (generation,)).fetchone(), (None,1))
            self.assertEqual(db.execute('SELECT erased FROM nn_mobile_synthetic WHERE generation=?',
                                        (generation+1,)).fetchone(), (0,))
        self.assertEqual(self.client.post(PREFIX+'/logout', headers=headers).status_code, 204)
        self.assertEqual(self.client.get(PREFIX+'/consent', headers=headers).status_code, 401)

    def test_parallel_exchange_has_one_winner(self):
        command = self.start()
        def consume(_):
            try:
                self.store.exchange_mobile(command['transaction'], command['code'], command['verifier'], RETURN_URI, now=NOW)
                return 200
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(consume, range(2))), [200,401])

    def test_parallel_revoke_and_send_never_leaves_server_copy(self):
        data, headers = self.login()
        generation = self.grant(headers)
        metadata = {'id': str(uuid4()), 'course_number':1}
        projection = MobileProjectionStore()
        def operation(action):
            try:
                return self.store.mobile_status(data['sub'], projection=projection, **action)
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(operation, [{'create':(generation,metadata)}, {'revoke':generation}]))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM nn_mobile_synthetic WHERE metadata IS NOT NULL').fetchone()[0], 0)

    def test_transaction_failure_preserves_original(self):
        data, headers = self.login()
        generation = self.grant(headers)
        command = self.metadata(generation)
        self.client.post(PREFIX+'/synthetic-completion', json=command, headers=headers)
        class FailingProjection(MobileProjectionStore):
            def erase(self, cursor, account, through):
                super().erase(cursor, account, through)
                raise RuntimeError('synthetic-injected')
        with self.assertRaises(RuntimeError):
            self.store.mobile_status(data['sub'], revoke=generation, projection=FailingProjection())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT active FROM mobile_consents').fetchone()[0],1)
            self.assertIsNotNone(db.execute('SELECT metadata FROM nn_mobile_synthetic').fetchone()[0])
