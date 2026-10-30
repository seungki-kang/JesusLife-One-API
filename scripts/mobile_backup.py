"""Full two-database backup and fresh-only rehearsal. Default plan is offline.

No resume, target override, DROP, GRANT, key access or decryption support.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DATABASES = ('platform_core', 'neorang_narang')
ACCOUNTS = ('platform_core_app', 'platform_core_migrator', 'nn_app')
FAILURE_STAGES = frozenset(('protect_directory', 'git_ignore', 'db_connect', 'permissions',
                            'capture', 'snapshot_write', 'snapshot_readback', 'restore',
                            'compare', 'result_write'))


def identifier(value):
    if not re.fullmatch(r'[a-z_][a-z_0-9]*', value):
        raise ValueError('Unsupported identifier')
    return '`' + value + '`'


def query(connection, sql, args=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, args)
        return list(cursor.fetchall())


PERMISSION_TARGETS = ('USER_PRIVILEGES', 'SCHEMA_PRIVILEGES', 'TABLE_PRIVILEGES',
                      'COLUMN_PRIVILEGES', 'accounts', 'roles', 'default_roles')
PERMISSION_CODES = frozenset('permissions_query_' + target.lower() for target in PERMISSION_TARGETS) | frozenset((
    'permissions_account_missing', 'permissions_unexpected_host',
    'permissions_roles_present', 'permissions_unclassified'))


class PermissionFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def permission_query(connection, target, sql, args):
    try:
        return query(connection, sql, args)
    except Exception:
        raise PermissionFailure('permissions_query_' + target.lower()) from None


def permissions(connection):
    try:
        return _permissions(connection)
    except PermissionFailure:
        raise
    except Exception:
        raise PermissionFailure('permissions_unclassified') from None


def _permissions(connection):
    # Never use SHOW GRANTS (older servers may include authentication material).
    result = {}
    holders = tuple("'" + user + "'@'%'" for user in ACCOUNTS)
    for view in ('USER_PRIVILEGES', 'SCHEMA_PRIVILEGES', 'TABLE_PRIVILEGES', 'COLUMN_PRIVILEGES'):
        result[view] = permission_query(connection, view, 'SELECT * FROM information_schema.' + view +
                             ' WHERE GRANTEE IN (%s,%s,%s)', holders)
    result['accounts'] = permission_query(connection, 'accounts', 'SELECT User,Host FROM mysql.user WHERE User IN (%s,%s,%s)', ACCOUNTS)
    # Roles are captured separately; effective role expansion requires human review.
    result['roles'] = permission_query(connection, 'roles', 'SELECT * FROM mysql.role_edges WHERE TO_USER IN (%s,%s,%s)', ACCOUNTS)
    result['default_roles'] = permission_query(connection, 'default_roles', 'SELECT * FROM mysql.default_roles WHERE USER IN (%s,%s,%s)', ACCOUNTS)
    if any(row['Host'] != '%' for row in result['accounts']):
        raise PermissionFailure('permissions_unexpected_host')
    if result['roles'] or result['default_roles']:
        raise PermissionFailure('permissions_roles_present')
    if {row['User'] for row in result['accounts']} != set(ACCOUNTS):
        raise PermissionFailure('permissions_account_missing')
    for rows in result.values():
        rows.sort(key=lambda row: repr(sorted(row.items())))
    return result


def capture(connection, database):
    identifier(database)
    tables = query(connection, 'SELECT TABLE_NAME, TABLE_TYPE, ENGINE FROM information_schema.tables '
                   'WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME', (database,))
    if not tables or any(t['TABLE_TYPE'] != 'BASE TABLE' or t['ENGINE'] != 'InnoDB' for t in tables):
        raise ValueError('Only nonempty InnoDB schemas supported')
    for view, column in (('TRIGGERS', 'TRIGGER_SCHEMA'), ('ROUTINES', 'ROUTINE_SCHEMA'), ('EVENTS', 'EVENT_SCHEMA')):
        if query(connection, f'SELECT * FROM information_schema.{view} WHERE {column}=%s', (database,)):
            raise ValueError('Unsupported executable schema object')
    result = {}
    for item in tables:
        table = item['TABLE_NAME']
        name = identifier(database) + '.' + identifier(table)
        ddl = query(connection, 'SHOW CREATE TABLE ' + name)[0]['Create Table']
        rows = query(connection, 'SELECT * FROM ' + name)
        foreign = query(connection, 'SELECT CONSTRAINT_NAME,COLUMN_NAME,ORDINAL_POSITION,'
                        'REFERENCED_TABLE_SCHEMA,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME '
                        'FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s '
                        'AND REFERENCED_TABLE_NAME IS NOT NULL ORDER BY CONSTRAINT_NAME,ORDINAL_POSITION',
                        (database, table))
        for fk in foreign:
            if fk['REFERENCED_TABLE_SCHEMA'] != database:
                raise ValueError('Cross-schema foreign key requires separate design')
            fk['REFERENCED_TABLE_SCHEMA'] = 'SELF'
        result[table] = {'schema': ddl, 'rows': rows, 'foreign_keys': foreign}
    return result


def order_tables(tables):
    pending = set(tables)
    ordered = []
    while pending:
        ready = sorted(t for t in pending if all(
            f['REFERENCED_TABLE_NAME'] in ordered for f in tables[t]['foreign_keys']))
        if not ready:
            raise ValueError('Unsupported cyclic or missing foreign key dependency')
        ordered.extend(ready)
        pending.difference_update(ready)
    return ordered


def restore(connection, snapshot, *, token=None):
    # New name on EVERY call; never accept a destination from a file or argv.
    token = token or secrets.token_hex(16)
    if not re.fullmatch('[a-f0-9]{32}', token):
        raise ValueError('Invalid run token')
    targets = {db: 'jl_rehearsal_' + token + '_' + str(i) for i, db in enumerate(DATABASES)}
    # No IF NOT EXISTS; on collision or lost CREATE response, abort immediately.
    # All databases must be confirmed created before any USE / table writes.
    with connection.cursor() as cursor:
        for target in targets.values():
            cursor.execute('CREATE DATABASE ' + identifier(target) + ' CHARACTER SET utf8mb4')
        cursor.execute('SET SESSION FOREIGN_KEY_CHECKS=1')
        for db in DATABASES:
            cursor.execute('USE ' + identifier(targets[db]))
            for table in order_tables(snapshot[db]):
                item = snapshot[db][table]
                ddl = item['schema']
                # SHOW CREATE base-table SQL only; reject executable suffixes and
                # qualified references so no statement can escape the fresh DB.
                if (not ddl.startswith('CREATE TABLE ' + identifier(table) + ' (')
                        or any(s in ddl for s in (';', '/*', '--', '.`'))
                        or re.search(r'REFERENCES\s+[^`]', ddl)):
                    raise ValueError('Unsupported backup DDL')
                cursor.execute(ddl)
                for row in item['rows']:
                    columns = ','.join(identifier(c) for c in row)
                    cursor.execute('INSERT INTO ' + identifier(table) + ' (' + columns + ') VALUES (' +
                                   ','.join('%s' for _ in row) + ')', tuple(row.values()))
    connection.commit()
    return targets


def equivalent(left, right):
    # Multiset comparison preserves duplicate rows without depending on row order.
    from scripts.core_mysql import encode
    return Counter(json.dumps(row, default=encode, sort_keys=True) for row in left) == Counter(
        json.dumps(row, default=encode, sort_keys=True) for row in right)


def compare(expected, actual):
    if set(expected) != set(actual):
        raise ValueError('Table inventory mismatch')
    for table, item in expected.items():
        other = actual[table]
        if (item['schema'] != other['schema'] or item['foreign_keys'] != other['foreign_keys']
                or not equivalent(item['rows'], other['rows'])):
            raise ValueError('Schema, foreign key or row mismatch')


def run(directory, evidence):
    stage = 'protect_directory'
    try:
        # Evidence is a protected operator record, never printed; not proof by itself.
        from scripts.core_mysql import encode, decode
        from scripts.local_mysql import protect
        from app.core.database import connect
        directory = Path(directory).resolve()
        directory.relative_to(ROOT / '.mobile-backups')
        if not evidence or not Path(evidence).is_file():
            raise ValueError('Write-stop evidence file required')
        directory.mkdir(parents=True, exist_ok=False)
        protect(directory)
        # Fail closed unless Git excludes the entire output directory.
        stage = 'git_ignore'
        ignored = subprocess.run(['git', 'check-ignore', '-q', '--', str(directory / 'snapshot.json')],
                                 cwd=ROOT, capture_output=True)
        if ignored.returncode:
            raise ValueError('Backup directory must be Git ignored')
        stage = 'db_connect'
        with connect(admin=True) as connection:
            # One consistent snapshot across both InnoDB schemas, no reconnect.
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            stage = 'permissions'
            before_permissions = permissions(connection)
            stage = 'capture'
            snapshot = {db: capture(connection, db) for db in DATABASES}
            connection.rollback()
            for tables in snapshot.values():
                order_tables(tables)
            stage = 'snapshot_write'
            path = directory / 'snapshot.json'
            with path.open('x', encoding='utf-8') as output:
                protect(path)
                json.dump({'databases': snapshot, 'permissions': before_permissions}, output, default=encode)
            stage = 'snapshot_readback'
            saved = json.loads(path.read_text(encoding='utf-8'), object_hook=decode)
            if saved != {'databases': snapshot, 'permissions': before_permissions}:
                raise ValueError('Backup readback mismatch')
            # Journal intended names BEFORE CREATE; lost responses leave inspectable
            # retained resources. No automatic cleanup or resume exists.
            stage = 'restore'
            token = secrets.token_hex(16)
            with (directory / 'attempt.json').open('x', encoding='utf-8') as output:
                protect(directory / 'attempt.json')
                json.dump({'token': token, 'status': 'attempt; completion unconfirmed'}, output)
            targets = restore(connection, saved['databases'], token=token)
            for db in DATABASES:
                for source in (targets[db], db):
                    stage = 'capture'
                    actual = capture(connection, source)
                    stage = 'compare'
                    compare(snapshot[db], actual)
            stage = 'permissions'
            if not equivalent([before_permissions], [permissions(connection)]):
                raise ValueError('Account privileges changed')
            stage = 'result_write'
            with (directory / 'result.json').open('x', encoding='utf-8') as output:
                protect(directory / 'result.json')
                json.dump({'data': 'PASS', 'schema': 'PASS', 'foreign_keys': 'PASS',
                           'permissions_unchanged': 'PASS', 'decrypt': 'NOT_RUN',
                           'write_stop_independently_verified': 'NOT_RUN', 'targets': targets}, output)
            stage = 'db_connect'
    except Exception as error:
        # Preserve exception types for callers; the CLI emits only allowlisted labels.
        error.mobile_backup_stage = stage
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('plan', 'rehearse'), default='plan')
    parser.add_argument('--directory')
    parser.add_argument('--write-stop-evidence')
    args = parser.parse_args(argv)
    if args.action == 'plan':
        print('PLAN: platform_core + neorang_narang; no configuration or DB access')
        print('Fresh-only retained restore; schema/data/FK and separate privilege inventory; decryption NOT_RUN')
        return 0
    try:
        if not args.directory:
            raise ValueError('New backup directory required')
        run(args.directory, args.write_stop_evidence)
    except Exception as error:
        stage = getattr(error, 'mobile_backup_stage', 'protect_directory')
        if stage == 'permissions':
            code = getattr(error, 'code', None)
            print(code if isinstance(code, str) and code in PERMISSION_CODES else 'permissions_unclassified')
        else:
            print(stage if isinstance(stage, str) and stage in FAILURE_STAGES else 'protect_directory')
        return 1
    print('PASS: MySQL schema/data/FK comparison; account privileges unchanged; decryption NOT_RUN')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
