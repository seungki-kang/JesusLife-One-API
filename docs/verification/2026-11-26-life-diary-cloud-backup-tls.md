# Life Diary cloud backup TLS verification

Date: 2026-11-26
Base commit: cfb64c3
Environment: Supabase development session pooler.

## Scope
- Explicit opt-in PostgreSQL TLS handshake verification.
- Network destination is fixed to the reviewed pooler on port 5432.
- Normal CA and hostname must complete a verified TLS handshake.
- An unrelated synthetic CA must fail certificate chain verification.
- A deliberately incorrect hostname must fail hostname verification.
- No password, PostgreSQL startup message or SQL is sent.
- Actual settings and CA files are not modified.

## Verification
- Offline TLS tests: 6 tests, OK.
- Full offline suite: 392 tests run, OK, 27 skipped.
- Live result:
  PASS: TLS baseline; unrelated CA rejected; wrong hostname rejected
  NO_DATABASE_AUTH: no password, startup message or SQL sent

## Limits
- These live checks use Python SSL and PostgreSQL SSLRequest directly.
- They do not directly exercise psycopg/libpq negative TLS behavior.
- Existing connector tests separately check verify-full connection arguments.
- This is not HTTPS API, database authorization or production deployment testing.
- No credentials, tokens, recovery codes or diary content are recorded.