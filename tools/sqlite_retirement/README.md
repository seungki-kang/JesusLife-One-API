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

Limitations: these are controlled Python exception/rollback experiments with one
connection at a time, not abrupt process-kill or power-loss tests. They establish
no Android SQLite, concurrent-worker, physical-erasure, or backup-recovery
guarantees. Undo is synthetic reinsertion, not a production recovery mechanism.
No application migration, sync integration, account authorization, or real-data
collection is approved by this probe. Application schema adoption remains
`AUTHOR_REVIEW_REQUIRED`; real-data collection remains `BLOCKED`.
