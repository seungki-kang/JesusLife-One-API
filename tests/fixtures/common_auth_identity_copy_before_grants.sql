-- CANDIDATE ONLY: compose AFTER common_auth.sql in the SAME transaction.
-- Administrator must be postgres, BYPASSRLS, member of jl_migration_owner.
-- Observed development preconditions: 1 account, 1 identity, 0 unexpired
-- sessions and 0 consents. Existing sources remain untouched.
-- No BEGIN/COMMIT here: caller owns the single all-or-nothing transaction.
DO $guard$
BEGIN
 IF current_user <> 'postgres' OR NOT EXISTS
   (SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolbypassrls)
   OR NOT pg_has_role(current_user, 'jl_migration_owner', 'MEMBER') THEN
   RAISE EXCEPTION 'Identity copy requires the verified administrator';
 END IF;
 IF has_schema_privilege(current_user, 'jl_core_auth', 'USAGE')
   OR has_table_privilege(current_user, (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='jl_core_auth' AND c.relname='accounts'), 'SELECT,INSERT')
   OR has_table_privilege(current_user, (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='jl_core_auth' AND c.relname='external_identities'), 'SELECT,INSERT') THEN
   RAISE EXCEPTION 'Unexpected pre-existing target grants; review required';
 END IF;
END $guard$;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='10s';
SET LOCAL ROLE jl_migration_owner;
-- Owner acquires locks; postgres cannot be assumed to have source UPDATE/DELETE.
LOCK TABLE jl_ld_auth.accounts, jl_ld_auth.external_identities,
 jl_ld_auth.app_sessions, jl_ld_auth.product_consents IN SHARE MODE;
LOCK TABLE jl_core_auth.accounts, jl_core_auth.external_identities,
 jl_core_auth.app_sessions, jl_core_auth.product_consents,
 jl_core_auth.session_access_tokens, jl_core_auth.login_transactions,
 jl_core_auth.app_bindings IN SHARE ROW EXCLUSIVE MODE;
-- RLS bypass does not confer table privileges. Use temporary transactional
-- grants to this administrator, then revoke explicitly before commit.
GRANT USAGE ON SCHEMA jl_core_auth TO postgres;
GRANT SELECT, INSERT ON jl_core_auth.accounts, jl_core_auth.external_identities TO postgres;
GRANT SELECT ON jl_core_auth.app_sessions, jl_core_auth.product_consents,
 jl_core_auth.session_access_tokens, jl_core_auth.login_transactions,
 jl_core_auth.app_bindings TO postgres;
RESET ROLE;
DO $copy$
BEGIN
 IF (SELECT count(*) FROM jl_ld_auth.accounts) <> 1
   OR (SELECT count(*) FROM jl_ld_auth.external_identities) <> 1
   OR EXISTS (SELECT 1 FROM jl_ld_auth.product_consents)
   OR EXISTS (SELECT 1 FROM jl_ld_auth.app_sessions
       WHERE revoked_at IS NULL AND expires_at > timezone('UTC', CURRENT_TIMESTAMP)) THEN
   RAISE EXCEPTION 'Source inventory changed; identity copy cancelled';
 END IF;
 IF EXISTS (SELECT 1 FROM jl_core_auth.accounts)
   OR EXISTS (SELECT 1 FROM jl_core_auth.external_identities)
   OR EXISTS (SELECT 1 FROM jl_core_auth.app_sessions)
   OR EXISTS (SELECT 1 FROM jl_core_auth.product_consents)
   OR EXISTS (SELECT 1 FROM jl_core_auth.session_access_tokens)
   OR EXISTS (SELECT 1 FROM jl_core_auth.login_transactions)
   OR EXISTS (SELECT 1 FROM jl_core_auth.app_bindings) THEN
   RAISE EXCEPTION 'Target is not pristine; identity copy cancelled';
 END IF;
 INSERT INTO jl_core_auth.accounts(account_id,status,security_version,created_at)
 SELECT account_id,status,security_version,created_at FROM jl_ld_auth.accounts;
 INSERT INTO jl_core_auth.external_identities(issuer,provider_subject,account_id,created_at)
 SELECT issuer,provider_subject,account_id,created_at FROM jl_ld_auth.external_identities;
 IF EXISTS (
   (SELECT account_id,status,security_version,created_at FROM jl_ld_auth.accounts
    EXCEPT SELECT account_id,status,security_version,created_at FROM jl_core_auth.accounts)
   UNION ALL
   (SELECT account_id,status,security_version,created_at FROM jl_core_auth.accounts
    EXCEPT SELECT account_id,status,security_version,created_at FROM jl_ld_auth.accounts)
 ) OR EXISTS (
   (SELECT issuer,provider_subject,account_id,created_at FROM jl_ld_auth.external_identities
    EXCEPT SELECT issuer,provider_subject,account_id,created_at FROM jl_core_auth.external_identities)
   UNION ALL
   (SELECT issuer,provider_subject,account_id,created_at FROM jl_core_auth.external_identities
    EXCEPT SELECT issuer,provider_subject,account_id,created_at FROM jl_ld_auth.external_identities)
 ) THEN
   RAISE EXCEPTION 'Identity copy equality check failed';
 END IF;
END $copy$;
SET LOCAL ROLE jl_migration_owner;
REVOKE SELECT, INSERT ON jl_core_auth.accounts, jl_core_auth.external_identities FROM postgres;
REVOKE SELECT ON jl_core_auth.app_sessions, jl_core_auth.product_consents,
 jl_core_auth.session_access_tokens, jl_core_auth.login_transactions,
 jl_core_auth.app_bindings FROM postgres;
REVOKE USAGE ON SCHEMA jl_core_auth FROM postgres;
RESET ROLE;
SELECT 'IDENTITY_COPY_VERIFIED_RELOGIN_REQUIRED' AS result;
