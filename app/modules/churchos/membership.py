"""Read the authenticated account's ChurchOS membership from its PostgreSQL source."""

from uuid import UUID

import psycopg

from app.core.postgres import PostgresConnectionError
from app.core.postgres_settings import PostgresConfigurationError


class MembershipUnavailable(RuntimeError):
    """Safe failure returned when the membership source cannot be queried."""


def read_membership(connect, *, account_id: UUID, church_id: UUID) -> bool | None:
    """Return the optional role-management permission for an active membership."""
    try:
        with connect() as db:
            db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY')
            db.execute(
                "SELECT set_config('jesuslife.account_id', %s, true), "
                "set_config('jesuslife.church_id', %s, true)",
                (str(account_id), str(church_id)),
            )
            row = db.execute(
                'SELECT can_manage_memberships FROM jl_churchos.memberships '
                'WHERE account_id=%s AND church_id=%s AND revoked_at IS NULL',
                (account_id, church_id),
            ).fetchone()
            return None if row is None else row[0]
    except (PostgresConnectionError, PostgresConfigurationError, psycopg.Error):
        pass
    raise MembershipUnavailable('Church membership unavailable')
