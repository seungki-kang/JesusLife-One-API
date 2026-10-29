import unittest
from unittest.mock import patch

from app.core.database import connect


class LocalDatabaseConfigurationTest(unittest.TestCase):
    def test_mariadb_port_or_external_host_never_connect(self):
        for config in ({'MYSQL_HOST': '127.0.0.1', 'MYSQL_PORT': '3306'},
                       {'MYSQL_HOST': '192.0.2.1', 'MYSQL_PORT': '3307'}):
            with patch('app.core.database.settings', return_value=config), \
                    patch('app.core.database.pymysql.connect') as driver:
                with self.assertRaises(ValueError):
                    connect()
                driver.assert_not_called()

    def test_unknown_backend_does_not_fall_back_to_memory(self):
        from app.modules.neorang_narang.store import get_completion_store
        from fastapi import HTTPException
        with patch('app.core.database.settings', return_value={'COMPLETION_STORE': 'invalid'}):
            with self.assertRaises(HTTPException) as caught:
                get_completion_store()
        self.assertEqual(caught.exception.status_code, 503)
