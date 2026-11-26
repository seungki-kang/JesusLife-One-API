"""Explicit opt-in backup routes; no automatic DB connection or installation."""
import base64
import binascii
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.modules.neorang_narang.router import SafeValidationRoute

Generation = Annotated[int, Path(ge=1, le=9223372036854775807)]


class CompletedBackupPayload(BaseModel):
    model_config = ConfigDict(
        extra='forbid', frozen=True, hide_input_in_errors=True)
    format_version: int = Field(strict=True, ge=1, le=1)
    ciphertext: str = Field(min_length=40, max_length=65536)


def completed_backup_router(*, authenticated_owner=None, store=None, enabled=False):
    router = APIRouter(
        prefix='/api/v1/mobile/life-diary/backup',
        route_class=SafeValidationRoute)
    if not enabled:
        return router
    if not callable(authenticated_owner) or store is None:
        raise ValueError('Explicit backup authentication and store required')

    @router.post('/consent')
    def grant(request: Request, response: Response):
        owner = authenticated_owner(request)
        generation = store.grant(owner)
        response.headers['Cache-Control'] = 'no-store'
        return {'generation': generation}

    @router.put('/entries/{generation}/{backup_id}')
    def upload(
        generation: Generation, backup_id: UUID,
        payload: CompletedBackupPayload, request: Request, response: Response,
    ):
        owner = authenticated_owner(request)
        if backup_id.version != 4:
            raise HTTPException(422, 'Invalid backup ID')
        try:
            ciphertext = base64.b64decode(payload.ciphertext, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, 'Invalid backup encoding') from None
        if (not 29 <= len(ciphertext) <= 49152 or
                base64.b64encode(ciphertext).decode('ascii') != payload.ciphertext):
            raise HTTPException(422, 'Invalid backup encoding')
        result = store.save(owner, generation, backup_id, ciphertext)
        if result not in ('created', 'replay'):
            raise HTTPException(503, 'Backup storage unavailable')
        response.status_code = 201 if result == 'created' else 200
        response.headers['Cache-Control'] = 'no-store'
        return {'result': result}

    @router.get('/entries/{generation}/{backup_id}')
    def download(
        generation: Generation, backup_id: UUID,
        request: Request, response: Response,
    ):
        owner = authenticated_owner(request)
        if backup_id.version != 4:
            raise HTTPException(422, 'Invalid backup ID')
        entry = store.load(owner, generation, backup_id)
        response.headers['Cache-Control'] = 'no-store'
        return {
            'format_version': entry['format_version'],
            'ciphertext': base64.b64encode(entry['ciphertext']).decode('ascii'),
        }

    @router.delete('/consent/{generation}', status_code=204)
    def withdraw(generation: Generation, request: Request):
        owner = authenticated_owner(request)
        store.withdraw(owner, generation)
        return Response(status_code=204, headers={'Cache-Control': 'no-store'})

    return router
