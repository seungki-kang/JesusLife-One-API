"""Migration orchestration mocks; no MySQL, DDL or GRANT is executed."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from scripts import mobile_mysql as migration


class FakeConnection:
    def __init__(self):
        self.database = None
        self.events = []
        self.fail_table = None
        self.fail_grant = False
        self.grants = 0
        self.state = {
            'platform_core': {'core_schema_version': self.table('core_schema_version', [{'version': 1}]),
                              'accounts': self.table('accounts', [])},
            'neorang_narang': {'nn_schema_version': self.table('nn_schema_version', [{'version': 1}])}}
        for database, path in migration.BASE_MIGRATIONS.items():
            for sql in migration.statements(path.read_text(encoding='utf-8')):
                name = migration.table_name(sql)
                if name:
                    self.state[database].setdefault(name, self.table(name))

    @staticmethod
    def table(name, rows=None):
        return {'schema': 'canonical-' + name, 'rows': rows or []}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def cursor(self):
        return self

    def commit(self):
        self.events.append(('commit', self.database))

    def fetchone(self):
        return {'acquired': 1}

    def execute(self, sql, args=()):
        self.events.append((sql, self.database))
        if sql.startswith('USE '):
            self.database = sql[4:].strip('`')
        elif sql.startswith('CREATE TABLE ') and self.database in self.state:
            table = re.match(r'CREATE TABLE ([a-z_]+)', sql)[1]
            if table == self.fail_table:
                raise RuntimeError('Injected partial DDL failure')
            if table in self.state[self.database]:
                raise AssertionError('Retry recreated existing table')
            self.state[self.database][table] = self.table(table)
        elif sql.startswith('INSERT INTO mobile_schema_version'):
            self.state['platform_core']['mobile_schema_version']['rows'] = [{'version': 1}]
        elif sql.startswith('GRANT '):
            self.grants += 1
            if self.fail_grant and self.grants == 2:
                raise RuntimeError('Injected GRANT failure after first grant')


class MobileMigrationTest(unittest.TestCase):
    def setUp(self):
        self.connection = FakeConnection()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.attempt = 0
        self.output = StringIO()

    def apply(self):
        self.attempt += 1
        with redirect_stdout(self.output), \
                patch.object(migration, 'connect', return_value=self.connection), \
                patch.object(migration, 'protect'), \
                patch.object(migration, 'inventory', side_effect=lambda c, db: deepcopy(c.state[db])), \
                patch.object(migration, 'shape', side_effect=lambda c, table: 'canonical-' + table):
            migration.apply(backup_directory=Path(self.temp.name)/str(self.attempt), acknowledged=True)

    def target_creates(self):
        return [sql for sql, db in self.connection.events
                if db in migration.MIGRATIONS and sql.startswith('CREATE TABLE ')]

    def test_partial_apply_then_retry_preserves_existing_tables(self):
        self.connection.fail_table = 'mobile_consents'
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertIn('mobile_logins', self.connection.state['platform_core'])
        self.assertEqual(self.connection.state['platform_core']['mobile_schema_version']['rows'], [])
        self.connection.fail_table = None
        self.apply()
        self.assertEqual(self.connection.state['platform_core']['mobile_schema_version']['rows'], [{'version': 1}])
        self.assertEqual(sum(sql.startswith('CREATE TABLE mobile_logins') for sql in self.target_creates()), 1)

    def test_unknown_product_shape_fails_before_any_target_ddl(self):
        self.connection.state['neorang_narang']['nn_mobile_synthetic'] = {'schema': 'unknown', 'rows': []}
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.target_creates(), [])

    def test_unknown_marker_fails_before_layout_or_target_ddl(self):
        self.connection.state['platform_core']['mobile_schema_version'] = FakeConnection.table(
            'mobile_schema_version', [{'version': 99}])
        with self.assertRaises(ValueError):
            self.apply()
        self.assertFalse(any(sql.startswith('CREATE ') for sql, _ in self.connection.events))

    def test_grant_failure_keeps_marker_but_is_not_success_and_retry_works(self):
        self.connection.fail_grant = True
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertEqual(self.connection.state['platform_core']['mobile_schema_version']['rows'], [{'version': 1}])
        self.assertNotIn('PASS:', self.output.getvalue())
        self.assertEqual(self.connection.grants, 2)
        count = len(self.target_creates())
        self.connection.fail_grant = False
        self.apply()
        self.assertEqual(len(self.target_creates()), count)
        self.assertTrue(any(sql.startswith('SELECT RELEASE_LOCK') for sql, _ in self.connection.events))

    def test_unknown_core_shape_also_fails_before_target_ddl(self):
        self.connection.state['platform_core']['mobile_logins'] = {'schema': 'unknown', 'rows': []}
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.target_creates(), [])

    def test_unknown_base_shape_fails_before_target_ddl(self):
        self.connection.state['platform_core']['accounts']['schema'] = 'unknown'
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.target_creates(), [])

    def test_missing_v1_table_fails_before_target_ddl(self):
        del self.connection.state['neorang_narang']['nn_completion_records']
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.target_creates(), [])

    def test_future_base_versions_fail_before_any_ddl(self):
        for database, marker in (('platform_core', 'core_schema_version'),
                                 ('neorang_narang', 'nn_schema_version')):
            with self.subTest(database=database):
                self.connection = FakeConnection()
                self.connection.state[database][marker]['rows'] = [{'version': 2}]
                with self.assertRaises(ValueError):
                    self.apply()
                self.assertFalse(any(sql.startswith('CREATE ') for sql, _ in self.connection.events))
