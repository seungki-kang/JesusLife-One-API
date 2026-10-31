"""Owned-process kill probe using only the existing synthetic test fixture."""

import multiprocessing
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import Mock

import test_retirement as fixture


TIMEOUT = 15
STAGES = {
    "after_marker": "INSERT OR IGNORE",
    "after_delete": "DELETE FROM completion",
    "after_commit": "COMMIT",
}


def child_entry(database_path, stage, pipe):
    """Spawn entry: never called on import; path supplied only by owned fixture."""
    connection = None
    try:
        if stage not in STAGES:
            raise ValueError("unknown checkpoint")
        path = Path(database_path)
        if not path.is_absolute():
            raise ValueError("absolute fixture path required")
        connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True,
                                     isolation_level=None)
        fixture.RetirementTests().configure(connection)

        class CheckpointConnection:
            def execute(self, sql, parameters=()):
                result = connection.execute(sql, parameters)
                if sql.startswith(STAGES[stage]):
                    pipe.send(("checkpoint", stage))
                    # Parent never sends a release: only kill may end this wait.
                    pipe.recv()
                    raise RuntimeError("unexpected checkpoint release")
                return result

        fixture.retire(CheckpointConnection())
        raise RuntimeError("operation returned without checkpoint")
    except BaseException as error:
        pipe.send(("error", type(error).__name__, str(error)))
        raise
    finally:
        if connection is not None:
            connection.close()
        pipe.close()


def receive_checkpoint(pipe, process, stage, timeout=TIMEOUT):
    if not pipe.poll(timeout):
        raise AssertionError(f"IPC timeout waiting for {stage}; exitcode={process.exitcode}")
    try:
        message = pipe.recv()
    except EOFError as error:
        raise AssertionError(f"child pipe EOF before {stage}; exitcode={process.exitcode}") from error
    if message != ("checkpoint", stage):
        raise AssertionError(f"unexpected child message for {stage}: {message!r}")
    if not process.is_alive():
        raise AssertionError(f"child exited before kill: exitcode={process.exitcode}")


def schema(connection):
    return connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()


class ProcessCrashTests(unittest.TestCase):
    def probe(self, stage):
        # Composition avoids inheriting/rerunning the eight fixture tests.
        owner = fixture.RetirementTests()
        process = None
        parent_pipe = child_pipe = None
        reaped = True
        try:
            owner.setUp()  # Initial creation and all parent connections close here.
            with owner.connect() as connection:
                initial_schema = schema(connection)
            context = multiprocessing.get_context("spawn")
            parent_pipe, child_pipe = context.Pipe(duplex=True)
            process = context.Process(target=child_entry, args=(
                str(Path(owner._temporary.name).resolve() / "probe.sqlite3"),
                stage, child_pipe))
            process.start()
            reaped = False
            child_pipe.close()
            receive_checkpoint(parent_pipe, process, stage)
            process.kill()
            process.join(TIMEOUT)
            self.assertFalse(process.is_alive(), "owned child not reaped after kill")
            reaped = True
            self.assertIsNotNone(process.exitcode)
            self.assertNotEqual(process.exitcode, 0, "normal exit is not crash evidence")
            # No journal removal or reinitialization: new connection triggers recovery.
            with owner.connect() as connection:
                self.assertEqual(schema(connection), initial_schema)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(),
                                 [("ok",)])
            expected = (([fixture.OTHER], [fixture.MAPPING, fixture.OTHER_MAPPING],
                         [fixture.MARKER]) if stage == "after_commit" else owner.initial)
            self.assertEqual(owner.rows(), expected)
            print(f"{stage}: exitcode={process.exitcode}; exact three-table rows PASS",
                  flush=True)
        finally:
            try:
                if process is not None and process.pid is not None:
                    if process.is_alive():
                        process.kill()
                    process.join(TIMEOUT)
                    reaped = not process.is_alive()
                    if reaped:
                        process.close()
            finally:
                if parent_pipe is not None:
                    parent_pipe.close()
                if child_pipe is not None:
                    child_pipe.close()
                if reaped:
                    self.assertTrue(owner.doCleanups(), "synthetic fixture cleanup failed")
                else:
                    # Preserve files even against TemporaryDirectory's GC finalizer.
                    owner._temporary._finalizer.detach()
                    raise AssertionError(
                        f"child reap failed; retained synthetic directory {owner._temporary.name}")

    def test_kill_after_marker_before_commit(self):
        self.probe("after_marker")

    def test_kill_after_delete_before_commit(self):
        self.probe("after_delete")

    def test_kill_after_commit_returns(self):
        self.probe("after_commit")

    def test_ipc_timeout_diagnostic(self):
        pipe = Mock()
        pipe.poll.return_value = False
        with self.assertRaisesRegex(AssertionError, "IPC timeout.*after_marker"):
            receive_checkpoint(pipe, Mock(exitcode=None), "after_marker", timeout=0)
        pipe.recv.assert_not_called()

    def test_child_error_diagnostic(self):
        pipe = Mock()
        pipe.recv.return_value = ("error", "OperationalError", "synthetic failure")
        with self.assertRaisesRegex(AssertionError, "unexpected child message.*OperationalError"):
            receive_checkpoint(pipe, Mock(), "after_marker", timeout=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
