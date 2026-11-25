"""Explicit completed-backup store. No default connector or startup DB work."""
from contextlib import contextmanager
from uuid import UUID

from fastapi import HTTPException
import psycopg


class CompletedBackupStore:
    def __init__(self, *, transaction):
        # The adapter must enforce the dedicated role, dict rows and
        # transaction-local verified account/app context.
        if not callable(transaction):
            raise ValueError('Explicit backup transaction adapter required')
        self._transaction = transaction

    @contextmanager
    def _db(self, account):
        account = UUID(str(account))
        failed = False
        try:
            with self._transaction(account) as db:
                yield db
        except psycopg.Error:
            failed = True
        if failed:
            raise HTTPException(503, 'Backup storage unavailable')

    @staticmethod
    def _generation(value):
        if type(value) is not int or not 1 <= value <= 9223372036854775807:
            raise HTTPException(422, 'Invalid backup generation')
        return value

    @staticmethod
    def _lock(db, account):
        return db.execute(
            'SELECT generation, active FROM jl_ld_backup.consent '
            'WHERE account_id=%s FOR UPDATE',
            (account,),
        ).fetchone()

    def grant(self, account):
        account = UUID(str(account))
        with self._db(account) as db:
            row = db.execute(
                'INSERT INTO jl_ld_backup.consent AS c '
                '(account_id,generation,active) VALUES (%s,1,true) '
                'ON CONFLICT (account_id) DO UPDATE SET '
                'generation=c.generation+CASE WHEN c.active THEN 0 ELSE 1 END, '
                'active=true RETURNING generation',
                (account,),
            ).fetchone()
            return row['generation']

    def save(self, account, generation, backup_id, ciphertext):
        account = UUID(str(account))
        generation = self._generation(generation)
        backup_id = UUID(str(backup_id))
        if backup_id.version != 4:
            raise HTTPException(422, 'Invalid backup ID')
        if not isinstance(ciphertext, bytes) or not 29 <= len(ciphertext) <= 49152:
            raise HTTPException(422, 'Invalid backup encoding')
        with self._db(account) as db:
            consent = self._lock(db, account)
            if not consent or not consent['active'] or consent['generation'] != generation:
                raise HTTPException(403, 'Backup consent is inactive or stale')
            row = db.execute(
                'INSERT INTO jl_ld_backup.entries '
                '(account_id,generation,backup_id,format_version,ciphertext) '
                'VALUES (%s,%s,%s,1,%s) ON CONFLICT DO NOTHING '
                'RETURNING backup_id',
                (account, generation, backup_id, ciphertext),
            ).fetchone()
            if row is not None:
                return 'created'
            existing = db.execute(
                'SELECT format_version,ciphertext FROM jl_ld_backup.entries '
                'WHERE account_id=%s AND generation=%s AND backup_id=%s',
                (account, generation, backup_id),
            ).fetchone()
            if existing is None:
                raise HTTPException(503, 'Backup storage unavailable')
            if existing['format_version'] != 1 or bytes(existing['ciphertext']) != ciphertext:
                raise HTTPException(409, 'Backup entry already exists')
            return 'replay'

    def load(self, account, generation, backup_id):
        account = UUID(str(account))
        generation = self._generation(generation)
        backup_id = UUID(str(backup_id))
        if backup_id.version != 4:
            raise HTTPException(422, 'Invalid backup ID')
        with self._db(account) as db:
            consent = self._lock(db, account)
            if not consent or not consent['active'] or consent['generation'] != generation:
                raise HTTPException(404, 'Backup entry unavailable')
            row = db.execute(
                'SELECT format_version,ciphertext FROM jl_ld_backup.entries '
                'WHERE account_id=%s AND generation=%s AND backup_id=%s',
                (account, generation, backup_id),
            ).fetchone()
            if row is None:
                raise HTTPException(404, 'Backup entry unavailable')
            return {'format_version': row['format_version'],
                    'ciphertext': bytes(row['ciphertext'])}

    def withdraw(self, account, generation):
        account = UUID(str(account))
        generation = self._generation(generation)
        with self._db(account) as db:
            consent = self._lock(db, account)
            if not consent or consent['generation'] != generation:
                return
            db.execute(
                'UPDATE jl_ld_backup.consent SET active=false WHERE account_id=%s',
                (account,),
            )
            db.execute(
                'DELETE FROM jl_ld_backup.entries '
                'WHERE account_id=%s AND generation=%s',
                (account, generation),
            )
