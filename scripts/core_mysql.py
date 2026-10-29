"""Approved local Core administration. No credential, row, SQL or exception output."""
import argparse
import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
import tempfile

from dotenv import dotenv_values, set_key

from app.core.database import ROOT, connect
from scripts.local_mysql import protect, snapshot_for

ADMIN_FILE = ROOT / '.env.core-admin'
APP_FILE = ROOT / '.env.auth0-pc'
MANIFEST = ROOT / '.env.core-schema'
PRODUCT_BASELINE = ROOT / '.env.core-product-baseline'
TABLES = ('core_schema_version', 'accounts', 'external_identities', 'login_transactions',
          'app_sessions', 'session_access_tokens', 'product_consents')


def local_config():
    return dict(dotenv_values(APP_FILE, interpolate=False))


def core_connect(*, migrator=False, database='platform_core'):
    if database != 'platform_core' and not re.fullmatch(r'core_(?:check|restore|layout)_[a-f0-9]{12}', database):
        raise ValueError('Invalid Core target')
    values = local_config()
    if (values.get('CORE_DB_HOST'), values.get('CORE_DB_PORT'), values.get('CORE_DB_NAME'),
            values.get('CORE_DB_USER')) != ('127.0.0.1', '3307', 'platform_core', 'platform_core_app'):
        raise ValueError('Invalid Core configuration')
    if migrator:
        password = dotenv_values(ADMIN_FILE, interpolate=False).get('CORE_MIGRATOR_PASSWORD')
        user = 'platform_core_migrator'
    else:
        password, user = values.get('CORE_DB_PASSWORD'), 'platform_core_app'
    if not password:
        raise ValueError('Missing Core credentials')
    return connect(database=database, user=user, password=password)


def statements():
    source = (ROOT / 'migrations/platform_core/001_pc_auth.sql').read_text(encoding='utf-8')
    source = re.sub(r'--[^\n]*', '', source)
    return [s.strip() for s in source.split(';') if s.strip() and not s.strip().upper().startswith('USE ')]


def shape(connection, table):
    with connection.cursor() as cursor:
        cursor.execute(f'SHOW CREATE TABLE `{table}`')
        return cursor.fetchone()['Create Table']


def migrate(connection, expected):
    with connection.cursor() as cursor:
        cursor.execute('SELECT DATABASE() AS db')
        target = cursor.fetchone()['db']
        if target != 'platform_core' and not re.fullmatch(r'core_check_[a-f0-9]{12}', target or ''):
            raise ValueError('Invalid migration target')
        cursor.execute('SELECT GET_LOCK(%s,10) AS acquired', ('core.migration.' + target,))
        if cursor.fetchone()['acquired'] != 1:
            raise RuntimeError('Core migration lock unavailable')
        try:
            cursor.execute('SHOW TABLES')
            existing = {next(iter(row.values())) for row in cursor.fetchall()}
            if not existing <= set(TABLES):
                raise RuntimeError('Unknown Core tables')
            if 'core_schema_version' in existing:
                cursor.execute('SELECT version FROM core_schema_version ORDER BY version')
                if [r['version'] for r in cursor.fetchall()] not in ([], [1]):
                    raise RuntimeError('Unsupported Core version')
            for table in existing:
                if shape(connection, table) != expected[table]:
                    raise RuntimeError('Existing Core schema mismatch')
            sql = statements()
            for statement in sql[:-1]:
                cursor.execute(statement)
            for table in TABLES:
                if shape(connection, table) != expected[table]:
                    raise RuntimeError('Core schema mismatch')
            cursor.execute(sql[-1])
            connection.commit()
        finally:
            cursor.execute('SELECT RELEASE_LOCK(%s)', ('core.migration.' + target,))


def capture_products(connection):
    result = {}
    for database in ('neorang_narang', 'life_diary'):
        with connection.cursor() as cursor:
            cursor.execute(f'USE `{database}`')
            cursor.execute('SHOW TABLES')
            tables = [next(iter(r.values())) for r in cursor.fetchall()]
            for table in tables:
                cursor.execute(f'SELECT * FROM `{table}`')
                result[database + '.' + table] = [hashlib.sha256(repr(sorted(r.items())).encode()).hexdigest()
                                                       for r in cursor.fetchall()]
    return result


def verify_products(connection):
    before = json.loads(PRODUCT_BASELINE.read_text(encoding='utf-8'))
    after = capture_products(connection)
    if set(before) != set(after) or any(not set(rows) <= set(after[t]) for t, rows in before.items()):
        raise RuntimeError('Existing product state changed')


def preflight(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS n FROM information_schema.schemata WHERE schema_name='platform_core'")
        db_exists = bool(cursor.fetchone()['n'])
        cursor.execute("SELECT COUNT(*) AS n FROM mysql.user WHERE User IN ('platform_core_app','platform_core_migrator')")
        users_exist = bool(cursor.fetchone()['n'])
    print('Core DB exists:', db_exists, '; named accounts exist:', users_exist)
    return db_exists or users_exist


def bootstrap():
    with connect(admin=True) as root:
        if preflight(root) or ADMIN_FILE.exists() or MANIFEST.exists():
            raise RuntimeError('Existing Core resources; no overwrite')
        values = local_config()
        if values.get('CORE_DB_PASSWORD'):
            raise RuntimeError('Existing Core credentials; no overwrite')
        with PRODUCT_BASELINE.open('x', encoding='utf-8') as output:
            protect(PRODUCT_BASELINE)
            output.write(json.dumps(capture_products(root)))
        # Canonical schema is built in a new isolated empty DB, never existing tables.
        layout = 'core_layout_' + secrets.token_hex(6)
        with root.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{layout}` CHARACTER SET utf8mb4')
            cursor.execute(f'USE `{layout}`')
            for statement in statements()[:-1]:
                cursor.execute(statement)
        expected = {table: shape(root, table) for table in TABLES}
        with MANIFEST.open('x', encoding='utf-8') as output:
            protect(MANIFEST)
            output.write(json.dumps(expected))
        app_password, migration_password = secrets.token_hex(32), secrets.token_hex(32)
        with ADMIN_FILE.open('x', encoding='utf-8') as output:
            protect(ADMIN_FILE)
            output.write('CORE_MIGRATOR_PASSWORD=' + migration_password + '\n')
        protect(APP_FILE)
        set_key(str(APP_FILE), 'CORE_DB_PASSWORD', app_password, quote_mode='always')
        protect(APP_FILE)
        with root.cursor() as cursor:
            cursor.execute('CREATE DATABASE platform_core CHARACTER SET utf8mb4')
            for user, password in (('platform_core_migrator', migration_password),
                                   ('platform_core_app', app_password)):
                cursor.execute('CREATE USER %s@%s IDENTIFIED BY %s', (user, '%', password))
            cursor.execute('GRANT SELECT, INSERT, CREATE, INDEX, REFERENCES ON platform_core.* TO %s@%s',
                           ('platform_core_migrator', '%'))
        root.commit()
        with core_connect(migrator=True) as migration:
            migrate(migration, expected)
        with root.cursor() as cursor:
            for table in TABLES:
                privileges = 'SELECT' if table == 'core_schema_version' else 'SELECT, INSERT, UPDATE'
                cursor.execute(f'GRANT {privileges} ON platform_core.{table} TO %s@%s',
                               ('platform_core_app', '%'))
        tighten_migrator(root)
        root.commit()
        verify_products(root)
    print('PASS: new Core DB and separate accounts created; products preserved')


def core_snapshot(connection):
    result = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'SELECT * FROM `{table}`')
            result[table] = sorted(cursor.fetchall(), key=repr)
    return result


def finish_bootstrap():
    # Explicit recovery only for resources created with this local manifest and
    # credentials. Never re-create accounts, reset passwords or replace tables.
    expected = json.loads(MANIFEST.read_text(encoding='utf-8'))
    with core_connect(migrator=True) as connection:
        migrate(connection, expected)
    with connect(admin=True) as root:
        with root.cursor() as cursor:
            for table in TABLES:
                privileges = 'SELECT' if table == 'core_schema_version' else 'SELECT, INSERT, UPDATE'
                cursor.execute(f'GRANT {privileges} ON platform_core.{table} TO %s@%s',
                               ('platform_core_app', '%'))
        tighten_migrator(root)
        root.commit()
        verify_products(root)
    print('PASS: owned partial bootstrap resumed without replacing resources')


def tighten_migrator(connection):
    with connection.cursor() as cursor:
        cursor.execute('GRANT SELECT, INSERT ON platform_core.core_schema_version TO %s@%s',
                       ('platform_core_migrator', '%'))
        cursor.execute('SHOW GRANTS FOR %s@%s', ('platform_core_migrator', '%'))
        grants = ' '.join(next(iter(r.values())) for r in cursor.fetchall())
        if 'SELECT, INSERT, CREATE' in grants:
            cursor.execute('REVOKE SELECT, INSERT ON platform_core.* FROM %s@%s',
                           ('platform_core_migrator', '%'))


def encode(value):
    if isinstance(value, bytes):
        return {'binary': base64.b64encode(value).decode()}
    if isinstance(value, datetime):
        return {'datetime': value.isoformat()}
    raise TypeError('Unsupported backup value')


def decode(value):
    if set(value) == {'binary'}:
        return base64.b64decode(value['binary'], validate=True)
    if set(value) == {'datetime'}:
        return datetime.fromisoformat(value['datetime'])
    return value


def backup_verify():
    with core_connect() as source:
        source.begin()
        rows = core_snapshot(source)
        source.rollback()
    expected = json.loads(MANIFEST.read_text(encoding='utf-8'))
    directory = Path(tempfile.mkdtemp(prefix='jesuslife-core-backup-'))
    protect(directory)
    backup = directory / 'core.json'
    with backup.open('x', encoding='utf-8') as output:
        protect(backup)
        json.dump({'schema': expected, 'rows': rows}, output, default=encode)
    saved = json.loads(backup.read_text(encoding='utf-8'), object_hook=decode)
    restore = 'core_restore_' + secrets.token_hex(6)
    with connect(admin=True) as root:
        with root.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{restore}` CHARACTER SET utf8mb4')
            cursor.execute(f'USE `{restore}`')
            for table in TABLES:
                cursor.execute(saved['schema'][table])
                for row in saved['rows'][table]:
                    columns = ','.join('`' + name + '`' for name in row)
                    cursor.execute(f'INSERT INTO `{table}` ({columns}) VALUES ({",".join(["%s"] * len(row))})',
                                   tuple(row.values()))
        root.commit()
        if core_snapshot(root) != rows:
            raise RuntimeError('Core restore mismatch')
        verify_products(root)
    location = ROOT / '.env.core-backup-location'
    location.write_text(str(directory), encoding='utf-8')
    protect(location)
    print('PASS: protected Core backup restored into isolated retained DB; all state matches')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('preflight', 'bootstrap', 'finish-bootstrap', 'migrate', 'backup-verify', 'verify-products'))
    action = parser.parse_args().action
    try:
        if action == 'bootstrap':
            bootstrap()
        elif action == 'finish-bootstrap':
            finish_bootstrap()
        elif action == 'migrate':
            with core_connect(migrator=True) as connection:
                migrate(connection, json.loads(MANIFEST.read_text(encoding='utf-8')))
            print('PASS: Core migration shape/version verified and safely replayed')
        elif action == 'backup-verify':
            backup_verify()
        else:
            with connect(admin=True) as connection:
                if action == 'preflight':
                    preflight(connection)
                    cfg = local_config()
                    print('Auth0 configured:', all(cfg.get(k) for k in ('AUTH0_ISSUER','AUTH0_CLIENT_ID','AUTH0_CLIENT_SECRET')))
                else:
                    verify_products(connection)
                    print('PASS: pre-existing product rows and table inventory preserved')
    except Exception as error:
        print('FAIL:', action, type(error).__name__, '(details suppressed)')
        if error.args and type(error.args[0]) is int:
            print('Database error code:', error.args[0])
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
