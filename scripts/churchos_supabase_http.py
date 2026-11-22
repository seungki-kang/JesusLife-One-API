"""Development-only HTTP observations and protected administrator SQL handoff."""
import hashlib
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from scripts.churchos_supabase_dev import DIRECTORY


def write_admin_sql(account, church):
    """Only verified server identity enters SQL; no client-provided identifiers."""
    from scripts.local_mysql import protect
    guard = """IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user
        AND (rolsuper OR rolbypassrls)) THEN
        RAISE EXCEPTION 'Administrator with RLS bypass required'; END IF;"""
    insert = f"""BEGIN;
SET LOCAL statement_timeout='5s';
DO $verification$
DECLARE affected integer;
BEGIN
  {guard}
  INSERT INTO jl_churchos.memberships
    (account_id, church_id, can_manage_memberships, revoked_at)
    VALUES ('{account}', '{church}', false, NULL);
  GET DIAGNOSTICS affected = ROW_COUNT;
  IF affected <> 1 THEN RAISE EXCEPTION 'Expected one synthetic row'; END IF;
END $verification$;
COMMIT;
SELECT 'PASS: one synthetic membership inserted; no policies created' AS result;
"""
    cleanup = f"""BEGIN;
SET LOCAL statement_timeout='5s';
DO $verification$
BEGIN
  {guard}
  IF EXISTS (SELECT 1 FROM jl_churchos.memberships
    WHERE church_id='{church}' AND
      (account_id<>'{account}' OR can_manage_memberships OR revoked_at IS NOT NULL))
    THEN RAISE EXCEPTION 'Unexpected row; manual review required'; END IF;
  DELETE FROM jl_churchos.memberships
    WHERE account_id='{account}' AND church_id='{church}'
      AND NOT can_manage_memberships AND revoked_at IS NULL;
  IF EXISTS (SELECT 1 FROM jl_churchos.memberships WHERE church_id='{church}')
    THEN RAISE EXCEPTION 'Synthetic row remains'; END IF;
END $verification$;
COMMIT;
SELECT NOT EXISTS (SELECT 1 FROM jl_churchos.memberships
  WHERE church_id='{church}') AS synthetic_rows_absent;
-- This run creates no policies, grants, schema or role changes.
SELECT count(*) AS temporary_verification_policies FROM pg_policies
 WHERE schemaname='jl_churchos' AND tablename='memberships'
 AND policyname LIKE 'jl_supabase_dev_verify_%';
"""
    # Recovery SQL first: if preparation fails, cleanup remains available.
    for name, content in (('cleanup.sql', cleanup), ('insert.sql', insert)):
        path = DIRECTORY / name
        with path.open('x', encoding='utf-8') as output:
            protect(path)
            output.write(content)


def install_verification(app, runtime):
    if any((DIRECTORY / name).exists() for name in ('insert.sql', 'cleanup.sql')):
        raise ValueError('Previous run requires cleanup and archival before a new run')
    own, other = uuid4(), uuid4()
    own_path = f'/api/v1/churches/{own}/membership'
    other_path = f'/api/v1/churches/{other}/membership'
    state = {'account': None, 'baseline_cookie': None, 'results': {}}

    @app.middleware('http')
    async def observe(request, call_next):
        response = await call_next(request)
        if request.url.path not in (own_path, other_path) or request.method != 'GET':
            return response
        if not request.cookies.get('jl_pc_session') and not request.headers.get('authorization'):
            if request.url.path == own_path:
                state['results']['unauthenticated'] = response.status_code
            return response
        if state['account'] is None:
            return response
        try:
            user = runtime.identity(request, product=False)
            if user.sub != state['account'] or request.headers.get('authorization'):
                return response
            cookie = hashlib.sha256(request.cookies['jl_pc_session'].encode()).digest()
            try:
                runtime.identity(request, product=False, required_scope='churchos:membership:read')
                scoped = True
            except HTTPException as error:
                if error.status_code != 403:
                    return response
                scoped = False
            if not scoped and request.url.path == own_path and response.status_code == 403:
                state['baseline_cookie'] = cookie
                state['results']['basic_login'] = response.status_code
            elif scoped and cookie != state['baseline_cookie']:
                label = 'own_membership' if request.url.path == own_path else 'other_church'
                state['results'][label] = response.status_code
        except Exception:
            pass
        return response

    @app.post('/dev/churchos/confirm-test-account')
    def confirm(request: Request):
        runtime.csrf(request)
        user = runtime.identity(request, product=False)
        if request.headers.get('authorization') or not request.cookies.get('jl_pc_session'):
            raise HTTPException(403, 'Cookie login required')
        try:
            runtime.identity(request, product=False, required_scope='churchos:membership:read')
        except HTTPException as error:
            if error.status_code != 403:
                raise
        else:
            raise HTTPException(409, 'Start with a fresh basic login')
        if state['account'] is not None:
            raise HTTPException(409, 'Test account already registered')
        write_admin_sql(user.sub, own)
        state['account'] = user.sub
        state['baseline_cookie'] = hashlib.sha256(request.cookies['jl_pc_session'].encode()).digest()
        return {'test_account_registered': True, 'admin_sql_prepared': True}

    @app.get('/dev/churchos/results')
    def results():
        expected = {'unauthenticated': 401, 'basic_login': 403,
                    'own_membership': 200, 'other_church': 403}
        return {'http_status': state['results'], 'http_pass': state['results'] == expected,
                'cleanup': 'NOT_RUN: administrator SQL confirmation required',
                'temporary_policies_created': False}

    @app.get('/dev/churchos/', response_class=HTMLResponse)
    def page():
        return '''<!doctype html><html lang="ko"><meta charset="utf-8">
<title>ChurchOS Supabase 개발 검증</title>
<h1>ChurchOS Supabase 개발 검증</h1>
<p>안내받은 단계의 버튼만 누르세요. 계정·토큰·응답 본문은 표시하지 않습니다.</p>
<button onclick="unauth()">1. 미로그인 요청</button>
<p><a href="/auth/poc/login">2. 기존 테스트 계정 기본 로그인</a></p>
<button onclick="register()">3. 현재 계정이 기존 테스트 계정임을 확인하고 SQL 준비</button>
<button onclick="check(OWN)">4. 기본 로그인 소속 조회</button>
<button onclick="logout()">5. 앱 로그아웃</button>
<p><a href="/auth/poc/login/churchos">6. 같은 테스트 계정 ChurchOS 로그인</a></p>
<button onclick="check(OWN)">7. 자기 소속 조회</button>
<button onclick="check(OTHER)">8. 다른 교회 조회</button>
<button onclick="results()">HTTP 결과</button><pre id="result"></pre>
<script>
const OWN=''' + repr(own_path) + ', OTHER=' + repr(other_path) + ''';
const out=document.getElementById('result');
function csrf(){const c=document.cookie.split('; ').find(x=>x.startsWith('jl_pc_csrf='));
return c?decodeURIComponent(c.substring(11)):'';}
async function unauth(){try{const r=await fetch(OWN,{credentials:'omit',cache:'no-store'});
out.textContent='미로그인 HTTP '+r.status;}catch{out.textContent='요청 실패';}}
async function check(path){try{const r=await fetch(path,{cache:'no-store'});
out.textContent='HTTP '+r.status;}catch{out.textContent='요청 실패';}}
async function register(){try{const r=await fetch('/dev/churchos/confirm-test-account',
{method:'POST',headers:{'X-CSRF-Token':csrf()}});out.textContent='SQL 준비 HTTP '+r.status;
}catch{out.textContent='요청 실패';}}
async function logout(){try{const r=await fetch('/api/v1/auth/logout',
{method:'POST',headers:{'X-CSRF-Token':csrf()}});out.textContent='로그아웃 HTTP '+r.status;
}catch{out.textContent='요청 실패';}}
async function results(){try{out.textContent=JSON.stringify(await(await fetch('/dev/churchos/results',
{cache:'no-store'})).json(),null,2);}catch{out.textContent='요청 실패';}}
</script></html>'''
