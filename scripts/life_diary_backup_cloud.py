"""Dedicated cloud backup connector; no automatic connection or migration."""
import os
import ssl

import psycopg

from app.core.postgres import PostgresConnectionError
from scripts.life_diary_backup_cloud_settings import (
    BackupCloudSettings, POOLER_HOST, PROJECT_REF, ROLE,
)


def connector(config, password, *, driver=None):
    if (
        not isinstance(config, BackupCloudSettings)
        or not config.enabled
        or config.pooler_host != POOLER_HOST
        or config.project_ref != PROJECT_REF
        or not isinstance(password, str)
        or not password
    ):
        raise ValueError('Explicit dedicated backup enablement and password required')

    connect_driver = driver if driver is not None else psycopg.connect

    def connect():
        failed = False
        try:
            if any(key.upper().startswith('PG') for key in os.environ):
                raise ValueError()
            if not config.certificate.is_absolute() or not config.certificate.is_file():
                raise ValueError()
            ssl.create_default_context(cafile=str(config.certificate))
            return connect_driver(
                host=POOLER_HOST,
                port=5432,
                dbname='postgres',
                user=ROLE + '.' + PROJECT_REF,
                password=password,
                sslmode='verify-full',
                sslrootcert=str(config.certificate),
                connect_timeout=5,
                application_name='jesuslife_ld_backup_dev',
                prepare_threshold=None,
                options='-c timezone=UTC -c statement_timeout=10000 -c lock_timeout=5000',
            )
        except Exception:
            failed = True
        if failed:
            raise PostgresConnectionError('Dedicated backup PostgreSQL connection failed')

    return connect
