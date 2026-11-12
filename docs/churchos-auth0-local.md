# ChurchOS PC 개발 검증

기준 `main 9820149`. PC 앱은 `scripts/auth0_pc_settings.py`의 `PATH`, 즉
프로젝트 루트 `.env.auth0-pc`를 `interpolate=False`로 읽는다. 일반 `.env`의
PostgreSQL 값이나 프로세스 환경의 활성화 값은 이 opt-in에 사용하지 않는다.
Core 서버 세션은 기존 로컬 MySQL과 기존 키를 그대로 사용한다.

`.env.auth0-pc`에 `JESUSLIFE_PC_CHURCHOS_ENABLED=1`과
`JESUSLIFE_POSTGRES_RUNTIME_DSN`을 명시한 경우에만 소속 조회와
`/auth/poc/login/churchos`를 등록한다. DSN은 비밀값으로 별도 입력하며 문서·명령·로그에
넣지 않는다. 정확한 `127.0.0.1`과 `jl_api_runtime`만 허용한다. migration 자격증명을
전달하지 않는다. import·시작 시 DB 접속은 없으며 인증·scope 통과 후 소속 조회만
연결한다. libpq의 `PG*` 환경 변수가 있으면 조회 연결을 거부한다.
설정 누락·오류 시 ChurchOS 경로를 등록하지 않고 기존 로그인을 유지한다.

`/auth/poc/login`의 기본 scope와 PKCE·nonce·브라우저 바인딩·서버 세션을 유지한다.
쿼리로 scope를 추가할 수 없다. 활성화된 `/auth/poc/login/churchos`에서만
기본 scope에 `churchos:membership:read`를 추가하며 기존 callback을 사용한다.
Auth0가 이 scope를 실제 토큰에 넣지 않으면 기존 인증 경계에서 403이다.
앱 요청값·본문·프로필로 scope나 계정 UUID를 대체하지 않는다.

실제 검증에는 기존 브라우저로 동일 개발 계정의 일반 로그인과 ChurchOS 로그인을
각각 새로 수행해야 한다. 기존 앱 로그아웃 후 다음 로그인을 진행하고, 서버에서
두 세션의 계정 동일성과 세션 구분을 확인한다. 계정 식별자·세션·토큰은 출력하지 않는다.
해당 계정의 Core UUID에 대한 합성 활성 소속을 임시 PostgreSQL 16에만 준비한다.
기존 001·002 migration을 임시 클러스터에만 적용하고 runtime 역할로 조회한다.
결과에는 요청 명령과 HTTP 상태만 남긴다. 검증 후 서버를 종료하고 임시 클러스터를
정리한다. 기존 데이터베이스와 실제 소속은 변경하지 않는다.

## 실제 Auth0 개발 검증 결과

사용자가 전달한 실제 개발 검증 결과와 로컬 요청 관측 기록을 구분해 기록한다.
이전 브라우저 연결 제약으로 인한 BLOCKED 기록은 아래 실제 검증 결과로 갱신한다.

| 요청 | 결과 | 근거 |
|---|---|---|
| 미로그인 소속 조회 | HTTP 401 | 사용자 전달 실제 검증 결과 |
| 같은 계정의 기본 로그인 후 소속 조회 | HTTP 403 | 사용자 전달 실제 검증 결과 |
| ChurchOS 전용 로그인 후 소속 조회 | HTTP 200, 교회 소속 조회 성공, `permissions: []` | 상태 코드는 실제 요청 관측 기록, 빈 권한 목록은 사용자 전달 결과 |

보호된 로컬 `.env.churchos-browser/request-observation.json`에서
`request_observed`, `verified`, `scope_present`, `same_account`, `cookie_session`,
`runtime_active_membership`, `runtime_other_account_hidden`이 모두 참이고
`http_status`가 200임을 확인했다. 이 기록은 PR에 포함하지 않는다.
합성 토큰·세션을 사용하는 PostgreSQL 통합 검증과 실제 Auth0 요청 증거는 구분한다.

성공에 필요한 Auth0 설정은 개발 API에 `churchos:membership:read`를 등록하고,
`jl-core-poc-pc`의 **User-delegated Access**에 해당 scope를 허용하는 것이다.
기본 로그인은 이 scope를 요청하지 않으며 ChurchOS 전용 로그인에서만 요청한다.
`permissions: []`는 소속 응답의 권한 목록이며 로그인 scope와 구분한다.
`memberships:manage`는 로그인 요청 scope가 아니다. 이번 마무리 작업에서는
Auth0 테넌트 설정을 추가 변경하지 않았다.

## 검증 후 정리 확인

- **PASS**: `.env.auth0-pc`에 ChurchOS 활성화 설정과 PostgreSQL 설정이 남아 있지 않다.
- **PASS**: 임시 `.env.churchos-browser/data` 디렉터리와 해당 경로의 PostgreSQL
  프로세스가 없다. 다른 PostgreSQL 프로세스는 변경하지 않았다.
- 지정된 `.env.churchos-browser/cleanup.py`는 존재하지 않았다. 임시 DB와 설정이
  이미 정리되어 추가 DB 정리는 수행하지 않았다.
- **PASS**: 남아 있던 이 프로젝트의 임시 요청 관측 서버만 종료하고,
  기존 `.env.auth0-pc`를 사용하는 `app.auth0_pc:app`을 재시작했다.
  재시작 후 실제 `GET http://127.0.0.1:8000/health`는 HTTP 200이다.
- 보호된 로컬 관측 기록·상태 파일·로그는 Git에 포함하지 않는다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.test_offline
.\.venv\Scripts\python.exe -B -m scripts.verify_postgres_rls --pg-bin 'C:/Program Files/PostgreSQL/16/bin'
.\.venv\Scripts\python.exe -B -m pip check
git diff --check
```

이번 마무리 검증 결과:

- **PASS**: `python -B -m scripts.test_offline` — 243개 실행, 220개 통과,
  23개 SKIP. 기본 공개 경로 회귀와 ChurchOS 설정·로그인 scope 회귀를 포함한다.
- **PASS**: `python -B -m pip check` — 의존성 충돌 없음.
- **PASS**: `git diff --check` — 공백 오류 없음.
- **PASS**: `git status -sb` — 개발 브랜치의 변경 파일 5개 확인.
- **NOT_RUN**: 위 PostgreSQL RLS 리허설 명령은 이번 마무리에서 재실행하지 않았다.
  실제 Auth0 로그인도 다시 수행하지 않고 사용자 전달 결과와 기존 요청 기록을 확인했다.

검증 후 opt-in 두 설정을 제거하면 기존 PC 앱 구성으로 복귀한다. 운영·Supabase·배포·
커밋·푸시는 포함하지 않는다. 인증 경계와 DB 변경의 운영 적용은 계속
**AUTHOR_REVIEW_REQUIRED**이며 이번 범위는 승인된 로컬 개발 검증에 한정한다.
