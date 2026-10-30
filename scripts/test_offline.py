"""Run API tests without environment files, inherited secrets or external I/O.

Only synthetic SQLite files in temporary directories are used. MySQL opt-in
tests remain skipped. This runner does not import configured apps until guards
are installed.
"""
import os
from pathlib import Path
import sys
import socket
import unittest
from unittest.mock import patch


def main():
    retained = {k: v for k, v in os.environ.items()
                if k.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH'}}
    os.environ.clear()
    os.environ.update(retained)
    os.environ['COMPLETION_STORE'] = 'memory'

    def audit(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            name = Path(os.fsdecode(args[0])).name.lower()
            if name == '.env' or name.startswith('.env.'):
                raise RuntimeError('Offline guard: environment file access denied')
        # Windows asyncio uses the stdlib socketpair fallback for its wakeup
        # pipe. Permit only that implementation's own loopback connection.
        internal_pair = (event == 'socket.connect'
                         and sys._getframe(1).f_code is getattr(socket.socketpair, '__code__', None)
                         and args[1][0] in ('127.0.0.1', '::1'))
        if event in {'socket.connect', 'socket.getaddrinfo'} and not internal_pair:
            raise RuntimeError('Offline guard: network access denied')

    sys.addaudithook(audit)
    with patch('dotenv.dotenv_values', return_value={}), \
            patch('pymysql.connect', side_effect=RuntimeError('Offline guard: MySQL denied')):
        suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
