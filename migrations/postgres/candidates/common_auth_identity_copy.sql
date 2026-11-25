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
-- Preserve direct and inherited rights. Add only missing administrator rights.
-- Snapshot object ACLs so successful cleanup must restore their exact values.
DO $grants$
DECLARE before_acl jsonb; added jsonb := '[]'::jsonb; r record; privilege text;
BEGIN
 SELECT jsonb_build_object(
  'schema', (SELECT nspacl::text FROM pg_namespace WHERE nspname='jl_core_auth'),
  'tables', (SELECT jsonb_object_agg(c.relname,c.relacl::text)
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='jl_core_auth' AND c.relname IN
    ('accounts','external_identities','app_sessions','product_consents',
     'session_access_tokens','login_transactions','app_bindings')))
 INTO before_acl;
 PERFORM set_config('jesuslife.copy_acl_before',before_acl::text,true);
 IF NOT has_schema_privilege('postgres','jl_core_auth','USAGE') THEN
  GRANT USAGE ON SCHEMA jl_core_auth TO postgres;
  added := added || jsonb_build_array(jsonb_build_object('kind','schema','name','jl_core_auth','privilege','USAGE'));
 END IF;
 FOR r IN SELECT c.oid,c.relname FROM pg_class c
  JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='jl_core_auth' AND c.relname IN
   ('accounts','external_identities','app_sessions','product_consents',
    'session_access_tokens','login_transactions','app_bindings') ORDER BY c.relname LOOP
  FOREACH privilege IN ARRAY CASE WHEN r.relname IN ('accounts','external_identities')
   THEN ARRAY['SELECT','INSERT'] ELSE ARRAY['SELECT'] END LOOP
   IF NOT has_table_privilege('postgres',r.oid,privilege) THEN
    EXECUTE format('GRANT %s ON TABLE jl_core_auth.%I TO postgres',privilege,r.relname);
    added := added || jsonb_build_array(jsonb_build_object('kind','table','name',r.relname,'privilege',privilege));
   END IF;
  END LOOP;
 END LOOP;
 PERFORM set_config('jesuslife.copy_added_grants',added::text,true);
END $grants$;
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
DO $cleanup$
DECLARE item jsonb; after_acl jsonb;
BEGIN
 FOR item IN SELECT value FROM jsonb_array_elements(current_setting('jesuslife.copy_added_grants')::jsonb) LOOP
  IF item->>'kind'='schema' AND item->>'name'='jl_core_auth' AND item->>'privilege'='USAGE' THEN
   REVOKE USAGE ON SCHEMA jl_core_auth FROM postgres;
  ELSIF item->>'kind'='table' AND item->>'name' IN
   ('accounts','external_identities','app_sessions','product_consents',
    'session_access_tokens','login_transactions','app_bindings') AND item->>'privilege' IN ('SELECT','INSERT') THEN
   EXECUTE format('REVOKE %s ON TABLE jl_core_auth.%I FROM postgres',item->>'privilege',item->>'name');
  ELSE RAISE EXCEPTION 'Unexpected grant cleanup journal';
  END IF;
 END LOOP;
 SELECT jsonb_build_object(
  'schema', (SELECT nspacl::text FROM pg_namespace WHERE nspname='jl_core_auth'),
  'tables', (SELECT jsonb_object_agg(c.relname,c.relacl::text)
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='jl_core_auth' AND c.relname IN
    ('accounts','external_identities','app_sessions','product_consents',
     'session_access_tokens','login_transactions','app_bindings')))
 INTO after_acl;
 IF after_acl IS DISTINCT FROM current_setting('jesuslife.copy_acl_before')::jsonb THEN
  RAISE EXCEPTION 'Administrator ACL restoration failed';
 END IF;
 PERFORM set_config('jesuslife.copy_added_grants','',true);
 PERFORM set_config('jesuslife.copy_acl_before','',true);
END $cleanup$;
RESET ROLE;
SELECT 'IDENTITY_COPY_VERIFIED_RELOGIN_REQUIRED' AS result;
