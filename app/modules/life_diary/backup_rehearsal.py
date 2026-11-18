"""Isolated HTTP contract rehearsal. No application installs this router."""
import base64
import binascii
from collections.abc import Callable
from threading import Lock
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from app.modules.neorang_narang.router import SafeValidationRoute


class BackupPayload(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    format_version: int = Field(strict=True, ge=1, le=1)
    ciphertext: str = Field(min_length=4, max_length=65536)


class MemoryBackupStore:
    def __init__(self):
        self.entries: dict[tuple[UUID, UUID], BackupPayload] = {}
        self.lock = Lock()

    def save(self, owner, entry_id, payload):
        with self.lock:
            key = (owner, entry_id)
            existing = self.entries.get(key)
            if existing is None:
                self.entries[key] = payload
                return True
            if existing != payload:
                raise HTTPException(409, 'Backup entry already exists')
            return False

    def load(self, owner, entry_id):
        with self.lock:
            return self.entries.get((owner, entry_id))


def rehearsal_router(
    authenticated_owner: Callable[[Request], UUID],
    backup_enabled: Callable[[UUID], bool],
    *,
    store=None,
) -> APIRouter:
    """Build an explicitly installed rehearsal router."""
    router = APIRouter(prefix='/api/v1/mobile/life-diary/backup/entries',
                       route_class=SafeValidationRoute)
    if store is None:
        store = MemoryBackupStore()

    def owner_for(request: Request) -> UUID:
        owner = authenticated_owner(request)
        if not backup_enabled(owner):
            raise HTTPException(403, 'Backup is disabled')
        return owner

    @router.put('/{entry_id}', response_model=BackupPayload)
    def save(entry_id: UUID, payload: BackupPayload, request: Request, response: Response):
        owner = owner_for(request)
        try:
            decoded = base64.b64decode(payload.ciphertext, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, 'Invalid backup encoding') from None
        if base64.b64encode(decoded).decode('ascii') != payload.ciphertext:
            raise HTTPException(422, 'Invalid backup encoding')

        if store.save(owner, entry_id, payload):
            response.status_code = 201

        response.headers['Cache-Control'] = 'no-store'
        return payload

    @router.get('/{entry_id}', response_model=BackupPayload)
    def load(entry_id: UUID, request: Request, response: Response):
        owner = owner_for(request)
        entry = store.load(owner, entry_id)
        if entry is None:
            raise HTTPException(404, 'Backup entry not found')
        response.headers['Cache-Control'] = 'no-store'
        return entry

    return router
