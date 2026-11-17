"""Run the Windows Life Diary HTTPS callback relay against local PostgreSQL."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit


def build_postgres_app(values, config, dsn, *, provider=None):
    from app.auth0_pc import PcRuntime
    from app.core.postgres import connect_runtime
    from app.core.postgres_mobile_store import PostgresMobileStore
    from app.core.postgres_settings import RUNTIME_DSN, load_postgres_runtime_settings
    from scripts.life_diary_dev import build_app

    postgres_environ = {RUNTIME_DSN: dsn}
    settings = load_postgres_runtime_settings(postgres_environ)
    if urlsplit(settings.dsn).hostname != '127.0.0.1':
        raise ValueError('Local PostgreSQL required')

    store = PostgresMobileStore(
        config.encryption_key,
        config.hmac_key,
        connector=lambda: connect_runtime(postgres_environ),
    )
    app = build_app(values, PcRuntime(config, store=store), provider=provider)
    with store.transaction() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT current_user AS role')
        if cursor.fetchone() != {'role': 'jl_ld_auth_runtime'}:
            raise ValueError('Dedicated Life Diary PostgreSQL role required')
        store.ready(cursor)
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable', action='store_true', required=True)
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--pc-settings', type=Path, required=True)
    parser.add_argument('--postgres-settings', type=Path, required=True)
    parser.add_argument('--check', action='store_true',
                        help='Verify local configuration and database without serving requests')
    args = parser.parse_args(argv)

    try:
        from dotenv import dotenv_values
        from scripts.auth0_pc_settings import validate

        values = dotenv_values(args.settings, interpolate=False)
        config = validate(dotenv_values(args.pc_settings, interpolate=False))
        postgres = dotenv_values(args.postgres_settings, interpolate=False)
        app = build_postgres_app(values, config, postgres.get('JESUSLIFE_LD_AUTH_POSTGRES_DSN'))
    except ImportError:
        print('NOT_READY: PostgreSQL adapter or Windows relay dependency unavailable')
        return 1
    except Exception:
        print('NOT_READY: PostgreSQL login settings, role or schema check failed')
        return 1

    if args.check:
        print('READY: local PostgreSQL Life Diary configuration, role and schema')
        return 0

    import uvicorn
    # Keep the Android-facing port 8000 via adb reverse. The host listens separately.
    uvicorn.run(app, host='127.0.0.1', port=18000, access_log=False, proxy_headers=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
