"""Explicit development server: common cloud auth plus disposable local backup."""
import argparse
import json
import os
from pathlib import Path
import socket
import ssl
import sys
from uuid import uuid4

from dotenv import dotenv_values
import psycopg
import uvicorn

from app.core.common_mobile_auth import CommonMobileAuthStore
from app.modules.life_diary.completed_backup_store import CompletedBackupStore
from app.modules.life_diary.completed_backup_transactions import CompletedBackupTransactions
from scripts.common_auth_cloud import connector
from scripts.life_diary_common_cloud import (
    APP_ID, create_app, probe, validate_settings,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auth-settings', type=Path, required=True)
    parser.add_argument('--backup-port', type=int, required=True)
    parser.add_argument('--allow-isolated-backup', action='store_true')
    args = parser.parse_args()
    stage = 'INPUT'
    try:
        if not args.allow_isolated_backup or not 1 <= args.backup_port <= 65535:
            raise ValueError()
        if any(key.upper().startswith('PG') for key in os.environ):
            raise ValueError()
        # Fail before DB work if another server owns the required callback port.
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 8000))

        supplied = sys.stdin.buffer.readline(16385)
        if len(supplied) > 16384:
            raise ValueError()
        passwords = json.loads(supplied.decode('utf-8'))
        if set(passwords) != {'auth_password', 'backup_password'}:
            raise ValueError()
        if any(not isinstance(value, str) or not value for value in passwords.values()):
            raise ValueError()

        stage = 'AUTH_SETTINGS'
        config = validate_settings(
            dotenv_values(args.auth_settings, interpolate=False))
        if not config.enabled:
            raise ValueError()
        ssl.create_default_context(cafile=str(config.certificate))

        def backup_connector():
            return psycopg.connect(
                host='127.0.0.1', port=args.backup_port, dbname='postgres',
                user='jl_ld_backup_runtime',
                password=passwords['backup_password'],
                sslmode='disable', connect_timeout=5,
                application_name='jesuslife_isolated_backup_dev',
                options='-c statement_timeout=10000 -c lock_timeout=5000',
            )

        stage = 'BACKUP_READINESS'
        transactions = CompletedBackupTransactions(connector=backup_connector)
        # Read-only check with a random synthetic account; no consent is granted.
        with transactions(uuid4()) as db:
            flags = db.execute(
                "SELECT count(*) AS total, "
                "bool_and(c.relrowsecurity AND c.relforcerowsecurity) AS forced "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='jl_ld_backup' AND "
                "c.relname IN ('schema_version','consent','entries')"
            ).fetchone()
            if flags != {'total': 3, 'forced': True}:
                raise ValueError()

        stage = 'AUTH_READINESS'
        auth_store = CommonMobileAuthStore(
            config.encryption_key, config.hmac_key,
            connector=connector(config, passwords['auth_password']), app_id=APP_ID)
        probe(auth_store, config)

        app = create_app(
            config, auth_store,
            backup_store=CompletedBackupStore(transaction=transactions))
        stage = 'SERVER_START'
        print('PASS: common auth and isolated backup readiness; development only',
              flush=True)
        uvicorn.run(
            app, host='127.0.0.1', port=8000, access_log=False,
            proxy_headers=False, log_level='critical')
    except KeyboardInterrupt:
        print('STOPPED: isolated backup development server')
    except Exception:
        raise SystemExit(
            'BLOCKED: stage=' + stage + '; details suppressed; no fallback'
        ) from None


if __name__ == '__main__':
    main()
