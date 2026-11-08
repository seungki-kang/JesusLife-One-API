"""Android broker routes. Constants intentionally limited to local ADB reverse PoC."""
import re
import secrets
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth0_poc import denied, pkce_challenge, validate_binding_candidate
from .core_store import stamp, utc

CALLBACK = 'http://127.0.0.1:8000/api/v1/auth/callback/android'
RETURN_URI = 'jesuslife-poc://auth/complete/android'
PREFIX = '/api/v1/mobile'


class SafeBody(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)


class Start(SafeBody):
    challenge: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    return_uri: str


class Exchange(SafeBody):
    transaction: UUID
    code: str = Field(min_length=43, max_length=128)
    verifier: str = Field(min_length=43, max_length=128)
    return_uri: str


class Generation(SafeBody):
    generation: int = Field(strict=True, ge=1)


class Synthetic(Generation):
    # A newly generated fixture, never a projection of historical user records.
    sync_id: UUID
    course_number: int = Field(strict=True, ge=1, le=2)
    participation_mode: str = Field(pattern=r'^(solo|together)$')
    completed_at: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}T.*Z$', max_length=40)
    synthetic: bool = Field(strict=True)


def install_mobile(app, current):
    from app.modules.neorang_narang.router import SafeValidationRoute
    from app.modules.neorang_narang.mobile_store import MobileProjectionStore
    projection = MobileProjectionStore()
    routes = APIRouter(route_class=SafeValidationRoute)

    def service():
        runtime = current()
        if not hasattr(runtime.store, 'exchange_mobile'):
            raise HTTPException(503, 'Mobile unavailable')
        return runtime

    def identity(request):
        runtime = service()
        authorization = request.headers.get('authorization', '')
        if not authorization.startswith('Bearer '):
            raise denied()
        credential = authorization[7:]
        raw, row = runtime.store.cookie_token(credential, now=runtime.now())
        if row.get('app_id') is not None:
            raise denied()
        token = runtime.provider.verify_access(raw, now=runtime.now())
        session = runtime.store.lookup(token.fingerprint)
        if session is None:
            raise denied()
        validate_binding_candidate(token, session, expected_version=session.version, now=runtime.now())
        required = 'neorang-narang:read' if request.method == 'GET' else 'neorang-narang:write'
        if required not in token.scopes:
            raise HTTPException(403, 'Access denied')
        return runtime, session.account_id, credential, row

    @routes.post(PREFIX + '/login-transactions')
    def start(command: Start):
        if command.return_uri != RETURN_URI:
            raise denied()
        runtime = service()
        state, transaction = secrets.token_urlsafe(32), str(uuid4())
        runtime.store.begin_mobile(state=state, transaction=transaction, challenge=command.challenge,
                                   return_uri=RETURN_URI, now=runtime.now())
        return {'transaction': transaction,
                'authorize_url': 'http://127.0.0.1:8000'+PREFIX+'/authorize?'+urlencode({'state': state})}

    @routes.get(PREFIX + '/authorize')
    def authorize(request: Request):
        runtime = service()
        state = request.query_params.get('state')
        if not state or not re.fullmatch(r'[A-Za-z0-9_-]{43}', state) or len(request.query_params) != 1:
            raise denied()
        runtime.store.mobile_binding(state, app_id=None, client_id=None, return_uri=RETURN_URI, now=runtime.now())
        browser, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(3)]
        runtime.store.bind_browser(state, browser, now=runtime.now())
        client = next(iter(runtime.config.policy.client_ids))
        runtime.store.begin_login(state=state, browser=browser, nonce=nonce, verifier=verifier,
                                  client_id=client, redirect_uri=CALLBACK, now=runtime.now())
        query = urlencode({'response_type': 'code', 'client_id': client, 'redirect_uri': CALLBACK,
                           'audience': runtime.config.policy.audience,
                           'scope': 'openid neorang-narang:read neorang-narang:write',
                           'state': state, 'nonce': nonce, 'code_challenge': pkce_challenge(verifier),
                           'code_challenge_method': 'S256', 'prompt': 'login'})
        response = RedirectResponse(runtime.config.policy.issuer+'authorize?'+query, 303)
        response.set_cookie('jl_mobile_login', browser, httponly=True, samesite='lax',
                            max_age=300, path='/api/v1/auth/callback/android')
        return response

    @routes.get('/api/v1/auth/callback/android')
    def callback(request: Request):
        runtime = service()
        query = request.query_params
        if (len(query.getlist('state')) != 1 or len(query.getlist('code')) != 1 or query.get('error')
                or not query['code'] or len(query['code']) > 4096):
            raise denied()
        state, browser = query['state'], request.cookies.get('jl_mobile_login')
        runtime.store.mobile_binding(state, app_id=None, client_id=None, return_uri=RETURN_URI, now=runtime.now())
        login = runtime.store.claim_login(state=state, browser=browser, now=runtime.now())
        if (login['redirect_uri'].decode() != CALLBACK
                or login['client_id'].decode() not in runtime.config.policy.client_ids):
            raise denied()
        raw, token = runtime.provider.exchange(code=query['code'], verifier=login['verifier'],
                                               nonce_hash=login['nonce_hash'], now=runtime.now(), redirect_uri=CALLBACK)
        credential, _, account = runtime.store.complete_login(state=state, browser=browser, token=token,
                                                              raw_token=raw, now=runtime.now())
        code = secrets.token_urlsafe(32)
        transaction, uri = runtime.store.finish_mobile(state, browser, credential, account, code, now=runtime.now())
        response = RedirectResponse(uri+'?'+urlencode({'transaction': transaction, 'code': code}), 303)
        response.delete_cookie('jl_mobile_login', path='/api/v1/auth/callback/android')
        return response

    @routes.post(PREFIX + '/session-exchange')
    def exchange(command: Exchange):
        if command.return_uri != RETURN_URI:
            raise denied()
        runtime = service()
        credential, account = runtime.store.exchange_mobile(str(command.transaction), command.code,
                                                            command.verifier, RETURN_URI, now=runtime.now())
        _, row = runtime.store.cookie_token(credential, now=runtime.now())
        return {'access_token': credential, 'token_type': 'Bearer', 'sub': str(account),
                'expires_at': stamp(row['expires_at'])}

    @routes.get(PREFIX + '/consent')
    def status(request: Request):
        """Deletion complete applies only through deletion_through (inclusive).

        current_generation_deletion_complete explicitly distinguishes an old
        completed deletion from a later active consent. Legacy fields remain.
        """
        runtime, account, _, _ = identity(request)
        return runtime.store.mobile_status(account, projection=projection)

    @routes.post(PREFIX + '/consent')
    def grant(request: Request):
        runtime, account, _, _ = identity(request)
        return runtime.store.mobile_status(account, grant=True, projection=projection)

    @routes.post(PREFIX + '/consent/revoke')
    def revoke(command: Generation, request: Request):
        runtime, account, _, _ = identity(request)
        return runtime.store.mobile_status(account, revoke=command.generation, projection=projection)

    @routes.post(PREFIX + '/synthetic-completion')
    def send(command: Synthetic, request: Request):
        runtime, account, _, _ = identity(request)
        if command.synthetic is not True:
            raise HTTPException(422, 'Synthetic fixture required')
        from app.modules.neorang_narang.schemas import CompletionRecordMetadata
        from pydantic import ValidationError
        try:
            metadata = CompletionRecordMetadata(id=command.sync_id, course_number=command.course_number,
                participation_mode=command.participation_mode, completed_at=command.completed_at, revision=1)
        except ValidationError:
            raise HTTPException(422, 'Invalid request') from None
        return runtime.store.mobile_status(account, projection=projection,
            create=(command.generation, metadata.model_dump(mode='json')))

    @routes.post(PREFIX + '/logout')
    def logout(request: Request):
        runtime, _, _, row = identity(request)
        # Bearer authentication is explicit; no browser ambient cookie/CSRF path.
        with runtime.store.transaction() as connection, connection.cursor() as c:
            c.execute('UPDATE app_sessions SET revoked_at=%s,version=version+1 '
                      'WHERE session_id=%s AND revoked_at IS NULL',
                      (utc(runtime.now()), row['session_id']))
        return Response(status_code=204)

    app.include_router(routes)
