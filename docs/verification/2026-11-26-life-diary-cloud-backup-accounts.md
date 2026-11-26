# Life Diary authenticated-account backup verification

Date: 2026-11-26
Environment: Supabase development DB and Windows loopback API server.
Client: LD_Backup_Restore_Test Android emulator (emulator-5558).

## Procedure and observed results
- Account A used the existing Google login.
- Account B used a separate email/password login.
- Account A created a new synthetic diary backup and retained its recovery code.
- Account B successfully logged in through the application.
- Account B attempted restoration using account A recovery code.
- The application reported backup or restoration failure.
- Account B verification list remained empty: zero diaries.
- Account A then logged in again through Google.
- The same recovery code returned the already-restored diary message.
- Account A subsequently withdrew backup consent successfully.

## Interpretation and limits
- The observed A/B behavior supports authenticated account isolation:
  account B could not restore the backup that account A could process.
- No HTTP status or response body was independently captured for B rejection.
- Account A already had the source diary; this was not an empty-target restore.
- Both accounts used the same emulator with account-scoped test SQLite storage.
- Post-withdrawal local diary count was not reconfirmed in this run.
- Earlier empty-target recovery, deduplication and withdrawal checks are
  documented in the cloud backup device verification record.
- No physical second-device or production HTTPS deployment test was performed.
- Connection interruptions and an Auth0 missing-session error occurred during
  account switching. Connectivity was restored and fresh login requests used;
  a permanent fix for those interruptions was not established.

## Data handling
- Only synthetic diary content was used.
- No email addresses, account identifiers, passwords, tokens or recovery codes
  are included in this document.
- The trial backup was withdrawn at the end of verification.

## Document validation
- Documentation-only change; functional tests not rerun.
- Staged whitespace check and PR CI must be checked before merge.