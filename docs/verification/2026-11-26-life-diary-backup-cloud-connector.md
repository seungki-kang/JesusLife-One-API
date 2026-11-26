# Dedicated Life Diary cloud backup connector

Date: 2026-11-26
Status: development connector implemented; live connection NOT_RUN.

## Implemented

- Dedicated minimal settings and explicit backup enablement.
- Fixed reviewed development project, session pooler and backup runtime role.
- Password supplied separately; no password or DSN in the settings file.
- TLS verify-full, explicit CA certificate and bounded connection/statement timeouts.
- Inherited PG environment options rejected.
- No connection on import or connector construction.
- No automatic migration, retry or persistence fallback.
- Driver errors replaced with a fixed message.

## Verification

- Settings and mocked-driver tests: 17 PASS.
- Full offline runner: 369 tests, 27 skipped, no failures.
- Actual remote TLS handshake and backup role login: NOT_RUN.
- Cloud RLS behavior and cloud upload/restore: NOT_RUN.

## Activation boundary

The Supabase backup role remains NOLOGIN.
This change does not provide a cloud server launcher or enable backup access.
Before activation, separately review credentials, effective grants and memberships,
readiness checks, app/account isolation and synthetic cloud recovery tests.
The existing dedicated transaction adapter must validate the actual DB role
and apply transaction-local account/app context.
