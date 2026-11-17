"""Real PostgreSQL tests, enabled only by scripts.verify_postgres_rls.

No environment credentials, existing server, or network on normal discovery.
"""
from pathlib import Path
from functools import partial
import unittest
from unittest.mock import patch
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.auth import AuthContext, get_current_user

from app.core.postgres import connect_migration, connect_runtime
from app.core.postgres_settings import MIGRATION_DSN, RUNTIME_DSN
from scripts.postgres_rls_support import local_connect

PORT = None
DATABASE = 'postgres'
SQL = Path(__file__).resolve().parents[1] / 'migrations/postgres/001_role_rls_foundation.sql'
A, B, C, X, Y, R, S = [str(UUID(int=n)) for n in range(1, 8)]
D = str(UUID(int=8))
TABLE = 'jl_rls_foundation.synthetic_records'


def admin(**kwargs):
    return local_connect(port=PORT, dbname=DATABASE, user='synthetic_admin',
                         connect_timeout=5, **kwargs)


def seed():
    """Called once on the original empty DB only; never on restored databases."""
    with admin() as db:
        db.execute('INSERT INTO jl_rls_foundation.memberships VALUES '
                   '(%s,%s,true),(%s,%s,false),(%s,%s,true),(%s,%s,true)',
                   (A, X, B, X, D, X, D, Y))
        db.execute('INSERT INTO ' + TABLE + ' VALUES (%s,%s,\'synthetic\'),(%s,%s,\'synthetic\')',
                   (R, X, S, Y))


def snapshot():
    """Full values from both tables under one stable snapshot."""
    with admin() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return (
            db.execute('SELECT account_id,church_id,can_write FROM '
                       'jl_rls_foundation.memberships ORDER BY account_id,church_id').fetchall(),
            db.execute('SELECT record_id,church_id,marker FROM ' + TABLE +
                       ' ORDER BY record_id').fetchall(),
        )


class PostgresRlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PORT is None:
            raise unittest.SkipTest('Run scripts.verify_postgres_rls for isolated PostgreSQL')

    def setUp(self):
        self.db = connect_runtime({RUNTIME_DSN:
            f'postgresql://jl_api_runtime:synthetic_only@127.0.0.1:{PORT}/{DATABASE}'},
            connector=partial(local_connect, port=PORT))
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)
        self.assertEqual((self.db.info.host, self.db.info.hostaddr, self.db.info.port),
                         ('127.0.0.1', '127.0.0.1', PORT))

    def scope(self, account=A, church=X):
        # Only synthetic trusted values, never an HTTP dependency or client IDs.
        self.db.execute("SELECT set_config('jesuslife.account_id', %s, true), "
                        "set_config('jesuslife.church_id', %s, true)", (account, church))

    def denied(self, sql, params=()):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.db.transaction():
                self.db.execute(sql, params)

    def count(self):
        return self.db.execute('SELECT count(*) FROM ' + TABLE).fetchone()[0]

    def rehearsal_app(self):
        app = FastAPI()

        @app.get('/rehearsal/churches/{church_id}/records')
        def read_records(church_id: UUID, user: AuthContext = Depends(get_current_user)):
            try:
                with self.db.transaction():
                    self.db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY')
                    self.scope(str(user.sub), str(church_id))
                    membership = self.db.execute(
                        'SELECT 1 FROM jl_rls_foundation.memberships '
                        'WHERE account_id=%s AND church_id=%s',
                        (user.sub, church_id),
                    ).fetchone()
                    if membership is None:
                        raise HTTPException(403, 'Access denied')
                    row = self.db.execute(
                        'SELECT ARRAY(SELECT record_id::text FROM ' + TABLE +
                        ' ORDER BY record_id) WHERE EXISTS ('
                        'SELECT 1 FROM jl_rls_foundation.memberships '
                        'WHERE account_id=%s AND church_id=%s)',
                        (user.sub, church_id),
                    ).fetchone()
                    if row is None:
                        raise HTTPException(403, 'Access denied')
                    return [[record_id] for record_id in row[0]]
            except psycopg.Error:
                pass
            raise HTTPException(503, 'Church access unavailable')

        return app

    def test_fastapi_synthetic_church_read(self):
        app = self.rehearsal_app()
        with TestClient(app) as client:
            path = f'/rehearsal/churches/{X}/records'
            other_church = f'/rehearsal/churches/{Y}/records'
            self.assertEqual(client.get(path).status_code, 401)
            app.dependency_overrides[get_current_user] = lambda: AuthContext(sub=UUID(A))
            result = client.get(path, params={'account_id': D, 'church_id': Y})
            self.assertEqual((result.status_code, result.json()), (200, [[R]]))
            self.assertEqual(self.count(), 0)
            self.db.rollback()
            self.assertEqual(client.get(other_church, params={'account_id': D}).status_code, 403)
            self.assertEqual(self.count(), 0)
            self.db.rollback()

            execute = self.db.execute

            def fail_membership_lookup(sql, params=None):
                if 'FROM jl_rls_foundation.memberships' in sql:
                    raise psycopg.OperationalError('synthetic lookup failure')
                return execute(sql, params)

            with patch.object(self.db, 'execute', side_effect=fail_membership_lookup) as query:
                result = client.get(path)
                self.assertEqual((result.status_code, result.json()),
                                 (503, {'detail': 'Church access unavailable'}))
                self.assertFalse(any(TABLE in call.args[0] for call in query.call_args_list))
            self.assertEqual(self.count(), 0)

    def test_fastapi_rechecks_membership_after_concurrent_revocation(self):
        app = self.rehearsal_app()
        app.dependency_overrides[get_current_user] = lambda: AuthContext(sub=UUID(A))
        original = snapshot()
        execute = self.db.execute

        with admin() as writer, TestClient(app) as client:
            for commit_revocation in (False, True):
                with self.subTest(commit_revocation=commit_revocation):
                    def change_membership_before_read(sql, params=None):
                        if sql.startswith('SELECT ARRAY('):
                            deleted = writer.execute(
                                'DELETE FROM jl_rls_foundation.memberships '
                                'WHERE account_id=%s AND church_id=%s', (A, X),
                            )
                            self.assertEqual(deleted.rowcount, 1)
                            if commit_revocation:
                                writer.commit()
                            else:
                                writer.rollback()
                        return execute(sql, params)

                    try:
                        with patch.object(self.db, 'execute',
                                          side_effect=change_membership_before_read):
                            result = client.get(f'/rehearsal/churches/{X}/records')
                        expected = (403, {'detail': 'Access denied'}) if commit_revocation else (200, [[R]])
                        self.assertEqual((result.status_code, result.json()), expected)
                    finally:
                        writer.rollback()
                        writer.execute(
                            'INSERT INTO jl_rls_foundation.memberships VALUES (%s,%s,true) '
                            'ON CONFLICT (account_id, church_id) DO NOTHING', (A, X),
                        )
                        writer.commit()
        self.assertEqual(snapshot(), original)

    def test_allowed_same_church_crud(self):
        self.scope()
        self.assertEqual(self.db.execute('SELECT record_id::text FROM ' + TABLE).fetchall(), [(R,)])
        self.db.execute('INSERT INTO ' + TABLE + ' VALUES (%s,%s,\'synthetic\')', (C, X))
        self.assertEqual(self.db.execute('UPDATE ' + TABLE + " SET marker='synthetic' WHERE record_id=%s", (C,)).rowcount, 1)
        self.assertEqual(self.db.execute('DELETE FROM ' + TABLE + ' WHERE record_id=%s', (C,)).rowcount, 1)
        self.db.rollback()

    def test_two_church_writer_cannot_move_rows_outside_request_scope(self):
        for source, target, record in ((X, Y, R), (Y, X, S)):
            self.scope(D, source)
            self.assertEqual(self.count(), 1)
            self.denied('UPDATE ' + TABLE + ' SET church_id=%s WHERE record_id=%s',
                        (target, record))
            self.assertEqual(self.db.execute('SELECT church_id::text FROM ' + TABLE +
                                            ' WHERE record_id=%s', (record,)).fetchone(), (source,))
            self.db.rollback()

    def test_memberships_direct_query_is_account_and_church_scoped(self):
        for account, church, expected in (
                (A, X, [(A, X, True)]), (B, X, [(B, X, False)]),
                (D, X, [(D, X, True)]), (D, Y, [(D, Y, True)]),
                (A, Y, []), (C, X, []), ('', X, []), (A, '', []), ('', '', [])):
            self.scope(account, church)
            self.assertEqual(self.db.execute('SELECT account_id::text,church_id::text,can_write '
                                            'FROM jl_rls_foundation.memberships '
                                            'ORDER BY account_id,church_id').fetchall(), expected)
            self.db.rollback()

    def test_cross_church_and_row_move_denied(self):
        self.scope()
        self.assertEqual(self.db.execute('SELECT * FROM ' + TABLE + ' WHERE church_id=%s', (Y,)).fetchall(), [])
        self.denied('INSERT INTO ' + TABLE + ' VALUES (%s,%s,\'synthetic\')', (C, Y))
        self.denied('UPDATE ' + TABLE + ' SET church_id=%s WHERE record_id=%s', (Y, R))
        for command in ('UPDATE ' + TABLE + " SET marker='synthetic'", 'DELETE FROM ' + TABLE):
            self.assertEqual(self.db.execute(command + ' WHERE church_id=%s', (Y,)).rowcount, 0)
        # A client-chosen church alone cannot confer membership.
        self.scope(A, Y)
        self.assertEqual(self.count(), 0)
        self.denied('INSERT INTO ' + TABLE + ' VALUES (%s,%s,\'synthetic\')', (C, Y))

    def test_missing_membership_scope_and_read_only(self):
        for account, church in ((C, X), ('', X), (A, ''), ('', ''), ('invalid', X)):
            self.scope(account, church)
            self.assertEqual(self.count(), 0)
            self.denied('INSERT INTO ' + TABLE + ' VALUES (%s,%s,\'synthetic\')', (C, X))
            self.assertEqual(self.db.execute('DELETE FROM ' + TABLE).rowcount, 0)
            self.assertEqual(self.db.execute('UPDATE ' + TABLE + " SET marker='synthetic'").rowcount, 0)
        self.scope(B, X)
        self.assertEqual(self.count(), 1)
        self.denied('INSERT INTO ' + TABLE + ' VALUES (%s,%s,\'synthetic\')', (C, X))
        self.assertEqual(self.db.execute('DELETE FROM ' + TABLE).rowcount, 0)
        self.assertEqual(self.db.execute('UPDATE ' + TABLE + " SET marker='synthetic'").rowcount, 0)

    def test_same_connection_scope_cleared_commit_and_rollback(self):
        self.assertEqual(self.count(), 0)
        self.db.rollback()
        for finish in (self.db.commit, self.db.rollback):
            self.scope()
            self.assertEqual(self.count(), 1)
            finish()
            # New transaction on the identical physical connection.
            self.assertEqual(self.count(), 0)
            self.assertEqual(self.db.execute("SELECT nullif(current_setting('jesuslife.account_id',true),''), "
                                            "nullif(current_setting('jesuslife.church_id',true),'')").fetchone(), (None, None))
            self.denied('INSERT INTO ' + TABLE + ' VALUES (%s,%s,\'synthetic\')', (C, X))
            self.db.rollback()

    def test_runtime_cannot_bypass_or_administer(self):
        self.scope()
        attrs = self.db.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolbypassrls "
                                "FROM pg_roles WHERE rolname=current_user").fetchone()
        self.assertEqual(attrs, (False,) * 6)
        self.assertEqual(self.db.execute('SELECT session_user,current_user').fetchone(), ('jl_api_runtime',) * 2)
        # Any outbound membership is forbidden, including NOINHERIT / SET-only edges.
        self.assertEqual(self.db.execute('SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)').fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM pg_class WHERE relnamespace='jl_rls_foundation'::regnamespace AND relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)").fetchone()[0], 0)
        for sql in ('SET ROLE jl_migration_owner', 'SET SESSION AUTHORIZATION jl_migration_owner',
                    'ALTER ROLE jl_api_runtime BYPASSRLS',
                    'GRANT jl_migration_owner TO jl_api_runtime',
                    'ALTER TABLE ' + TABLE + ' DISABLE ROW LEVEL SECURITY',
                    'ALTER TABLE ' + TABLE + ' OWNER TO jl_api_runtime',
                    'TRUNCATE ' + TABLE,
                    'CREATE TABLE jl_rls_foundation.unapproved (id int)',
                    'CREATE TABLE public.unapproved (id int)',
                    'INSERT INTO jl_rls_foundation.memberships VALUES (gen_random_uuid(),gen_random_uuid(),true)'):
            self.denied(sql)
        with self.db.transaction():
            self.db.execute('SET LOCAL row_security=off')
            self.denied('SELECT * FROM ' + TABLE)

    def test_owner_force_rls_and_migration_atomicity(self):
        with connect_migration({MIGRATION_DSN:
                f'postgresql://jl_migration_owner:synthetic_only@127.0.0.1:{PORT}/{DATABASE}'},
                connector=partial(local_connect, port=PORT)) as owner:
            self.assertEqual(owner.execute('SELECT current_user').fetchone(), ('jl_migration_owner',))
            owner.execute('CREATE TABLE jl_rls_foundation.ddl_probe (id integer)')
            owner.execute('DROP TABLE jl_rls_foundation.ddl_probe')
            self.assertEqual(owner.execute('SELECT count(*) FROM ' + TABLE).fetchone()[0], 0)
            owner.rollback()
        with admin() as db:
            rows = db.execute("SELECT c.relname,r.rolname,c.relrowsecurity,c.relforcerowsecurity "
                              "FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner "
                              "WHERE c.relnamespace='jl_rls_foundation'::regnamespace AND c.relkind='r'").fetchall()
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row[1:] == ('jl_migration_owner', True, True) for row in rows))
            db.execute('SET LOCAL ROLE jl_migration_owner')
            self.assertEqual(db.execute('SELECT count(*) FROM ' + TABLE).fetchone()[0], 0)
        with admin() as db:
            with self.assertRaises(psycopg.errors.DuplicateObject):
                with db.transaction():
                    db.execute(SQL.read_text(encoding='utf-8'))
            self.assertEqual(db.execute('SELECT count(*) FROM ' + TABLE).fetchone()[0], 2)
