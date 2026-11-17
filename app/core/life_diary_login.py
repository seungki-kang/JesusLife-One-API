"""Disabled-by-default Android login draft. No diary data or provider setup I/O."""
from dataclasses import dataclass
import re
import secrets
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from .auth0_poc import denied, pkce_challenge, validate_binding_candidate
from .core_store import stamp, utc
from .mobile_routes import Start, Exchange

APP_ID = 'life_diary'
RETURN_URI = 'jesuslife-life-diary-poc://auth/complete/android'
CALLBACK = 'http://127.0.0.1:8000/api/v1/auth/callback/life-diary/android'
PREFIX = '/api/v1/mobile/life-diary'
DEVELOPMENT_CALLBACK = 'https://unwary-founder-peculiar.ngrok-free.dev/api/v1/auth/callback/life-diary/android'
COMPLETE = '/api/v1/auth/callback/life-diary/android/complete'


@dataclass(frozen=True)
class Registration:
    # Server-owned registration; request fields never select a provider/config.
    client_id: str
    enabled: bool = False
    app_id: str = APP_ID
    return_uri: str = RETURN_URI
    scope: str = 'openid'
    callback_uri: str = CALLBACK


class AppStart(Start):
    app_id: str
    client_id: str


class AppExchange(Exchange):
    app_id: str
    client_id: str


def install_life_diary(app, current):
    from .life_diary_dev_relay import DevelopmentRelay
    relay = DevelopmentRelay()
    from app.modules.neorang_narang.router import SafeValidationRoute
    routes = APIRouter(route_class=SafeValidationRoute)

    def service():
        parent = current()
        registration = getattr(parent, 'life_diary_registration', None)
        runtime = getattr(parent, 'life_diary_runtime', None)
        if not registration or not registration.enabled or runtime is None:
            raise HTTPException(503, 'Authentication unavailable')
        if (registration.app_id != APP_ID or registration.return_uri != RETURN_URI
                or registration.callback_uri not in (CALLBACK, DEVELOPMENT_CALLBACK)
                or registration.scope != 'openid' or not registration.client_id
                or registration.client_id in parent.config.policy.client_ids
                or runtime.config.policy.client_ids != frozenset({registration.client_id})
                or runtime.config.policy.issuer != parent.config.policy.issuer
                or runtime.config.policy.audience != parent.config.policy.audience
                or runtime.store is not parent.store):
            raise HTTPException(503, 'Authentication unavailable')
        return runtime, registration

    def command_binding(command, registration):
        if (command.app_id, command.client_id, command.return_uri) != (
                registration.app_id, registration.client_id, registration.return_uri):
            raise denied()

    def binding(runtime, registration, state):
        runtime.store.mobile_binding(state, app_id=registration.app_id,
            client_id=registration.client_id, return_uri=registration.return_uri, now=runtime.now())

    @routes.post(PREFIX + '/login-transactions')
    def start(command: AppStart):
        runtime, registration = service()
        command_binding(command, registration)
        state, transaction = secrets.token_urlsafe(32), str(uuid4())
        runtime.store.begin_mobile(state=state, transaction=transaction, challenge=command.challenge,
            return_uri=registration.return_uri, app_id=registration.app_id,
            client_id=registration.client_id, now=runtime.now())
        return {'transaction': transaction, 'authorize_url':
                'http://127.0.0.1:8000'+PREFIX+'/authorize?'+urlencode({'state': state})}

    @routes.get(PREFIX + '/authorize')
    def authorize(request: Request):
        runtime, registration = service()
        state = request.query_params.get('state', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', state) or len(request.query_params.multi_items()) != 1:
            raise denied()
        binding(runtime, registration, state)
        browser, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(3)]
        runtime.store.bind_browser(state, browser, now=runtime.now())
        runtime.store.begin_login(state=state, browser=browser, nonce=nonce, verifier=verifier,
            client_id=registration.client_id, redirect_uri=registration.callback_uri, now=runtime.now())
        if registration.callback_uri == DEVELOPMENT_CALLBACK:
            relay.begin(state, browser, runtime.now())
        query = urlencode({'response_type': 'code', 'client_id': registration.client_id,
            'redirect_uri': registration.callback_uri, 'audience': runtime.config.policy.audience,
            'scope': registration.scope, 'state': state, 'nonce': nonce,
            'code_challenge': pkce_challenge(verifier), 'code_challenge_method': 'S256', 'prompt': 'login'})
        response = RedirectResponse(runtime.config.policy.issuer+'authorize?'+query, 303)
        response.set_cookie('jl_ld_login', browser, httponly=True, samesite='lax', max_age=300,
                            path='/api/v1/auth/callback/life-diary/android')
        return response

    @routes.get('/api/v1/auth/callback/life-diary/android')
    def callback(request: Request):
        runtime, registration = service()
        query = request.query_params
        expected = {'code', 'state'}
        if 'iss' in query:
            if query.getlist('iss') != [runtime.config.policy.issuer]:
                raise denied()
            expected.add('iss')
        if (set(query.keys()) != expected
                or len(query.getlist('state')) != 1 or len(query.getlist('code')) != 1
                or query.get('error') or not query['code'] or len(query['code']) > 4096):
            raise denied()
        state, browser = query['state'], request.cookies.get('jl_ld_login')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', state):
            raise denied()
        binding(runtime, registration, state)
        if registration.callback_uri == DEVELOPMENT_CALLBACK:
            if request.url.hostname != 'unwary-founder-peculiar.ngrok-free.dev':
                raise denied()
            ticket = relay.receive(state, query['code'], runtime.now())
            return RedirectResponse('http://127.0.0.1:8000'+COMPLETE+'?'+urlencode({'ticket': ticket}), 303)
        return finish(runtime, registration, state, browser, query['code'])

    @routes.get(COMPLETE)
    def complete(request: Request):
        runtime, registration = service()
        ticket = request.query_params.get('ticket', '')
        if (registration.callback_uri != DEVELOPMENT_CALLBACK
                or request.url.netloc != '127.0.0.1:8000'
                or len(request.query_params.multi_items()) != 1
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', ticket)):
            raise denied()
        browser = request.cookies.get('jl_ld_login')
        state, code = relay.consume(ticket, browser, runtime.now())
        binding(runtime, registration, state)
        return finish(runtime, registration, state, browser, code)

    def finish(runtime, registration, state, browser, authorization_code):
        from .auth_diagnostics import stage

        with stage('ld_claim_login'):
            login = runtime.store.claim_login(state=state, browser=browser, now=runtime.now())
        with stage('ld_registration_binding'):
            if (login['client_id'] != registration.client_id.encode() or login['redirect_uri'] != registration.callback_uri.encode()):
                raise denied()
        with stage('ld_provider_exchange'):
            raw, token = runtime.provider.exchange(code=authorization_code, verifier=login['verifier'],
                nonce_hash=login['nonce_hash'], now=runtime.now(), redirect_uri=registration.callback_uri)
        if token.client_id != registration.client_id or 'openid' not in token.scopes:
            raise denied()
        code = secrets.token_urlsafe(32)
        def handoff(connection, credential, account):
            return runtime.store.finish_mobile(state, browser, credential, account, code,
                now=runtime.now(), app_id=registration.app_id, client_id=registration.client_id,
                connection=connection)
        transaction, uri = runtime.store.complete_login(state=state, browser=browser, token=token,
            raw_token=raw, now=runtime.now(), app_id=registration.app_id, handoff=handoff)
        response = RedirectResponse(uri+'?'+urlencode({'transaction': transaction, 'code': code}), 303)
        response.delete_cookie('jl_ld_login', path='/api/v1/auth/callback/life-diary/android')
        return response

    def identity(request):
        runtime, registration = service()
        authorization = request.headers.get('authorization', '')
        if not authorization.startswith('Bearer '):
            raise denied()
        credential = authorization[7:]
        raw, row = runtime.store.cookie_token(credential, now=runtime.now())
        if row.get('app_id') != registration.app_id.encode() or row['client_id'] != registration.client_id.encode():
            raise denied()
        token = runtime.provider.verify_access(raw, now=runtime.now())
        session = runtime.store.lookup(token.fingerprint)
        if session is None or str(session.session_id) != row['session_id']:
            raise denied()
        validate_binding_candidate(token, session, expected_version=session.version, now=runtime.now())
        if 'openid' not in token.scopes:
            raise denied()
        return runtime, row, session

    @routes.post(PREFIX + '/session-exchange')
    def exchange(command: AppExchange):
        runtime, registration = service()
        command_binding(command, registration)
        credential, account = runtime.store.exchange_mobile(str(command.transaction), command.code,
            command.verifier, registration.return_uri, now=runtime.now(), app_id=registration.app_id,
            client_id=registration.client_id)
        _, row = runtime.store.cookie_token(credential, now=runtime.now())
        return {'access_token': credential, 'token_type': 'Bearer', 'sub': str(account),
                'expires_at': stamp(row['expires_at'])}

    @routes.get(PREFIX + '/session')
    def session(request: Request):
        _, _, session = identity(request)
        return {'sub': str(session.account_id), 'app_id': APP_ID}

    @routes.post(PREFIX + '/logout')
    def logout(request: Request):
        runtime, row, _ = identity(request)
        with runtime.store.transaction() as connection, connection.cursor() as c:
            c.execute('UPDATE app_sessions SET revoked_at=%s,version=version+1 '
                      'WHERE session_id=%s AND app_id=%s AND client_id=%s AND revoked_at IS NULL',
                      (utc(runtime.now()), row['session_id'], APP_ID.encode(), row['client_id']))
        return Response(status_code=204)

    app.include_router(routes)
