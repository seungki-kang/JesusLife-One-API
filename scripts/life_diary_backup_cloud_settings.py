"""Explicit development backup target. No dotenv loading or database access."""
from dataclasses import dataclass
from pathlib import Path
import ssl

ENABLED = 'JESUSLIFE_LD_BACKUP_ENABLED'
PROJECT_NAME = 'jesuslife-api-dev'
PROJECT_REF = 'zfhphrihdyjctbwnnyyx'
POOLER_HOST = 'aws-0-ap-northeast-2.pooler.supabase.com'
ROLE = 'jl_ld_backup_runtime'
KEYS = frozenset({
    ENABLED, 'PROJECT_NAME', 'PROJECT_REF', 'POOLER_HOST', 'SSLROOTCERT',
})


@dataclass(frozen=True, repr=False)
class BackupCloudSettings:
    enabled: bool
    pooler_host: str
    project_ref: str
    certificate: Path


def validate(values):
    failed = False
    try:
        # A dedicated minimal file; credentials and endpoint overrides forbidden.
        if (
            set(values) != KEYS
            or values.get(ENABLED) not in ('0', '1')
            or values.get('PROJECT_NAME') != PROJECT_NAME
            or values.get('PROJECT_REF') != PROJECT_REF
            or values.get('POOLER_HOST') != POOLER_HOST
        ):
            raise ValueError()
        raw = values.get('SSLROOTCERT')
        if not isinstance(raw, str) or not raw or raw.strip() != raw:
            raise ValueError()
        certificate = Path(raw)
        if not certificate.is_absolute() or not certificate.is_file():
            raise ValueError()
        # Validate CA parsing as well as existence. No network connection.
        ssl.create_default_context(cafile=str(certificate))
        result = BackupCloudSettings(
            enabled=values[ENABLED] == '1',
            pooler_host=POOLER_HOST,
            project_ref=PROJECT_REF,
            certificate=certificate,
        )
    except Exception:
        failed = True
    if failed:
        raise ValueError('Invalid dedicated Life Diary backup settings')
    return result
