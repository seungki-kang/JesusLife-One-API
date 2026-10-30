# 로컬 Platform Core + PC Auth0 PoC

2026-10-29. 사용자 승인으로 Core DB·역할 분리·migration·callback·영속 세션을 구현하고
합성 검증했다. 2026-10-30 실제 Auth0 A/B PC 브라우저 인수는 사용자 전달 결과 PASS다.
상세 범위와 한계는 [인수 기록](verification/2026-10-30-auth0-ab-acceptance.md)을 따른다.
기존 [첫 설정 순서](architecture/auth0-pc-first-flow.md)의 Application/API 각 하나를 그대로 쓴다.

## 로컬 구성

- DB `platform_core`, 대상 `127.0.0.1:3307`의 기존 별도 MySQL. MariaDB:3306과 무관하다.
- 앱 `platform_core_app`: 6개 Core 자료 표 SELECT/INSERT/UPDATE, 버전 표 SELECT만.
- `platform_core_migrator`: Core CREATE/INDEX/REFERENCES, 버전 표 SELECT/INSERT만.
  업무 계정·세션 자료 SELECT/INSERT/UPDATE·DELETE, 제품 DB 접근은 거부된다.
- 관리자(root)는 기존 로컬 bootstrap/백업에만 사용한다. 앱은 관리자 자격을 읽지 않는다.
- 암호는 Git 제외 `.env.auth0-pc`/`.env.core-admin`에 접근 제한으로 저장한다. 값 출력 금지.
- 기존 Core 이름 충돌 시 bootstrap은 실패하며 계정/DB/표를 교체하지 않는다.
  부분 적용 재개는 이 도구가 만든 로컬 manifest·자격이 있는 경우에만 명시적 `finish-bootstrap`으로 한다.

신규 schema는 [001](../migrations/platform_core/001_pc_auth.sql)의 7개 표다. 공통 identity
매핑·로그인 거래·세션·token 결합·동의가 Core에만 있고 제품 owner 변경은 없다.
정확한 SHOW CREATE 구조를 전용 신규 layout DB와 비교하며, 알려지지 않은 표·다른 구조·
상위 schema version을 거부한다. IF NOT EXISTS만으로 기존 구조를 승인하지 않는다.
버전 receipt는 INSERT만 사용하므로 migrator에 UPDATE가 필요 없다.
DDL의 암묵 commit을 전제로 중단 재개·반복을 검증했다. 자동 시작 migration은 없다.

## 실행

사용자가 `.env.auth0-pc`에 실제 `AUTH0_ISSUER`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`을
로컬 편집기로 입력한다. DB 암호와 HMAC/암호화 key는 이미 생성되어 있으므로 변경하지 않는다.
설정 파일 전체나 토큰을 대화에 보내지 않는다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.auth0_pc_settings check
.\.venv\Scripts\python.exe -B -m uvicorn app.auth0_pc:app --host 127.0.0.1 --port 8000 --no-access-log
```

PC에서 `http://127.0.0.1:8000/auth/poc/`를 연다. Application은 Regular Web 하나이며 callback은
`http://127.0.0.1:8000/api/v1/auth/callback/web`다. Flutter 복귀는 없다.
새 서버는 이 **별도 진입점**에만 실제 인증을 설치한다. 기존 `app.main:app`은 그대로 401이다.
포트 8000을 이미 다른 프로세스가 사용하면 임의 종료하지 말고 기존 서버 상태를 확인한다.
설정이 없거나 잘못되면 PC 로그인은 고정 503, 인증된 제품 API는 401이며 가짜 인증은 없다.

웹 cookie는 loopback HTTP 개발 전용이라 Secure가 꺼져 있다. HttpOnly 인증 cookie와
SameSite·고엔트로피 CSRF 자격·고정 Origin 검사를 사용한다. 운영/외부 host에 배포하지 않는다.
브라우저에 JWT/secret을 반환하지 않으며 access JWT·PKCE verifier는 AES-GCM 암호화,
cookie/state/nonce는 hash, token 결합은 HMAC으로 보관한다. 원문 ID token·refresh는 보관하지 않는다.
API 호출마다 서명/issuer/audience/RFC9068/client/시간/scope 및 DB 세션·계정·동의를 확인한다.
미검증 session header·bearer 재등록·메모리 fallback은 없다.

기본 logout은 현재 Core 세션을 영속 폐기한다. 같은 token의 fingerprint는 지우지 않아
새 세션으로 재결합할 수 없다. 다른 세션은 유지하고 IdP SSO 종료는 호출하지 않는다.
현재 PoC는 refresh를 요청하지 않으며 10분 만료 후 새 로그인한다.
진행 중 인증을 이미 통과한 요청은 완료될 수 있고 logout 이후 신규 판단은 차단한다.
별도 사용자 동의 버튼을 누르기 전 기록 API는 403이다. 본인 기록만 허용한다.

### PoC 화면의 서버 확인 상태

`/auth/poc/`와 `/auth/poc/signed-out`은 기존 `identity(product=False)` 검증을 호출하여
로그인 상태와 세션 유효 여부만 표시한다. 제품 동의 여부는 로그인 상태에 영향을 주지 않는다.
401은 로그인되지 않음/유효하지 않음, 검증 서비스 오류는 확인 불가로 표시한다.
토큰·쿠키 값·이메일·계정 식별자는 HTML에 포함하지 않는다. 응답은 `Cache-Control: no-store`다.
페이지 요청 시점의 결과이며 새로고침/서버 상태 다시 확인 버튼으로 재검증한다.
뒤로 가기로 브라우저 캐시에서 복원되면 재요청한다. 현재 앱 로그아웃의 서버 204 응답 후
signed-out 화면으로 이동해 상태를 다시 검증한다. Auth0 SSO 종료나 refresh는 추가하지 않는다.

2026-10-30 검증:

- PASS: `.venv\Scripts\python.exe -B -m scripts.verify_core tests` — 93개, 실패/오류/skip 0.
  기존 인증 회귀와 제품 데이터 보존 검사를 포함한다. 합성 Auth0 + 실제 로컬 MySQL에서
  반복 페이지 요청, 민감값 미포함, 로그아웃 후 기존 쿠키/API 접근 401을 확인했다.
  새 Python 프로세스에서 동일 DB/key와 암호화 전달한 합성 쿠키로 활성 세션 화면/API 유지,
  폐기 세션 화면/API 거부를 확인했다. 기존 토큰의 폐기 상태 유지 검사도 포함한다.
- PASS: `.venv\Scripts\python.exe -B -m pip check`, `git diff --check`.
- PASS (사용자 전달, 2026-10-30): 실제 Auth0 A/B PC 브라우저 인수.
  same_account_relogin/distinct_b true, acceptance PASS, A/B 각 19개 PASS.
- NOT_RUN: 실행 중 Uvicorn 서버의 실제 중단·재시작. 새 프로세스 HTTP 검증과 구분한다.

기존 실제 Auth0 callback PASS 증거는 변경하지 않았다. 데이터 초기화·migration·commit·push는
수행하지 않았다. 표시 변경을 되돌릴 때에는 이번 화면/검증 변경만 되돌리고 Core DB/key는 유지한다.

## 검사·관리 명령

### callback 이후 오류 진단 (2026-10-30)

`auth_request`는 고정된 요청 분류와 HTTP 상태만 기록한다. 원본 URL/query/header,
예외 본문, 계정 식별자, 쿠키/토큰은 기록하지 않는다. `auth_session` 단계는
runtime_ready → csrf(변경 요청) → cookie_present → cookie_lookup →
cookie_session_validation → token_decrypt → access_verify → session_lookup →
session_binding 순서다. DB 연결/schema는 `auth_database`, A 등록은
`auth_acceptance stage=register_a`로 구분한다. 제품 API는 scope_consent도 검사한다.
callback 응답 쿠키 구성은 `auth_callback stage=response_cookies`로 구분한다.
FAIL 다음의 상위 단계 FAIL은 같은 오류의 전파일 수 있다.

실행 중 서버가 `--reload` 없이 시작되었으면 파일 수정만으로 진단이 반영되지 않는다.
기존 서버 터미널에서 Ctrl+C 후 위의 동일 실행 명령으로 다시 시작한다.
DB/key/owner는 변경하지 않는다. callback 주소를 새로고침하면 일회용 코드/state를
재사용하게 되므로 `/auth/poc/`를 직접 열고 필요할 때 새 로그인을 시작한다.

이번 조사에서 실행 중 서버의 health/page 응답과 익명 me 401, 현재 설정으로 DB 읽기·
저장 토큰 복호화·세션 조회를 확인했다. 합성 제공자와 실제 로컬 MySQL의 callback,
A/B 등록·재로그인·격리, CSRF/재사용 거부, 새 프로세스 세션 유지 5개 회귀가 통과했다.
이전 진단 시점에는 실제 브라우저 실패 원인이 미확정이었다. 이후 사용자 전달 결과에서는
중지된 MySQL 서비스 시작, API scope 등록, Application의 User-Delegated Access 2/2 허용 후
A 재로그인 및 A/B 인수가 통과했다. Always grant all permissions는 사용하지 않았다.
상세는 [인수 기록](verification/2026-10-30-auth0-ab-acceptance.md)을 따른다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.core_mysql preflight
.\.venv\Scripts\python.exe -B -m scripts.core_mysql migrate
.\.venv\Scripts\python.exe -B -m scripts.verify_core tests
.\.venv\Scripts\python.exe -B -m scripts.verify_core backup-verify
.\.venv\Scripts\python.exe -B -m scripts.core_mysql verify-products
```

검사 출력은 건수·상태만이다. 실패 상세도 토큰·SQL 원문을 반사하지 않는다.
합성 MySQL suite는 새 UUID만 추가·수정·soft-delete하고 보존한다.
`RUN_CORE_TESTS=1` 없는 일반 unittest는 Core 통합 검사를 skip한다.
전체 검증기는 기존 MySQL 9개도 포함하며 자동 DROP·표 덮어쓰기·사용자 자료 초기화를 하지 않는다.

Core 백업은 접근 제한 외부 임시 폴더의 JSON 형식으로 byte/datetime을 보존한다.
서버 token 암호화 key와 HMAC key도 별도 접근 제한 백업 정책이 필요하다. DB 파일만으로 복호화되지 않는다.
테스트 복원은 새 `core_restore_*` DB에만 하고 원본과 비교한다. 백업 위치는 Git 제외
`.env.core-backup-location`에서 로컬로 확인한다. 복원 DB·합성 fixture·layout/check DB는 보존한다.
운영용 mysqldump/PITR·보유기간·장애/부하 검증을 완료했다는 뜻은 아니다.

기존 제품 행은 시작 시 값의 digest만 기록해 검사하며 행 원문을 출력하지 않는다.
제품 표 목록과 시작 시 모든 행이 남아 있는지 확인한다. 별도 합성 회귀가 새 행을 추가할 수 있다.

## 복구와 한계

프로세스 재시작은 같은 DB·key를 사용하여 활성/폐기 세션을 보존한다. 새 Python 프로세스로 검증했다.
백업을 실제 서비스 DB에 복원하는 작업은 이번에 하지 않았다. 향후 복원 시 오래된 활성 세션이
살아나지 않도록 전체 세션을 폐기하고 재로그인하는 절차를 별도로 적용해야 한다.
실제 사용자 자료 삭제·schema down migration·DROP 없이 기존 `app.main`의 401로 복귀할 수 있다.
Core DB/세션/제품 기록은 보존한다.

제한: 자체 제한형 JWT parser는 개발 PoC 범위다. 운영 JWT 라이브러리/보안 검토·실제 Auth0
key rotation 상호운용·브라우저 다중 tab·보안/복구 이벤트·운영 Secure cookie/TLS·보유/정리 정책은
별도 단계다. 실제 외부 Auth0 A/B PC 연결은 사용자 전달 인수 PASS이며,
유효한 토큰과 기존 브라우저 쿠키를 사용한 실제 API 프로세스 재시작 후 세션 복원은
[사용자 전달 PASS](verification/2026-10-30-restart-verification.md)다.
모바일·운영 적용과 토큰 만료 후 처리는 NOT_RUN이다.
