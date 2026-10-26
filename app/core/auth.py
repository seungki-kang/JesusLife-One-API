"""Provider-neutral identity and ownership boundary; no token verification yet."""

from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field


class AuthContext(BaseModel):
    """Trusted common-account identity, constructed only after authentication.

    UUID shape validation is not authentication. A future verified adapter must
    map provider identities to the common account sub before constructing this.
    Never populate this context from request body, query, or unverified headers.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    sub: UUID = Field(repr=False)


def get_current_user() -> AuthContext:
    """Fail closed until an approved authentication adapter is implemented.

    Tests may use FastAPI dependency_overrides on isolated test applications.
    Production has no fake identity, header shortcut, or configuration bypass.
    """
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_record_owner(*, owner_sub: UUID, current_user: AuthContext) -> None:
    """Check a server-owned record's owner against the authenticated subject.

    The caller must obtain owner_sub from trusted server state, never request
    fields. New records must derive their owner from current_user.sub. This
    guard grants no sharing, church-role, consent, or persistence capabilities.
    """
    if owner_sub != current_user.sub:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
