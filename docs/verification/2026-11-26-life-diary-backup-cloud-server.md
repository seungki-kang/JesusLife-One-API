# Life Diary cloud backup development server

Date: 2026-11-26
Base commit: f6e8d1d
Branch: feature/ld-cloud-backup-server

## Scope
- Add an explicit development launcher combining common cloud authentication
  with the dedicated cloud backup connector.
- Require separate authentication and backup settings and passwords.
- Require both configurations enabled and the same reviewed cloud target.
- check validates settings and CA format without database access.
- probe performs read-only readiness checks without starting a server.
- serve starts only after backup and authentication readiness succeed.
- Bind to 127.0.0.1:8000 with access logging and proxy headers disabled.
- Suppress exception details; no fallback or automatic migration.

## Verification
- Launcher unit and mocked runtime tests: 13 tests, OK.
- Full offline suite: 382 tests run, OK, 27 skipped.
- All launcher network, database and server operations are mocked in tests.
- Backup readiness checks schema version through the existing transaction
  wrapper and checks that all three backup tables enable and force RLS.

## Limits and next checks
- Live cloud TLS connection: NOT_RUN.
- Live cloud account isolation, consent, upload and recovery: NOT_RUN.
- Effective cloud grants and policy behavior require separate live verification.
- Supabase backup runtime role remains NOLOGIN as last verified.
- No role changes, schema application or deployment performed in this step.
- No actual settings, passwords, tokens or diary contents included.
- Offline success does not establish production readiness.