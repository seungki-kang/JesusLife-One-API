"""Store control-flow tests. No PostgreSQL connection or RLS/concurrency claim."""
from contextlib import contextmanager
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import HTTPException
import psycopg

from app.modules.life_diary.completed_backup_store import CompletedBackupStore


class CompletedBackupStoreTests(unittest.TestCase):
    def setUp(self):
        self.account = uuid4()
        self.backup_id = uuid4()
        self.ciphertext = b'x' * 29
        self.db = MagicMock()
        self.accounts = []

        @contextmanager
        def transaction(account):
            self.accounts.append(account)
            yield self.db

        self.store = CompletedBackupStore(transaction=transaction)

    def rows(self, *values):
        self.db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=value))
            for value in values
        ]

    def assert_status(self, status, operation):
        with self.assertRaises(HTTPException) as caught:
            operation()
        self.assertEqual(caught.exception.status_code, status)

    def save(self):
        return self.store.save(
            self.account, 1, self.backup_id, self.ciphertext)

    def test_grant_uses_account_and_returns_generation(self):
        self.rows({'generation': 2})
        self.assertEqual(self.store.grant(self.account), 2)
        self.assertEqual(self.accounts, [self.account])
        query, params = self.db.execute.call_args.args
        self.assertIn('ON CONFLICT', query)
        self.assertEqual(params, (self.account,))

    def test_new_upload_locks_consent_before_insert(self):
        self.rows({'generation': 1, 'active': True},
                  {'backup_id': self.backup_id})
        self.assertEqual(self.save(), 'created')
        calls = self.db.execute.call_args_list
        self.assertIn('FOR UPDATE', calls[0].args[0])
        self.assertIn('INSERT INTO', calls[1].args[0])
        self.assertEqual(self.accounts, [self.account])

    def test_inactive_or_stale_consent_blocks_insert(self):
        for consent in (None, {'generation': 1, 'active': False},
                        {'generation': 2, 'active': True}):
            with self.subTest(consent=consent):
                self.db.reset_mock()
                self.rows(consent)
                self.assert_status(403, self.save)
                self.assertEqual(self.db.execute.call_count, 1)

    def test_identical_upload_is_replay(self):
        self.rows({'generation': 1, 'active': True}, None,
                  {'format_version': 1, 'ciphertext': self.ciphertext})
        self.assertEqual(self.save(), 'replay')

    def test_different_upload_is_conflict_without_overwrite(self):
        self.rows({'generation': 1, 'active': True}, None,
                  {'format_version': 1, 'ciphertext': b'y' * 29})
        self.assert_status(409, self.save)
        queries = [call.args[0] for call in self.db.execute.call_args_list]
        self.assertFalse(any('UPDATE jl_ld_backup.entries' in q for q in queries))

    def test_load_returns_ciphertext_only(self):
        self.rows({'generation': 1, 'active': True},
                  {'format_version': 1, 'ciphertext': self.ciphertext})
        self.assertEqual(
            self.store.load(self.account, 1, self.backup_id),
            {'format_version': 1, 'ciphertext': self.ciphertext})

    def test_stale_load_returns_not_found(self):
        self.rows({'generation': 2, 'active': True})
        self.assert_status(
            404, lambda: self.store.load(self.account, 1, self.backup_id))
        self.assertEqual(self.db.execute.call_count, 1)

    def test_withdraw_locks_disables_and_deletes_in_one_context(self):
        self.rows({'generation': 1, 'active': True}, None, None)
        self.store.withdraw(self.account, 1)
        queries = [call.args[0] for call in self.db.execute.call_args_list]
        self.assertIn('FOR UPDATE', queries[0])
        self.assertIn('SET active=false', queries[1])
        self.assertIn('DELETE FROM', queries[2])
        self.assertEqual(self.accounts, [self.account])

    def test_old_withdrawal_cannot_revoke_new_generation(self):
        self.rows({'generation': 2, 'active': True})
        self.store.withdraw(self.account, 1)
        self.assertEqual(self.db.execute.call_count, 1)

    def test_invalid_ciphertext_stops_before_transaction(self):
        for value in (b'x' * 28, b'x' * 49153, 'not-bytes'):
            self.assert_status(
                422, lambda: self.store.save(
                    self.account, 1, self.backup_id, value))
        self.assertEqual(self.accounts, [])

    def test_database_error_is_sanitized(self):
        self.db.execute.side_effect = psycopg.OperationalError(
            'synthetic-private-driver-detail')
        with self.assertRaises(HTTPException) as caught:
            self.store.grant(self.account)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.detail, 'Backup storage unavailable')


if __name__ == '__main__':
    unittest.main()
