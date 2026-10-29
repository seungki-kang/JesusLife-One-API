"""Fixed vocabulary only: never log request values or exception text."""
from contextlib import contextmanager
import logging

logger = logging.getLogger('uvicorn.error')


@contextmanager
def stage(name, *, flow='callback'):
    try:
        yield
    except Exception:
        logger.warning('auth_%s stage=%s result=FAIL', flow, name)
        raise
    else:
        logger.info('auth_%s stage=%s result=PASS', flow, name)


class CallbackQueryFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn's access logger receives (client, method, target, version, status).
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str) and args[2].split('?', 1)[0].startswith('/api/v1/auth/callback'):
                args[2] = args[2].split('?', 1)[0]
                record.args = tuple(args)
        return True


def protect_access_log():
    access = logging.getLogger('uvicorn.access')
    if not any(isinstance(f, CallbackQueryFilter) for f in access.filters):
        access.addFilter(CallbackQueryFilter())
