"""Platform Core-only persistence; no product table access or memory fallback."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import dotenv_values
from fastapi import HTTPException
import pymysql

from .auth0_poc import AppSession, denied
from .database import ROOT, connect
from .auth_diagnostics import stage


def connect_core():
    cfg = dotenv_values(ROOT / '.env.auth0-pc', interpolate=False)
    if (cfg.get('CORE_DB_HOST'), cfg.get('CORE_DB_PORT'), cfg.get('CORE_DB_NAME'),
            cfg.get('CORE_DB_USER')) != ('127.0.0.1', '3307', 'platform_core', 'platform_core_app'):
        raise HTTPException(503, 'Authentication unavailable')
    if not cfg.get('CORE_DB_PASSWORD'):
        raise HTTPException(503, 'Authentication unavailable')
    return connect(database='platform_core', user='platform_core_app', password=cfg['CORE_DB_PASSWORD'])


def digest(value):
    try:
        if not isinstance(value, str) or len(value) > 4096:
            raise denied()
        return hashlib.sha256(value.encode('ascii')).digest()
    except UnicodeError:
        raise denied() from None


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)


def stamp(value):
    return int(value.replace(tzinfo=timezone.utc).timestamp())


class CoreStore:
    def __init__(self, encryption_key, hmac_key, connector=connect_core):
        self._cipher, self._hmac, self._connect = AESGCM(encryption_key), hmac_key, connector

    def encrypt(self, value, aad):
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, value.encode(), aad)

    def decrypt(self, value, aad):
        return self._cipher.decrypt(value[:12], value[12:], aad).decode()

    @contextmanager
    def transaction(self):
        connection = None
        try:
            with stage('connect', flow='database'):
                connection = self._connect()
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            connection.begin()
            with stage('schema', flow='database'), connection.cursor() as cursor:
                cursor.execute('SELECT version FROM core_schema_version ORDER BY version')
                if cursor.fetchall() != [{'version': 1}]:
                    raise HTTPException(503, 'Authentication unavailable')
            yield connection
            connection.commit()
        except pymysql.MySQLError:
            raise HTTPException(503, 'Authentication unavailable') from None
        finally:
            if connection is not None:
                try:
                    connection.rollback()
                except pymysql.MySQLError:
                    pass
                connection.close()

    def begin_login(self, *, state, browser, nonce, verifier, client_id, redirect_uri, now):
        state_hash = digest(state)
        with self.transaction() as connection, connection.cursor() as cursor:
            cursor.execute('INSERT INTO login_transactions '
                           '(state_hash,browser_binding_hash,nonce_hash,verifier_ciphertext,key_version,'
                           'client_id,redirect_uri,created_at,expires_at) VALUES (%s,%s,%s,%s,1,%s,%s,%s,%s)',
                           (state_hash, digest(browser), digest(nonce), self.encrypt(verifier, state_hash),
                            client_id.encode(), redirect_uri.encode(), utc(now), utc(now + 300)))

    def claim_login(self, *, state, browser, now):
        if not state or not browser or len(state) > 256 or len(browser) > 256:
            raise denied()
        with self.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE login_transactions SET status='exchanging' WHERE state_hash=%s "
                           "AND browser_binding_hash=%s AND status='pending' AND expires_at>%s",
                           (digest(state), digest(browser), utc(now)))
            if cursor.rowcount != 1:
                raise denied()
            cursor.execute('SELECT * FROM login_transactions WHERE state_hash=%s', (digest(state),))
            row = cursor.fetchone()
        row['verifier'] = self.decrypt(row['verifier_ciphertext'], digest(state))
        return row

    def complete_login(self, *, state, browser, token, raw_token, now):
        # Only a verified, server-exchanged token may enter this internal method.
        if not hmac.compare_digest(hmac.digest(self._hmac, raw_token.encode('ascii'), 'sha256'), token.fingerprint):
            raise denied()
        for attempt in range(3):
            try:
                return self._complete(state, browser, token, raw_token, now)
            except HTTPException as error:
                # Retry only explicitly tagged transaction conflicts, never arbitrary storage errors.
                if error.status_code != 409 or attempt == 2:
                    raise
        raise denied()

    def _complete(self, state, browser, token, raw_token, now):
        with self.transaction() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT * FROM login_transactions WHERE state_hash=%s FOR UPDATE', (digest(state),))
            login = cursor.fetchone()
            if (not login or login['status'] != 'exchanging' or login['expires_at'] <= utc(now)
                    or login['browser_binding_hash'] != digest(browser)
                    or login['client_id'] != token.client_id.encode() or token.expires_at <= now):
                raise denied()
            issuer, subject = token.issuer.encode(), token.subject.encode()
            cursor.execute('SELECT account_id FROM external_identities WHERE issuer=%s AND provider_subject=%s',
                           (issuer, subject))
            identity = cursor.fetchone()
            account = identity['account_id'] if identity else str(uuid4())
            if identity is None:
                try:
                    cursor.execute('INSERT INTO accounts (account_id,created_at) VALUES (%s,%s)', (account, utc(now)))
                    cursor.execute('INSERT INTO external_identities (issuer,provider_subject,account_id,created_at) '
                                   'VALUES (%s,%s,%s,%s)', (issuer, subject, account, utc(now)))
                except pymysql.IntegrityError:
                    raise HTTPException(409, 'Authentication conflict') from None
                except pymysql.OperationalError as error:
                    if error.args[0] in (1205, 1213):
                        raise HTTPException(409, 'Authentication conflict') from None
                    raise
            cursor.execute('SELECT * FROM accounts WHERE account_id=%s FOR UPDATE', (account,))
            owner = cursor.fetchone()
            if owner['status'] != 'active':
                raise denied()
            sid, cookie, csrf = str(uuid4()), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            cursor.execute('INSERT INTO app_sessions (session_id,account_id,issuer,provider_subject,client_id,'
                           'cookie_hash,csrf_hash,account_security_version,created_at,expires_at) '
                           'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                           (sid, account, issuer, subject, token.client_id.encode(), digest(cookie), digest(csrf),
                            owner['security_version'], utc(now), utc(token.expires_at)))
            try:
                cursor.execute('INSERT INTO session_access_tokens (fingerprint,fingerprint_key_version,session_id,'
                               'jwt_ciphertext,encryption_key_version,issued_at,expires_at) VALUES (%s,1,%s,%s,1,%s,%s)',
                               (token.fingerprint, sid, self.encrypt(raw_token, token.fingerprint), utc(now), utc(token.expires_at)))
            except pymysql.IntegrityError:
                raise denied() from None
            cursor.execute("UPDATE login_transactions SET status='completed',consumed_at=%s WHERE state_hash=%s",
                           (utc(now), digest(state)))
            return cookie, csrf, UUID(account)

    def lookup(self, fingerprint):
        with self.transaction() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT s.*,a.status AS account_status,a.security_version FROM session_access_tokens t '
                           'JOIN app_sessions s ON s.session_id=t.session_id JOIN accounts a ON a.account_id=s.account_id '
                           'WHERE t.fingerprint=%s', (fingerprint,))
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute('SELECT revoked_at FROM product_consents WHERE account_id=%s AND product=%s '
                           'AND purpose=%s AND policy_version=%s',
                           (row['account_id'], b'neorang_narang', b'completion-metadata', b'pc-poc-v1'))
            consent = cursor.fetchone()
            return AppSession(UUID(row['session_id']), UUID(row['account_id']), row['issuer'].decode(),
                              row['provider_subject'].decode(), row['client_id'].decode(), stamp(row['expires_at']),
                              row['version'], row['revoked_at'] is not None,
                              row['account_status'] == 'active' and row['security_version'] == row['account_security_version'],
                              consent is not None and consent['revoked_at'] is None)

    def cookie_token(self, cookie, *, now, csrf=None, allow_revoked=False):
        if not cookie or len(cookie) > 256:
            raise denied()
        with stage('cookie_lookup', flow='session'), self.transaction() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT s.*,t.fingerprint,t.jwt_ciphertext FROM app_sessions s '
                           'JOIN session_access_tokens t ON t.session_id=s.session_id WHERE s.cookie_hash=%s',
                           (digest(cookie),))
            row = cursor.fetchone()
        with stage('cookie_session_validation', flow='session'):
            if (not row or (not allow_revoked and (row['revoked_at'] is not None or row['expires_at'] <= utc(now)))
                    or (csrf is not None and not hmac.compare_digest(row['csrf_hash'], digest(csrf)))):
                raise denied()
        with stage('token_decrypt', flow='session'):
            raw = self.decrypt(row['jwt_ciphertext'], row['fingerprint'])
        return raw, row

    def logout(self, cookie, csrf, *, now):
        self.cookie_token(cookie, now=now, csrf=csrf, allow_revoked=True)
        with self.transaction() as connection, connection.cursor() as cursor:
            cursor.execute('UPDATE app_sessions SET revoked_at=%s,version=version+1 '
                           'WHERE cookie_hash=%s AND revoked_at IS NULL', (utc(now), digest(cookie)))

    def grant_consent(self, account, *, now):
        with self.transaction() as connection, connection.cursor() as cursor:
            cursor.execute('INSERT INTO product_consents '
                           '(account_id,product,purpose,policy_version,generation,granted_at) '
                           'VALUES (%s,%s,%s,%s,1,%s) AS new '
                           'ON DUPLICATE KEY UPDATE policy_version=new.policy_version,generation=product_consents.generation+1,'
                           'granted_at=new.granted_at,revoked_at=NULL',
                           (str(account), b'neorang_narang', b'completion-metadata', b'pc-poc-v1', utc(now)))
