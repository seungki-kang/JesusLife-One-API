"""Environment/endpoint regressions with mocked transport; no network I/O."""
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.postgres_rls_support import isolated_environment, local_connect
from scripts.verify_postgres_rls import launch_worker, worker


class PostgresRlsIsolationTest(unittest.TestCase):
    def test_parent_pg_environment_never_reaches_python_worker(self):
        parent = {'PATH': 'synthetic_path', 'SYSTEMROOT': 'synthetic_root',
                  'PGHOSTADDR': '192.0.2.1', 'PGHOST': 'synthetic.invalid',
                  'PGPORT': '1', 'PGSERVICE': 'synthetic_service',
                  'PGOPTIONS': '-c role=synthetic_role', 'pgpassword': 'synthetic'}
        with patch.dict(os.environ, parent, clear=True), \
                patch('subprocess.run', return_value=Mock(returncode=0)) as run:
            self.assertEqual(launch_worker(Path('synthetic-bin')), 0)
        child = run.call_args.kwargs['env']
        self.assertEqual(child, {'PATH': 'synthetic_path', 'SYSTEMROOT': 'synthetic_root'})
        self.assertIn('--worker', run.call_args.args[0])
        self.assertFalse(any(key.upper().startswith('PG') for key in child))
        self.assertEqual(isolated_environment(child), child)

    def test_tcp_host_hostaddr_port_are_pinned_without_network(self):
        with patch.dict(os.environ, {}, clear=True), patch('psycopg.connect') as connect:
            local_connect('postgresql://synthetic:synthetic@127.0.0.1:6543/postgres',
                          port=6543, host='synthetic.invalid', hostaddr='192.0.2.1')
        self.assertEqual(connect.call_args.kwargs,
                         {'port': 6543, 'host': '127.0.0.1', 'hostaddr': '127.0.0.1'})

    def test_unsanitized_worker_and_connection_fail_before_any_connect(self):
        with patch.dict(os.environ, {'PGHOSTADDR': '192.0.2.1'}, clear=True), \
                patch('psycopg.connect') as connect:
            with self.assertRaises(RuntimeError):
                local_connect(port=6543)
            with self.assertRaises(RuntimeError):
                worker(Path('synthetic-bin'))
            connect.assert_not_called()
