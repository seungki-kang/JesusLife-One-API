# Life Diary cloud backup RLS isolation verification

Date: 2026-11-26
Base commit: 0f00b77
Environment: Supabase development project jesuslife-api-dev.

## Implementation
- Explicit opt-in CLI using the dedicated TLS backup connector.
- Two random synthetic account UUIDs and synthetic byte payloads.
- Existing backup transaction wrapper supplies role and schema checks.
- All synthetic writes occur in one transaction that is forcibly rolled back.
- Independent transactions verify that neither synthetic account persisted.
- No schema changes, role changes or real diary content.

## Verification
- Offline isolation tests: 4 tests, OK.
- Full offline suite: 386 tests run, OK, 27 skipped.
- Live CLI result:
  PASS: cloud RLS isolation; synthetic changes rolled back

## Confirmed behavior
- Account A can read its own synthetic consent and entry.
- Account B cannot read account A consent or entries.
- Account B can create its own synthetic consent.
- Cross-account consent and entry inserts are rejected.
- Cross-account consent update and entry deletion affect zero rows.
- Wrong app and empty account/app context hide account A rows.
- Account A data remains intact before rollback.
- No synthetic consent or entries remain after rollback.

## Limits
- This verifies trusted server-supplied database context under RLS.
- It does not verify two authenticated users through the HTTP API.
- Custom settings do not protect against a stolen database credential.
- Synthetic payloads are not an encryption or recovery test.
- Negative TLS cases and production deployment remain unverified.
- No passwords, tokens, recovery codes or diary contents are recorded.