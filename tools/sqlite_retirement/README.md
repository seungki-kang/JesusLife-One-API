# Synthetic SQLite retirement transaction probe

This is a standalone standard-library unittest experiment. Its schema is **not
an approved application migration**. No application imports, environment files,
existing databases, MySQL, devices, or external services are used. There is no
database-path argument. Each test creates its own fresh `TemporaryDirectory`,
creates one synthetic database there, closes every connection, and removes the
directory on cleanup. Reopens are restricted to that test's generated URI with
`mode=rw`; only initial creation uses `mode=rwc`.

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tools/sqlite_retirement -p 'test_*.py' -v
.\.venv\Scripts\python.exe -B -c "import sys, sqlite3; print(sys.version); print(sqlite3.sqlite_version)"
```

Verified runtime: Windows CPython 3.14.8, SQLite **3.50.4**. Other runtimes must
be checked independently; the second command reports the linked SQLite version.

Connections use `isolation_level=None` (no implicit Python transactions), explicit
`BEGIN IMMEDIATE`, SQL `COMMIT`/`ROLLBACK`, `journal_mode=DELETE`,
`synchronous=FULL`, and `foreign_keys=ON`. Tests assert the PRAGMA values.
The schema deliberately has no cascading foreign key from mapping to completion:
the account/generation/sync-ID mapping must survive local deletion. Retirement
has a composite primary key on that identity; `INSERT OR IGNORE` makes retries
idempotent. All IDs and payloads are fixed synthetic strings.

The atomic operation inserts the retirement marker from the retained mapping,
then deletes the local completion in the same explicit transaction. Exceptions
injected immediately after marker insertion and after deletion before commit
cause explicit rollback. Tests close the operation connection and independently
read exact rows from all three tables through a fresh connection. They check
success, both rollback points, retries, and an unrelated synthetic record.

Synthetic undo inserts the original local record in its own transaction without
removing the mapping or marker. A local SQL upload-eligibility simulation joins
the mapping and excludes retired identities; it is checked before retirement
and after undo. It performs no upload and provides no server authorization.

The test-only negative control intentionally commits deletion in one transaction
and inserts the marker in a second transaction. Failure after marker insertion
but before the second commit rolls that transaction back, leaving deletion
without a marker. The test passes only when independent reopened row checks
observe this deliberately unsafe state.

Limitations of `test_retirement.py`: these are controlled Python exception/rollback
experiments with one connection at a time, not abrupt process-kill or power-loss tests. They establish
no Android SQLite, concurrent-worker, physical-erasure, or backup-recovery
guarantees. Undo is synthetic reinsertion, not a production recovery mechanism.
No application migration, sync integration, account authorization, or real-data
collection is approved by this probe. Application schema adoption remains
`AUTHOR_REVIEW_REQUIRED`; real-data collection remains `BLOCKED`.

## Owned-process forced termination probe

`test_process_crash.py` composes the existing `RetirementTests` fixture, including
its initial `mode=rwc` creation, configuration assertions, exact-row reader and
temporary directory cleanup. It calls the existing `retire()` through a small
connection wrapper that delegates SQL unchanged and pauses immediately after the
selected SQL statement returns. Thus the schema and transaction SQL are reused,
not copied into a second implementation. This tests the standalone synthetic
operation, not an application transaction. No application or configuration loader
is imported. There is no caller-selected database-path CLI.

The parent closes initial connections, then passes only the generated absolute
temporary DB path (plus checkpoint and Pipe endpoint) to its owned child using
`multiprocessing.get_context("spawn")`. The module-level entry opens `mode=rw`,
checks `journal_mode=DELETE`, `synchronous=FULL` (2), `foreign_keys=ON` (1), and
uses `isolation_level=None`. It sends an exact checkpoint tuple and blocks in
Pipe receive, without timing sleeps. The parent uses a bounded 15-second poll,
rejects errors, EOF, unexpected messages and premature exit, calls `kill()` on
that Process only, joins with a 15-second bound, and requires nonzero exitcode.
The successful crash path never reaches child rollback or normal connection close.

After reaping, fresh connections perform SQLite recovery without journal removal
or DB reinitialization. Checks compare the full sqlite_master schema with the
fixture's pre-crash schema, run integrity_check, and compare exact rows of all
three tables, including both mappings and the unrelated synthetic completion.

| Kill checkpoint | Expected and observed completion | Expected and observed retirement |
|---|---|---|
| Immediately after marker INSERT, before COMMIT | TARGET and OTHER | empty |
| Immediately after DELETE, before COMMIT | TARGET and OTHER | empty |
| Immediately after COMMIT returns | OTHER only | MARKER only |

Both mapping rows remain unchanged at every checkpoint. Partial deletion/marker
application fails the exact-row comparison. Finally blocks reap owned children
and close Pipe/Process/DB handles. If reaping fails, the test fails and retains
the synthetic directory (disabling its automatic finalizer), reporting its path
instead of deleting files still potentially owned by the child.

Two additional diagnostic tests use mocked IPC to verify timeout and explicit
child-error rejection; they are not additional real process-crash scenarios.

Commands executed from the repository root in PowerShell on 2026-10-31:

```powershell
.\.venv\Scripts\python.exe -B -c "import sys, sqlite3; print(sys.version); print(sqlite3.sqlite_version)"
.\.venv\Scripts\python.exe -B -m unittest discover -s tools/sqlite_retirement -p test_process_crash.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s tools/sqlite_retirement -p 'test_*.py' -v
```

Current execution: Windows CPython **3.14.8**, SQLite **3.50.4**; new suite
**5 tests PASS**, complete SQLite experiment suite **13 tests PASS**. All three
owned children returned **exitcode=-15** after kill; all exact-row, schema,
configuration and integrity checks passed. These are this execution's results;
the earlier runtime/results above describe the pre-existing exception experiment.

This is SQLite recovery after process termination. It does not verify power
failure, OS crash, Android, MySQL, actual application transactions, server sync,
physical erasure, concurrent workers, or real device/DB behavior. ACK and SQLite
experiments now have dedicated CI configuration as described below; remote CI
execution remains **NOT_RUN**. Product-wide tests, pip check, model exploration,
real devices and real DBs are **NOT_RUN** for this task.
Real collection remains **BLOCKED**; applying protection boundaries or this
experimental schema to the application remains **AUTHOR_REVIEW_REQUIRED**.

## Dedicated CI

`.github/workflows/nn-sync-experiments.yml` supports PRs targeting main, pushes
to main, and manual dispatch. PR/push path filters include both experiment
directories and the workflow itself. Existing offline-tests and sync-model
workflows are unchanged.

The job uses Windows Server 2022 and Python 3.14.8, matching the Python version
in existing CI, with a 10-minute timeout and only `contents: read`. Separate
PowerShell steps log Python/SQLite versions, run ACK discovery, and run the full
SQLite discovery command shown above. Each step explicitly returns Python's
exit code. No pip installation, application/configuration imports, secrets,
service containers, or real databases are needed. The existing spawn, bounded
checkpoint wait, owned-child kill/join and cleanup behavior is unchanged;
failures are not skipped or allowed to pass.

Local revalidation on 2026-10-31: Windows CPython **3.14.8**, SQLite **3.50.4**;
full SQLite discovery passed **13 tests** (8 transaction tests, 3 real owned-child
kills and 2 mock diagnostics). All three killed children reported exitcode=-15.
These are local results, not CI PASS. Workflow configuration is written;
GitHub execution is **NOT_RUN**, and its linked SQLite version must be checked
from that run's version log.

For this CI-wiring task, local `python -B -m pip check` also passed using the
existing project virtual environment; no packages were installed.
