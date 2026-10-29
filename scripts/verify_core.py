"""Synthetic integration runner with all failure payloads/credentials suppressed."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import unittest

from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException

from app.core.auth0_poc import OfflineAccessVerifier, OfflineSessionGate
from app.core.core_store import CoreStore
from app.core.database import ROOT
from scripts.auth0_pc_settings import validate
from scripts.core_mysql import local_config, backup_verify, verify_products
from app.core.database import connect


def restart_check(path):
    cfg = validate(local_config() | {'AUTH0_ISSUER':'https://synthetic.auth0.com/',
                   'AUTH0_CLIENT_ID':'synthetic-pc-client','AUTH0_CLIENT_SECRET':'synthetic-only'})
    store = CoreStore(cfg.encryption_key,cfg.hmac_key)
    proof = json.loads(Path(path).read_text(encoding='utf-8'))
    key = serialization.load_pem_public_key(proof['public'].encode())
    gate = OfflineSessionGate(OfflineAccessVerifier(cfg.policy,{'synthetic-key':key},cfg.hmac_key),store)
    raw = store.decrypt(base64.b64decode(proof['revoked']),b'restart-proof')
    try:
        gate.authorize(raw,required_scope='neorang-narang:read',now=proof['now'])
    except HTTPException as error:
        if error.status_code != 401:
            raise
    else:
        raise RuntimeError('Revoked token accepted')
    active = store.decrypt(base64.b64decode(proof['active']),b'restart-proof')
    gate.authorize(active,required_scope='neorang-narang:read',now=proof['now'])
    # A fresh process renders the same cookie-backed server status through HTTP.
    from fastapi.testclient import TestClient
    from app.auth0_pc import PcRuntime, create_app, ORIGIN
    class VerifiedProvider:
        def verify_access(self, raw, *, now):
            return gate.verifier.verify(raw, now=now)
    runtime = PcRuntime(cfg, store=store, provider=VerifiedProvider(), clock=lambda: proof['now'])
    with TestClient(create_app(runtime), base_url=ORIGIN) as client:
        for name, expected, status in (('active_cookie', '유효', 200),
                                       ('revoked_cookie', '유효하지 않음', 401)):
            cookie = store.decrypt(base64.b64decode(proof[name]), b'restart-proof')
            client.cookies.set('jl_pc_session', cookie)
            response = client.get('/auth/poc/')
            if ('id="session-state">' + expected not in response.text
                    or client.get('/api/v1/me').status_code != status):
                raise RuntimeError('Restart page verification failed')
    print('PASS: new Python process preserved active and revoked session state')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=('tests','restart-check','backup-verify'))
    parser.add_argument('proof',nargs='?')
    args = parser.parse_args()
    try:
        if args.action == 'restart-check':
            restart_check(args.proof)
        elif args.action == 'backup-verify':
            backup_verify()
        else:
            os.environ['RUN_MYSQL_TESTS']='1'
            os.environ['RUN_CORE_TESTS']='1'
            result = unittest.TextTestRunner(stream=io.StringIO(),verbosity=2).run(
                unittest.defaultTestLoader.discover(str(ROOT/'tests')))
            for case,_ in result.failures+result.errors:
                print('FAIL:',case.id())
            print('Tests:',result.testsRun,'failures:',len(result.failures),'errors:',len(result.errors),'skipped:',len(result.skipped))
            if not result.wasSuccessful():
                raise RuntimeError('Synthetic tests failed')
            with connect(admin=True) as root:
                verify_products(root)
            print('PASS: full synthetic suite and pre-existing product preservation')
    except Exception as error:
        print('FAIL:',args.action,type(error).__name__,'(details suppressed)')
        raise SystemExit(1) from None


if __name__=='__main__':
    main()
