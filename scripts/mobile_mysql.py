"""Opt-in additive local mobile migration. Default plan never opens a DB.

Apply requires a stopped API and verified backup/restore rehearsal. No DROP,
DELETE, ALTER, credential changes or service startup. Layout DBs are retained.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets

from app.core.database import ROOT, connect
from scripts.core_mysql import encode, decode, shape
from scripts.local_mysql import protect

MIGRATIONS = {
    'platform_core': ROOT/'migrations/platform_core/002_mobile_broker.sql',
    'neorang_narang': ROOT/'migrations/neorang_narang/002_mobile_synthetic.sql',
}
NEW_TABLES = {
    'platform_core': ('mobile_schema_version', 'mobile_logins', 'mobile_consents'),
    'neorang_narang': ('nn_mobile_synthetic',),
}
BASE_MIGRATIONS = {
    'platform_core': ROOT/'migrations/platform_core/001_pc_auth.sql',
    'neorang_narang': ROOT/'migrations/neorang_narang/001_initial.sql',
}


def table_name(sql):
    match = re.match(r'CREATE TABLE (?:IF NOT EXISTS )?([a-z_]+)', sql)
    return match[1] if match else None


def statements(source):
    clean = re.sub(r'--[^\n]*', '', source)
    return [s.strip() for s in clean.split(';') if s.strip() and not s.strip().upper().startswith('USE ')]


def inventory(connection, database):
    if database not in MIGRATIONS:
        raise ValueError('Unsupported migration database')
    with connection.cursor() as c:
        c.execute(f'USE `{database}`')
        c.execute('SHOW TABLES')
        tables = sorted(next(iter(row.values())) for row in c.fetchall())
        result = {}
        for table in tables:
            if not re.fullmatch(r'[a-z_]+', table):
                raise ValueError('Unsupported table name')
            c.execute(f'SELECT * FROM `{table}`')
            result[table] = {'schema': shape(connection, table), 'rows': sorted(c.fetchall(), key=repr)}
        return result


def validate_versions(snapshot):
    marker = snapshot['platform_core'].get('mobile_schema_version')
    if marker and marker['rows'] not in ([], [{'version': 1}]):
        raise ValueError('Unknown mobile schema version')


def validate_existing(snapshot, expected):
    validate_versions(snapshot)
    for database, tables in expected.items():
        for table, canonical in tables.items():
            existing = snapshot[database].get(table)
            if existing is None and table not in NEW_TABLES[database]:
                raise ValueError('Required v1 table missing')
            if existing is not None and existing['schema'] != canonical:
                raise ValueError('Mobile schema shape mismatch')


def apply(*, backup_directory, acknowledged):
    if not acknowledged:
        raise ValueError('Backup/restore rehearsal and stopped API acknowledgement required')
    # Credentials are read by the existing restricted local connector, never argv.
    directory = Path(backup_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    protect(directory)
    with connect(admin=True) as connection, connection.cursor() as c:
        c.execute('SELECT GET_LOCK(%s,10) AS acquired', ('jesuslife.mobile.migration',))
        if c.fetchone()['acquired'] != 1:
            raise RuntimeError('Migration lock unavailable')
        try:
            snapshot = {database: inventory(connection, database) for database in MIGRATIONS}
            if [r['version'] for r in snapshot['platform_core']['core_schema_version']['rows']] != [1]:
                raise ValueError('Core v1 required')
            if [r['version'] for r in snapshot['neorang_narang']['nn_schema_version']['rows']] != [1]:
                raise ValueError('Product v1 required')
            validate_versions(snapshot)
            backup = directory/'snapshot.json'
            with backup.open('x', encoding='utf-8') as out:
                protect(backup)
                json.dump(snapshot, out, default=encode, sort_keys=True)
            if json.loads(backup.read_text(encoding='utf-8'), object_hook=decode) != snapshot:
                raise RuntimeError('Backup readback mismatch')
            # Derive canonical MySQL shapes in a new, retained layout DB before
            # touching target schemas. Never overwrite or reuse an unknown layout.
            layout = 'core_mobile_layout_' + secrets.token_hex(6)
            c.execute(f'CREATE DATABASE `{layout}` CHARACTER SET utf8mb4')
            c.execute(f'USE `{layout}`')
            expected = {}
            for database, path in MIGRATIONS.items():
                expected[database] = {}
                # Derive v1 shapes from source, not from potentially unknown
                # target accounts DDL. No target DDL has been issued yet.
                for source in (BASE_MIGRATIONS[database], path):
                    for sql in statements(source.read_text(encoding='utf-8')):
                        table = table_name(sql)
                        if table is None:
                            continue
                        c.execute(sql)
                        expected[database][table] = shape(connection, table)
            # Inspect BOTH schemas before any target DDL. A bad product table
            # must not leave newly created Core tables (or vice versa).
            validate_existing(snapshot, expected)
            for database, path in MIGRATIONS.items():
                c.execute(f'USE `{database}`')
                existing = snapshot[database]
                for sql in statements(path.read_text(encoding='utf-8')):
                    if not sql.upper().startswith('CREATE TABLE '):
                        continue
                    table = re.match(r'CREATE TABLE ([a-z_]+)', sql).group(1)
                    if table not in existing:
                        c.execute(sql)
                    if shape(connection, table) != expected[database][table]:
                        raise ValueError('Mobile schema shape mismatch')
            # Marker only after all Core AND product tables have correct shapes.
            c.execute('USE platform_core')
            c.execute('INSERT INTO mobile_schema_version (version) SELECT 1 '
                      'WHERE NOT EXISTS (SELECT 1 FROM mobile_schema_version)')
            connection.commit()
            for database, tables in NEW_TABLES.items():
                for table in tables:
                    privileges = 'SELECT' if table == 'mobile_schema_version' else 'SELECT, INSERT, UPDATE'
                    c.execute(f'GRANT {privileges} ON `{database}`.`{table}` TO %s@%s',
                              ('platform_core_app', '%'))
            for database in MIGRATIONS:
                after = inventory(connection, database)
                for table, original in snapshot[database].items():
                    if table not in NEW_TABLES[database] and after[table] != original:
                        raise RuntimeError('Original data changed; stop and inspect retained backup')
            connection.commit()
        finally:
            c.execute('SELECT RELEASE_LOCK(%s)', ('jesuslife.mobile.migration',))
    print('PASS: additive mobile schema and least-table grants applied; backup/layout retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'apply'), default='plan', nargs='?')
    parser.add_argument('--backup-directory')
    parser.add_argument('--ack-stopped-api-and-restore-rehearsal', action='store_true')
    args = parser.parse_args()
    if args.action == 'plan':
        print('AUTHOR_REVIEW_REQUIRED: additive mobile Core/product DDL; no DB accessed')
        for database, path in MIGRATIONS.items():
            print(database + ': ' + path.relative_to(ROOT).as_posix())
        print('Prerequisites: stopped API, protected full backup + isolated restore rehearsal; existing v1 schemas')
        print('Old Core migrate/backup tools exclude mobile tables; use full DB backups after this migration')
        return
    try:
        if not args.backup_directory:
            raise ValueError('Backup directory required')
        apply(backup_directory=args.backup_directory,
              acknowledged=args.ack_stopped_api_and_restore_rehearsal)
    except Exception:
        print('FAIL: mobile migration; details suppressed. Preserve backup and partial additive tables; do not reset records.')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
