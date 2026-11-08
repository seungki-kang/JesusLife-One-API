"""Synthetic SQLite + mock RSA/Auth0 only; no live DB, secrets or network."""
from dataclasses import replace
from contextlib import closing
import secrets
import sqlite3
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from urllib.parse import parse_qs, urlsplit

from app.auth0_pc import PcRuntime
from app.core.auth0_poc import pkce_challenge
from app.core.life_diary_login import APP_ID, CALLBACK, PREFIX, RETURN_URI, Registration
from app.core.mobile_routes import PREFIX as NN_PREFIX, RETURN_URI as NN_URI
from tests.test_core_persistence import SyntheticAuth0
from tests import test_mobile_broker as legacy


class LifeDiaryLoginTest(unittest.TestCase):
    setUp = legacy.MobileBrokerTest.setUp
    start = legacy.MobileBrokerTest.start
    login = legacy.MobileBrokerTest.login
    grant = legacy.MobileBrokerTest.grant

    def enable(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript('ALTER TABLE mobile_logins ADD app_id BLOB;'
                             'ALTER TABLE mobile_logins ADD client_id BLOB;'
                             'ALTER TABLE app_sessions ADD app_id BLOB;')
        client = 'synthetic-life-diary-client'
        config = replace(self.config, policy=replace(self.config.policy, client_ids=frozenset({client})))
        self.ld = SyntheticAuth0(config)
        original = self.ld.jwt.signed
        def signed(**kwargs):
            kwargs['claims'] = (kwargs.get('claims') or {}) | {'scope': 'openid'}
            return original(**kwargs)
        self.ld.jwt.signed = signed
        self.runtime.life_diary_runtime = PcRuntime(config, store=self.store, provider=self.ld.provider,
                                                   clock=lambda: self.now)
        self.runtime.life_diary_registration = Registration(client, enabled=True)
        self.fields = {'app_id': APP_ID, 'client_id': client, 'return_uri': RETURN_URI}

    def ld_start(self, wrong_nonce=False, callback_status=303):
        verifier = secrets.token_urlsafe(32)
        response = self.client.post(PREFIX+'/login-transactions', json=self.fields | {
            'challenge': pkce_challenge(verifier)})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.get(response.json()['authorize_url'], follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        query = parse_qs(urlsplit(response.headers['location']).query)
        self.assertEqual(query['scope'], ['openid'])
        self.assertEqual(query['client_id'], [self.fields['client_id']])
        code, state = self.ld.issue(response.headers['location'], 'auth0|synthetic-a', wrong_nonce=wrong_nonce)
        response = self.client.get(CALLBACK, params={'code': code, 'state': state}, follow_redirects=False)
        if wrong_nonce or callback_status != 303:
            self.assertEqual(response.status_code, 401 if wrong_nonce else callback_status)
            return response
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers['location'].split('?')[0], RETURN_URI)
        query = parse_qs(urlsplit(response.headers['location']).query)
        return self.fields | {'transaction': query['transaction'][0], 'code': query['code'][0], 'verifier': verifier}

    def test_disabled_and_invalid_registration(self):
        command = {'app_id': APP_ID, 'client_id': 'synthetic', 'return_uri': RETURN_URI,
                   'challenge': pkce_challenge(secrets.token_urlsafe(32))}
        self.assertEqual(self.client.post(PREFIX+'/login-transactions', json=command).status_code, 503)
        self.enable()
        self.runtime.life_diary_registration = replace(self.runtime.life_diary_registration, enabled=False)
        self.assertEqual(self.client.post(PREFIX+'/login-transactions', json=command).status_code, 503)
        self.runtime.life_diary_registration = Registration(next(iter(self.config.policy.client_ids)), enabled=True)
        self.assertEqual(self.client.post(PREFIX+'/login-transactions', json=command).status_code, 503)

    def test_mapping_cross_exchange_replay_and_logout_isolation(self):
        self.enable()
        nn, nn_headers = self.login()
        self.grant(nn_headers)
        command = self.ld_start()
        for field, value in [('app_id', 'neorang_narang'), ('client_id', 'synthetic-pc-client'),
                             ('return_uri', NN_URI), ('verifier', secrets.token_urlsafe(32))]:
            self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command | {field:value}).status_code, 401)
        nn_command = {k:v for k,v in command.items() if k not in ('app_id','client_id')}
        self.assertEqual(self.client.post(NN_PREFIX+'/session-exchange', json=nn_command | {'return_uri':NN_URI}).status_code, 401)
        response = self.client.post(PREFIX+'/session-exchange', json=command)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['sub'], nn['sub'])
        headers = {'Authorization': 'Bearer '+response.json()['access_token']}
        self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command).status_code, 401)
        self.assertEqual(self.client.get(PREFIX+'/session', headers=nn_headers).status_code, 401)
        self.assertEqual(self.client.post(PREFIX+'/logout', headers=nn_headers).status_code, 401)
        self.assertEqual(self.client.post(NN_PREFIX+'/logout', headers=headers).status_code, 401)
        self.assertEqual(self.client.get(NN_PREFIX+'/consent', headers=headers).status_code, 401)
        self.assertEqual(self.client.get(PREFIX+'/session', headers=headers).status_code, 200)
        self.assertEqual(self.client.post(PREFIX+'/logout', headers=headers).status_code, 204)
        self.assertEqual(self.client.get(PREFIX+'/session', headers=headers).status_code, 401)
        self.assertEqual(self.client.get(NN_PREFIX+'/consent', headers=nn_headers).status_code, 200)
        command = self.start()
        self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command | self.fields).status_code, 401)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM external_identities').fetchone()[0], 1)

    def test_missing_binding_nonce_and_saved_session_mismatch(self):
        self.enable()
        for field in ('app_id', 'client_id'):
            command = self.fields | {'challenge':pkce_challenge(secrets.token_urlsafe(32))}
            del command[field]
            self.assertEqual(self.client.post(PREFIX+'/login-transactions', json=command).status_code, 422)
        self.assertEqual(self.ld_start(wrong_nonce=True).status_code, 401)
        command = self.ld_start()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE app_sessions SET app_id=NULL'); db.commit()
        self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command).status_code, 401)

    def test_null_legacy_rows_are_not_reclassified(self):
        self.enable()
        command = self.start()
        self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command | self.fields).status_code, 401)
        self.assertEqual(self.client.post(NN_PREFIX+'/session-exchange', json=command).status_code, 200)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT app_id,client_id FROM mobile_logins').fetchone(), (None,None))
            self.assertIsNone(db.execute('SELECT app_id FROM app_sessions').fetchone()[0])

    def test_stored_transaction_binding_and_callback_replay(self):
        self.enable()
        for field, value in [('app_id', None), ('client_id', b'other'), ('return_uri', NN_URI.encode())]:
            response = self.client.post(PREFIX+'/login-transactions', json=self.fields | {
                'challenge':pkce_challenge(secrets.token_urlsafe(32))})
            url = response.json()['authorize_url']
            with closing(sqlite3.connect(self.path)) as db:
                # Field names are a fixed synthetic test list, never request input.
                db.execute(f'UPDATE mobile_logins SET {field}=?', (value,)); db.commit()
            self.assertEqual(self.client.get(url, follow_redirects=False).status_code, 401)
        response = self.client.post(PREFIX+'/login-transactions', json=self.fields | {
            'challenge':pkce_challenge(secrets.token_urlsafe(32))})
        url = response.json()['authorize_url']
        self.assertEqual(self.client.get(url.replace(PREFIX, NN_PREFIX), follow_redirects=False).status_code, 401)
        response = self.client.get(url, follow_redirects=False)
        code, state = self.ld.issue(response.headers['location'], 'auth0|synthetic-a')
        params = {'code':code, 'state':state}
        self.assertEqual(self.client.get(CALLBACK, params=params, follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.get(CALLBACK, params=params, follow_redirects=False).status_code, 401)

    def test_neorang_logout_keeps_life_diary_session(self):
        self.enable()
        _, nn_headers = self.login()
        response = self.client.post(PREFIX+'/session-exchange', json=self.ld_start())
        self.assertEqual(response.status_code, 200)
        headers = {'Authorization':'Bearer '+response.json()['access_token']}
        self.assertEqual(self.client.post(NN_PREFIX+'/logout', headers=nn_headers).status_code, 204)
        self.assertEqual(self.client.get(PREFIX+'/session', headers=headers).status_code, 200)

    def test_handoff_write_failure_rolls_back_bound_session_and_token(self):
        self.enable()
        _, legacy_headers = self.login()
        original = legacy.Cursor.execute
        observed = []
        credentials = []
        finish = self.store.finish_mobile
        def capture_handoff(state, browser, credential, account, code, **kwargs):
            credentials.append(credential)
            return finish(state, browser, credential, account, code, **kwargs)
        def fail_after_write(cursor, sql, args=()):
            result = original(cursor, sql, args)
            if sql.startswith('UPDATE mobile_logins SET handoff_hash='):
                # Verify binding already exists inside the uncommitted transaction.
                rows = cursor.raw.connection.execute(
                    'SELECT app_id,client_id FROM app_sessions WHERE app_id IS NOT NULL').fetchall()
                observed.extend(tuple(row) for row in rows)
                raise HTTPException(503, 'Synthetic handoff failure')
            return result
        with patch.object(self.store, 'finish_mobile', capture_handoff), \
                patch.object(legacy.Cursor, 'execute', fail_after_write):
            response = self.ld_start(callback_status=503)
        self.assertEqual(observed, [(APP_ID.encode(), self.fields['client_id'].encode())])
        self.assertNotIn('location', response.headers)
        self.assertNotIn('access_token', response.text)
        self.assertEqual(len(credentials), 1)
        with self.assertRaises(HTTPException) as rejected:
            self.store.cookie_token(credentials[0], now=self.now)
        self.assertEqual(rejected.exception.status_code, 401)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT app_id FROM app_sessions').fetchall(), [(None,)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM session_access_tokens').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT status,consumed_at FROM login_transactions WHERE client_id=?',
                (self.fields['client_id'].encode(),)).fetchone(), ('exchanging', None))
            self.assertEqual(db.execute('SELECT handoff_hash,credential_ciphertext,consumed_at FROM mobile_logins '
                'WHERE app_id=?', (APP_ID.encode(),)).fetchone(), (None, None, None))
            account, browser = db.execute('SELECT account_id,browser_ciphertext FROM mobile_logins '
                'WHERE app_id=?', (APP_ID.encode(),)).fetchone()
            self.assertIsNone(account)
            self.assertIsNotNone(browser)
        self.assertEqual(self.client.get(NN_PREFIX+'/consent', headers=legacy_headers).status_code, 200)
        # The provider code and claimed login are not retried; a fresh login succeeds.
        self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=self.ld_start()).status_code, 200)

    def test_saved_binding_mismatch_does_not_consume_valid_exchange(self):
        self.enable()
        for table in ('mobile_logins', 'app_sessions'):
            for field, valid in (('app_id', APP_ID.encode()),
                                 ('client_id', self.fields['client_id'].encode())):
                with self.subTest(table=table, field=field):
                    command = self.ld_start()
                    with closing(sqlite3.connect(self.path)) as db:
                        if table == 'mobile_logins':
                            where, key = 'transaction_id=?', command['transaction']
                        else:
                            where, key = 'session_id=(SELECT session_id FROM app_sessions ORDER BY rowid DESC LIMIT 1)', None
                        args = (b'wrong-binding',) + ((key,) if key else ())
                        db.execute(f'UPDATE {table} SET {field}=? WHERE {where}', args)
                        db.commit()
                        before = db.execute('SELECT * FROM mobile_logins WHERE transaction_id=?',
                                            (command['transaction'],)).fetchone()
                    self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command).status_code, 401)
                    with closing(sqlite3.connect(self.path)) as db:
                        self.assertEqual(db.execute('SELECT * FROM mobile_logins WHERE transaction_id=?',
                            (command['transaction'],)).fetchone(), before)
                        row = db.execute('SELECT consumed_at,credential_ciphertext FROM mobile_logins WHERE transaction_id=?',
                                         (command['transaction'],)).fetchone()
                        self.assertIsNone(row[0])
                        self.assertIsNotNone(row[1])
                        db.execute(f'UPDATE {table} SET {field}=? WHERE {where}',
                                   (valid,) + ((key,) if key else ()))
                        db.commit()
                    self.assertEqual(self.client.post(PREFIX+'/session-exchange', json=command).status_code, 200)
