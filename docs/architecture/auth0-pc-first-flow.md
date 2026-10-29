# PC 브라우저 Auth0 첫 연결: Application 하나

2026-10-29. 기존 [개발 PoC](auth0-development-poc.md)를 첫 PC 흐름에 한해 축소한다.
범위: PC browser → Core → Auth0 → Core callback → 영속 Core 앱 세션.
Application 1개·API 1개·합성 A/B만 사용한다. 모바일·Flutter·SPA·refresh·IdP SSO 종료는 제외한다.
현재 구현: 승인 후 Core migration·callback·영속 repository를 적용하고 합성 검증했다.
2026-10-30 실제 Auth0 A/B PC 인수는 사용자 전달 결과 PASS다.
[인수 기록](../verification/2026-10-30-auth0-ab-acceptance.md)의 범위·한계를 따른다. 아래 최초 설계/승인 검토 기록보다
[현재 실행 안내](../local-core-auth.md)와 최신 검증 기록을 우선한다.

## 1. 계정과 tenant 생성 순서

1. [Auth0 가격](https://auth0.com/pricing)에서 **Free / $0 / Start building for free**를 선택한다.
   관리자 계정을 본인이 생성하고 필요한 관리자 이메일 인증을 완료한다.
   카드·결제·유료 addon 가입을 요구하면 중단한다. custom domain은 설정하지 않는다.
2. 첫 tenant 생성 화면 또는 Dashboard 왼쪽 위 tenant 메뉴의 **Create Tenant**를 연다.
   이름 후보 `jesuslife-core-poc`를 사용하되 가용한 이름을 고른다. Environment는
   Development를 선택할 수 있으면 선택한다. 여러 유료 환경 구성을 만들 필요는 없다.
3. **Region 드롭다운을 실제로 확인**한다. 공식 공개 locality는 Japan, Australia, Canada,
   Europe, United Kingdom, United States다. 이 목록이 특정 사용자 Free 가입 화면에
   모두 표시된다고 확인된 것은 아니다. 한국 PC 테스트에는 **Japan(JP)**를 추천한다.
   JP가 없거나 유료 선택으로 표시되면 생성하지 않고 표시된 무료 선택지를 다시 검토한다.
   region은 단순 변경할 수 없으며 실제 지연·국내 저장을 보장하지 않는다.
4. 가입 화면의 plan/subscription이 **Free/$0**인지 확인한다. 자동 trial이 보이면
   유료 전환/결제 수단을 추가하지 않고 이번 기능이 Free에서도 가능한지 확인한다.
   무료 가능 여부가 불명확하면 진행하지 않는다. 현재 계정 화면은 아직 확인하지 못했다.
5. Dashboard **Settings → General** 또는 생성한 Application Settings에서 실제 Domain을
   확인한다. issuer는 `https://실제-Domain/`이며 끝 `/`를 포함한다.
   tenant 이름만으로 region suffix를 추측하지 않는다. Domain은 공개 설정이나 secret은 아니다.

근거: [tenant/지역](https://auth0.com/docs/get-started/auth0-overview/create-tenants),
[Free 가격](https://auth0.com/pricing). 공개 자료 확인과 사용자 계정 UI 확인을 구분한다.

## 2. API 하나 만들기

Dashboard **Applications → APIs → Create API**:

| 필드 | 입력 |
|---|---|
| Name | `JesusLife Core PoC API` |
| Identifier | `https://api.jesuslife.example/poc` |
| Signing Algorithm | `RS256` |

Identifier는 API 대상 식별자이며 해당 호스트를 실제로 접속할 필요는 없다.
생성 후 API **Settings**에서 access token profile을 **RFC 9068**
(`rfc9068_profile`)로 설정한다. 해당 설정이 무료로 제공되는지 실제 화면에서 확인한다.
Token Expiration과 Browser Flows 값을 보이는 범위에서 각각 **600초**로 설정하고 저장한다.
JWE는 사용하지 않는다. **Allow Offline Access는 끈 상태로 유지**한다.
이번 흐름은 refresh token을 요청하지 않으므로 rotation·grant revoke 설정은 필요 없다.
API **Permissions**에 `neorang-narang:read`, `neorang-narang:write` 두 항목을 추가한다.
`jl-core-poc-pc`의 User-Delegated Access에서도 두 권한을 명시적으로 허용하고
2/2 저장을 확인한다. Always grant all permissions는 사용하지 않는다. 변경 후 재로그인한다.
이 scope 자체가 개인 기록 공유 동의나 owner 인증은 아니다.
API 생성 중 자동으로 생성된 Test/M2M Application은 이번 로그인에 사용하지 않으며
M2M 테스트 token을 받거나 코드에 넣지 않는다.

프로파일 설정 메뉴는 UI 버전에 따라 달라질 수 있다. 찾을 수 없으면 기본 Auth0 프로파일로
조용히 대체하지 않는다. [공식 profile 안내](https://auth0.com/docs/secure/tokens/access-tokens/access-token-profiles)의
Configure Access Token Profile 링크를 따라 확인한다.

## 3. Regular Web Application 하나 만들기

Dashboard **Applications → Applications → Create Application**:

- Name: `jl-core-poc-pc`
- Type: **Regular Web Applications** → Create
- Settings → Allowed Callback URLs:
  `http://127.0.0.1:8000/api/v1/auth/callback/web`
- Settings → Allowed Logout URLs:
  `http://127.0.0.1:8000/auth/poc/signed-out`
- Application Login URI가 필수로 표시될 때만:
  `http://127.0.0.1:8000/auth/poc/login`
- 브라우저가 Auth0 token endpoint를 직접 부르지 않으므로 Allowed Web Origins/CORS는
  이번 Core 서버 흐름을 위해 추가하지 않는다. wildcard는 넣지 않는다.
- Advanced Settings의 Grant Types는 **Authorization Code만** 사용한다.
  Client Credentials/Implicit/Password/Refresh Token은 이번 PC 흐름에서 사용하지 않는다.
- Credential Settings의 token endpoint client 인증은 **Client Secret Post**로 설정한다.
  ID token 서명 알고리즘도 RS256인지 확인한다. API 서명 알고리즘과 별개다.
- Connections에서 테스트용 Database connection 하나를 이 Application에 활성화한다.
  기존 기본 DB connection을 사용해도 되며 사용자 import나 자동 linking은 하지 않는다.
- Save Changes. Client ID·Client Secret·Domain을 확인하되 secret은 로컬 파일에만 입력한다.

Core가 confidential OAuth client이므로 브라우저·Flutter에는 client secret을 주지 않는다.
Core가 state/nonce/PKCE S256 verifier를 생성·보관하고 code 교환을 수행한다.
[Application 설정](https://auth0.com/docs/get-started/applications/application-settings),
[confidential 앱](https://auth0.com/docs/get-started/applications/confidential-and-public-applications)

## 4. Core callback과 복귀 주소

| 역할 | 정확한 개발 주소 | 등록 위치 |
|---|---|---|
| 로그인 시작 후보 | `http://127.0.0.1:8000/auth/poc/login` | Core의 향후 로컬 UI |
| Auth0 → Core callback | `http://127.0.0.1:8000/api/v1/auth/callback/web` | Auth0 Allowed Callback URLs |
| Core 세션 생성 후 PC 화면 | `http://127.0.0.1:8000/auth/poc/` | Core 내부 고정 경로 |
| Core logout 후 화면 | `http://127.0.0.1:8000/auth/poc/signed-out` | Core 내부 경로; IdP logout 실험 대비 Auth0 허용목록 |
| Flutter 복귀 | **이번에는 없음** | deep link·5173·다른 Application 등록 불필요 |

Auth0 callback은 Flutter 복귀 주소가 아니다. 위 경로는 아직 구현되지 않았고 현재 404다.
`localhost`와 `127.0.0.1`을 섞거나 포트를 변경하지 않는다. 로그인 후 고정 PC 화면으로만
303 이동하고 query의 임의 return URL로 이동하지 않는다.
기본 logout은 Core 세션 폐기이며 Auth0 `/oidc/logout`을 호출하지 않는다.
따라서 재로그인 시 IdP SSO cookie로 같은 계정이 선택될 수 있다. 합성 A/B 전환 검증에는
명시적 재인증/계정 선택 또는 서로 다른 브라우저 프로필을 사용한다.

## 5. 로컬 설정 파일과 환경변수 계약

프로젝트 루트 PowerShell에서 다음을 실행하면 **기존 파일을 덮어쓰지 않고**
`.env.auth0-pc`를 만들고 파일 접근을 제한한다. 기존 MySQL `.env`는 수정하지 않는다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.auth0_pc_settings prepare
```

로컬 편집기로 `.env.auth0-pc`만 열어 다음 값을 입력한다. 파일 전체를 터미널·대화·로그로
보내지 않는다. 사용자 비밀번호와 access/refresh token은 이 파일에도 입력하지 않는다.

| 이름 | 입력/관리 |
|---|---|
| `AUTH0_ISSUER` | 실제 Domain의 HTTPS issuer, 끝 `/` 포함 |
| `AUTH0_CLIENT_ID` | PC Regular Web Application의 Client ID |
| `AUTH0_CLIENT_SECRET` | 해당 앱 secret, 로컬 파일에만 |
| `AUTH0_AUDIENCE` | 고정 `https://api.jesuslife.example/poc` |
| `AUTH0_CALLBACK_URL` | 고정 `http://127.0.0.1:8000/api/v1/auth/callback/web` |
| `CORE_DB_HOST`, `CORE_DB_PORT` | `127.0.0.1`, `3307` |
| `CORE_DB_NAME`, `CORE_DB_USER` | `platform_core`, `platform_core_app` |
| `CORE_DB_PASSWORD` | DB 적용 승인 후 별도 앱 계정 생성 시 설정. 기존 nn_app 비밀번호 재사용 금지 |
| `CORE_TOKEN_HMAC_KEY` | prepare가 생성하는 독립 32바이트 base64 key. 유지하고 출력하지 않음 |
| `CORE_TOKEN_ENCRYPTION_KEY` | prepare가 생성하는 별도 32바이트 base64 key. 재시작 간 유지 |

`.env.auth0-pc`는 현재 `.gitignore`의 `.env.*` 규칙으로 제외된다.
프로세스 환경변수명도 위 이름을 사용할 계획이지만 **현재 실행 앱은 이 설정을 읽지 않는다**.
준비 도구는 파일만 명시적으로 읽고 보간하지 않는다. secret에 `$` 등이 있어도 확장하지 않는다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.auth0_pc_settings check
```

check는 값 대신 준비 상태만 출력한다. 실제 Auth0 연결·키/secret 유효성·DB 연결·로그인
가능 여부를 검증하지 않는다. DB 승인 전 비밀번호가 비어 있으면 NOT_READY가 정상이다.

## 6. Core migration 승인 검토안

아래는 최초 검토안이다. 후속 사용자 지시로 신규 Core DB·서비스 계정·migration 적용과
callback 구현이 명시적으로 승인되어 적용했다. 추가 승인을 다시 요구하지 않는다.
실행/권한/복구 결과는 [현재 안내](../local-core-auth.md)를 따른다.

제안 대상: 기존 로컬 MySQL **127.0.0.1:3307**에 별도 논리 DB `platform_core`와
앱 계정 `platform_core_app`을 생성한다. 관리자 runner만 DDL을 수행하고 앱 계정은
Core DB의 SELECT/INSERT/UPDATE만 갖는다. DELETE/DDL/타 제품 DB 접근 권한은 없다.
`nn_app`·`life_diary_app`에도 Core DB 권한을 추가하지 않는다.

[구체 migration 초안](../../migrations/platform_core/001_pc_auth.sql)의 **7개 표**:

| 표 | 저장·제약 |
|---|---|
| `accounts` | 공통 UUID·계정 상태·security version |
| `external_identities` | 정확한 `(issuer, subject)` UNIQUE와 Core UUID. VARBINARY로 대소문자/후행 공백까지 구분 |
| `login_transactions` | state/cookie/nonce hash, 암호화 PKCE verifier, 고정 client/callback, 단일 소비·만료 상태 |
| `app_sessions` | Core UUID·외부 identity/client, hash된 고엔트로피 cookie·CSRF 자격, 폐기/만료·version |
| `session_access_tokens` | UNIQUE HMAC fingerprint·암호화 access JWT·세션·만료. 재결합 금지 |
| `product_consents` | 너랑나랑 메타데이터 테스트 동의, 목적/버전/generation·철회. 로그인만으로 자동 생성하지 않음 |
| `core_schema_version` | Core migration 1, 마지막에 receipt 기록 |

첫 흐름은 refresh를 보유하지 않으므로 refresh vault/outbox/lease 테이블은 만들지 않는다.
session 만료도 access JWT 유효기간을 넘기지 않는다. 만료 시 새 code 로그인으로 복구한다.
인증 자체에는 제품 동의가 필요 없고 기록 테스트 시작 전에 별도 동의를 받는다.
계정·매핑·세션·token 결합은 단일 Core 트랜잭션, identity UNIQUE 충돌 시 전체 rollback 후
기존 매핑 재조회다. triple FK로 identity와 session의 account UUID 일치도 제한한다.
기존 너랑나랑 owner와 자동 매핑·JOIN·FK·cascade·자료 이전은 없다.

**적용 절차 (승인 전 미실행):**

1. 호스트/포트·DB 이름·기존 Core 존재 여부를 확인하고 대상 Core DB가 있으면 먼저 접근 제한
   백업을 만든다. 기존 제품은 행을 출력하지 않고 schema·기존 행 보존 증거를 비교한다.
2. 새 DB/앱 계정을 별도 생성하고 admin runner에서 migration named lock을 잡는다.
   지원하지 않는/상위 version·예상과 다른 기존 schema는 거부한다.
3. FK 순서로 additive DDL 실행. MySQL DDL의 암묵 commit을 전제로 중간 실패 후
   표 구조를 검사한 뒤 재개한다. IF NOT EXISTS만으로 구조 일치를 주장하지 않는다.
4. 버전 receipt는 전체 구조 확인 후에만 기록한다. SQL 파일은 검토 초안이며 직접 통째로
   실행하는 runner가 아니다. 실행 도구·검증기가 준비되기 전 수동 적용하지 않는다.
5. 별도 합성 검증 환경에서 새 설치·중단 재개·반복·상위 버전 거부·UNIQUE/권한·동시 매핑을
   검증한다. 이미 존재하는 Core 버전 upgrade 경로는 없으며 0→1만 대상이다.
6. Core 백업을 별도 DB에 복원하고 매핑·폐기·token 결합 상태를 비교한다. 복원 후에는
   이전 세션 전부를 fail-closed로 무효화하고 새 로그인으로 복구하여 폐기 상태 역행을 막는다.

**rollback:** PC 로그인/연결을 비활성화하고 기존 인증 401로 복귀한다. Core·제품 DB와
세션 tombstone은 보존한다. DROP/down migration/owner 변경으로 되돌리지 않는다.
동일 앱 버전·동일 암호키로의 **단순 서버 재시작**은 DB 상태를 유지해야 하며 백업 복원과 구분한다.
혼재 버전은 Core schema가 없으면 401/503, 이전 앱은 현재 공개 경로·기록 동작을 유지한다.

## 7. 설정/승인 후 실제 검증 순서

User Management → Users → Create User에서 합성 A/B 두 계정을 전용 connection에 만든다.
테스트용 이메일/비밀번호는 사용자 로컬에서만 관리한다. 메일 인증을 요구하는 정책이면
본인이 관리하는 테스트 mailbox를 사용해 정상 완료하고 인증을 우회하지 않는다.

영속 broker 구현·Core DB 적용 이후 다음을 실제 Auth0 연결로 검사한다.

1. A 로그인: PKCE/state/browser binding/code 단일 소비, ID token 서명·issuer·client aud·nonce·시간,
   필요한 azp/at_hash, access token 서명·RFC9068·API audience·client_id·jti·시간·scope 검증.
   token/claim 원문 대신 검사 항목별 PASS/FAIL만 저장한다. 기본 프로파일이면 FAIL로 중단한다.
2. A 재로그인: 다른 세션에서 동일 Core UUID인지 내부 비교하고 UUID 원문 대신 동일 여부만 보고한다.
3. B 로그인: 다른 UUID인지 확인하고 선택 동의 후 합성 기록만 생성한다. A/B의 목록·조회·수정·
   삭제·재시도와 같은 record ID를 격리한다. 기존 사용자 기록은 선택/수정하지 않는다.
4. A logout: Core 폐기 commit 뒤 보관 중인 A의 기존 JWT로 서버 내부 요청을 재생하여 401 확인.
   B와 A의 다른 세션은 유지한다. 토큰을 브라우저/대화로 꺼내지 않는다.
5. 서버 프로세스만 재시작: 같은 DB·key로 A의 폐기 상태와 UUID 매핑, 만료 전 B 세션·기록 유지.
   만료된 token은 재시작 여부와 무관하게 401이다. Core 메모리 fallback 금지.
6. 로그와 보고서에는 code·state·Authorization·Cookie·secret·token·subject·개인 원문을 남기지 않는다.
   개발 서버도 access log/debug traceback을 끄고 callback 실패는 고정 오류로 처리한다.

합성 오프라인 테스트 결과와 실제 Auth0/DB/재시작 결과는 별도 표로 보고한다.
2026-10-30 실제 연결과 A 재로그인·B 구분·양방향 기록 격리는 사용자 전달 인수 PASS다.
A/B 각 19개 항목만 확인된 범위이며, 위 5번의 실제 서버 재시작 인수, 모바일·운영 배포는
**NOT_RUN**이다. 실제 token claim별 독립 검증이나 SSO 전체 종료까지 완료했다고 간주하지 않는다.
