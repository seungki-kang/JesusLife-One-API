# Life Diary common backup candidate verification

Date: 2026-11-26
Status: AUTHOR_REVIEW_REQUIRED. Candidate only; not applied to Supabase.

## Scope

- Reuse app-scoped common mobile authentication to obtain the verified account.
- Keep backup consent separate from login.
- Install backup routes only when create_app receives an explicit backup store.
- Use a dedicated backup role and schema; do not grant backup access to the
  common authentication runtime.
- Store format version and ciphertext, not recovery keys or diary plaintext.

## Evidence

- Synthetic authentication, router, store, transaction and composition tests:
  61 tests passed; three real-DB test classes skipped.
- Disposable PostgreSQL 16 integration tests: seven passed.
  Covered account RLS, missing/wrong app context, upload replay/conflict,
  withdrawal and generation changes, concurrent upload, upload/withdrawal race,
  and transaction rollback.
- Combined ordinary discovery passed with four DB classes skipped.
- Python syntax check: 11 files passed.
- Live tests used a new labelled container, loopback-only dynamic port and tmpfs.
  Existing containers and Supabase were not changed.
- The candidate keeps the backup role NOLOGIN. Only the disposable test role was
  enabled for login with an ephemeral synthetic password.

## Limits

NOT_RUN: remote TLS, Supabase migration, existing-data migration, Flutter-to-server
backup/restore, device-to-device recovery, deployment and security audit.

The account/app custom settings are trusted server context. RLS does not protect
against a stolen runtime DB credential that can set arbitrary context.
Consent activity and generation are enforced by store operations under row locks,
not by the account-isolation RLS policy alone.

## Application prerequisites

1. Review authentication changes, separate DB credentials, TLS configuration,
   least privileges, consent lifecycle and deployment composition.
2. Inventory target roles/schema. The candidate intentionally fails on existing
   names; do not replace them or rerun it blindly.
3. Prepare and validate a separate migration identity and backup runtime connector.
   No production connector or CLI activation is provided by this change.
4. Obtain a restorable target backup and verify isolated restoration.
5. Review upgrade, rollback and recovery with representative synthetic data.
6. Apply only after explicit target-specific approval, then verify role flags,
   grants, forced RLS, app/account isolation and consent behavior.

## Rollback and recovery

- Before schema application: discard only reviewed candidate changes.
- If transactional schema creation fails: verify rollback before retrying.
- After use: disable backup composition and new writes first.
- Do not drop populated schema, role or ciphertext as a routine rollback.
  Preserve encrypted data and a tested recovery route; use a reviewed forward fix
  or isolated restoration before any destructive action.
- Authentication-only service operation remains separate from backup activation.

## Disposable environment cleanup

Remove only the newly created container after verifying its exact name and
jesuslife.purpose=ld-backup-isolated-test label. Its tmpfs data is disposable.
Do not remove existing containers, volumes, application databases or user records.
