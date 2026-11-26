"""Offline checks for rollback and explicit RLS rejection handling."""
from contextlib import contextmanager
import unittest
from unittest.mock import MagicMock, patch

from psycopg.errors import InsufficientPrivilege
from scripts import life_diary_backup_cloud_isolation as cli


class CloudIsolationTests(unittest.TestCase):
    def test_success_forces_rollback_before_independent_checks(self):
        events = []
        accounts = []
        db = MagicMock()
        db.execute.return_value.rowcount = 0
        db.execute.return_value.fetchone.return_value = {'active': True}

        @contextmanager
        def transactions(account):
            accounts.append(account)
            try:
                yield db
            except Exception as error:
                events.append(type(error))
                raise
            else:
                events.append('normal')

        counts = [0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0]
        with patch.object(cli, 'count', side_effect=counts) as count, \
             patch.object(cli, 'denied') as denied:
            cli.verify(transactions)
        self.assertEqual(count.call_count, len(counts))
        self.assertEqual(denied.call_count, 2)
        self.assertEqual(events, [cli.RollbackVerification, 'normal', 'normal'])
        self.assertEqual(accounts[0], accounts[1])
        self.assertNotEqual(accounts[1], accounts[2])

    def test_failed_assertion_propagates_out_of_transaction(self):
        events = []

        @contextmanager
        def transactions(account):
            try:
                yield MagicMock()
            except Exception as error:
                events.append(type(error))
                raise

        with patch.object(cli, 'count', return_value=1):
            with self.assertRaises(ValueError):
                cli.verify(transactions)
        self.assertEqual(events, [ValueError])

    def test_denied_accepts_only_insufficient_privilege(self):
        db = MagicMock()
        db.execute.side_effect = InsufficientPrivilege('synthetic')
        cli.denied(db, 'synthetic statement', ())
        db.transaction.assert_called_once()

        db = MagicMock()
        db.execute.side_effect = RuntimeError('synthetic')
        with self.assertRaises(RuntimeError):
            cli.denied(db, 'synthetic statement', ())

    def test_denied_rejects_unexpected_write_success(self):
        db = MagicMock()
        with self.assertRaises(ValueError):
            cli.denied(db, 'synthetic statement', ())


if __name__ == '__main__':
    unittest.main()