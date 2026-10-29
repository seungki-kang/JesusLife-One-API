"""Local development configuration. Never render settings or driver exceptions."""
import os
from pathlib import Path

import pymysql
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def settings():
    return {**dotenv_values(ROOT / '.env'), **os.environ}


def connect(*, admin=False, database=None, user=None, password=None):
    config = settings()
    # This connector is approved only for the separate local MySQL, never MariaDB:3306.
    host, port = config.get('MYSQL_HOST', '127.0.0.1'), int(config.get('MYSQL_PORT', '3307'))
    if host != '127.0.0.1' or port != 3307:
        raise ValueError('Unsupported local database endpoint')
    return pymysql.connect(
        host=host, port=port,
        user=user or ('root' if admin else config.get('NN_DB_USER', 'nn_app')),
        password=password if password is not None else config.get(
            'MYSQL_ROOT_PASSWORD' if admin else 'NN_DB_PASSWORD', ''),
        database=database if database is not None else (None if admin else config.get('NN_DB', 'neorang_narang')),
        charset='utf8mb4', autocommit=False, connect_timeout=5,
        read_timeout=10, write_timeout=10, local_infile=False,
        cursorclass=pymysql.cursors.DictCursor,
        init_command="SET time_zone = '+00:00'",
    )
