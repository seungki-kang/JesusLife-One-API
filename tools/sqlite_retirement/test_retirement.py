"""Synthetic-only transaction probe; no application imports or path inputs."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


TARGET = ("synthetic-local-1", "synthetic-payload-1")
OTHER = ("synthetic-local-2", "synthetic-payload-2")
MAPPING = (TARGET[0], "synthetic-account", 1, "synthetic-sync-1")
OTHER_MAPPING = (OTHER[0], "synthetic-account", 2, "synthetic-sync-2")
MARKER = MAPPING[1:]


class InjectedFailure(RuntimeError):
    pass


def retire(connection, failure=None):
    """One explicit transaction, including both durable retirement and deletion."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            "INSERT OR IGNORE INTO retirement SELECT account, generation, sync_id "
            "FROM mapping WHERE local_id = ?", (TARGET[0],)
        )
        if failure == "after_marker":
            raise InjectedFailure(failure)
        connection.execute("DELETE FROM completion WHERE local_id = ?", (TARGET[0],))
        if failure == "after_delete":
            raise InjectedFailure(failure)
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise


def simulated_upload_allowed(connection):
    return bool(connection.execute(
        "SELECT 1 FROM completion c JOIN mapping m USING (local_id) "
        "WHERE c.local_id = ? AND NOT EXISTS (SELECT 1 FROM retirement r "
        "WHERE r.account = m.account AND r.generation = m.generation "
        "AND r.sync_id = m.sync_id)", (TARGET[0],)
    ).fetchall())


class RetirementTests(unittest.TestCase):
    def setUp(self):
        # Each test owns a fresh directory. No caller can supply a database path.
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-retirement-")
        self.addCleanup(temporary.cleanup)
        self._temporary = temporary
        self._uri = (Path(temporary.name) / "probe.sqlite3").as_uri()
        with closing(sqlite3.connect(self._uri + "?mode=rwc", uri=True,
                                     isolation_level=None)) as connection:
            self.configure(connection)
            connection.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE completion (
                    local_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE mapping (
                    local_id TEXT PRIMARY KEY, account TEXT NOT NULL,
                    generation INTEGER NOT NULL, sync_id TEXT NOT NULL,
                    UNIQUE (account, generation, sync_id));
                CREATE TABLE retirement (
                    account TEXT NOT NULL, generation INTEGER NOT NULL,
                    sync_id TEXT NOT NULL,
                    PRIMARY KEY (account, generation, sync_id));
                COMMIT;
            """)
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany("INSERT INTO completion VALUES (?, ?)",
                                   (TARGET, OTHER))
            connection.executemany("INSERT INTO mapping VALUES (?, ?, ?, ?)",
                                   (MAPPING, OTHER_MAPPING))
            connection.execute("COMMIT")
        self.initial = self.rows()
        self.assertEqual(self.initial, ([TARGET, OTHER],
                                       [MAPPING, OTHER_MAPPING], []))

    def configure(self, connection):
        self.assertEqual(connection.execute("PRAGMA journal_mode=DELETE").fetchone(),
                         ("delete",))
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        self.assertEqual(connection.execute("PRAGMA synchronous").fetchone(), (2,))
        self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone(), (1,))

    def connect(self):
        # Reopen only this test's database, never create one during verification.
        connection = sqlite3.connect(self._uri + "?mode=rw", uri=True,
                                     isolation_level=None)
        try:
            self.configure(connection)
        except BaseException:
            connection.close()
            raise
        return closing(connection)

    def rows(self):
        # Independent SQL oracle: never use operation return values as evidence.
        with self.connect() as connection:
            return (
                connection.execute("SELECT local_id, payload FROM completion "
                                   "ORDER BY local_id").fetchall(),
                connection.execute("SELECT local_id, account, generation, sync_id "
                                   "FROM mapping ORDER BY local_id").fetchall(),
                connection.execute("SELECT account, generation, sync_id "
                                   "FROM retirement ORDER BY account, generation, sync_id")
                .fetchall(),
            )

    def delete(self, failure=None):
        with self.connect() as connection:
            retire(connection, failure)

    def assert_retired(self):
        self.assertEqual(self.rows(), ([OTHER], [MAPPING, OTHER_MAPPING], [MARKER]))

    def test_success_retains_mapping_and_marker(self):
        self.delete()
        self.assert_retired()

    def test_configuration_failure_closes_connection_and_propagates(self):
        failure = InjectedFailure("configuration")
        connections = []

        def fail_configuration(connection):
            self.addCleanup(connection.close)
            connections.append(connection)
            raise failure

        with patch.object(self, "configure", side_effect=fail_configuration):
            with self.assertRaises(InjectedFailure) as raised:
                self.connect()

        self.assertIs(raised.exception, failure)
        self.assertEqual(len(connections), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")

    def test_failure_after_marker_rolls_back(self):
        with self.assertRaises(InjectedFailure):
            self.delete("after_marker")
        self.assertEqual(self.rows(), self.initial)

    def test_failure_after_delete_rolls_back(self):
        with self.assertRaises(InjectedFailure):
            self.delete("after_delete")
        self.assertEqual(self.rows(), self.initial)

    def test_repeated_deletion_is_idempotent(self):
        self.delete()
        self.assert_retired()
        self.delete()
        self.assert_retired()

    def test_undo_retains_retirement_and_blocks_upload(self):
        with self.connect() as connection:
            self.assertTrue(simulated_upload_allowed(connection))
        self.delete()
        self.assert_retired()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO completion VALUES (?, ?)", TARGET)
            connection.execute("COMMIT")
        self.assertEqual(self.rows(), ([TARGET, OTHER],
                                       [MAPPING, OTHER_MAPPING], [MARKER]))
        with self.connect() as connection:
            self.assertFalse(simulated_upload_allowed(connection))

    def test_unrelated_record_unchanged_through_delete_and_retry(self):
        self.delete()
        self.delete()
        self.assert_retired()  # Exact full rows include unrelated payload and mapping.

    def test_negative_control_split_transactions_leave_unmarked_deletion(self):
        # Intentionally unsafe, test-only control: deletion commits first.
        with self.assertRaises(InjectedFailure):
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM completion WHERE local_id = ?",
                                   (TARGET[0],))
                connection.execute("COMMIT")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute("INSERT INTO retirement VALUES (?, ?, ?)", MARKER)
                    raise InjectedFailure("before_second_commit")
                except InjectedFailure:
                    connection.execute("ROLLBACK")
                    raise
        self.assertEqual(self.rows(), ([OTHER], [MAPPING, OTHER_MAPPING], []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
