"""Account-scoped backup snapshots. Payloads are encrypted by the client."""
from fastapi import HTTPException


def backup_table_exists(cursor):
    cursor.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema=DATABASE() AND table_name='nn_mobile_backups'"
    )
    return cursor.fetchone() is not None


def erase_backups(cursor, owner, through):
    # Existing installations can continue revoking before migration.
    if backup_table_exists(cursor):
        cursor.execute(
            'DELETE FROM nn_mobile_backups WHERE account_id=%s AND generation<=%s',
            (owner, through),
        )


def access_backup(store, account, *, update=None):
    owner = str(account)
    with store.transaction() as connection, connection.cursor() as c:
        store.ready(c)
        c.execute('SELECT generation,active,deletion_through FROM mobile_consents '
                  'WHERE account_id=%s FOR UPDATE', (owner,))
        consent = c.fetchone()
        if not consent or not consent['active'] or consent['generation'] <= consent['deletion_through']:
            raise HTTPException(403, 'Backup consent required')
        generation = consent['generation']
        if update is not None and update.generation != generation:
            raise HTTPException(409, 'Consent generation changed')
        if not backup_table_exists(c):
            raise HTTPException(503, 'Backup unavailable')
        c.execute('SELECT revision,envelope FROM nn_mobile_backups '
                  'WHERE account_id=%s AND generation=%s', (owner, generation))
        row = c.fetchone()
        revision = row['revision'] if row else 0
        if update is None:
            if not row:
                raise HTTPException(404, 'No backup')
            return {'generation': generation, 'revision': revision,
                    'envelope': row['envelope'].decode('ascii')}
        encoded = update.envelope.encode('ascii')
        if row and row['envelope'] == encoded:
            return {'generation': generation, 'revision': revision}
        if update.base_revision != revision:
            raise HTTPException(409, 'Backup revision changed')
        if row:
            c.execute('UPDATE nn_mobile_backups SET revision=%s,envelope=%s '
                      'WHERE account_id=%s AND generation=%s',
                      (revision + 1, encoded, owner, generation))
        else:
            c.execute('INSERT INTO nn_mobile_backups (account_id,generation,revision,envelope) '
                      'VALUES (%s,%s,%s,%s)', (owner, generation, 1, encoded))
        return {'generation': generation, 'revision': revision + 1}
