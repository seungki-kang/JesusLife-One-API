"""Two app auth, no optional feature grants. Disposable real DB opt-in."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import secrets
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth0_poc import PocTokenPolicy, pkce_challenge
from app.core.common_mobile_auth import CommonMobileAuthStore, MobileRegistration, PROFILES, install_common_mobile
from tools.chgo_server.mock_oidc import LocalOIDC

ADMIN_CONNECT = RUNTIME_CONNECT = None
NOW = 1_800_000_000
ORIGIN = 'http://127.0.0.1:8000'


class MobileOptInTest(unittest.TestCase):
    def test_default_install_has_no_mobile_or_bible_routes(self):
        app = FastAPI()
        install_common_mobile(app)
        with TestClient(app) as client:
            for path in ('/api/v1/mobile/life-diary/login-transactions',
                         '/api/v1/mobile/neorang-narang/login-transactions',
                         '/api/v1/mobile/jl-bible/login-transactions'):
                self.assertEqual(client.post(path, json={}).status_code, 404)

    def test_bible_is_not_activated_by_client_or_server_candidate(self):
        with self.assertRaises(ValueError):
            install_common_mobile(FastAPI(), (MobileRegistration('jl_bible','synthetic',None,True),))
        unused = MagicMock()
        install_common_mobile(FastAPI(), (MobileRegistration('life_diary','synthetic',unused),))
        unused.assert_not_called()


class MobilePostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ADMIN_CONNECT is None or RUNTIME_CONNECT is None:
            raise unittest.SkipTest('Disposable mobile PostgreSQL harness required')

    def setUp(self):
        self.app = FastAPI()
        self.clock = [NOW]
        self.providers = {}
        registrations = []
        for app_id in PROFILES:
            client_id = 'synthetic-mobile-' + app_id
            config = SimpleNamespace(policy=PocTokenPolicy('https://synthetic-common.auth0.com/',
                'urn:jesuslife:synthetic-api',frozenset({client_id})),
                hmac_key=secrets.token_bytes(32),client_secret=secrets.token_urlsafe(32))
            provider = LocalOIDC(config)
            self.providers[app_id] = provider
            store = CommonMobileAuthStore(secrets.token_bytes(32),config.hmac_key,
                                           connector=RUNTIME_CONNECT,app_id=app_id)
            runtime = SimpleNamespace(config=config,provider=provider.provider,store=store,now=lambda:self.clock[0])
            registrations.append(MobileRegistration(app_id,client_id,runtime,True))
            with ADMIN_CONNECT() as db:
                db.execute('INSERT INTO jl_core_auth.app_bindings VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                    (app_id.encode(),client_id.encode(),PROFILES[app_id][1].encode()))
        install_common_mobile(self.app, registrations)

    def binding(self, app):
        return {'app_id':app,'client_id':'synthetic-mobile-'+app,'return_uri':PROFILES[app][2]}

    def handoff(self, client, app='life_diary', subject=None, wrong_nonce=False):
        verifier = secrets.token_urlsafe(32)
        prefix, callback, _ = PROFILES[app]
        response = client.post(prefix+'/login-transactions',json=self.binding(app)|{'challenge':pkce_challenge(verifier)})
        self.assertEqual(response.status_code, 200)
        transaction = response.json()['transaction']
        authorize = client.get(response.json()['authorize_url'],follow_redirects=False)
        self.assertEqual(authorize.status_code, 303)
        self.assertEqual(parse_qs(urlsplit(authorize.headers['location']).query)['scope'], ['openid'])
        subject = subject or str(uuid4())
        code, state = self.providers[app].issue(authorize.headers['location'],subject,wrong_nonce=wrong_nonce)
        callback_result = client.get(urlsplit(callback).path,params={'code':code,'state':state},follow_redirects=False)
        if wrong_nonce:
            return callback_result, None
        self.assertEqual(callback_result.status_code, 303)
        location = callback_result.headers['location']
        self.assertNotIn(self.providers[app].issued[subject], location)
        query = parse_qs(urlsplit(location).query)
        self.assertEqual(query['transaction'], [transaction])
        return callback_result, self.binding(app)|{'transaction':transaction,'code':query['code'][0],'verifier':verifier}

    def exchange(self, client, app='life_diary', subject=None):
        _, body = self.handoff(client,app,subject)
        response = client.post(PROFILES[app][0]+'/session-exchange',json=body)
        self.assertEqual(response.status_code,200)
        return response.json(), body

    def test_life_diary_exact_client_contract_and_logout(self):
        prefix = PROFILES['life_diary'][0]
        with TestClient(self.app,base_url=ORIGIN) as client:
            token, _ = self.exchange(client)
            headers = {'Authorization':'Bearer '+token['access_token']}
            response = client.get(prefix+'/session',headers=headers)
            self.assertEqual(response.json(),{'sub':token['sub'],'app_id':'life_diary'})
            self.assertEqual(client.post(prefix+'/logout',headers=headers).status_code,204)
            self.assertEqual(client.get(prefix+'/session',headers=headers).status_code,401)

    def test_two_apps_same_account_but_separate_sessions_and_no_consent_granted(self):
        subject = str(uuid4())
        with ADMIN_CONNECT() as db:
            before = db.execute('SELECT count(*) FROM jl_core_auth.product_consents').fetchone()
        with TestClient(self.app,base_url=ORIGIN) as client:
            ld, _ = self.exchange(client,'life_diary',subject)
            nn, _ = self.exchange(client,'neorang_narang',subject)
            self.assertEqual(ld['sub'],nn['sub'])
            ld_header = {'Authorization':'Bearer '+ld['access_token']}
            nn_header = {'Authorization':'Bearer '+nn['access_token']}
            self.assertEqual(client.get(PROFILES['life_diary'][0]+'/session',headers=nn_header).status_code,401)
            self.assertEqual(client.post(PROFILES['neorang_narang'][0]+'/logout',headers=nn_header).status_code,204)
            self.assertEqual(client.get(PROFILES['life_diary'][0]+'/session',headers=ld_header).status_code,200)
            for path in ('/api/v1/mobile/consent','/api/v1/mobile/jl-bible/login-transactions',
                         '/api/v1/mobile/life-diary/backups','/api/v1/chgo/recommendations'):
                self.assertEqual(client.post(path,json={},headers=ld_header).status_code,404)
        with ADMIN_CONNECT() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jl_core_auth.product_consents').fetchone(),before)

    def test_wrong_verifier_or_app_rejected_then_correct_exchange_is_single_use(self):
        prefix = PROFILES['life_diary'][0]
        with TestClient(self.app,base_url=ORIGIN) as client:
            _, body = self.handoff(client)
            self.assertEqual(client.post(prefix+'/session-exchange',json=body|{'verifier':secrets.token_urlsafe(32)}).status_code,401)
            self.assertEqual(client.post(prefix+'/session-exchange',json=body|{'app_id':'jl_bible'}).status_code,401)
            self.assertEqual(client.post(prefix+'/session-exchange',json=body).status_code,200)
            self.assertEqual(client.post(prefix+'/session-exchange',json=body).status_code,401)

    def test_concurrent_exchange_only_one_winner(self):
        with TestClient(self.app,base_url=ORIGIN) as client:
            _, body = self.handoff(client)
        barrier = Barrier(2)
        def attempt(_):
            with TestClient(self.app,base_url=ORIGIN) as client:
                barrier.wait(timeout=5)
                return client.post(PROFILES['life_diary'][0]+'/session-exchange',json=body).status_code
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(attempt,range(2))),[200,401])

    def test_handoff_expiry_and_wrong_nonce_are_rejected(self):
        with TestClient(self.app,base_url=ORIGIN) as client:
            rejected, _ = self.handoff(client,wrong_nonce=True)
            self.assertEqual(rejected.status_code,401)
            _, body = self.handoff(client)
            self.clock[0] += 61
            self.assertEqual(client.post(PROFILES['life_diary'][0]+'/session-exchange',json=body).status_code,401)
