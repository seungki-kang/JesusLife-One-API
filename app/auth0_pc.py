"""Separate loopback-only development entry point; no fake authentication.

Run: python -B -m uvicorn app.auth0_pc:app --host 127.0.0.1 --port 8000 --no-access-log
"""
import secrets
import time
from urllib.parse import urlencode

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.auth_diagnostics import logger, protect_access_log, stage
from app.core.auth0_poc import denied
from app.core.auth0_provider import Auth0Provider
from app.core.core_store import CoreStore
from app.modules.neorang_narang.router import router
from scripts.auth0_pc_settings import PATH, CALLBACK, validate

protect_access_log()

ORIGIN = 'http://127.0.0.1:8000'


class PcRuntime:
    def __init__(self, config, *, provider=None, store=None, clock=time.time):
        self.config, self.provider, self.clock = config, provider or Auth0Provider(config), clock
        self.store = store or CoreStore(config.encryption_key, config.hmac_key)

    def now(self):
        return int(self.clock())

    def csrf(self, request):
        with stage('csrf', flow='session'):
            if request.headers.get('origin') != ORIGIN or not request.headers.get('x-csrf-token'):
                raise HTTPException(403, 'Access denied')
        return request.headers['x-csrf-token']

    def identity(self, request, *, product=True):
        authorization = request.headers.get('authorization')
        if authorization is not None:
            if not authorization.startswith('Bearer '):
                raise denied()
            raw = authorization[7:]
        else:
            csrf = self.csrf(request) if request.method not in ('GET', 'HEAD') else None
            with stage('cookie_present', flow='session'):
                cookie = request.cookies.get('jl_pc_session')
                if not cookie:
                    raise denied()
            with stage('cookie_token', flow='session'):
                raw, _ = self.store.cookie_token(cookie, now=self.now(), csrf=csrf)
        with stage('access_verify', flow='session'):
            token = self.provider.verify_access(raw, now=self.now())
        with stage('session_lookup', flow='session'):
            session = self.store.lookup(token.fingerprint)
        from app.core.auth0_poc import validate_binding_candidate
        with stage('session_binding', flow='session'):
            if session is None:
                raise denied()
            validate_binding_candidate(token, session, expected_version=session.version, now=self.now())
        if product:
            with stage('scope_consent', flow='session'):
                required = 'neorang-narang:read' if request.method in ('GET', 'HEAD') else 'neorang-narang:write'
                if required not in token.scopes or not session.consent_active:
                    raise HTTPException(403, 'Access denied')
        from app.core.auth import AuthContext
        return AuthContext(sub=session.account_id)


def create_app(runtime=None):
    app = FastAPI(title='JesusLife PC Auth0 development PoC', debug=False)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'testserver'])
    app.state.auth_runtime = runtime
    from app.core.ab_acceptance import AcceptanceRuns, check_records
    from threading import Lock
    acceptance = AcceptanceRuns()
    acceptance_busy = Lock()
    app.include_router(router)

    @app.middleware('http')
    async def headers(request, call_next):
        # Never log raw paths, queries, headers, identifiers or exception text.
        category = {
            '/api/v1/auth/callback/web': 'callback', '/auth/poc/': 'page',
            '/auth/poc/signed-out': 'signed_out', '/api/v1/me': 'me',
            '/auth/poc/acceptance/start-a': 'register_a',
        }.get(request.url.path, 'other')
        try:
            response = await call_next(request)
        except Exception:
            # Do not serialize/log provider, SQL or cryptographic exceptions.
            logger.warning('auth_request route=%s result=UNHANDLED', category)
            response = JSONResponse({'detail': 'Authentication unavailable'}, status_code=503)
        logger.info('auth_request route=%s status=%d', category, response.status_code)
        response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                                 'X-Content-Type-Options': 'nosniff',
                                 'Content-Security-Policy': "default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    def current():
        value = app.state.auth_runtime
        with stage('runtime_ready', flow='session'):
            if value is None:
                raise HTTPException(503, 'Authentication unavailable')
        return value

    from app.core.mobile_routes import install_mobile
    install_mobile(app, current)

    @app.get('/health')
    def health():
        return {'status': 'ok', 'service': 'jesuslife-pc-poc'}

    @app.get('/auth/poc/login')
    def login():
        service = current()
        state, browser, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(4)]
        client = next(iter(service.config.policy.client_ids))
        service.store.begin_login(state=state, browser=browser, nonce=nonce, verifier=verifier,
                                  client_id=client, redirect_uri=CALLBACK, now=service.now())
        from app.core.auth0_poc import pkce_challenge
        query = urlencode({'response_type': 'code', 'client_id': client, 'redirect_uri': CALLBACK,
                           'audience': service.config.policy.audience,
                           'scope': 'openid neorang-narang:read neorang-narang:write',
                           'state': state, 'nonce': nonce, 'code_challenge': pkce_challenge(verifier),
                           'code_challenge_method': 'S256', 'prompt': 'login'})
        response = RedirectResponse(service.config.policy.issuer + 'authorize?' + query, status_code=303)
        response.set_cookie('jl_pc_login', browser, httponly=True, samesite='lax', max_age=300,
                            path='/api/v1/auth/callback')
        return response

    @app.get('/api/v1/auth/callback/web')
    def callback(request: Request):
        service = current()
        with stage('callback_input'):
            state, code = request.query_params.get('state'), request.query_params.get('code')
            if (not state or not code or len(code) > 4096 or request.query_params.get('error')
                    or len(request.query_params.getlist('state')) != 1
                    or len(request.query_params.getlist('code')) != 1):
                raise denied()
        with stage('state_browser_pkce'):
            browser = request.cookies.get('jl_pc_login')
            login = service.store.claim_login(state=state, browser=browser, now=service.now())
            if login['client_id'].decode() not in service.config.policy.client_ids or login['redirect_uri'].decode() != CALLBACK:
                raise denied()
        with stage('provider'):
            raw, token = service.provider.exchange(code=code, verifier=login['verifier'],
                                                   nonce_hash=login['nonce_hash'], now=service.now())
        with stage('core_session'):
            cookie, csrf, _ = service.store.complete_login(state=state, browser=browser, token=token,
                                                           raw_token=raw, now=service.now())
        with stage('response_cookies'):
            response = RedirectResponse('/auth/poc/', status_code=303)
            ttl = max(0, token.expires_at - service.now())
            response.set_cookie('jl_pc_session', cookie, httponly=True, samesite='lax', max_age=ttl)
            response.set_cookie('jl_pc_csrf', csrf, httponly=False, samesite='strict', max_age=ttl)
            response.delete_cookie('jl_pc_login', path='/api/v1/auth/callback')
        return response

    @app.get('/api/v1/me')
    def me(request: Request):
        return {'sub': str(current().identity(request, product=False).sub)}

    @app.post('/api/v1/me/consents/neorang-narang-sync')
    def consent(request: Request):
        service = current()
        service.csrf(request)
        user = service.identity(request, product=False)
        service.store.grant_consent(user.sub, now=service.now())
        return {'consent': 'granted', 'policy_version': 'pc-poc-v1'}

    @app.post('/api/v1/auth/logout')
    def logout(request: Request):
        service = current()
        csrf = service.csrf(request)
        service.store.logout(request.cookies.get('jl_pc_session'), csrf, now=service.now())
        acceptance.logout(request.cookies.get('jl_pc_acceptance'), request.cookies.get('jl_pc_session'))
        response = Response(status_code=204)
        response.delete_cookie('jl_pc_session')
        response.delete_cookie('jl_pc_csrf')
        return response

    @app.post('/auth/poc/acceptance/{action}')
    async def acceptance_action(action: str, request: Request):
        # This helper cannot supply identity, scope or consent to product APIs.
        service = current()
        service.csrf(request)
        user = service.identity(request, product=False)
        session = request.cookies.get('jl_pc_session')
        if not session or request.headers.get('authorization') is not None:
            raise denied()
        if not acceptance_busy.acquire(blocking=False):
            raise HTTPException(409, 'Acceptance check in progress')
        try:
            if action == 'start-a':
                with stage('register_a', flow='acceptance'):
                    key = acceptance.start(user.sub, session)
                    response = JSONResponse({'A_registered': True})
                    response.set_cookie('jl_pc_acceptance', key, httponly=True, samesite='strict', max_age=3600)
                return response
            run = acceptance.get(request.cookies.get('jl_pc_acceptance'))
            if action == 'compare':
                return acceptance.compare(run, user.sub, session)
            label = acceptance.label(run, user.sub)
            if action == 'results':
                complete = run['same'] and run['b'] is not None and run['verified_after_foreign'] == {'A', 'B'} and all(
                    run['results'].get(account, {}).get('foreign_delete_retry_1') == 'PASS'
                    and run['results'].get(account, {}).get('delete_retry') == 'PASS'
                    and 'FAIL' not in run['results'].get(account, {}).values()
                    for account in ('A', 'B'))
                failed = any('FAIL' in checks.values() for checks in run['results'].values())
                return {'same_account_relogin': run['same'], 'distinct_b': run['b'] is not None,
                        'acceptance': 'FAIL' if failed else ('PASS' if complete else 'NOT_RUN'),
                        'checks': run['results']}
            if action == 'consent':
                service.store.grant_consent(user.sub, now=service.now())
                run['consent'].add(label)
                return {'account': label, 'test_metadata_consent': True}
            if action == 'check':
                if not run['same'] or label not in run['consent']:
                    raise HTTPException(409, 'Re-login comparison and separate consent required')
                service.identity(request, product=True)
                import httpx
                # Forward only this authenticated session; never echo credentials.
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                        headers={'Origin': ORIGIN, 'X-CSRF-Token': request.headers['x-csrf-token']},
                        cookies={'jl_pc_session': session}) as client:
                    return {'account': label, 'checks': await check_records(client, run, label)}
            raise HTTPException(404, 'Not Found')
        finally:
            acceptance_busy.release()

    @app.get('/auth/poc/', response_class=HTMLResponse)
    @app.get('/auth/poc/signed-out', response_class=HTMLResponse)
    def page(request: Request):
        # No token/subject/profile is embedded or echoed in HTML.
        try:
            current().identity(request, product=False)
            login_status, session_status = '로그인됨', '유효'
        except HTTPException as error:
            if error.status_code == 401:
                login_status, session_status = '로그인되지 않음', '유효하지 않음'
            else:
                login_status, session_status = '확인 불가', '확인 불가'
        except Exception:
            login_status, session_status = '확인 불가', '확인 불가'
        return '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>Core Auth0 PC PoC</title>
<h1>Core Auth0 PC PoC</h1><p><a href="/auth/poc/login">Auth0 합성 계정 로그인</a></p>
<p>서버 확인 로그인 상태: <strong id="login-state">''' + login_status + '''</strong></p>
<p>서버 확인 세션: <strong id="session-state">''' + session_status + '''</strong></p>
<p>이 상태는 페이지 요청 시 확인됩니다. 만료 후에는 다시 로그인하세요.</p>
<button onclick="location.reload()">서버 상태 다시 확인</button>
<p>동의하면 완료 메타데이터만 서버에 저장합니다. 이름·문답·서명은 전송하지 않습니다.</p>
<button onclick="send('/api/v1/me/consents/neorang-narang-sync')">테스트 메타데이터 동의</button>
<button onclick="send('/api/v1/auth/logout')">현재 앱 로그아웃</button><p id="status"></p>
<h2>실제 테스트 계정 A/B 인수 검증</h2>
<p>전용 테스트 계정만 사용하세요. 앱 로그아웃은 Auth0 SSO를 종료하지 않습니다.
B는 Auth0 로그인 화면에서 별도 계정으로 직접 로그인하고 서버 비교로 확인하세요.
자동으로 A에 돌아오면 B 검증을 진행하지 마세요. 비밀번호나 이메일을 이 화면에 입력하지 마세요.</p>
<p>순서: A 등록 → 앱 로그아웃 → A 재로그인 → 비교 → A 별도 동의 → 검사.
그다음 앱 로그아웃 → B 로그인 → 비교(동일 false·별도 B true) → B 별도 동의 → 검사.
마지막으로 A 재로그인·비교·검사, B 재로그인·비교·검사로 양쪽 원본 보존까지 확인하세요.</p>
<p>검사는 합성 완료 메타데이터만 저장하고 이번 실행의 합성 자료만 수정·소프트 삭제합니다.
계정별 동의 버튼은 현재 계정의 테스트 저장에 대한 명시적 동의입니다.
실행 상태는 서버 메모리에 1시간 유지되며 재시작 시 처음부터 진행합니다.</p>
<button onclick="ab('start-a')">현재 계정이 전용 A임을 확인하고 등록</button>
<button onclick="ab('compare')">재로그인 계정 서버 비교</button>
<button onclick="ab('consent')">현재 테스트 계정의 합성 메타데이터 저장에 별도 동의</button>
<button onclick="ab('check')">현재 계정 격리 검사</button><pre id="ab-result"></pre>
<button onclick="ab('results')">이번 실행 결과만 확인</button>
<script>async function send(path){try{const csrf=document.cookie.split('; ').find(x=>x.startsWith('jl_pc_csrf='));
const r=await fetch(path,{method:'POST',cache:'no-store',headers:{'X-CSRF-Token':csrf?decodeURIComponent(csrf.substring(11)):''}});
if(path==='/api/v1/auth/logout' && r.status===204){location.replace('/auth/poc/signed-out');return;}
if(r.status===401){location.reload();return;}
document.getElementById('status').textContent=r.ok?'요청 완료':'요청 실패 (HTTP '+r.status+')';
}catch{document.getElementById('login-state').textContent='확인 불가';
document.getElementById('session-state').textContent='확인 불가';
document.getElementById('status').textContent='서버 연결을 확인한 후 다시 시도하세요.';}}
async function ab(action){const out=document.getElementById('ab-result');try{
const csrf=document.cookie.split('; ').find(x=>x.startsWith('jl_pc_csrf='));
const r=await fetch('/auth/poc/acceptance/'+action,{method:'POST',cache:'no-store',
headers:{'X-CSRF-Token':csrf?decodeURIComponent(csrf.substring(11)):''}});
out.textContent=r.ok?JSON.stringify(await r.json(),null,2):'진행 불가 (HTTP '+r.status+'). 계정·로그인 순서·별도 동의를 확인하세요.';
}catch{out.textContent='서버 확인 불가';}}
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});</script></html>'''

    return app


def configured_app():
    try:
        config = validate(dotenv_values(PATH, interpolate=False))
        return create_app(PcRuntime(config))
    except Exception:
        return create_app()


app = configured_app()
