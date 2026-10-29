"""Explicit local incident rotation. Never render secrets, rows or exceptions.

Protected recovery bundle is retained outside Git. No automatic rollback to
compromised credentials. A failed run leaves the app DB account locked.
"""
import base64
import hmac
import json
from pathlib import Path
import secrets
import socket
import tempfile
from types import SimpleNamespace

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import dotenv_values, set_key

from app.core.database import ROOT, connect
from scripts.core_mysql import APP_FILE, TABLES, core_snapshot, encode, capture_products
from scripts.local_mysql import protect


def seal(cipher, value, aad):
    nonce = secrets.token_bytes(12)
    result = nonce + cipher.encrypt(nonce, value, aad)
    assert cipher.decrypt(result[:12], result[12:], aad) == value
    return result


def validate(values):
    # Rotation must work before an Auth0 tenant has been configured.
    if tuple(values.get(k) for k in ('CORE_DB_HOST', 'CORE_DB_PORT', 'CORE_DB_NAME', 'CORE_DB_USER')) != (
            '127.0.0.1', '3307', 'platform_core', 'platform_core_app'):
        raise ValueError('Unexpected database target')
    encryption_key = base64.b64decode(values['CORE_TOKEN_ENCRYPTION_KEY'], validate=True)
    hmac_key = base64.b64decode(values['CORE_TOKEN_HMAC_KEY'], validate=True)
    if len(encryption_key) != 32 or len(hmac_key) != 32 or encryption_key == hmac_key or not values.get('CORE_DB_PASSWORD'):
        raise ValueError('Invalid secret configuration')
    return SimpleNamespace(encryption_key=encryption_key, hmac_key=hmac_key, database_password=values['CORE_DB_PASSWORD'])


def rotate():
    if (ROOT / '.env.core-rotation-location').exists():
        raise RuntimeError('Existing rotation receipt requires manual review')
    # No running HTTP process may retain old keys. Do not terminate unknown apps.
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 8000)) == 0:
            raise RuntimeError('Stop the local HTTP server before rotation')
    values = dict(dotenv_values(APP_FILE, interpolate=False))
    old = validate(values)
    password = secrets.token_hex(32)
    new_hmac, new_key = secrets.token_bytes(32), secrets.token_bytes(32)
    replacement = dict(values, CORE_DB_PASSWORD=password,
                       CORE_TOKEN_HMAC_KEY=base64.b64encode(new_hmac).decode(),
                       CORE_TOKEN_ENCRYPTION_KEY=base64.b64encode(new_key).decode())
    validate(replacement)
    directory = Path(tempfile.mkdtemp(prefix='jesuslife-incident-'))
    protect(directory)
    bundle = directory / 'recovery.json'
    # Create and restrict empty files BEFORE writing sensitive data.
    bundle.touch(exist_ok=False)
    protect(bundle)
    location = ROOT / '.env.core-rotation-location'
    location.touch(exist_ok=True)
    protect(location)
    location.write_text(str(directory), encoding='utf-8')
    staged = directory / 'replacement.env'
    staged.touch(exist_ok=False)
    protect(staged)
    staged.write_text(APP_FILE.read_text(encoding='utf-8'), encoding='utf-8')
    for name in ('CORE_DB_PASSWORD', 'CORE_TOKEN_HMAC_KEY', 'CORE_TOKEN_ENCRYPTION_KEY'):
        set_key(str(staged), name, replacement[name], quote_mode='always')
    protect(staged)
    old_cipher, new_cipher = AESGCM(old.encryption_key), AESGCM(new_key)
    with connect(admin=True, database='platform_core') as root:
        with root.cursor() as cursor:
            cursor.execute("SELECT User,Host FROM mysql.user WHERE User='platform_core_app'")
            if cursor.fetchall() != [{'User': 'platform_core_app', 'Host': '%'}]:
                raise RuntimeError('Unexpected app account inventory')
            cursor.execute('SHOW GRANTS FOR %s@%s', ('platform_core_app', '%'))
            grants = cursor.fetchall()
            # Maintenance gate survives failures and blocks new connections.
            cursor.execute('ALTER USER %s@%s ACCOUNT LOCK', ('platform_core_app', '%'))
            cursor.execute("SELECT ID FROM information_schema.PROCESSLIST WHERE USER='platform_core_app'")
            for row in cursor.fetchall():
                cursor.execute('KILL CONNECTION ' + str(int(row['ID'])))
        root.begin()
        before = core_snapshot(root)
        products = capture_products(root)
        with root.cursor() as cursor:
            cursor.execute('USE platform_core')
        bundle.write_text(json.dumps({'old_settings': values, 'new_settings': replacement,
                                     'rows': before, 'grants': grants,
                                     'phase': 'locked_before_rotation'}, default=encode), encoding='utf-8')
        tokens, logins = [], []
        for row in before['session_access_tokens']:
            aad = row['fingerprint']
            raw = old_cipher.decrypt(row['jwt_ciphertext'][:12], row['jwt_ciphertext'][12:], aad)
            if not hmac.compare_digest(hmac.digest(old.hmac_key, raw, 'sha256'), aad):
                raise RuntimeError('Token binding mismatch')
            fingerprint = hmac.digest(new_hmac, raw, 'sha256')
            tokens.append((fingerprint, seal(new_cipher, raw, fingerprint), aad))
        if len({r[0] for r in tokens}) != len(tokens):
            raise RuntimeError('Fingerprint collision')
        for row in before['login_transactions']:
            raw = old_cipher.decrypt(row['verifier_ciphertext'][:12], row['verifier_ciphertext'][12:], row['state_hash'])
            logins.append((seal(new_cipher, raw, row['state_hash']), row['state_hash']))
        print('PASS: all existing ciphertext authenticated and recoverable; protected recovery bundle retained')
        with root.cursor() as cursor:
            for fingerprint, ciphertext, prior in tokens:
                cursor.execute('UPDATE session_access_tokens SET fingerprint=%s,jwt_ciphertext=%s WHERE fingerprint=%s',
                               (fingerprint, ciphertext, prior))
            for ciphertext, state in logins:
                cursor.execute('UPDATE login_transactions SET verifier_ciphertext=%s WHERE state_hash=%s', (ciphertext, state))
            cursor.execute("UPDATE login_transactions SET status='failed' WHERE status IN ('pending','exchanging')")
            cursor.execute('UPDATE app_sessions SET revoked_at=UTC_TIMESTAMP(6),version=version+1 WHERE revoked_at IS NULL')
        after = core_snapshot(root)
        for table in TABLES:
            if len(before[table]) != len(after[table]):
                raise RuntimeError('Row inventory changed')
        for table in ('accounts', 'external_identities', 'product_consents', 'core_schema_version'):
            if before[table] != after[table]:
                raise RuntimeError('Persistent identity or consent changed')
        for row in after['session_access_tokens']:
            raw = new_cipher.decrypt(row['jwt_ciphertext'][:12], row['jwt_ciphertext'][12:], row['fingerprint'])
            if hmac.digest(new_hmac, raw, 'sha256') != row['fingerprint']:
                raise RuntimeError('New binding mismatch')
        if any(r['revoked_at'] is None for r in after['app_sessions']):
            raise RuntimeError('Session still active')
        root.commit()
        # Password DDL commits implicitly; DB remains locked through file switch.
        with root.cursor() as cursor:
            cursor.execute('ALTER USER %s@%s IDENTIFIED BY %s', ('platform_core_app', '%', password))
        protect(APP_FILE)
        APP_FILE.write_text(staged.read_text(encoding='utf-8'), encoding='utf-8')
        protect(APP_FILE)
        if validate(dict(dotenv_values(APP_FILE, interpolate=False))).encryption_key != new_key:
            raise RuntimeError('Settings switch failed')
        if products != capture_products(root):
            raise RuntimeError('Product data changed')
        with root.cursor() as cursor:
            cursor.execute('ALTER USER %s@%s ACCOUNT UNLOCK', ('platform_core_app', '%'))
        with connect(database='platform_core', user='platform_core_app', password=password) as app:
            if core_snapshot(app) != after:
                raise RuntimeError('New app credential verification failed')
        try:
            connection = connect(database='platform_core', user='platform_core_app', password=old.database_password)
        except Exception as error:
            if not error.args or error.args[0] != 1045:
                raise RuntimeError('Old credential rejection unverified') from None
        else:
            connection.close()
            raise RuntimeError('Old password accepted')
        (directory / 'COMPLETE').write_text('Rotation verified. Never restore old active sessions or exposed credentials.\n', encoding='utf-8')
        protect(directory / 'COMPLETE')
    print('PASS: DB password replaced; old password rejected; keys replaced; all sessions revoked; all user rows preserved')


if __name__ == '__main__':
    try:
        rotate()
    except Exception as error:
        import traceback
        print('Failure type:', type(error).__name__)
        print('Failure locations:', [(Path(f.filename).name, f.lineno) for f in traceback.extract_tb(error.__traceback__)])
        print('BLOCKED: no completion verified; details suppressed. Check recovery receipt and account lock state; do not retry blindly.')
        raise SystemExit(1) from None
