"""Opt-in mobile authentication only. No record sync, backup or CHGO grant."""
from dataclasses import dataclass, field
import re
import secrets
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth0_poc import denied, pkce_challenge, validate_binding_candidate
from .core_store import stamp, utc
from .mobile_store import MobileCoreStore
from .postgres_common_auth import PostgresCommonAuthStore

PROFILES = {
    'neorang_narang': ('/api/v1/mobile/neorang-narang',
        'http://127.0.0.1:8000/api/v1/auth/callback/android',
        'jesuslife-poc://auth/complete/android'),
    'life_diary': ('/api/v1/mobile/life-diary',
        'http://127.0.0.1:8000/api/v1/auth/callback/life-diary/android',
        'jesuslife-life-diary-poc://auth/complete/android'),
}


class CommonMobileAuthStore(PostgresCommonAuthStore, MobileCoreStore):
    def ready(self, cursor):
        cursor.execute('SELECT version FROM common_mobile_schema_version ORDER BY version')
        if cursor.fetchall() != [{'version': 1}]:
            raise HTTPException(503, 'Common mobile authentication unavailable')

    def mobile_status(self, *args, **kwargs):
        # Never execute the legacy MySQL consent/projection transaction.
        raise HTTPException(503, 'Product consent is not enabled by mobile login')


@dataclass(frozen=True, repr=False)
class MobileRegistration:
    app_id: str
    client_id: str
    runtime: object = field(repr=False)
    enabled: bool = False


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    app_id: str
    client_id: str
    return_uri: str
    challenge: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class ExchangeCommand(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    app_id: str
    client_id: str
    return_uri: str
    transaction: UUID
    code: str = Field(min_length=43, max_length=128)
    verifier: str = Field(min_length=43, max_length=128)


def install_common_mobile(app, registrations=()):
    # Authentication only: callers must enforce separate product consent.
    owners = {}
    seen = set()
    for registration in registrations:
        if not registration.enabled:
            continue
        if registration.app_id not in PROFILES or registration.app_id in seen:
            raise ValueError('Mobile application is not registered for this phase')
        runtime = registration.runtime
        if (not isinstance(runtime.store, CommonMobileAuthStore)
                or runtime.store._app_id != registration.app_id
                or runtime.config.policy.client_ids != frozenset({registration.client_id})):
            raise ValueError('Explicit app-scoped common mobile runtime required')
        seen.add(registration.app_id)
        owners[registration.app_id] = _install(app, registration)
    return owners


def _install(app, registration):
    from app.modules.neorang_narang.router import SafeValidationRoute
    routes = APIRouter(route_class=SafeValidationRoute)
    prefix, callback_uri, return_uri = PROFILES[registration.app_id]
    runtime = registration.runtime
    cookie_name = 'jl_common_mobile_' + registration.app_id

    def command_binding(command):
        if (command.app_id, command.client_id, command.return_uri) != (
                registration.app_id, registration.client_id, return_uri):
            raise denied()

    def binding(state):
        runtime.store.mobile_binding(state, app_id=registration.app_id,
            client_id=registration.client_id, return_uri=return_uri, now=runtime.now())

    def identity(credential):
        raw, row = runtime.store.cookie_token(credential, now=runtime.now())
        if (row.get('app_id') != registration.app_id.encode()
                or row['client_id'] != registration.client_id.encode()):
            raise denied()
        token = runtime.provider.verify_access(raw, now=runtime.now())
        session = runtime.store.lookup(token.fingerprint)
        if session is None or str(session.session_id) != row['session_id']:
            raise denied()
        validate_binding_candidate(token, session, expected_version=session.version, now=runtime.now())
        if 'openid' not in token.scopes:
            raise denied()
        return row, session

    def bearer(request):
        value = request.headers.get('authorization', '')
        if not value.startswith('Bearer '):
            raise denied()
        return value[7:]

    @routes.post(prefix + '/login-transactions')
    def start(command: Start):
        command_binding(command)
        state, transaction = secrets.token_urlsafe(32), str(uuid4())
        runtime.store.begin_mobile(state=state, transaction=transaction, challenge=command.challenge,
            return_uri=return_uri, now=runtime.now(), app_id=registration.app_id,
            client_id=registration.client_id)
        return {'transaction': transaction, 'authorize_url':
            'http://127.0.0.1:8000' + prefix + '/authorize?' + urlencode({'state': state})}

    @routes.get(prefix + '/authorize')
    def authorize(request: Request):
        state = request.query_params.get('state', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', state) or len(request.query_params.multi_items()) != 1:
            raise denied()
        binding(state)
        browser, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(3)]
        runtime.store.bind_browser(state, browser, now=runtime.now())
        runtime.store.begin_login(state=state, browser=browser, nonce=nonce, verifier=verifier,
            client_id=registration.client_id, redirect_uri=callback_uri, now=runtime.now())
        query = urlencode({'response_type':'code','client_id':registration.client_id,
            'redirect_uri':callback_uri,'audience':runtime.config.policy.audience,'scope':'openid',
            'state':state,'nonce':nonce,'code_challenge':pkce_challenge(verifier),
            'code_challenge_method':'S256','prompt':'login'})
        response = RedirectResponse(runtime.config.policy.issuer + 'authorize?' + query, 303)
        response.set_cookie(cookie_name, browser, httponly=True, samesite='lax', max_age=300,
                            path=callback_uri.removeprefix('http://127.0.0.1:8000'))
        return response

    @routes.get(callback_uri.removeprefix('http://127.0.0.1:8000'))
    def callback(request: Request):
        query = request.query_params
        expected = {'state', 'code'}
        if 'iss' in query:
            if query.getlist('iss') != [runtime.config.policy.issuer]:
                raise denied()
            expected.add('iss')
        if (set(query.keys()) != expected or len(query.getlist('state')) != 1
                or len(query.getlist('code')) != 1 or not query['code'] or len(query['code']) > 4096
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', query['state'])):
            raise denied()
        state, browser = query['state'], request.cookies.get(cookie_name)
        binding(state)
        login = runtime.store.claim_login(state=state, browser=browser, now=runtime.now())
        if (login['client_id'] != registration.client_id.encode()
                or login['redirect_uri'] != callback_uri.encode()):
            raise denied()
        raw, token = runtime.provider.exchange(code=query['code'], verifier=login['verifier'],
            nonce_hash=login['nonce_hash'], now=runtime.now(), redirect_uri=callback_uri)
        if token.client_id != registration.client_id or 'openid' not in token.scopes:
            raise denied()
        code = secrets.token_urlsafe(32)
        def handoff(connection, credential, account):
            return runtime.store.finish_mobile(state, browser, credential, account, code,
                now=runtime.now(), app_id=registration.app_id, client_id=registration.client_id,
                connection=connection)
        transaction, uri = runtime.store.complete_login(state=state, browser=browser,
            token=token, raw_token=raw, now=runtime.now(), app_id=registration.app_id, handoff=handoff)
        response = RedirectResponse(uri + '?' + urlencode({'transaction':transaction,'code':code}), 303)
        response.delete_cookie(cookie_name, path=callback_uri.removeprefix('http://127.0.0.1:8000'))
        return response

    @routes.post(prefix + '/session-exchange')
    def exchange(command: ExchangeCommand):
        command_binding(command)
        credential, account = runtime.store.exchange_mobile(str(command.transaction), command.code,
            command.verifier, return_uri, now=runtime.now(), app_id=registration.app_id,
            client_id=registration.client_id)
        row, _ = identity(credential)
        return {'access_token':credential,'token_type':'Bearer','sub':str(account),
                'expires_at':stamp(row['expires_at'])}

    @routes.get(prefix + '/session')
    def session(request: Request):
        _, current = identity(bearer(request))
        return {'sub':str(current.account_id),'app_id':registration.app_id}

    @routes.post(prefix + '/logout')
    def logout(request: Request):
        row, _ = identity(bearer(request))
        with runtime.store.transaction() as db:
            db.execute('UPDATE app_sessions SET revoked_at=%s,version=version+1 '
                'WHERE session_id=%s AND app_id=%s AND revoked_at IS NULL',
                (utc(runtime.now()), row['session_id'], registration.app_id.encode()))
        return Response(status_code=204)

    app.include_router(routes)

    def authenticated_owner(request: Request) -> UUID:
        _, current = identity(bearer(request))
        return UUID(str(current.account_id))

    return authenticated_owner
