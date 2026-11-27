# Life Diary cloud backup account recheck

Date: 2026-11-27
Base commit: ba2e168
Evidence: user-operated manual verification and supplied screenshots.

## Observed results
- Cloud settings and CA format check: PASS.
- Common auth and cloud backup readiness probe: PASS.
- Account A synthetic completed-diary backup: success.
- Account A restore: already restored diary reported.
- Account B using the same recovery code: HTTP 404 displayed.
- Account A using the same code again: already restored diary reported.
- Account A consent withdrawal: completion message displayed.
- Account A restore after withdrawal: HTTP 404 displayed.
- Existing local diary remained visible after withdrawal.

## Interpretation and limits
- The A/B/A sequence supports authenticated account isolation.
- HTTP 404 was observed in the app; raw response bodies were not captured.
- Account A already had the diary; this was not an empty-target restore.
- Both accounts used the same emulator, LD_Backup_Restore_Test.
- No physical second-device or production HTTPS test was performed.
- Local diary retention was confirmed visually, not by a database count.
- Withdrawal blocked recovery; physical cloud deletion was not independently inspected.
- ADB reverse mapping disappeared repeatedly. Restoring tcp:8000 forwarding
  allowed login to continue; the cause remains unresolved.
- Offline suite before this record: 392 tests, OK, 27 skipped.

## Data handling
- Synthetic diary content only.
- Trial backup consent was withdrawn.
- No credentials, tokens, account identifiers or recovery codes recorded.