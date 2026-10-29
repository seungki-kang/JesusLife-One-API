"""Explicit local administration. Never print configuration, SQL, dumps or exceptions."""
import argparse
import os
import re
from pathlib import Path
import secrets
import subprocess
import tempfile

from app.core.database import ROOT, connect, settings

DATABASES = ('neorang_narang', 'life_diary')


def protect(path):
    if os.name == 'nt':
        output = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, check=True).stdout
        identity = '*' + re.search(rb'S-1-\d+(?:-\d+)+', output).group().decode('ascii')
        # Files may be created by Codex's sandbox identity. Also allow the workspace owner.
        owner = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             "([System.Security.Principal.NTAccount](Get-Acl -LiteralPath .).Owner).Translate([System.Security.Principal.SecurityIdentifier]).Value"],
            cwd=ROOT, capture_output=True, check=True).stdout
        owner_identity = '*' + re.search(rb'S-1-\d+(?:-\d+)+', owner).group().decode('ascii')
        suffix = ':(OI)(CI)F' if path.is_dir() else ':F'
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', identity + suffix, owner_identity + suffix],
                       capture_output=True, check=True)
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def prepare():
    path = ROOT / '.env'
    # Exclusive creation prevents accidentally changing credentials for an existing volume.
    with path.open('x', encoding='utf-8') as output:
        protect(path)
        output.write('COMPLETION_STORE=mysql\nMYSQL_HOST=127.0.0.1\nMYSQL_PORT=3307\n'
                     'NN_DB=neorang_narang\nNN_DB_USER=nn_app\n'
                     'LIFE_DIARY_DB=life_diary\nLIFE_DIARY_DB_USER=life_diary_app\n')
        for key in ('MYSQL_ROOT_PASSWORD', 'NN_DB_PASSWORD', 'LIFE_DIARY_DB_PASSWORD'):
            output.write(f'{key}={secrets.token_hex(32)}\n')


def migrate(connection):
    # Version 1 is additive and restartable after any individual DDL statement.
    source = ROOT / 'migrations/neorang_narang/001_initial.sql'
    with connection.cursor() as cursor:
        cursor.execute('SELECT GET_LOCK(%s, 10) AS acquired', ('jesuslife.nn.migration',))
        if cursor.fetchone()['acquired'] != 1:
            raise RuntimeError('Migration lock unavailable')
        try:
            cursor.execute("SELECT COUNT(*) AS count FROM information_schema.tables "
                           "WHERE table_schema=DATABASE() AND table_name='nn_schema_version'")
            if cursor.fetchone()['count']:
                cursor.execute('SELECT version FROM nn_schema_version ORDER BY version')
                if [row['version'] for row in cursor.fetchall()] not in ([], [1]):
                    raise RuntimeError('Unsupported schema version')
            for statement in source.read_text(encoding='utf-8').split(';'):
                if statement.strip():
                    cursor.execute(statement)
            cursor.execute('SELECT version FROM nn_schema_version ORDER BY version')
            if [row['version'] for row in cursor.fetchall()] != [1]:
                raise RuntimeError('Unsupported schema version')
            connection.commit()
        finally:
            cursor.execute('SELECT RELEASE_LOCK(%s)', ('jesuslife.nn.migration',))


def bootstrap():
    config = settings()
    with connect(admin=True) as connection:
        with connection.cursor() as cursor:
            for database in DATABASES:
                cursor.execute(f'CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
            for user, key in (('nn_app', 'NN_DB_PASSWORD'), ('life_diary_app', 'LIFE_DIARY_DB_PASSWORD')):
                password = config[key]
                if not password:
                    raise RuntimeError('Missing local password')
                cursor.execute('CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s', (user, '%', password))
                # This script owns only these new accounts. Re-running does not rotate passwords.
            cursor.execute('USE neorang_narang')
        migrate(connection)
        with connection.cursor() as cursor:
            # No DDL, physical DELETE, grant option, or cross-product permissions for apps.
            for table in ('nn_completion_owners', 'nn_completion_records'):
                cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON neorang_narang.{table} TO %s@%s', ('nn_app', '%'))
            cursor.execute('GRANT SELECT ON neorang_narang.nn_schema_version TO %s@%s', ('nn_app', '%'))
            # No life_diary business tables are created in this task.
            cursor.execute('GRANT SELECT, INSERT, UPDATE ON life_diary.* TO %s@%s', ('life_diary_app', '%'))
        connection.commit()


def docker(*arguments, input=None):
    result = subprocess.run(['docker', *arguments], input=input, capture_output=True)
    if result.returncode:
        raise RuntimeError('Docker operation failed')
    return result.stdout


def snapshot(connection):
    with connection.cursor() as cursor:
        result = {}
        for table, order in (('nn_schema_version', 'version'), ('nn_completion_owners', 'owner_sub'),
                             ('nn_completion_records', 'owner_sub, record_id')):
            cursor.execute(f'SELECT * FROM {table} ORDER BY {order}')
            result[table] = cursor.fetchall()
        return result


def backup_verify():
    # Only the new local synthetic database; no access to MariaDB or real user data.
    dump = docker('exec', 'jesuslife-local-mysql', 'sh', '-c',
                  'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysqldump -uroot '
                  '--single-transaction --no-tablespaces --set-gtid-purged=OFF '
                  '--skip-add-drop-table --skip-comments --skip-dump-date neorang_narang')
    print('PASS: synthetic dump captured without console output')
    directory = Path(tempfile.mkdtemp(prefix='jesuslife-mysql-backup-'))
    protect(directory)
    (directory / 'neorang_narang.sql').write_bytes(dump)
    restore = 'nn_restore_' + secrets.token_hex(6)
    with connect(admin=True) as connection:
        before = snapshot_for(connection, 'neorang_narang')
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{restore}` CHARACTER SET utf8mb4')
        docker('exec', '-i', 'jesuslife-local-mysql', 'sh', '-c',
               f'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -uroot {restore}', input=dump)
        print('PASS: isolated restore loaded')
        after = snapshot_for(connection, restore)
        if before != after:
            raise RuntimeError('Backup verification failed')
    # Keep backup and restored DB; never automatically DROP or delete a volume.
    (ROOT / '.env.backup-location').write_text(str(directory), encoding='utf-8')
    print('PASS: protected backup and isolated restore match (including versions and tombstones)')


def snapshot_for(connection, database):
    with connection.cursor() as cursor:
        cursor.execute(f'USE `{database}`')
    return snapshot(connection)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'bootstrap', 'migrate', 'backup-verify'))
    action = parser.parse_args().action
    try:
        if action == 'prepare':
            prepare()
        elif action == 'bootstrap':
            bootstrap()
        elif action == 'migrate':
            with connect(admin=True, database='neorang_narang') as connection:
                migrate(connection)
        else:
            backup_verify()
        print(f'PASS: {action}')
    except Exception as error:
        print(f'FAIL: {action} ({type(error).__name__}); details suppressed to protect credentials and records')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
