"""PostgreSQL storage for the explicitly installed backup rehearsal."""
import base64

from fastapi import HTTPException

from .backup_rehearsal import BackupPayload


class PostgresBackupRehearsalStore:
    def __init__(self, transaction):
        """The supplied context manager must start a read-committed transaction."""
        self.transaction = transaction

    def save(self, owner, entry_id, payload):
        ciphertext = base64.b64decode(payload.ciphertext, validate=True)
        with self.transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO jl_ld_backup_rehearsal.entries '
                '(owner_id, entry_id, format_version, ciphertext) VALUES (%s, %s, %s, %s) '
                'ON CONFLICT (owner_id, entry_id) DO NOTHING',
                (owner, entry_id, payload.format_version, ciphertext),
            )
            if cursor.rowcount == 1:
                return True
            existing = self._read(cursor, owner, entry_id)
            if existing is None:
                raise HTTPException(503, 'Backup storage unavailable')
            if existing != payload:
                raise HTTPException(409, 'Backup entry already exists')
            return False

    def load(self, owner, entry_id):
        with self.transaction() as connection, connection.cursor() as cursor:
            return self._read(cursor, owner, entry_id)

    @staticmethod
    def _read(cursor, owner, entry_id):
        cursor.execute(
            'SELECT format_version, ciphertext FROM jl_ld_backup_rehearsal.entries '
            'WHERE owner_id = %s AND entry_id = %s',
            (owner, entry_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return BackupPayload(
            format_version=row['format_version'],
            ciphertext=base64.b64encode(row['ciphertext']).decode('ascii'),
        )
