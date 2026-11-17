"""Explicit loopback-only Life Diary development server. No import-time I/O."""
import argparse
from dataclasses import replace

CALLBACK = 'https://unwary-founder-peculiar.ngrok-free.dev/api/v1/auth/callback/life-diary/android'


def build_app(values, parent, *, provider=None):
    """Validate server-owned settings before enabling the existing factory."""
    required = ('LD_AUTH0_CLIENT_ID', 'LD_AUTH0_CLIENT_SECRET', 'NN_AUTH0_CLIENT_ID')
    if (values.get('LD_AUTH0_APPLICATION') != 'jl-life-diary-dev'
            or values.get('LD_AUTH0_CALLBACK_URL') != CALLBACK
            or any(not isinstance(values.get(k), str) or not values[k].strip()
                   or values[k] != values[k].strip() for k in required)
            or values['LD_AUTH0_CLIENT_ID'] in (
                parent.config.policy.client_ids | {values['NN_AUTH0_CLIENT_ID']})):
        raise ValueError('Invalid Life Diary development settings')
    from app.auth0_mobile import create_development_app
    config = replace(parent.config, client_secret=values['LD_AUTH0_CLIENT_SECRET'],
                     policy=replace(parent.config.policy,
                                    client_ids=frozenset({values['LD_AUTH0_CLIENT_ID']})))
    return create_development_app(parent, life_diary_config=config, enabled=True,
                                  provider=provider, callback_uri=CALLBACK)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable', action='store_true', required=True)
    parser.add_argument('--settings', required=True, help='Explicit Life Diary settings file')
    parser.add_argument('--pc-settings', help='PC settings file; defaults to worktree .env.auth0-pc')
    args = parser.parse_args(argv)
    try:
        from dotenv import dotenv_values
        from scripts.auth0_pc_settings import PATH, validate
        values = dotenv_values(args.settings, interpolate=False)
        config = validate(dotenv_values(args.pc_settings or PATH, interpolate=False))
        from app.auth0_pc import PcRuntime
        from app.core.mobile_store import MobileCoreStore
        store_options = {}
        if args.pc_settings:
            # Keep the selected credentials for later DB requests too. The default
            # Core connector otherwise reopens the worktree's .env.auth0-pc.
            from app.core.database import connect

            def selected_core_connection():
                return connect(database='platform_core', user='platform_core_app',
                               password=config.database_password)

            store_options['connector'] = selected_core_connection
        parent = PcRuntime(config, store=MobileCoreStore(config.encryption_key, config.hmac_key,
                                                        **store_options))
        app = build_app(values, parent)
    except Exception:
        print('NOT_READY: development settings missing or invalid; details suppressed')
        return 1
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000, access_log=False, proxy_headers=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
