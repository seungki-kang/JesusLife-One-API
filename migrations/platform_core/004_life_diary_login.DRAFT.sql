-- AUTHOR_REVIEW_REQUIRED. DRAFT ONLY: do not run via existing migration tools.
-- 003 is reserved for the independent NN mobile backup draft in the other workspace.
-- Preconditions: exact Core 001/mobile 002 shapes and versions; inspect whether
-- independent 003 exists. Stop on partial DDL/unknown columns; MySQL DDL commits.
-- Stop writers and drain/expire in-flight login transactions before upgrade.
-- Take a consistent encrypted full Core + product backup including identities,
-- sessions, tokens, consents and version tables. Preserve matching encryption/HMAC
-- key versions separately; prove isolated restore and row counts before any DDL.
-- Upgrade rehearsal: restore pre-upgrade snapshot to isolated MySQL, apply once,
-- compare all existing rows/counts/identity mappings, exercise legacy + LD flows.
-- Existing rows deliberately remain NULL. Never infer app from client/URI or
-- bulk reclassify accounts, sessions, transactions or consents.
USE platform_core;
ALTER TABLE mobile_logins ADD COLUMN app_id VARBINARY(64) NULL,
                          ADD COLUMN client_id VARBINARY(255) NULL;
ALTER TABLE app_sessions ADD COLUMN app_id VARBINARY(64) NULL;
-- No core/mobile version stamp change: old code uses the same tables and shapes
-- plus additive nullable columns. Existing exact-shape preflight tools must be
-- reviewed/extended before use with this draft; do not bypass their checks.
-- Rollback: disable LD first, stop writers, preserve a post-upgrade full backup.
-- Compare rollback target b4e5111 (pre-draft HEAD), app/core/mobile_store.py:
-- its exchange_mobile does NOT check app_id/client_id or session app binding;
-- only URI, handoff hash, PKCE, expiry and consumption protect exchange there.
-- Its NN route supplies the fixed jesuslife-poc://auth/complete/android URI, so
-- an intact LD row with its distinct LD URI is still rejected by old exchange.
-- This URI check is NOT an app/client check: with a matching NN URI, old code
-- does not reject a row solely because its stored app_id/client_id is non-NULL
-- or mismatched. The new code explicitly rejects those bindings independently.
-- The NEW draft rejects non-NULL binding on NN paths; that guard disappears on
-- rollback. Old provider verification rejects the dedicated LD client only if
-- its allowlist still excludes LD; this is not an exchange-time binding guard.
-- Before code rollback, disable LD, stop/drain writers and expire all LD handoffs
-- (including in-flight callbacks) before reopening legacy exchange. Keep the LD
-- client excluded from legacy provider configuration. Preserve columns/LD rows. Do not drop columns while any bound rows exist. If full restore is
-- required, restore the verified snapshot WITH its key versions in isolation,
-- reconcile writes since backup and obtain approval before replacing service DB.
-- Never delete records or identities to make downgrade work. Partial DDL needs
-- shape inspection and an approved forward repair or verified snapshot restore.
