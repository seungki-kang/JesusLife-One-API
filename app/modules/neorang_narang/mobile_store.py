"""Product-owned synthetic projection adapter; shares the Core unit of work.

No local records, names, free text or signatures can enter this table.
"""
import json
import pymysql
from fastapi import HTTPException


class MobileProjectionStore:
    def create(self, cursor, account, generation, metadata):
        cursor.execute('SELECT * FROM neorang_narang.nn_mobile_synthetic WHERE sync_id=%s FOR UPDATE',
                       (metadata['id'],))
        row = cursor.fetchone()
        if row:
            if (row['owner_sub'] != account or row['generation'] != generation or row['erased']
                    or json.loads(row['metadata']) != metadata):
                raise HTTPException(409, 'Sync conflict')
            return {'status': 'stored', 'replayed': True}
        cursor.execute('SELECT sync_id FROM neorang_narang.nn_mobile_synthetic '
                       'WHERE owner_sub=%s AND generation=%s', (account, generation))
        if cursor.fetchone():
            raise HTTPException(409, 'One synthetic completion per consent')
        try:
            cursor.execute('INSERT INTO neorang_narang.nn_mobile_synthetic '
                           '(sync_id,owner_sub,generation,metadata) VALUES (%s,%s,%s,%s)',
                           (metadata['id'], account, generation, json.dumps(metadata, sort_keys=True)))
        except pymysql.IntegrityError:
            raise HTTPException(409, 'Sync conflict') from None
        return {'status': 'stored', 'replayed': False}

    def erase(self, cursor, account, through):
        # Retain only the UUID/owner/generation barrier, with metadata erased.
        cursor.execute('UPDATE neorang_narang.nn_mobile_synthetic SET metadata=NULL,erased=TRUE '
                       'WHERE owner_sub=%s AND generation<=%s', (account, through))
