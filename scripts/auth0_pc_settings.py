"""Prepare/check local PC PoC settings without rendering any values.

No DB access, Auth0 requests, migrations, server startup or authentication.
The separate app.auth0_pc entry point consumes these explicit local settings.
"""
import argparse
import base64
from dataclasses import dataclass, field
import secrets

from dotenv import dotenv_values

from app.core.auth0_poc import PocTokenPolicy
from app.core.database import ROOT
from scripts.local_mysql import protect

CALLBACK = 'http://127.0.0.1:8000/api/v1/auth/callback/web'
AUDIENCE = 'https://api.jesuslife.example/poc'
PATH = ROOT / '.env.auth0-pc'
REQUIRED = ('AUTH0_ISSUER', 'AUTH0_CLIENT_ID', 'AUTH0_CLIENT_SECRET',
            'CORE_DB_PASSWORD', 'CORE_TOKEN_HMAC_KEY', 'CORE_TOKEN_ENCRYPTION_KEY')


@dataclass(frozen=True, repr=False)
class PcSettings:
    policy: PocTokenPolicy
    client_secret: str = field(repr=False)
    database_password: str = field(repr=False)
    hmac_key: bytes = field(repr=False)
    encryption_key: bytes = field(repr=False)


def validate(values):
    missing = [name for name in REQUIRED if not values.get(name)]
    if missing:
        raise ValueError('Missing setting names: ' + ', '.join(missing))
    fixed = {'AUTH0_AUDIENCE': AUDIENCE, 'AUTH0_CALLBACK_URL': CALLBACK,
             'CORE_DB_HOST': '127.0.0.1', 'CORE_DB_PORT': '3307',
             'CORE_DB_NAME': 'platform_core', 'CORE_DB_USER': 'platform_core_app'}
    if any(values.get(name) != value for name, value in fixed.items()):
        raise ValueError('Invalid fixed PC PoC settings')
    try:
        hmac_key = base64.b64decode(values['CORE_TOKEN_HMAC_KEY'], validate=True)
        encryption_key = base64.b64decode(values['CORE_TOKEN_ENCRYPTION_KEY'], validate=True)
        if len(hmac_key) != 32 or len(encryption_key) != 32 or hmac_key == encryption_key:
            raise ValueError('Invalid key')
        policy = PocTokenPolicy(values['AUTH0_ISSUER'], AUDIENCE,
                                frozenset({values['AUTH0_CLIENT_ID']}))
    except Exception:
        raise ValueError('Invalid local token policy or key format') from None
    return PcSettings(policy, values['AUTH0_CLIENT_SECRET'], values['CORE_DB_PASSWORD'],
                      hmac_key, encryption_key)


def prepare():
    # Never overwrite existing tenant/client/DB credentials or keys.
    with PATH.open('x', encoding='utf-8') as output:
        protect(PATH)
        output.write('# PC Auth0 PoC only. Never paste these contents into chat/logs.\n'
                     'AUTH0_ISSUER=\nAUTH0_CLIENT_ID=\nAUTH0_CLIENT_SECRET=\n'
                     f'AUTH0_AUDIENCE={AUDIENCE}\nAUTH0_CALLBACK_URL={CALLBACK}\n'
                     'CORE_DB_HOST=127.0.0.1\nCORE_DB_PORT=3307\n'
                     'CORE_DB_NAME=platform_core\nCORE_DB_USER=platform_core_app\n'
                     'CORE_DB_PASSWORD=\n')
        for name in ('CORE_TOKEN_HMAC_KEY', 'CORE_TOKEN_ENCRYPTION_KEY'):
            output.write(name + '=' + base64.b64encode(secrets.token_bytes(32)).decode() + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'check'))
    action = parser.parse_args().action
    try:
        if action == 'prepare':
            prepare()
            print('PASS: protected local settings file prepared; values not printed')
        else:
            validate(dotenv_values(PATH, interpolate=False))
            print('PASS: local settings syntax only; Auth0/DB/runtime not verified')
    except FileExistsError:
        print('NOT_CHANGED: local settings file already exists')
        raise SystemExit(1) from None
    except Exception:
        print('NOT_READY: local settings missing/invalid or file protection failed; details suppressed')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
