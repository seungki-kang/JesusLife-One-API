"""Explicit cloud RLS verification with synthetic data and mandatory rollback."""
import argparse
from getpass import getpass
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from psycopg.errors import InsufficientPrivilege

from app.modules.life_diary.completed_backup_transactions import CompletedBackupTransactions
from scripts.life_diary_backup_cloud import connector
from scripts.life_diary_backup_cloud_settings import validate


class RollbackVerification(Exception):
    pass


def require(condition):
    if not condition:
        raise ValueError('Isolation verification failed')


def context(db, account, app='life_diary'):
    db.execute(
        "SELECT set_config('jesuslife.backup_app_id', %s, true)",
        (app,))
    db.execute(
        "SELECT set_config('jesuslife.backup_account_id', %s, true)",
        (str(account),))


def count(db, table, account):
    # Table names are supplied only by the fixed calls below.
    return db.execute(
        'SELECT count(*) AS total FROM jl_ld_backup.' + table
        + ' WHERE account_id=%s', (account,)).fetchone()['total']


def denied(db, query, parameters):
    try:
        with db.transaction():
            db.execute(query, parameters)
    except InsufficientPrivilege:
        return
    raise ValueError('Expected RLS rejection')


def verify(transactions):
    first, second, backup = uuid4(), uuid4(), uuid4()
    try:
        with transactions(first) as db:
            require(count(db, 'consent', first) == 0)
            require(count(db, 'entries', first) == 0)
            db.execute(
                'INSERT INTO jl_ld_backup.consent '
                '(account_id,generation,active) VALUES (%s,1,true)',
                (first,))
            db.execute(
                'INSERT INTO jl_ld_backup.entries '
                '(account_id,generation,backup_id,format_version,ciphertext) '
                'VALUES (%s,1,%s,1,%s)',
                (first, backup, b'x' * 29))
            require(count(db, 'consent', first) == 1)
            require(count(db, 'entries', first) == 1)

            context(db, second)
            require(count(db, 'consent', first) == 0)
            require(count(db, 'entries', first) == 0)
            db.execute(
                'INSERT INTO jl_ld_backup.consent '
                '(account_id,generation,active) VALUES (%s,1,true)',
                (second,))
            require(count(db, 'consent', second) == 1)

            denied(db,
                'INSERT INTO jl_ld_backup.consent '
                '(account_id,generation,active) VALUES (%s,1,true)',
                (first,))
            denied(db,
                'INSERT INTO jl_ld_backup.entries '
                '(account_id,generation,backup_id,format_version,ciphertext) '
                'VALUES (%s,1,%s,1,%s)',
                (first, uuid4(), b'y' * 29))

            require(db.execute(
                'UPDATE jl_ld_backup.consent SET active=false '
                'WHERE account_id=%s', (first,)).rowcount == 0)
            require(db.execute(
                'DELETE FROM jl_ld_backup.entries WHERE account_id=%s',
                (first,)).rowcount == 0)

            context(db, first, 'neorang_narang')
            require(count(db, 'consent', first) == 0)
            require(count(db, 'entries', first) == 0)

            context(db, '', '')
            require(count(db, 'consent', first) == 0)
            require(count(db, 'entries', first) == 0)

            context(db, first)
            require(count(db, 'entries', first) == 1)
            require(db.execute(
                'SELECT active FROM jl_ld_backup.consent '
                'WHERE account_id=%s', (first,)).fetchone()['active'] is True)
            raise RollbackVerification()
    except RollbackVerification:
        pass

    # Independent transactions confirm that neither synthetic account persisted.
    for account in (first, second):
        with transactions(account) as db:
            require(count(db, 'consent', account) == 0)
            require(count(db, 'entries', account) == 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-settings', type=Path, required=True)
    parser.add_argument('--allow-cloud-isolation-test', action='store_true')
    args = parser.parse_args()
    stage = 'INPUT'
    try:
        if not args.allow_cloud_isolation_test:
            raise ValueError()
        stage = 'SETTINGS'
        config = validate(dotenv_values(args.backup_settings, interpolate=False))
        if not config.enabled:
            raise ValueError()
        stage = 'PASSWORD'
        password = getpass('Dedicated backup role password (hidden): ')
        stage = 'ISOLATION'
        verify(CompletedBackupTransactions(
            connector=connector(config, password)))
        print('PASS: cloud RLS isolation; synthetic changes rolled back')
    except KeyboardInterrupt:
        raise SystemExit('STOPPED: cloud isolation verification') from None
    except Exception:
        raise SystemExit(
            'BLOCKED: stage=' + stage + '; details suppressed') from None


if __name__ == '__main__':
    main()