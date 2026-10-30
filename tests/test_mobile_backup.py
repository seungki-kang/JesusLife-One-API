"""Offline synthetic orchestration proof, never evidence of a MySQL restore."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime
from io import StringIO
from pathlib import Path
import tempfile
import json
import unittest
from unittest.mock import MagicMock, patch

from scripts import mobile_backup as backup


def fixture():
    parent = {'schema': 'CREATE TABLE `parent` (`id` int PRIMARY KEY) ENGINE=InnoDB',
              'rows': [{'id': 1}], 'foreign_keys': []}
    child = {'schema': 'CREATE TABLE `child` (`id` int, FOREIGN KEY (`id`) REFERENCES `parent` (`id`)) ENGINE=InnoDB',
             'rows': [{'id': 1}], 'foreign_keys': [{'REFERENCED_TABLE_NAME': 'parent'}]}
    return {db: {'parent': deepcopy(parent), 'child': deepcopy(child)} for db in backup.DATABASES}


class Connection:
    def __init__(self, fail=None, collision=None):
        self.events = []
        self.databases = set(backup.DATABASES)
        self.database = None
        self.fail = fail
        self.collision = collision

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def cursor(self):
        return self

    def execute(self, sql, args=()):
        self.events.append((sql, args, self.database))
        if sql.startswith('CREATE DATABASE '):
            name = sql.split('`')[1]
            if name in self.databases or name == self.collision:
                raise RuntimeError('Already exists')
            self.databases.add(name)
        if self.fail and self.fail(sql):
            raise RuntimeError('Injected response loss / partial failure: sensitive sentinel')
        if sql.startswith('USE '):
            self.database = sql.split('`')[1]
        if sql.startswith(('CREATE TABLE ', 'INSERT INTO ')):
            if not self.database or not self.database.startswith('jl_rehearsal_'):
                raise AssertionError('Write escaped isolation')

    def commit(self):
        self.events.append(('COMMIT', (), self.database))

    def rollback(self):
        pass


class BackupTest(unittest.TestCase):
    def test_query_normalizes_fetchall_to_list(self):
        for rows in ((), ({'id': 2}, {'id': 1}), [], [{'id': 2}, {'id': 1}]):
            with self.subTest(rows=rows):
                connection = MagicMock()
                cursor = connection.cursor.return_value.__enter__.return_value
                cursor.fetchall.return_value = rows
                result = backup.query(connection, 'SELECT synthetic WHERE id=%s', (1,))
                self.assertIsInstance(result, list)
                self.assertEqual(result, list(rows))
                cursor.execute.assert_called_once_with('SELECT synthetic WHERE id=%s', (1,))

    def test_permissions_sorts_driver_tuples_and_lists(self):
        for container in (tuple, list):
            with self.subTest(container=container.__name__):
                connection = MagicMock()
                cursor = connection.cursor.return_value.__enter__.return_value
                privileges = [{'PRIVILEGE_TYPE': 'UPDATE'}, {'PRIVILEGE_TYPE': 'SELECT'}]
                accounts = [{'User': user, 'Host': '%'} for user in reversed(backup.ACCOUNTS)]
                cursor.fetchall.side_effect = [container(privileges), container(), container(),
                                             container(), container(accounts), container(), container()]
                result = backup.permissions(connection)
                self.assertTrue(all(isinstance(rows, list) for rows in result.values()))
                self.assertEqual(result['USER_PRIVILEGES'], list(reversed(privileges)))
                self.assertEqual(result['accounts'], sorted(accounts, key=lambda row: repr(sorted(row.items()))))
                self.assertEqual(result['roles'], [])
                self.assertEqual(result['default_roles'], [])

    def test_capture_empty_driver_rows_survive_json_readback(self):
        for container in (tuple, list):
            with self.subTest(container=container.__name__):
                connection = MagicMock()
                cursor = connection.cursor.return_value.__enter__.return_value
                cursor.fetchall.side_effect = [
                    container([{'TABLE_NAME': 'synthetic', 'TABLE_TYPE': 'BASE TABLE', 'ENGINE': 'InnoDB'}]),
                    container(), container(), container(),
                    container([{'Create Table': 'CREATE TABLE `synthetic` (`id` int) ENGINE=InnoDB'}]),
                    container(), container()]
                result = backup.capture(connection, 'platform_core')
                self.assertEqual(result['synthetic']['rows'], [])
                self.assertEqual(result['synthetic']['foreign_keys'], [])
                readback = json.loads(json.dumps(result))
                self.assertEqual(readback, result)
                backup.compare(result, readback)

    def test_capture_discovers_v1_and_mobile_tables_and_normalizes_fk(self):
        names = ('accounts', 'core_schema_version', 'mobile_schema_version', 'mobile_logins', 'mobile_consents')
        def rows(c, sql, args=()):
            if 'information_schema.tables' in sql:
                return [{'TABLE_NAME': name, 'TABLE_TYPE': 'BASE TABLE', 'ENGINE': 'InnoDB'} for name in names]
            if sql.startswith('SHOW CREATE'):
                return [{'Create Table': 'synthetic canonical DDL'}]
            if sql.startswith('SELECT * FROM `'):
                return [{'id': 1}]
            if 'KEY_COLUMN_USAGE' in sql and args[1] == 'mobile_consents':
                return [{'REFERENCED_TABLE_SCHEMA': 'platform_core', 'REFERENCED_TABLE_NAME': 'accounts'}]
            return []
        with patch.object(backup, 'query', side_effect=rows):
            result = backup.capture(None, 'platform_core')
        self.assertEqual(set(result), set(names))
        self.assertEqual(result['mobile_consents']['foreign_keys'][0]['REFERENCED_TABLE_SCHEMA'], 'SELF')
        self.assertEqual(result['mobile_logins']['rows'], [{'id': 1}])

    def test_default_plan_never_imports_configuration_or_opens_files(self):
        with patch.object(Path, 'open', side_effect=AssertionError('file read')), \
                patch('app.core.database.connect', side_effect=AssertionError('DB access')), \
                patch('dotenv.dotenv_values', side_effect=AssertionError('config access')), \
                redirect_stdout(StringIO()):
            self.assertEqual(backup.main([]), 0)

    def test_restore_fk_enabled_parent_first_and_only_fresh_targets(self):
        conn = Connection()
        targets = backup.restore(conn, fixture())
        self.assertEqual(len(set(targets.values())), 2)
        sql = [event[0] for event in conn.events]
        self.assertIn('SET SESSION FOREIGN_KEY_CHECKS=1', sql)
        creates = [s for s in sql if s.startswith('CREATE TABLE')]
        self.assertTrue(creates[0].startswith('CREATE TABLE `parent`'))
        self.assertFalse(any('DROP' in s or 'GRANT' in s or 'IF NOT EXISTS' in s for s in sql))

    def test_collision_aborts_before_use_or_table_write(self):
        token = 'a' * 32
        conn = Connection(collision='jl_rehearsal_' + token + '_1')
        with self.assertRaises(RuntimeError):
            backup.restore(conn, fixture(), token=token)
        self.assertFalse(any(s.startswith(('USE', 'INSERT', 'CREATE TABLE')) for s, _, _ in conn.events))

    def test_lost_create_response_and_retry_never_reuse_database(self):
        conn = Connection(fail=lambda sql: sql.startswith('CREATE DATABASE'))
        with self.assertRaises(RuntimeError):
            backup.restore(conn, fixture(), token='b' * 32)
        self.assertIn('jl_rehearsal_' + 'b' * 32 + '_0', conn.databases)
        self.assertFalse(any(s.startswith('USE') for s, _, _ in conn.events))
        conn.fail = None
        backup.restore(conn, fixture(), token='c' * 32)
        self.assertFalse(any(db and 'b' * 32 in db for _, _, db in conn.events))

    def test_partial_table_and_commit_failures_do_not_resume(self):
        for prefix in ('INSERT INTO', 'CREATE TABLE'):
            conn = Connection(fail=lambda sql: sql.startswith(prefix))
            with self.assertRaises(RuntimeError):
                backup.restore(conn, fixture(), token='d' * 32)
            conn.fail = None
            backup.restore(conn, fixture(), token='e' * 32)
            self.assertEqual(len(conn.databases), 6)
        conn = Connection()
        with patch.object(conn, 'commit', side_effect=RuntimeError('lost commit response')):
            with self.assertRaises(RuntimeError):
                backup.restore(conn, fixture())
        backup.restore(conn, fixture())
        self.assertEqual(len(conn.databases), 6)

    def test_mismatch_detection_keeps_duplicates_schema_and_fk_separate(self):
        expected = fixture()['platform_core']
        backup.compare(expected, deepcopy(expected))
        for field, value in (('rows', [{'id': 1}, {'id': 1}]), ('schema', 'changed'), ('foreign_keys', [])):
            actual = deepcopy(expected)
            actual['child'][field] = value
            with self.assertRaises(ValueError):
                backup.compare(expected, actual)

    def test_cycle_and_qualified_ddl_rejected(self):
        data = fixture()
        data['platform_core']['parent']['foreign_keys'] = [{'REFERENCED_TABLE_NAME': 'child'}]
        with self.assertRaises(ValueError):
            backup.restore(Connection(), data)
        data = fixture()
        data['platform_core']['child']['schema'] += '; DROP DATABASE platform_core'
        conn = Connection()
        with self.assertRaises(ValueError):
            backup.restore(conn, data)
        self.assertFalse(any('DROP' in s for s, _, _ in conn.events))

    def test_end_to_end_mock_readback_result_and_exclusive_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.mobile-backups').mkdir()
            evidence = root / 'evidence.txt'
            evidence.write_text('synthetic operator evidence', encoding='utf-8')
            directory = root / '.mobile-backups' / 'before'
            conn = Connection()
            data = fixture()
            data['platform_core']['parent']['rows'][0].update(
                payload=b'\x00\xffsynthetic-ciphertext', created=datetime(2026, 1, 1, 0, 0, 0, 123456))
            def capture(c, db):
                if db in data:
                    return deepcopy(data[db])
                return deepcopy(data[backup.DATABASES[int(db[-1])]])
            with patch.object(backup, 'ROOT', root), \
                    patch('app.core.database.connect', return_value=conn), \
                    patch('scripts.local_mysql.protect') as protect, \
                    patch.object(backup.subprocess, 'run') as git, \
                    patch.object(backup, 'permissions', return_value={'synthetic': True}), \
                    patch.object(backup, 'capture', side_effect=capture):
                git.return_value.returncode = 0
                backup.run(directory, evidence)
                self.assertTrue((directory / 'result.json').is_file())
                self.assertIn('NOT_RUN', (directory / 'result.json').read_text())
                self.assertEqual(protect.call_count, 4)
                count = len(conn.events)
                with self.assertRaises(FileExistsError):
                    backup.run(directory, evidence)
                self.assertEqual(len(conn.events), count)

    def test_git_exclusion_failure_prevents_database_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = root / 'evidence.txt'
            evidence.touch()
            with patch.object(backup, 'ROOT', root), \
                    patch('scripts.local_mysql.protect'), \
                    patch.object(backup.subprocess, 'run') as git, \
                    patch('app.core.database.connect') as connect:
                git.return_value.returncode = 1
                with self.assertRaises(ValueError):
                    backup.run(root / '.mobile-backups' / 'attempt', evidence)
                connect.assert_not_called()

    def test_failed_privilege_verification_leaves_no_success_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = root / 'evidence.txt'
            evidence.touch()
            directory = root / '.mobile-backups' / 'attempt'
            data = fixture()
            with patch.object(backup, 'ROOT', root), \
                    patch('scripts.local_mysql.protect'), \
                    patch.object(backup.subprocess, 'run') as git, \
                    patch('app.core.database.connect', return_value=Connection()), \
                    patch.object(backup, 'permissions', side_effect=[{'p': 1}, {'p': 2}]), \
                    patch.object(backup, 'capture', side_effect=lambda c, db: deepcopy(
                        data[db] if db in data else data[backup.DATABASES[int(db[-1])]])):
                git.return_value.returncode = 0
                with self.assertRaises(ValueError):
                    backup.run(directory, evidence)
                self.assertTrue((directory / 'attempt.json').is_file())
                self.assertFalse((directory / 'result.json').exists())

    def test_failure_redacts_exception_and_no_false_pass(self):
        output = StringIO()
        with patch.object(backup, 'run', side_effect=RuntimeError('sensitive sentinel')), redirect_stdout(output):
            self.assertEqual(backup.main(['rehearse', '--directory', 'synthetic']), 1)
        self.assertNotIn('sensitive sentinel', output.getvalue())
        self.assertNotIn('PASS', output.getvalue())

    def test_each_failure_stage_is_the_only_cli_output(self):
        # All paths and evidence are synthetic; every DB/Git/ACL boundary is mocked.
        cases = (
            ('protect_directory', 'scripts.local_mysql.protect', 1),
            ('git_ignore', 'scripts.mobile_backup.subprocess.run', 1),
            ('db_connect', 'app.core.database.connect', 1),
            ('permissions', 'scripts.mobile_backup.permissions', 1),
            ('permissions', 'scripts.mobile_backup.permissions', 2),
            ('capture', 'scripts.mobile_backup.capture', 1),
            ('capture', 'scripts.mobile_backup.capture', 3),
            ('snapshot_write', 'scripts.mobile_backup.json.dump', 1),
            ('snapshot_readback', 'scripts.mobile_backup.json.loads', 1),
            ('restore', 'scripts.mobile_backup.json.dump', 2),
            ('restore', 'scripts.mobile_backup.restore', 1),
            ('compare', 'scripts.mobile_backup.compare', 1),
            ('result_write', 'scripts.mobile_backup.json.dump', 3),
        )
        for stage, target, nth in cases:
            with self.subTest(stage=stage, target=target, nth=nth), \
                    tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
                root = Path(temp)
                evidence = root / 'synthetic-evidence'
                evidence.touch()
                directory = root / '.mobile-backups' / 'new'
                stack.enter_context(patch.object(backup, 'ROOT', root))
                stack.enter_context(patch('scripts.local_mysql.protect'))
                stack.enter_context(patch.object(backup.subprocess, 'run')).return_value.returncode = 0
                stack.enter_context(patch('app.core.database.connect', return_value=Connection()))
                stack.enter_context(patch.object(backup, 'permissions', return_value={'p': 1}))
                stack.enter_context(patch.object(backup, 'capture', side_effect=lambda c, db: deepcopy(
                    fixture()[db] if db in backup.DATABASES else fixture()[backup.DATABASES[int(db[-1])]])))
                stack.enter_context(patch.object(backup, 'restore', return_value={
                    db: 'synthetic_' + str(i) for i, db in enumerate(backup.DATABASES)}))
                # Preserve the successful behavior until the selected invocation.
                from pkgutil import resolve_name
                original = resolve_name(target)
                calls = 0
                def fail_at(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == nth:
                        raise RuntimeError('sensitive sentinel SQL settings backup payload')
                    return original(*args, **kwargs)
                stack.enter_context(patch(target, side_effect=fail_at))
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = backup.main(['rehearse', '--directory', str(directory),
                                        '--write-stop-evidence', str(evidence)])
                self.assertEqual(code, 1)
                self.assertEqual(stdout.getvalue(), (
                    'permissions_unclassified' if stage == 'permissions' else stage) + '\n')
                self.assertEqual(stderr.getvalue(), '')
                self.assertFalse((directory / 'result.json').exists() and stage != 'result_write')
                self.assertTrue(evidence.is_file())

    def test_rehearse_cli_forwards_only_directory_and_evidence(self):
        with patch.object(backup, 'run') as run, redirect_stdout(StringIO()):
            self.assertEqual(backup.main(['rehearse', '--directory', 'synthetic',
                                          '--write-stop-evidence', 'evidence']), 0)
            run.assert_called_once_with('synthetic', 'evidence')
        with patch.object(backup, 'run') as run, redirect_stdout(StringIO()):
            self.assertEqual(backup.main(['rehearse']), 1)
            run.assert_not_called()

    def test_permission_diagnostics_are_fixed_and_fail_closed(self):
        def valid(c, sql, args=()):
            if 'mysql.user' in sql:
                return [{'User': user, 'Host': '%'} for user in backup.ACCOUNTS]
            return []

        cases = []
        for index, target in enumerate(backup.PERMISSION_TARGETS):
            def make_failure(index):
                calls = 0
                def fail(c, sql, args=()):
                    nonlocal calls
                    current = calls
                    calls += 1
                    if current == index:
                        raise RuntimeError('sensitive sentinel SQL credentials payload')
                    return valid(c, sql, args)
                return fail
            cases.append(('permissions_query_' + target.lower(), make_failure(index)))
        for code, target, rows in (
            ('permissions_account_missing', 'mysql.user', []),
            ('permissions_unexpected_host', 'mysql.user', [{'User': u, 'Host': 'synthetic'} for u in backup.ACCOUNTS]),
            ('permissions_roles_present', 'mysql.role_edges', [{'synthetic': True}]),
            ('permissions_roles_present', 'mysql.default_roles', [{'synthetic': True}]),
            ('permissions_unclassified', 'mysql.user', [{}]),
        ):
            cases.append((code, lambda c, sql, args=(), target=target, rows=rows:
                          deepcopy(rows) if target in sql else valid(c, sql, args)))
        for code, response in cases:
            with self.subTest(code=code):
                stdout, stderr = StringIO(), StringIO()
                def run(*args):
                    try:
                        backup.permissions(None)
                    except Exception as error:
                        error.mobile_backup_stage = 'permissions'
                        raise
                with patch.object(backup, 'query', side_effect=response) as query, \
                        patch.object(backup, 'run', side_effect=run), \
                        redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(backup.main(['rehearse', '--directory', 'synthetic']), 1)
                self.assertEqual(stdout.getvalue(), code + '\n')
                self.assertEqual(stderr.getvalue(), '')
                self.assertLessEqual(query.call_count, 7)

    def test_account_roles_or_missing_accounts_fail_closed(self):
        def result(c, sql, args=()):
            if 'mysql.user' in sql:
                return [{'User': user, 'Host': '%'} for user in backup.ACCOUNTS]
            return []
        with patch.object(backup, 'query', side_effect=result):
            self.assertEqual(len(backup.permissions(None)['accounts']), 3)
        with patch.object(backup, 'query', return_value=[]):
            with self.assertRaises(ValueError):
                backup.permissions(None)


if __name__ == '__main__':
    unittest.main()
