"""Ephemeral, cookie-bound acceptance evidence. Never an authentication source."""
import secrets
import time
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException

from app.core.core_store import digest


class AcceptanceRuns:
    def __init__(self, clock=time.time):
        self.clock, self.runs, self.lock = clock, {}, RLock()

    def start(self, owner, session):
        with self.lock:
            self.runs = {k: v for k, v in self.runs.items() if v['expires'] > self.clock()}
            if len(self.runs) >= 32:
                raise HTTPException(409, 'Acceptance capacity reached')
            key = secrets.token_urlsafe(32)
            self.runs[digest(key)] = dict(expires=self.clock()+3600, a=owner, b=None,
                session=digest(session), logged_out=False, same=False, consent=set(),
                ids={label: str(uuid4()) for label in ('A', 'B', 'shared')},
                seeded=set(), results={}, verified_after_foreign=set())
            return key

    def get(self, key):
        run = self.runs.get(digest(key)) if key else None
        if run is None or run['expires'] <= self.clock():
            raise HTTPException(409, 'Acceptance run unavailable; start again')
        return run

    def logout(self, key, session):
        with self.lock:
            try:
                run = self.get(key)
            except HTTPException:
                return
            if run['session'] == digest(session):
                run['logged_out'] = True

    def compare(self, run, owner, session):
        if not run['logged_out'] or digest(session) == run['session']:
            raise HTTPException(409, 'Log out and sign in again first')
        same = owner == run['a']
        if same:
            run['same'] = True
        elif run['same'] and run['b'] is None:
            run['b'] = owner
        return {'same_account': same, 'distinct_b': run['b'] == owner and not same}

    @staticmethod
    def label(run, owner):
        if owner == run['a']:
            return 'A'
        if owner == run['b']:
            return 'B'
        raise HTTPException(409, 'Compare the account first')


def metadata(record_id, revision=1):
    return dict(id=record_id, course_number=1, participation_mode='solo',
                completed_at='2099-01-01T00:00:00Z', revision=revision, deleted_at=None)


async def check_records(client, run, label):
    """Exercise public HTTP contracts; return only PASS/FAIL, never response bodies.

    Only randomly generated IDs in this run are mutated. Existing records are
    never selected as mutation targets. Soft deletions retain synthetic evidence.
    """
    base = '/api/v1/neorang-narang/completions'
    results = {}

    async def expect(name, method, path, status, body=None, predicate=None):
        response = await client.request(method, base+path, json=body)
        ok = response.status_code == status
        if ok and predicate:
            ok = predicate(response.json())
        results[name] = 'PASS' if ok else 'FAIL'
        if not ok:
            raise HTTPException(409, 'Acceptance check failed')

    try:
        own = run['ids'][label]
        if label not in run['seeded']:
            await expect('fresh_id', 'GET', '/'+own, 404)
            await expect('create', 'POST', '', 201, metadata(own))
            run['seeded'].add(label)
        await expect('own_get', 'GET', '/'+own, 200, predicate=lambda x: x == metadata(own))
        await expect('own_create_retry', 'POST', '', 200, metadata(own), lambda x: x['replayed'])
        other = 'B' if label == 'A' else 'A'
        if run['results'].get(other, {}).get('foreign_delete_retry_1') == 'PASS':
            run['verified_after_foreign'].add(label)
        foreign = run['ids'][other]
        await expect('list', 'GET', '?limit=20', 200, predicate=lambda rows:
                     own in [r['id'] for r in rows] and foreign not in [r['id'] for r in rows])
        if other in run['seeded']:
            await expect('foreign_get', 'GET', '/'+foreign, 404)
            for attempt in range(2):
                await expect('foreign_update_retry_'+str(attempt), 'PUT', '/'+foreign, 404,
                             dict(base_revision=1, metadata=metadata(foreign, 2)))
                await expect('foreign_delete_retry_'+str(attempt), 'DELETE', '/'+foreign, 404,
                             dict(base_revision=1, revision=2))
        # The same record ID belongs independently to each authenticated owner.
        shared = run['ids']['shared']
        if run['results'].get(label, {}).get('delete_retry') != 'PASS':
            await expect('shared_fresh', 'GET', '/'+shared, 404)
            await expect('shared_create', 'POST', '', 201, metadata(shared))
            await expect('shared_create_retry', 'POST', '', 200, metadata(shared), lambda x: x['replayed'])
            update = dict(base_revision=1, metadata=metadata(shared, 2))
            await expect('update', 'PUT', '/'+shared, 200, update)
            await expect('stale_update_retry', 'PUT', '/'+shared, 409, update)
            deletion = dict(base_revision=2, revision=3)
            await expect('delete', 'DELETE', '/'+shared, 200, deletion)
            await expect('delete_retry', 'DELETE', '/'+shared, 200, deletion, lambda x: x['replayed'])
            await expect('deleted_get', 'GET', '/'+shared, 404)
            await expect('deleted_create_retry', 'POST', '', 409, metadata(shared))
    except Exception:
        results['completed'] = 'FAIL'
    run['results'].setdefault(label, {}).update(results)
    return dict(run['results'][label])
