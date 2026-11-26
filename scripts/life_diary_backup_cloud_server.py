"""Explicit development server with separate cloud auth and backup roles."""
import argparse
import json
import os
from pathlib import Path
import socket
import ssl
import sys
from uuid import uuid4

from dotenv import dotenv_values
import uvicorn

from app.core.common_mobile_auth import CommonMobileAuthStore
from app.modules.life_diary.completed_backup_store import CompletedBackupStore
from app.modules.life_diary.completed_backup_transactions import CompletedBackupTransactions
from scripts.common_auth_cloud import connector as auth_connector
from scripts.life_diary_backup_cloud import connector as backup_connector
from scripts.life_diary_backup_cloud_settings import validate as validate_backup
from scripts.life_diary_common_cloud import (
    APP_ID, create_app, probe, validate_settings,
)


def load_settings(auth_path, backup_path):
    auth = validate_settings(dotenv_values(auth_path, interpolate=False))
    backup = validate_backup(dotenv_values(backup_path, interpolate=False))
    if not auth.enabled or not backup.enabled:
        raise ValueError()
    if (auth.pooler_host != backup.pooler_host
            or auth.project_ref != backup.project_ref):
        raise ValueError()
    ssl.create_default_context(cafile=str(auth.certificate))
    return auth, backup


def read_passwords(stream):
    supplied = stream.readline(16385)
    if not supplied or len(supplied) > 16384:
        raise ValueError()
    passwords = json.loads(supplied.decode('utf-8'))
    if not isinstance(passwords, dict):
        raise ValueError()
    if set(passwords) != {'auth_password', 'backup_password'}:
        raise ValueError()
    if any(not isinstance(value, str) or not value
           for value in passwords.values()):
        raise ValueError()
    return passwords


def probe_backup(transactions):
    # Read-only readiness check; never grants consent or writes diary data.
    with transactions(uuid4()) as db:
        flags = db.execute(
            'SELECT count(*) AS total, '
            'bool_and(c.relrowsecurity AND c.relforcerowsecurity) AS forced '
            'FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace '
            "WHERE n.nspname='jl_ld_backup' AND "
            "c.relname IN ('schema_version','consent','entries')"
        ).fetchone()
        if flags != {'total': 3, 'forced': True}:
            raise ValueError()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'probe', 'serve'))
    parser.add_argument('--auth-settings', type=Path, required=True)
    parser.add_argument('--backup-settings', type=Path, required=True)
    parser.add_argument('--allow-cloud-backup', action='store_true')
    args = parser.parse_args()
    stage = 'INPUT'
    try:
        if not args.allow_cloud_backup:
            raise ValueError()
        if any(key.upper().startswith('PG') for key in os.environ):
            raise ValueError()

        stage = 'SETTINGS'
        auth, backup = load_settings(args.auth_settings, args.backup_settings)
        if args.action == 'check':
            print('PASS: enabled cloud settings and CA format; no DB connection')
            return

        if args.action == 'serve':
            stage = 'PORT'
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 8000))

        stage = 'PASSWORD_INPUT'
        passwords = read_passwords(sys.stdin.buffer)

        stage = 'BACKUP_READINESS'
        transactions = CompletedBackupTransactions(
            connector=backup_connector(backup, passwords['backup_password']))
        probe_backup(transactions)

        stage = 'AUTH_READINESS'
        auth_store = CommonMobileAuthStore(
            auth.encryption_key, auth.hmac_key,
            connector=auth_connector(auth, passwords['auth_password']),
            app_id=APP_ID)
        probe(auth_store, auth)
        print('PASS: common auth and cloud backup readiness; development only',
              flush=True)
        if args.action == 'probe':
            return

        stage = 'APP_BUILD'
        app = create_app(
            auth, auth_store,
            backup_store=CompletedBackupStore(transaction=transactions))
        stage = 'SERVER_START'
        uvicorn.run(
            app, host='127.0.0.1', port=8000, access_log=False,
            proxy_headers=False, log_level='critical')
    except KeyboardInterrupt:
        print('STOPPED: cloud backup development server')
    except Exception:
        raise SystemExit(
            'BLOCKED: stage=' + stage + '; details suppressed; no fallback'
        ) from None


if __name__ == '__main__':
    main()