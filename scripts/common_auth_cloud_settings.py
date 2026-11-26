"""Dedicated development cloud settings. No legacy Core DB configuration."""
import base64
from dataclasses import dataclass, field
from pathlib import Path
import re

from app.core.auth0_poc import PocTokenPolicy

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / '.env.common-auth-cloud'
SETTINGS = DIRECTORY / 'settings.env'
ENABLED = 'JESUSLIFE_COMMON_AUTH_ENABLED'
ORIGIN = 'http://127.0.0.1:8000'
CALLBACK = ORIGIN + '/api/v1/auth/callback/web'
AUDIENCE = 'https://api.jesuslife.example/poc'


@dataclass(frozen=True, repr=False)
class CloudSettings:
    enabled: bool
    policy: PocTokenPolicy
    client_secret: str = field(repr=False)
    hmac_key: bytes = field(repr=False)
    encryption_key: bytes = field(repr=False)
    pooler_host: str
    project_ref: str
    certificate: Path
    app_id: str = 'churchos'


def validate(values):
    try:
        # This phase validates the ChurchOS browser dev entrypoint only.
        if (values.get(ENABLED) not in ('0', '1')
                or values.get('APP_ID') != 'churchos'
                or values.get('PROJECT_NAME') != 'jesuslife-api-dev'
                or values.get('AUTH0_AUDIENCE') != AUDIENCE
                or values.get('AUTH0_CALLBACK_URL') != CALLBACK
                or not values.get('AUTH0_CLIENT_SECRET')
                or not re.fullmatch(r'aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com', values.get('POOLER_HOST', ''))
                or not re.fullmatch(r'[a-z0-9]{20}', values.get('PROJECT_REF', ''))):
            raise ValueError()
        # A DB password, alternative DSN or legacy endpoint must never silently
        # change which persistence implementation is selected.
        if any(k.startswith(('CORE_DB_', 'MYSQL_', 'PG')) or k.endswith('_DSN')
               or k in ('DB_PASSWORD', 'DATABASE_URL') for k in values):
            raise ValueError()
        hmac_key = base64.b64decode(values['COMMON_TOKEN_HMAC_KEY'], validate=True)
        encryption = base64.b64decode(values['COMMON_TOKEN_ENCRYPTION_KEY'], validate=True)
        if len(hmac_key) != 32 or len(encryption) != 32 or hmac_key == encryption:
            raise ValueError()
        cert = Path(values['SSLROOTCERT'])
        if not cert.is_absolute() or not cert.is_file():
            raise ValueError()
        policy = PocTokenPolicy(values['AUTH0_ISSUER'], AUDIENCE,
                                frozenset({values['AUTH0_CLIENT_ID']}))
        return CloudSettings(values[ENABLED] == '1', policy, values['AUTH0_CLIENT_SECRET'],
                             hmac_key, encryption, values['POOLER_HOST'], values['PROJECT_REF'], cert)
    except Exception:
        pass
    raise ValueError('Invalid common cloud settings')
