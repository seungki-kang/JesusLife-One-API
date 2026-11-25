"""Loopback-only browser authentication verification; no product DB routes."""
import secrets
import time
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth0_poc import denied, pkce_challenge, validate_binding_candidate
from .auth0_provider import Auth0Provider
from .postgres_common_auth import PostgresCommonAuthStore
from scripts.common_auth_cloud_settings import CALLBACK, ORIGIN


def create_cloud_app(config, *, store, provider=None, clock=time.time):
    if (not config.enabled or not isinstance(store, PostgresCommonAuthStore)
            or store._app_id != config.app_id):
        raise ValueError('Explicit common PostgreSQL authentication required')
    provider = provider or Auth0Provider(config)
    app = FastAPI(title='Common PostgreSQL authentication development verification',
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'testserver'])

    @app.middleware('http')
    async def protect(request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse({'detail': 'Common authentication unavailable'}, status_code=503)
        response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    def csrf(request):
        value = request.headers.get('X-CSRF-Token')
        if request.headers.get('Origin') != ORIGIN or not value:
            raise HTTPException(403, 'Access denied')
        return value

    def identity(request):
        now = int(clock())
        raw, row = store.cookie_token(request.cookies.get('jl_cloud_session'), now=now)
        token = provider.verify_access(raw, now=now)
        session = store.lookup(token.fingerprint)
        if session is None:
            raise denied()
        validate_binding_candidate(token, session, expected_version=session.version, now=now)
        return row

    @app.get('/health')
    def health():
        return {'status': 'ok', 'authentication_store': 'COMMON_POSTGRES', 'development_only': True}

    @app.get('/auth/cloud/login')
    def login():
        state, browser, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(4)]
        client = next(iter(config.policy.client_ids))
        store.begin_login(state=state, browser=browser, nonce=nonce, verifier=verifier,
                          client_id=client, redirect_uri=CALLBACK, now=int(clock()))
        query = urlencode({'response_type': 'code', 'client_id': client, 'redirect_uri': CALLBACK,
            'audience': config.policy.audience, 'scope': 'openid', 'state': state, 'nonce': nonce,
            'code_challenge': pkce_challenge(verifier), 'code_challenge_method': 'S256', 'prompt': 'login'})
        response = RedirectResponse(config.policy.issuer + 'authorize?' + query, status_code=303)
        response.set_cookie('jl_cloud_login', browser, httponly=True, samesite='lax',
                            max_age=300, path='/api/v1/auth/callback')
        return response

    @app.get('/api/v1/auth/callback/web')
    def callback(request: Request):
        state, code = request.query_params.get('state'), request.query_params.get('code')
        if (not state or not code or len(code) > 4096 or request.query_params.get('error')
                or len(request.query_params.getlist('state')) != 1
                or len(request.query_params.getlist('code')) != 1):
            raise denied()
        browser = request.cookies.get('jl_cloud_login')
        now = int(clock())
        login = store.claim_login(state=state, browser=browser, now=now)
        if (login['client_id'].decode() not in config.policy.client_ids
                or login['redirect_uri'].decode() != CALLBACK):
            raise denied()
        raw, token = provider.exchange(code=code, verifier=login['verifier'],
                                       nonce_hash=login['nonce_hash'], now=now)
        cookie, csrf_value, _ = store.complete_login(state=state, browser=browser,
                                                     token=token, raw_token=raw, now=now)
        response = RedirectResponse('/auth/cloud/', status_code=303)
        ttl = max(0, token.expires_at - now)
        response.set_cookie('jl_cloud_session', cookie, httponly=True, samesite='lax', max_age=ttl)
        response.set_cookie('jl_cloud_csrf', csrf_value, samesite='strict', max_age=ttl)
        response.delete_cookie('jl_cloud_login', path='/api/v1/auth/callback')
        return response

    @app.get('/api/v1/auth/cloud-status')
    def status(request: Request):
        identity(request)
        return {'authenticated': True, 'app': config.app_id, 'authentication_store': 'COMMON_POSTGRES'}

    @app.post('/api/v1/auth/cloud-logout')
    def logout(request: Request):
        csrf_value = csrf(request)
        identity(request)
        store.logout(request.cookies.get('jl_cloud_session'), csrf_value, now=int(clock()))
        response = Response(status_code=204)
        response.delete_cookie('jl_cloud_session')
        response.delete_cookie('jl_cloud_csrf')
        return response

    @app.get('/auth/cloud/', response_class=HTMLResponse)
    def page():
        return '''<!doctype html><html lang="ko"><meta charset="utf-8">
<title>공통 클라우드 인증 검증</title><h1>공통 PostgreSQL 인증 검증</h1>
<p>개발용 로그인만 확인합니다. 기록 업로드와 교회 권한 부여는 하지 않습니다.</p>
<a href="/auth/cloud/login">테스트 계정 로그인</a>
<button onclick="check()">인증 상태 확인</button><button onclick="logout()">로그아웃</button>
<pre id="out"></pre><script>
const out=document.getElementById('out');
async function check(){try{const r=await fetch('/api/v1/auth/cloud-status',{cache:'no-store'});
out.textContent='인증 상태 HTTP '+r.status;}catch{out.textContent='요청 실패';}}
async function logout(){try{const c=document.cookie.split('; ').find(x=>x.startsWith('jl_cloud_csrf='));
const r=await fetch('/api/v1/auth/cloud-logout',{method:'POST',headers:{'X-CSRF-Token':c?decodeURIComponent(c.substring(14)):''}});
out.textContent='로그아웃 HTTP '+r.status;}catch{out.textContent='요청 실패';}}
</script></html>'''

    return app
