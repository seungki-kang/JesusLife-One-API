"""ChurchOS read routes for explicit application registration."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import AuthContext
from app.modules.churchos.membership import MembershipUnavailable, read_membership


class MembershipResponse(BaseModel):
    church_id: UUID
    permissions: list[str]


def create_membership_router(authenticate, connect):
    router = APIRouter(prefix='/api/v1/churches')

    @router.get('/{church_id}/membership', response_model=MembershipResponse)
    def get_membership(church_id: UUID, user: AuthContext = Depends(authenticate)):
        try:
            permission = read_membership(connect, account_id=user.sub, church_id=church_id)
        except MembershipUnavailable:
            raise HTTPException(503, 'Church membership unavailable') from None
        if permission is None:
            raise HTTPException(403, 'Access denied')
        return MembershipResponse(
            church_id=church_id,
            permissions=['memberships:manage'] if permission else [],
        )

    return router
