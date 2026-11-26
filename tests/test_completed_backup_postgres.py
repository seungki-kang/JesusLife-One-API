"""Disposable PostgreSQL only; ordinary discovery skips this test class."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
from uuid import uuid4

from fastapi import HTTPException
from app.modules.life_diary.completed_backup_store import CompletedBackupStore
from app.modules.life_diary.completed_backup_transactions import CompletedBackupTransactions

CONNECT = None


class BackupPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if CONNECT is None:
            raise unittest.SkipTest('Explicit disposable PostgreSQL connector required')

    def setUp(self):
        self.account = uuid4()
        self.other = uuid4()
        self.backup = uuid4()
        self.raw = b'x' * 29
        self.tx = CompletedBackupTransactions(connector=CONNECT)
        self.store = CompletedBackupStore(transaction=self.tx)

    def assert_status(self, status, action):
        with self.assertRaises(HTTPException) as caught:
            action()
        self.assertEqual(caught.exception.status_code, status)

    def test_upload_replay_conflict_and_download(self):
        generation = self.store.grant(self.account)
        self.assertEqual(self.store.save(self.account, generation, self.backup, self.raw), 'created')
        self.assertEqual(self.store.save(self.account, generation, self.backup, self.raw), 'replay')
        self.assert_status(409, lambda: self.store.save(
            self.account, generation, self.backup, b'y' * 29))
        self.assertEqual(self.store.load(
            self.account, generation, self.backup)['ciphertext'], self.raw)

    def test_rls_hides_other_account_and_blocks_write(self):
        generation = self.store.grant(self.account)
        self.store.save(self.account, generation, self.backup, self.raw)
        with self.tx(self.other) as db:
            self.assertEqual(db.execute(
                'SELECT * FROM jl_ld_backup.entries').fetchall(), [])
            self.assertEqual(db.execute(
                'SELECT * FROM jl_ld_backup.consent').fetchall(), [])
        self.assert_status(503, lambda: self.cross_account_write())

    def cross_account_write(self):
        with self.tx(self.other) as db:
            db.execute(
                'INSERT INTO jl_ld_backup.consent VALUES (%s,1,true)',
                (self.account,))

    def test_missing_context_and_wrong_app_hide_rows(self):
        self.store.grant(self.account)
        with CONNECT() as db:
            self.assertEqual(db.execute(
                'SELECT * FROM jl_ld_backup.consent').fetchall(), [])
            db.execute("SELECT set_config('jesuslife.backup_account_id', %s, true)",
                       (str(self.account),))
            db.execute("SELECT set_config('jesuslife.backup_app_id', %s, true)",
                       ('neorang_narang',))
            self.assertEqual(db.execute(
                'SELECT * FROM jl_ld_backup.consent').fetchall(), [])

    def test_withdrawal_and_regrant_reject_old_requests(self):
        first = self.store.grant(self.account)
        self.store.save(self.account, first, self.backup, self.raw)
        self.store.withdraw(self.account, first)
        self.assert_status(404, lambda: self.store.load(self.account, first, self.backup))
        self.assert_status(403, lambda: self.store.save(self.account, first, self.backup, self.raw))
        second = self.store.grant(self.account)
        self.assertEqual(second, first + 1)
        self.store.withdraw(self.account, first)
        self.assertEqual(self.store.grant(self.account), second)
        self.assert_status(403, lambda: self.store.save(self.account, first, self.backup, self.raw))
        self.assertEqual(self.store.save(self.account, second, self.backup, self.raw), 'created')

    def test_concurrent_identical_upload_is_created_once(self):
        generation = self.store.grant(self.account)
        barrier = Barrier(2, timeout=5)

        def save():
            barrier.wait()
            return self.store.save(self.account, generation, self.backup, self.raw)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=15) for f in futures),
                             ['created', 'replay'])

    def test_save_withdraw_race_leaves_no_readable_backup(self):
        generation = self.store.grant(self.account)
        barrier = Barrier(2, timeout=5)

        def save():
            barrier.wait()
            try:
                return self.store.save(self.account, generation, self.backup, self.raw)
            except HTTPException as error:
                return error.status_code

        def withdraw():
            barrier.wait()
            self.store.withdraw(self.account, generation)

        with ThreadPoolExecutor(max_workers=2) as pool:
            saved = pool.submit(save)
            withdrawn = pool.submit(withdraw)
            self.assertIn(saved.result(timeout=15), ('created', 403))
            withdrawn.result(timeout=15)
        self.assert_status(404, lambda: self.store.load(self.account, generation, self.backup))
        with self.tx(self.account) as db:
            self.assertEqual(db.execute(
                'SELECT * FROM jl_ld_backup.entries').fetchall(), [])

    def test_failure_rolls_back_state_change(self):
        self.store.grant(self.account)
        with self.assertRaises(RuntimeError):
            with self.tx(self.account) as db:
                db.execute('UPDATE jl_ld_backup.consent SET active=false')
                raise RuntimeError('synthetic rollback')
        with self.tx(self.account) as db:
            self.assertTrue(db.execute(
                'SELECT active FROM jl_ld_backup.consent').fetchone()['active'])
