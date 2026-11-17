"""Single-process development callback relay; restart invalidates pending logins."""
from threading import Lock
import secrets

from .auth0_poc import denied
from .core_store import digest


class DevelopmentRelay:
    def __init__(self):
        self._lock = Lock()
        self._pending = {}

    def _prune(self, now):
        self._pending = {k: v for k, v in self._pending.items() if v['expires'] > now}

    def begin(self, state, browser, now):
        with self._lock:
            self._prune(now)
            key = digest(state)
            if key in self._pending or len(self._pending) >= 256:
                raise denied()
            self._pending[key] = dict(state=state, browser=digest(browser), expires=now+300,
                                      ticket=None, code=None)

    def receive(self, state, code, now):
        with self._lock:
            self._prune(now)
            row = self._pending.get(digest(state))
            if row is None or row['ticket'] is not None:
                raise denied()
            ticket = secrets.token_urlsafe(32)
            row.update(ticket=digest(ticket), code=code, expires=min(row['expires'], now+60))
            return ticket

    def consume(self, ticket, browser, now):
        if not browser:
            raise denied()
        with self._lock:
            self._prune(now)
            for key, row in self._pending.items():
                if row['ticket'] == digest(ticket):
                    if not secrets.compare_digest(row['browser'], digest(browser)):
                        raise denied()
                    del self._pending[key]  # Claim atomically before provider/DB work.
                    return row['state'], row['code']
            raise denied()
