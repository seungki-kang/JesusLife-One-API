"""Dedicated transaction adapter tests. No live DB, TLS or RLS execution."""
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import HTTPException
import psycopg
from psycopg.rows import dict_row

from app.modules.life_diary.completed_backup_transactions import (
    CompletedBackupTransactions,
)


class BackupTransactionTests(unittest.TestCase):
    def setUp(self):
        self.account = uuid4()
        self.connector = MagicMock()
        self.db = MagicMock()
        self.db.autocommit = False
        self.connector.return_value.__enter__.return_value = self.db
        self.db.execute.return_value.fetchone.return_value = {
            'expected_role': True, 'restricted': True}
        self.db.execute.return_value.fetchall.return_value = [{'version': 1}]
        self.transaction = CompletedBackupTransactions(connector=self.connector)

    def assert_unavailable(self):
        with self.assertRaises(HTTPException) as caught:
            with self.transaction(self.account):
                self.fail('Rejected transaction yielded a connection')
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.detail, 'Backup storage unavailable')

    def test_construction_does_not_connect(self):
        self.connector.assert_not_called()

    def test_verified_account_context_is_transaction_local(self):
        with self.transaction(self.account) as db:
            self.assertIs(db, self.db)
        self.assertIs(self.db.row_factory, dict_row)
        calls = self.db.execute.call_args_list
        self.assertEqual(
            calls[0].args[0],
            'SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        self.assertIn('pg_catalog, jl_ld_backup, pg_temp', calls[1].args[0])
        self.assertIn("current_user = 'jl_ld_backup_runtime'", calls[2].args[0])
        self.assertEqual(calls[3].args, (
            "SELECT set_config('jesuslife.backup_app_id', %s, true)",
            ('life_diary',)))
        self.assertEqual(calls[4].args, (
            "SELECT set_config('jesuslife.backup_account_id', %s, true)",
            (str(self.account),)))
        self.connector.return_value.__exit__.assert_called_once_with(
            None, None, None)

    def test_autocommit_is_rejected_before_queries(self):
        self.db.autocommit = True
        self.assert_unavailable()
        self.db.execute.assert_not_called()

    def test_wrong_or_privileged_role_is_rejected(self):
        for role in (
            {'expected_role': False, 'restricted': True},
            {'expected_role': True, 'restricted': False},
            None,
        ):
            with self.subTest(role=role):
                self.db.execute.return_value.fetchone.return_value = role
                self.assert_unavailable()

    def test_wrong_schema_version_is_rejected(self):
        self.db.execute.return_value.fetchall.return_value = [{'version': 2}]
        self.assert_unavailable()

    def test_invalid_account_is_rejected_before_connection(self):
        with self.assertRaises(ValueError):
            with self.transaction('invalid-account'):
                self.fail('Invalid account accepted')
        self.connector.assert_not_called()

    def test_connection_failure_is_sanitized(self):
        self.connector.side_effect = psycopg.OperationalError(
            'synthetic-private-connection-detail')
        self.assert_unavailable()

    def test_body_failure_reaches_connection_exit_and_is_sanitized(self):
        with self.assertRaises(HTTPException) as caught:
            with self.transaction(self.account):
                raise psycopg.OperationalError('synthetic-private-body-detail')
        self.assertEqual(caught.exception.status_code, 503)
        args = self.connector.return_value.__exit__.call_args.args
        self.assertIs(args[0], psycopg.OperationalError)

    def test_commit_failure_is_sanitized(self):
        self.connector.return_value.__exit__.side_effect = (
            psycopg.OperationalError('synthetic-private-commit-detail'))
        with self.assertRaises(HTTPException) as caught:
            with self.transaction(self.account):
                pass
        self.assertEqual(caught.exception.status_code, 503)


if __name__ == '__main__':
    unittest.main()
