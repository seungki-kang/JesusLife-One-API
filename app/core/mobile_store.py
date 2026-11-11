"""Durable mobile handoff + generation serialization. No refresh credentials."""
from uuid import UUID
from fastapi import HTTPException
from .core_store import CoreStore, digest, utc
from .mobile_backup_store import erase_backups
from .auth0_poc import denied, matches_pkce


class MobileCoreStore(CoreStore):
    def ready(self, cursor):
        cursor.execute('SELECT version FROM mobile_schema_version ORDER BY version')
        if cursor.fetchall() != [{'version': 1}]:
            raise HTTPException(503, 'Mobile storage unavailable')

    def begin_mobile(self, *, state, transaction, challenge, return_uri, now):
        with self.transaction() as connection, connection.cursor() as c:
            self.ready(c)
            c.execute('INSERT INTO mobile_logins '
                      '(state_hash,transaction_id,challenge,return_uri,expires_at) VALUES (%s,%s,%s,%s,%s)',
                      (digest(state), transaction, challenge.encode(), return_uri.encode(), utc(now+300)))

    def bind_browser(self, state, browser, *, now):
        with self.transaction() as connection, connection.cursor() as c:
            self.ready(c)
            c.execute('UPDATE mobile_logins SET browser_ciphertext=%s WHERE state_hash=%s '
                      'AND browser_ciphertext IS NULL AND expires_at>%s',
                      (self.encrypt(browser, digest(state)), digest(state), utc(now)))
            if c.rowcount != 1:
                raise denied()

    def finish_mobile(self, state, browser, credential, account, code, *, now):
        with self.transaction() as connection, connection.cursor() as c:
            self.ready(c)
            c.execute('SELECT * FROM mobile_logins WHERE state_hash=%s FOR UPDATE', (digest(state),))
            row = c.fetchone()
            if (not row or not row['browser_ciphertext'] or row['handoff_hash']
                    or row['expires_at'] <= utc(now)
                    or self.decrypt(row['browser_ciphertext'], digest(state)) != browser):
                raise denied()
            c.execute('UPDATE mobile_logins SET handoff_hash=%s,credential_ciphertext=%s,'
                      'account_id=%s,expires_at=%s,browser_ciphertext=NULL WHERE state_hash=%s',
                      (digest(code), self.encrypt(credential, digest(code)), str(account), utc(now+60), digest(state)))
            return row['transaction_id'], row['return_uri'].decode()

    def exchange_mobile(self, transaction, code, verifier, return_uri, *, now):
        with self.transaction() as connection, connection.cursor() as c:
            self.ready(c)
            c.execute('SELECT * FROM mobile_logins WHERE transaction_id=%s FOR UPDATE', (transaction,))
            row = c.fetchone()
            if (not row or row['consumed_at'] is not None or row['expires_at'] <= utc(now)
                    or row['handoff_hash'] != digest(code) or row['return_uri'] != return_uri.encode()
                    or not matches_pkce(verifier, row['challenge'].decode())):
                raise denied()
            credential = self.decrypt(row['credential_ciphertext'], digest(code))
            c.execute('UPDATE mobile_logins SET consumed_at=%s,credential_ciphertext=NULL WHERE state_hash=%s',
                      (utc(now), row['state_hash']))
            return credential, UUID(row['account_id'])

    def mobile_status(self, account, *, grant=False, revoke=None, create=None, projection):
        owner = str(account)
        with self.transaction() as connection, connection.cursor() as c:
            self.ready(c)
            c.execute('INSERT INTO mobile_consents (account_id) VALUES (%s) '
                      'ON DUPLICATE KEY UPDATE account_id=account_id', (owner,))
            c.execute('SELECT * FROM mobile_consents WHERE account_id=%s FOR UPDATE', (owner,))
            row = c.fetchone()
            generation, active = row['generation'], bool(row['active'])
            through, deletion = row['deletion_through'], row['deletion_status']
            if grant and not active:
                generation, active = generation + 1, True
            if revoke is not None:
                if revoke > generation:
                    raise HTTPException(409, 'Consent conflict')
                # Replaying an old deletion cannot revoke a later grant.
                if revoke == generation:
                    active = False
                through = max(through, revoke)
                projection.erase(c, owner, through)
                erase_backups(c, owner, through)
                deletion = 'complete'
            result = None
            if create:
                expected, metadata = create
                if not active or expected != generation or generation <= through:
                    raise HTTPException(410, 'Consent generation expired')
                result = projection.create(c, owner, generation, metadata)
            c.execute('UPDATE mobile_consents SET generation=%s,active=%s,deletion_through=%s,'
                      'deletion_status=%s WHERE account_id=%s', (generation, active, through, deletion, owner))
            return result or {'generation': generation, 'active': active,
                              'deletion_through': through, 'deletion_status': deletion,
                              # Historical completion is scoped by deletion_through.
                              # Keep legacy fields unchanged for existing clients.
                              'current_generation_deletion_complete': (
                                  generation > 0 and not active and through >= generation
                                  and deletion == 'complete')}
