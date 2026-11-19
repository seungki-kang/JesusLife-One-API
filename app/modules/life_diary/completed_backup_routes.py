"""Authenticated routes for generation-scoped completed diary backup."""

import base64
import binascii
from contextlib import closing
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.modules.neorang_narang.router import SafeValidationRoute

from .backup_rehearsal import BackupPayload

SCHEMA = 'ld_backup_race'


def scalar(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]



def create_completed_backup_router(authenticated_owner, connect):
    """Build routes using the supplied session owner and PostgreSQL connection factory."""
    router = APIRouter(prefix='/api/v1/mobile/life-diary/backup', route_class=SafeValidationRoute)

    @router.put('/entries/{generation}/{entry_id}')
    def upload(generation: int, entry_id: UUID, payload: BackupPayload, request: Request, response: Response):
        owner = authenticated_owner(request)
        if not 1 <= generation <= 9223372036854775807:
            raise HTTPException(422, 'Invalid backup generation')
        try:
            ciphertext = base64.b64decode(payload.ciphertext, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, 'Invalid backup encoding') from None
        if base64.b64encode(ciphertext).decode('ascii') != payload.ciphertext:
            raise HTTPException(422, 'Invalid backup encoding')
        with closing(connect()) as conn, conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            status = scalar(conn, f'SELECT {SCHEMA}.save_backup(%s, %s, %s, %s)',
                            (owner, generation, entry_id, ciphertext))
            if status == 'denied':
                raise HTTPException(403, 'Backup consent is inactive or stale')
            if status == 'conflict':
                raise HTTPException(409, 'Backup entry already exists')
            if status not in ('created', 'replay'):
                raise HTTPException(503, 'Backup storage unavailable')
        response.status_code = 201 if status == 'created' else 200
        return {'result': status}

    @router.get('/entries/{generation}/{entry_id}')
    def download(generation: int, entry_id: UUID, request: Request, response: Response):
        owner = authenticated_owner(request)
        if not 1 <= generation <= 9223372036854775807:
            raise HTTPException(422, 'Invalid backup generation')
        with closing(connect()) as conn:
            row = conn.execute(
                f'''SELECT e.ciphertext FROM {SCHEMA}.backup_entries AS e
                    JOIN {SCHEMA}.backup_consent AS c
                    USING (owner_id, generation)
                    WHERE e.owner_id = %s AND e.generation = %s
                      AND e.entry_id = %s AND c.active''',
                (owner, generation, entry_id),
            ).fetchone()
        if row is None:
            raise HTTPException(404, 'Backup entry unavailable')
        response.headers['Cache-Control'] = 'no-store'
        return {'format_version': 1, 'ciphertext': base64.b64encode(row[0]).decode('ascii')}

    @router.delete('/consent/{generation}', status_code=204)
    def withdraw(generation: int, request: Request):
        owner = authenticated_owner(request)
        if not 1 <= generation <= 9223372036854775807:
            raise HTTPException(422, 'Invalid backup generation')
        with closing(connect()) as conn, conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            scalar(conn, f'SELECT {SCHEMA}.withdraw_backup(%s, %s)', (owner, generation))
        return Response(status_code=204)

    @router.post('/consent')
    def grant(request: Request, response: Response):
        user = authenticated_owner(request)
        with closing(connect()) as conn, conn.transaction():
            generation = scalar(conn, f'SELECT {SCHEMA}.grant_backup(%s)', (user,))
        response.headers['Cache-Control'] = 'no-store'
        return {'generation': generation}

    return router
