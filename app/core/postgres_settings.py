"""PostgreSQL configuration only: no dotenv loading, driver or connection I/O."""
from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from urllib.parse import parse_qs, unquote, urlsplit


RUNTIME_DSN = 'JESUSLIFE_POSTGRES_RUNTIME_DSN'
MIGRATION_DSN = 'JESUSLIFE_POSTGRES_MIGRATION_DSN'


class PostgresConfigurationError(ValueError):
    """Safe fixed messages; never include input or parser exceptions."""


@dataclass(frozen=True)
class PostgresSettings:
    purpose: str
    dsn: str = field(repr=False)


def _validate(value):
    # libpq accepts query overrides for credentials, hosts and TLS. Restrict the
    # contract to one URI endpoint plus sslmode so overrides cannot bypass checks.
    valid = False
    identity = None
    try:
        if isinstance(value, str) and value and not any(c.isspace() or ord(c) < 32 for c in value):
            uri = urlsplit(value)
            query = parse_qs(uri.query, keep_blank_values=True, strict_parsing=True)
            mode = query.get('sslmode', [])
            local = uri.hostname in {'localhost', '127.0.0.1', '::1'}
            valid = (
                uri.scheme in {'postgresql', 'postgres'}
                and bool(uri.hostname) and bool(uri.username) and bool(uri.password)
                and bool(uri.path.lstrip('/')) and not uri.fragment
                and (uri.port is None or 1 <= uri.port <= 65535)
                and set(query) <= {'sslmode'}
                and (not mode or len(mode) == 1)
                and (mode in (['require'], ['verify-ca'], ['verify-full'])
                     or (local and (not mode or mode in (['disable'], ['prefer'], ['allow']))))
            )
            identity = (uri.hostname, uri.port or 5432, unquote(uri.username or ''), unquote(uri.path))
    except (ValueError, TypeError):
        pass
    # Raise outside the parser handler: no raw parser exception in the chain.
    if not valid:
        raise PostgresConfigurationError('Invalid PostgreSQL DSN or TLS configuration')
    return identity


def _load(purpose, key, other_key, environ):
    config = os.environ if environ is None else environ
    value = config.get(key)
    if not value:
        raise PostgresConfigurationError('Required PostgreSQL DSN is missing')
    identity = _validate(value)
    other = config.get(other_key)
    if other and identity == _validate(other):
        raise PostgresConfigurationError('PostgreSQL runtime and migration credentials must be separate')
    return PostgresSettings(purpose=purpose, dsn=value)


def load_postgres_runtime_settings(environ: Mapping[str, str] | None = None):
    """Load only runtime credentials; migration credentials are not required."""
    return _load('runtime', RUNTIME_DSN, MIGRATION_DSN, environ)


def load_postgres_migration_settings(environ: Mapping[str, str] | None = None):
    """Load only migration credentials in a separately provisioned environment."""
    return _load('migration', MIGRATION_DSN, RUNTIME_DSN, environ)
