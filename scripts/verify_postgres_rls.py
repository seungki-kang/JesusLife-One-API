"""Disposable PostgreSQL 16 rehearsal in a PG-free Python worker.

python -B -m scripts.verify_postgres_rls --pg-bin <installed bin directory>
Only temporary loopback clusters and synthetic data; never an existing server.
"""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

import psycopg

from scripts.postgres_rls_support import isolated_environment, local_connect
from tests import test_postgres_rls as checks
from tests.churchos_membership_rehearsal import verify_membership_read


def launch_worker(pg_bin):
    # No parent's PGHOSTADDR/PGSERVICE/PGOPTIONS enter the connecting process.
    return subprocess.run(
        [sys.executable, '-B', '-m', 'scripts.verify_postgres_rls',
         '--pg-bin', str(pg_bin), '--worker'],
        env=isolated_environment(os.environ), check=False,
    ).returncode


def security_snapshot():
    """Compare names/privileges, not cluster-specific OIDs or ACL array order."""
    queries = (
        "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolreplication,"
        "rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname IN "
        "('jl_api_runtime','jl_migration_owner','synthetic_admin') ORDER BY rolname",
        "SELECT pg_get_userbyid(roleid),pg_get_userbyid(member),admin_option,inherit_option,set_option "
        "FROM pg_auth_members WHERE pg_get_userbyid(roleid) LIKE 'jl_%' "
        "OR pg_get_userbyid(member) LIKE 'jl_%' ORDER BY 1,2",
        "SELECT nspname,pg_get_userbyid(nspowner) FROM pg_namespace "
        "WHERE nspname IN ('public','jl_rls_foundation','jl_churchos') ORDER BY 1",
        "SELECT nspname,pg_get_userbyid(a.grantor),CASE WHEN a.grantee=0 THEN 'PUBLIC' "
        "ELSE pg_get_userbyid(a.grantee) END,a.privilege_type,a.is_grantable "
        "FROM pg_namespace CROSS JOIN LATERAL aclexplode(coalesce(nspacl,acldefault('n',nspowner))) a "
        "WHERE nspname IN ('public','jl_rls_foundation','jl_churchos') ORDER BY 1,2,3,4,5",
        "SELECT nspname,relname,pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity "
        "FROM pg_class JOIN pg_namespace ON relnamespace=pg_namespace.oid "
        "WHERE nspname IN ('jl_rls_foundation','jl_churchos') AND relkind='r' ORDER BY 1,2",
        "SELECT nspname,relname,pg_get_userbyid(a.grantor),CASE WHEN a.grantee=0 THEN 'PUBLIC' "
        "ELSE pg_get_userbyid(a.grantee) END,a.privilege_type,a.is_grantable "
        "FROM pg_class JOIN pg_namespace ON relnamespace=pg_namespace.oid "
        "CROSS JOIN LATERAL aclexplode(coalesce(relacl,acldefault('r',relowner))) a "
        "WHERE nspname IN ('jl_rls_foundation','jl_churchos') AND relkind='r' ORDER BY 1,2,3,4,5,6",
        "SELECT pg_get_userbyid(datdba),pg_get_userbyid(a.grantor),CASE WHEN a.grantee=0 THEN 'PUBLIC' "
        "ELSE pg_get_userbyid(a.grantee) END,a.privilege_type,a.is_grantable "
        "FROM pg_database CROSS JOIN LATERAL aclexplode(coalesce(datacl,acldefault('d',datdba))) a "
        "WHERE datname=current_database() ORDER BY 1,2,3,4,5",
    )
    with checks.admin() as db:
        return tuple(db.execute(query).fetchall() for query in queries)


def membership_snapshot():
    """All ChurchOS membership values, ordered by the complete primary key."""
    with checks.admin() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return db.execute(
            'SELECT account_id,church_id,can_manage_memberships,revoked_at '
            'FROM jl_churchos.memberships ORDER BY account_id,church_id'
        ).fetchall()


def run_suite(expected_rows, expected_memberships):
    # No fixture setup here; all test writes are rolled back.
    if checks.snapshot() != expected_rows:
        raise AssertionError('Full restored rows differ before RLS checks')
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(checks))
    if checks.snapshot() != expected_rows:
        raise AssertionError('RLS checks changed preserved rows')
    if membership_snapshot() != expected_memberships:
        raise AssertionError('RLS checks changed preserved ChurchOS memberships')
    return result.wasSuccessful()


def worker(pg_bin):
    if any(key.upper().startswith('PG') for key in os.environ):
        raise RuntimeError('Worker must not inherit PG environment')
    suffix = '.exe' if os.name == 'nt' else ''
    binaries = {name: pg_bin / (name + suffix) for name in
                ('initdb', 'pg_ctl', 'pg_dump', 'pg_restore', 'pg_dumpall', 'psql')}
    if not all(path.is_file() for path in binaries.values()):
        print('BLOCKED: installed PostgreSQL binaries are required; nothing installed')
        return 2

    def run(name, *arguments):
        subprocess.run([str(binaries[name]), *map(str, arguments)],
                       env=isolated_environment(os.environ), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=60)

    @contextmanager
    def cluster(bootstrap):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        temporary = tempfile.TemporaryDirectory(prefix='jl-rls-synthetic-')
        root = Path(temporary.name).resolve()
        data, log = root / 'data', root / 'postgres.log'
        started = False
        stopped = False
        try:
            run('initdb', '-D', data, '-U', bootstrap, '-A', 'trust',
                '--encoding=UTF8', '--no-locale')
            options = f'-h 127.0.0.1 -p {port}'
            if os.name != 'nt':
                options += " -c unix_socket_directories=''"
            run('pg_ctl', '-D', data, '-l', log, '-o', options, '-w', 'start')
            started = True
            with local_connect(port=port, dbname='postgres', user=bootstrap) as db:
                version, address, server_port = db.execute(
                    "SELECT current_setting('server_version_num')::int,"
                    'host(inet_server_addr()),inet_server_port()').fetchone()
                if version // 10000 != 16 or (address, server_port) != ('127.0.0.1', port):
                    raise RuntimeError('Expected temporary loopback PostgreSQL 16')
            yield root, port
        finally:
            try:
                if started or (data / 'postmaster.pid').exists():
                    run('pg_ctl', '-D', data, '-m', 'fast', '-w', 'stop')
                stopped = True
            finally:
                if stopped:
                    temporary.cleanup()
                else:
                    temporary._finalizer.detach()
                    print('BLOCKED: temporary cluster shutdown failed; directory preserved')

    with cluster('synthetic_admin') as (root, port):
        checks.PORT, checks.DATABASE = port, 'postgres'
        with checks.admin() as db:
            try:
                with db.transaction():
                    db.execute(checks.SQL.read_text(encoding='utf-8'))
                    db.execute('SELECT 1/0')
            except psycopg.errors.DivisionByZero:
                pass
            if db.execute("SELECT count(*) FROM pg_roles WHERE rolname IN "
                          "('jl_api_runtime','jl_migration_owner')").fetchone() != (0,):
                raise AssertionError('Role rollback failed')
            if db.execute("SELECT to_regnamespace('jl_rls_foundation')").fetchone() != (None,):
                raise AssertionError('Schema rollback failed')
            db.execute(checks.SQL.read_text(encoding='utf-8'))
        checks.seed()
        with checks.admin() as db:
            migration = checks.SQL.with_name('002_churchos_memberships.sql')
            db.execute(migration.read_text(encoding='utf-8'))
            db.execute(
                'INSERT INTO jl_churchos.memberships VALUES '
                '(%s,%s,true,NULL),(%s,%s,false,NULL),(%s,%s,true,now())',
                (checks.A, checks.X, checks.A, checks.Y, checks.B, checks.X),
            )
        initial_memberships = membership_snapshot()
        verify_membership_read(port, checks.DATABASE)
        if membership_snapshot() != initial_memberships:
            raise AssertionError('HTTP checks changed preserved ChurchOS memberships')
        if not run_suite(checks.snapshot(), initial_memberships):
            return 1
        print('PASS: isolated PG-free worker, loopback endpoint, install and RLS checks')

        # Snapshot immediately before backup; no writers run during dump.
        expected_security = security_snapshot()
        expected_rows = checks.snapshot()
        expected_memberships = membership_snapshot()
        dump, roles = root / 'synthetic.dump', root / 'roles.sql'
        run('pg_dump', '-h', '127.0.0.1', '-p', port, '-U', 'synthetic_admin',
            '-d', 'postgres', '-Fc', '-f', dump)
        run('pg_dumpall', '-h', '127.0.0.1', '-p', port, '-U', 'synthetic_admin',
            '--roles-only', '--no-role-passwords', '-f', roles)

        def restore(target_port, bootstrap):
            with local_connect(port=target_port, dbname='postgres', user=bootstrap,
                               autocommit=True) as db:
                db.execute('CREATE DATABASE synthetic_restored OWNER synthetic_admin')
            run('pg_restore', '-h', '127.0.0.1', '-p', target_port, '-U', bootstrap,
                '-d', 'synthetic_restored', '--exit-on-error', dump)
            checks.PORT, checks.DATABASE = target_port, 'synthetic_restored'
            # Compare actual ACLs and owners, with no repairs before checking.
            if security_snapshot() != expected_security:
                raise AssertionError('Restored role/ownership/ACL snapshot differs')
            if membership_snapshot() != expected_memberships:
                raise AssertionError('Full restored ChurchOS memberships differ before HTTP checks')
            if checks.snapshot() != expected_rows:
                raise AssertionError('Full restored rows differ before HTTP checks')
            verify_membership_read(target_port, checks.DATABASE)
            if membership_snapshot() != expected_memberships:
                raise AssertionError('HTTP checks changed preserved ChurchOS memberships')
            return run_suite(expected_rows, expected_memberships)

        if not restore(port, 'synthetic_admin'):
            return 1
        print('PASS: same-cluster DB restore, full rows/ACLs and RLS; no reseeding')
        with cluster('restore_admin') as (_, restored_port):
            # A different bootstrap role proves source roles are recreated.
            with local_connect(port=restored_port, dbname='postgres', user='restore_admin') as db:
                if db.execute("SELECT count(*) FROM pg_roles WHERE rolname IN "
                              "('jl_api_runtime','jl_migration_owner','synthetic_admin')").fetchone() != (0,):
                    raise AssertionError('Target cluster roles already exist')
            run('psql', '-X', '-h', '127.0.0.1', '-p', restored_port, '-U', 'restore_admin',
                '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-1', '-f', roles)
            if not restore(restored_port, 'restore_admin'):
                return 1
            print('PASS: new-cluster roles + DB ACL/ownership/full rows + RLS restore')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', type=Path, required=True)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    return worker(args.pg_bin) if args.worker else launch_worker(args.pg_bin)


if __name__ == '__main__':
    raise SystemExit(main())
