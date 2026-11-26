# Life Diary cloud backup schema verification

Date: 2026-11-26
Target: jesuslife-api-dev, project reference zfhphrihdyjctbwnnyyx.
Status: schema applied; backup runtime login remains disabled.

## Pre-application backup and rehearsal

- PostgreSQL server and dump/restore tools: 17.11.
- Custom archive covered jl_churchos, jl_core_auth, jl_ld_auth,
  jl_nn_backup and ld_backup_race.
- Archive size: 128137 bytes; 176 TOC entries.
- SHA256: 8855FE96B78BE36CA133D444974BD6B1615F65D6BE4235EBE7253F136B4D3B9C.
- Restored into a separate network-disabled PostgreSQL 17 container.
- Restore exit code 0, using no-owner, no-privileges and one transaction.
- Five schemas, 25 tables and 14 policies matched source structure counts.
- Row-count queries completed for all restored tables.
- Original ownership/grants and exact data equality were not verified.
- This is not a full Supabase project backup; managed schemas, Storage objects
  and role definitions were excluded. Archive remains outside Git.

## Application

- Used the merged candidate with transaction-local lock/statement timeouts
  and guards for execution identity, database, role-switch permission,
  absent backup objects and presence of the common accounts table.
- Rehearsed the guarded SQL successfully in the isolated restored database.
- User executed it in the Supabase SQL Editor; success reported.
- New jl_ld_backup schema and jl_ld_backup_runtime role created.
- Existing authentication data was outside the migration's write scope.

## Observed cloud state

- jl_ld_backup_runtime: rolcanlogin=false, rolsuper=false, rolbypassrls=false.
- consent, entries and schema_version owned by jl_migration_owner.
- All three tables: RLS enabled and forced; one policy per table.
- schema_version=1, consent rows=0, entry rows=0.
- No custom default ACL entries were found for jl_migration_owner before apply.

## Limits and next gate

- Catalog inspection confirms structure, not effective account isolation.
- Cloud runtime login and backup credentials have not been enabled.
- Remote backup TLS, cloud RLS behavior, upload/withdrawal races and
  Flutter-to-cloud backup/restore remain NOT_RUN.
- Production deployment, physical-device recovery and security audit remain
  unverified.
- Do not blindly rerun the creation SQL or remove populated backup objects.
- Review dedicated connector, least privileges, recovery and rollback before
  separately enabling runtime access.
