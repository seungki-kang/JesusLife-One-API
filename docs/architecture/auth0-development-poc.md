# Auth0 개발 PoC 실행 계약과 사용자 설정 순서

2026-10-29. Auth0 최종 채택 전 개발 PoC만 승인됨. Free 플랜·합성 계정만 사용한다.
유료 가입·운영 적용·실제 기록 이관은 범위 밖이다. 기존 [계약](platform-auth-contract-draft.md)과
[비교](managed-oidc-provider-comparison.md)를 이번 PoC에 한해 아래처럼 구체화한다.
이 문서의 프로파일/기간/주소는 PoC 제안값이며 운영 기본값이 아니다.

## 1. Flutter PKCE와 Core 중개의 구분

직접 방식에서는 Flutter Native 앱이 Auth0의 public OAuth client가 되어 PKCE verifier를
만들고 code 교환·refresh를 수행한다. 이 방식은 mobile secret을 필요로 하지 않지만,
Core가 모르는 토큰이 계속 발급될 수 있다. 이번 세션 결합 PoC에는 이 직접 방식을 쓰지 않는다.

이번 방식에서 Auth0의 OAuth client는 **Core의 confidential Regular Web Application**이다.
Flutter는 사용자 에이전트를 여는 클라이언트이며 Auth0 token endpoint를 직접 호출하지 않는다.
별도의 Native/SPA client에 broker의 secret을 복사하거나 앱에서 Auth0 SDK 자동 refresh를
동시에 켜지 않는다. Core broker별 client는 Android/iOS/Web를 분리하는 안으로 시작한다.
이 client들은 같은 tenant/로그인 도메인을 사용하지만 앱 세션은 각각 독립이다.

두 종류의 verifier를 구분한다.

1. **Core→Auth0 PKCE:** Core가 upstream verifier·state·nonce를 만들고 로그인 거래에
   보관한다. 브라우저는 Auth0 `/authorize`로 이동하고 고정 Core callback에 code를 반환한다.
   Core만 client 인증+upstream verifier로 code를 한 번 교환한다. ID token은 로그인 용도로
   issuer·서명·client audience·exp·nonce 등을 검증하고 access token과 subject가 같은지 확인한다.
2. **Flutter→Core 인계 PKCE:** 모바일이 별도 verifier/challenge를 만들고 challenge를
   로그인 거래 생성 요청에 보낸다. Core callback 후 등록된 앱 return URI에 짧은 일회용
   인계 코드만 보낸다. Flutter는 인계 code+모바일 verifier로 Core에 교환 요청한다.
   Core는 거래·앱·return URI·challenge 결합과 만료/단일 소비를 원자적으로 확인한다.

Upstream state/nonce와 downstream verifier는 서로 대체하지 않는다. 다른 앱의 code,
바꾼 return URI, 재생한 state/code/verifier는 거부한다. PKCE verifier는 43~128자의
고엔트로피 무작위 값, S256만 사용한다. 재시도 때 새 로그인 거래와 verifier를 생성한다.
웹은 같은 역할의 Core BFF를 사용하되 callback 후 HttpOnly 세션 cookie를 설정하고
허용된 웹 경로로 이동한다. cookie와 Origin/CSRF 보호로 브라우저 거래를 결합한다.

| 자격/상태 | 모바일 | Core | 웹 브라우저 |
|---|---|---|---|
| Auth0 client secret | 없음 | OS/비밀 보관소에만. Git/로그 제외 | 없음 |
| Auth0 refresh token | 없음 | 암호화 보관, 키 분리. 회전 상태 직렬화 | 없음 |
| Auth0 access JWT | 메모리 중심. 업무 API의 Bearer | 웹 대리 호출용 보호 보관, HMAC 결합 색인 | BFF 사용 시 전달하지 않음 |
| Core 갱신 자격 | Keychain/Keystore. 서버에는 hash | 세션별 hash·회전/폐기 상태 | HttpOnly/Secure/SameSite cookie |
| 인계 verifier·code | 짧은 거래 동안 메모리, 소비 후 제거 | challenge와 보호된 거래 상태·소비 결과 | 웹은 서버 거래+cookie |
| 공통 UUID·캐시·큐 | 계정별 분리. token 저장소와 기록 DB 구분 | Core 계정 저장소 | 계정 전환 시 이전 응답 폐기 |

Core 갱신 자격은 높은 엔트로피의 비밀이고 단순 session UUID가 아니다. 성공 시 회전하며
재사용 탐지·응답 유실 정책을 정의해야 한다. secret·refresh·code는 URL/로그에 넣지 않는다.
기본 logout은 전송/refresh 중지·자격 제거와 Core 폐기를 수행한다. Auth0 SSO cookie는
남을 수 있어 명시적 재로그인은 비밀번호 재입력 없이 진행될 수 있다. 계정 선택/전환은
별도 사용자 동작이며 새 로그인 거래와 로컬 generation을 사용한다.

## 2. access JWT를 특정 앱 세션에 결합

채택할 PoC 프로파일 후보: **RS256 + RFC 9068(`rfc9068_profile`)**, `typ=at+jwt`,
`client_id`, `jti`, issuer, API audience, sub, iat, exp, scope를 검증한다.
Auth0 기본 프로파일의 `azp`와 혼용하지 않는다. 기본 프로파일 token은 이번 검증기가 거부한다.
API 대상은 client ID가 아니며 ID token·M2M·opaque token을 개인 기록 API에 받지 않는다.
최대 access 수명 600초, clock skew 최대 30초를 PoC 값으로 제안한다.
Core 세션 결합 검사는 token 만료 시각 자체 이후에는 허용하지 않아 실제 API 만료 유예는 없다.

1. Core가 직접 교환한 Auth0 응답을 검증하고 `(issuer, subject)`를 공통 UUID에 매핑한다.
2. 신뢰된 로그인 거래에 묶인 app/client·공통 UUID·새 Core session을 확정한다.
3. JWT 원문에 Core 전용 HMAC-SHA256을 적용한다. fingerprint를 유일 키로 session에 등록한다.
   원문 JWT나 헤더 session ID를 소유권 증거로 저장하지 않는다.
4. API에서 서명·프로파일 검증 후 같은 fingerprint로 결합을 조회한다. 해당 세션의
   identity/client 일치·활성/만료·계정 상태·scope·동의를 확인한 뒤 Core UUID를 사용한다.
5. 토큰이 유효해도 등록되어 있지 않으면 401. 공개 bearer 등록 API는 만들지 않는다.
   `X-Session-ID`를 바꿔도 fingerprint가 가리키는 세션을 바꿀 수 없다.

Auth0 `sid`/사용자 UUID는 Core 앱 세션 ID가 아니다. jti만 믿거나 사용자별 전체 토큰을
같은 세션으로 간주하지 않는다. 토큰을 세션에 등록할 권한은 검증된 code/refresh 결과의
한 번만 소비되는 서버 거래 증거에서 나오며 client 요청의 JWT 단독 제출에서는 나오지 않는다.

## 3. 재등록·refresh·logout·재로그인과 경합

- fingerprint 전역 UNIQUE. A1에 등록된 토큰은 A2 또는 B1에 옮길 수 없다.
  logout 때 결합 행을 삭제하지 않는다. 폐기된 세션·결합의 tombstone을 token 만료와
  재생 방지 기간까지 유지한다. PoC 중에는 청소하지 않는다.
- HMAC key를 바꾸어 토큰이 새 fingerprint가 되는 것도 재등록 우회가 될 수 있다.
  이번 오프라인 PoC는 한 key만 사용한다. 실제 키 교체 시 모든 유효 key version의 결합을
  조회·중복 검사하고 기존 token의 수명 종료 전 구 key/index를 폐기하지 않는 별도 설계가 필요하다.
- Core refresh 자격 확인 → 세션별 single-flight/lease 획득 → version 캡처 → Auth0 refresh →
  JWT 검증 → 활성 세션·같은 version·lease를 CAS로 재확인 → 새 token/refresh 자격을
  commit한 뒤 반환한다. IdP refresh 호출 자체를 병렬로 보내지 않는다.
- logout은 같은 세션 version을 증가시키고 폐기를 commit한다. refresh가 늦게 돌아오면
  CAS 실패로 등록/반환하지 않으며 새 IdP 자격은 보호된 outbox로 폐기한다.
- logout commit 뒤의 신규 인증 판단은 구·갱신 JWT 모두 401. 그 전에 인증이 끝난
  진행 중 요청은 완료될 수 있다. Flutter는 logout/전환 후 늦은 응답을 generation으로 폐기한다.
- 재로그인은 새 code 거래·새 세션·새 토큰을 요구한다. 동일 계정은 같은 Core UUID를
  사용하되 과거 token/큐를 새 세션에 자동 등록하지 않는다. Auth0가 우연히 동일 JWT를
  반환해도 결합 충돌로 거부하고 새 거래로 복구한다.
- Auth0 refresh token 회전을 켜고 **Refresh Token Revocation Deletes Grant를 끈다.**
  grant 전체 revoke로 다른 기기를 로그아웃시키지 않는다. 실제 `/oauth/revoke`의
  family 단위 영향·재사용 탐지는 두 세션으로 검증한다. 기본 logout에 global revoke나
  `/oidc/logout`을 자동 호출하지 않는다.
- 외부 revoke 장애여도 Core 폐기 commit은 API 접근을 차단한다. Core 장애/commit 실패는
  503이며 성공으로 표시하지 않는다. 회전 응답 유실은 구 refresh를 무한 재사용하지 않고
  안전하게 재로그인한다. 세션 재시작/다중 worker/복원 후에도 폐기 상태를 유지해야 한다.

## 4. Core DB 경계와 이번 코드 범위

공통 계정·외부 identity·세션·로그인 거래·결합·동의·폐기 outbox는 **Platform Core** 소유다.
별도 논리 DB `platform_core`와 전용 계정을 제안하되 엔진·DDL·grant·migration은 미적용이다.
너랑나랑 `nn_completion_owners`는 잠금 표 그대로이며 공통 계정 DB로 사용하지 않는다.
기존 owner UUID·revision·tombstone과 Flutter 로컬 기록을 변경/자동 매핑하지 않는다.
상세 후보 스키마와 원자적 UUID 매핑은 [계약 2~3절](platform-auth-contract-draft.md)을 따른다.

[오프라인 코드](../../app/core/auth0_poc.py)는 S256, 명시적 신뢰키 기반 RS256/RFC9068 검증,
결합 후보 검사, 세션 registry 조회 gate만 제공한다. 실제 `get_current_user`에는 연결하지 않았다.
새 dependency override·개발 로그인·특수 헤더·환경변수 인증 우회가 없다. 실행 API는 계속 401이다.
추가 패키지는 설치하지 않고 기존 cryptography를 사용했다. 이 제한된 PoC parser는 운영
JWT 라이브러리 채택/보안 검토를 대체하지 않는다. 전면 활성화 전에 검증된 JWT 라이브러리와
JWKS cache/회전·실제 Auth0 token에 대한 상호운용 테스트를 포함해 재검토한다.

미구현: HTTP 로그인/인계/refresh/logout, upstream ID token·nonce 검증, JWKS 네트워크 취득,
영속 Core repository·원자적 계정 매핑, 암호화 refresh 보관/outbox, Flutter/BFF 연결.
따라서 Auth0 대시보드를 설정하는 것만으로 현재 서버 인증이 활성화되지는 않는다.

## 5. tenant·앱·API 설정 제안값과 확정 필요값

region 추천: **Japan(JP)**. 한국 개발 환경에서 가까운 공개 지역을 우선 비교하려는 선택이며
실측 지연/법적 적합성을 보장하지 않는다. 공개 자료상 Japan locality가 있다. 실제 Free 생성
화면의 선택 가능 여부를 확인하고 없으면 임의로 다른 지역에 생성하지 않는다. tenant region은
나중에 단순 변경할 수 없으므로 개발용 합성 자료만 사용한다. [tenant 공식 자료](https://auth0.com/docs/get-started/auth0-overview/create-tenants)

플랜 추천: **Free $0**, 카드 등록·custom domain·유료 addon·Enterprise trial 기능에 의존하지 않음.
무료 범위에서 설정이 불가능하면 미확인/BLOCKED로 남기고 업그레이드하지 않는다.
현재 공개 가격은 Free 25,000 MAU를 표시하지만 PoC는 합성 2계정만 사용한다.
[공식 가격](https://auth0.com/pricing), [trial 종료 안내](https://support.auth0.com/center/s/article/Question-regarding-the-Free-and-the-Trial-plan)

| 설정 | PoC 값/확인 방식 |
|---|---|
| Tenant | 제안 이름 `jesuslife-core-poc`, Environment Development, Japan. 이름 가용성 미확인 |
| 정확한 issuer | **미확정**. 생성 후 Dashboard Domain과 discovery의 `issuer`를 정확히 복사. `https://<실제-domain>/`의 끝 `/` 포함. tenant 이름으로 추측하지 않음 |
| JWKS | 신뢰한 discovery의 `jwks_uri` 확인. 기대 위치는 issuer의 `.well-known/jwks.json`. 호스트/HTTPS 허용목록 확정 |
| API 이름 / Identifier(audience) | `JesusLife Core PoC API` / **`https://api.jesuslife.example/poc`**. 이 Identifier는 식별용 URI이며 실제 접속 서버 URL이 아님 |
| API 서명 / token profile | RS256 / RFC 9068 `rfc9068_profile`, JWE 비활성 |
| API permissions | `neorang-narang:read`, `neorang-narang:write`. 인가와 별개로 Core의 제품 동의 필수 |
| access token 기간 | 일반/browser 모두 600초 제안. 실제 발급 exp-iat 확인 |
| API Allow Offline Access | 켬. 로그인 요청에 `openid offline_access`와 필요한 제품 scope. 불필요한 profile/email scope 제외 |
| Broker apps | `jl-core-poc-android`, `jl-core-poc-ios`, `jl-core-poc-web`: **모두 Regular Web Application**. 모바일에 설치되는 confidential 앱이 아니라 Core 서버 client 구분 |
| client 인증/Grant | Core 서버에서만 Client Secret Post, Authorization Code+Refresh Token. upstream PKCE S256 추가. Implicit/Password/Client Credentials grant는 사용하지 않음 |
| refresh | Rotation on, inactivity 1일·absolute 7일의 개발 제안. 응답 유실 시 재로그인. 실제 무료 설정 가용성 확인 |
| tenant revoke | Refresh Token Revocation Deletes Grant off. 다른 세션 유지 여부 실측 |
| 연결 | 전용 DB connection, 합성 A/B만. 기존 사용자 import·이메일 자동 linking 없음 |

정확히 사용할 **로컬 데스크톱 PoC callback** (아직 HTTP 경로 미구현):

| Broker | Auth0 Allowed Callback URL | Auth0 Allowed Logout URL |
|---|---|---|
| Android | `http://127.0.0.1:8000/api/v1/auth/callback/android` | `http://127.0.0.1:8000/auth/poc/signed-out` |
| iOS | `http://127.0.0.1:8000/api/v1/auth/callback/ios` | `http://127.0.0.1:8000/auth/poc/signed-out` |
| Web | `http://127.0.0.1:8000/api/v1/auth/callback/web` | `http://127.0.0.1:8000/auth/poc/signed-out` |

HTTP loopback는 개발 컴퓨터 브라우저에서만 쓴다. 실제 Android/iOS 브라우저의
`127.0.0.1`은 폰 자신이므로 이 값을 실기기 callback으로 쓰지 않는다. 실기기 단계에는
개발 Core의 **실제 HTTPS origin**이 필요하며 아직 제공되지 않아 정확한 URL은 미확정이다.
승인된 HTTPS 개발 origin이 생기면 위 callback의 origin만 교체하고 Auth0/서버 양쪽
허용목록에 정확히 등록한다. wildcard·임의 redirect·운영 도메인 대용은 금지한다.

Core→Flutter 모바일 return URI 후보는 `jesuslife-poc://auth/complete/android`,
`jesuslife-poc://auth/complete/ios`다. **Auth0 callback이 아니라 Core의 별도 허용목록**이다.
실제 앱 ID·deep link/App Link/Universal Link 설정 확인 전 확정값으로 보지 않는다.
인계 PKCE로 custom scheme 가로채기 시 code 교환을 막으며 소유 검증 가능한 HTTPS link를
실기기 최종안으로 우선 검토한다. 웹 return origin은 개발 제안 `http://127.0.0.1:5173`이다.
실제 BFF reverse proxy 배치 후 같은 origin을 사용하고 credential CORS wildcard는 허용하지 않는다.

## 6. 사용자가 수행할 순서

1. 무료 Auth0 계정에서 개발 전용 tenant를 만들기 전에 region JP·Free·과금 조건을 확인한다.
   실제 로그인 비밀번호나 인증 코드를 대화/저장소에 남기지 않는다.
2. tenant Domain과 discovery의 issuer를 확인한다. 공유 가능한 것은 **공개 Domain/issuer**뿐이며
   client secret·비밀번호·access/refresh token을 전달할 필요가 없다.
3. 위 API Identifier·RS256·RFC9068·permissions·600초·offline access를 설정한다.
   무료 계정에서 해당 프로파일/refresh 설정이 실제 제공되는지 확인한다.
4. broker app 세 개를 Regular Web Application으로 만들고 앱별 callback/로그아웃 URL을
   정확히 등록한다. 데스크톱과 실기기 URL을 혼동하지 않는다. secret은 로컬 Core의 비밀
   보관소에만 넣는다. .env를 쓰더라도 Git 제외·접근 제한하고 화면/터미널에 전체 값을 출력하지 않는다.
5. code/refresh grant·rotation·만료·grant-delete off를 확인한다. Native/SPA SDK를 추가해
   토큰을 별도로 발급받는 우회 흐름은 만들지 않는다.
6. 전용 connection의 A/B 합성 계정을 만든다. 실제 교인/이름/신앙 기록은 입력하지 않는다.
7. 공개 설정 값(issuer·client IDs·audience·callback)만 검토하고 Core DB 엔진/스키마 적용을
   별도로 확정한다. 그 후 미구현 broker/JWKS/ID 검증/영속 repository를 구현·검증한다.
8. callback/PKCE·로그인·refresh·A1/A2/B1 폐기·SSO를 실제 tenant에서 검사한다.
   ID token/비밀을 덤프하거나 jwt.io 등 외부 사이트에 실토큰을 붙이지 않는다.
9. 실제 Android/iOS/웹과 다중 worker/재시작에서 모두 인수 조건을 통과한 후 최종 채택을 판단한다.
   PoC 성공도 운영 배포·유료 가입 승인으로 해석하지 않는다.

## 7. 검증 범위와 아직 남은 증거

[오프라인 테스트](../../tests/test_auth0_poc.py)는 RSA 합성 서명 검증, issuer/audience/client/
유효기간·알고리즘·token 종류 거부, PKCE 공식 벡터, A/B UUID 전달, 미등록 거부,
A1 logout 후 A1 old/refreshed 차단과 A2/B1 유지, 구 token 재결합·거래 재생 거부,
refresh CAS 동시성·logout 중 늦은 refresh·동의/계정 상태/저장소 장애를 검사한다.
registry는 **테스트 전용 reference model**이며 영속 Core DB 구현이 아니다.
CAS 모델 성공을 실제 DB 트랜잭션이나 Auth0 refresh single-flight 검증으로 확대하지 않는다.

실제 PoC에서는 아래를 추가로 증명한다.

- code/state/nonce/인계 code의 단일 소비·만료·교차 앱 거부·잘못된 verifier 거부.
- JWKS 키 교체·unknown kid 갱신 제한·SSRF 차단·네트워크 실패 시 503.
- 실제 Core DB UNIQUE·CAS·refresh lease와 두 worker 동시성, 재시작·복원 후 폐기 보존.
- 동일 이메일의 다른 issuer/subject가 자동 병합되지 않으며 동시 첫 로그인에 UUID 하나만 생성.
- 실제 A1/A2/B1로 기본 logout이 A1의 JWT 전부만 차단하고 Auth0 family 폐기도 같은 범위인지 확인.
- Core 폐기 실패/IdP revoke 실패/refresh 응답 유실·재로그인·로그아웃 후 구 token 재등록 차단.
- API A/B 본인 기록 격리, 기존 owner 무변경, Flutter A→B 큐/캐시/늦은 응답 격리.
- 프록시·access log·APM·오류에 code·JWT·secret·기록 원문이 없는지 합성 sentinel로 확인.

## 공식 참고 자료

- [PKCE](https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow-with-pkce)
- [confidential/public 앱](https://auth0.com/docs/get-started/applications/confidential-and-public-applications)
- [Auth0 token profile 차이](https://auth0.com/docs/secure/tokens/access-tokens/access-token-profiles)
- [Refresh rotation](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-rotation)
- [Revoke와 grant 범위](https://auth0.com/docs/secure/tokens/refresh-tokens/revoke-refresh-tokens)
- [RFC 7636 S256 테스트 벡터](https://www.rfc-editor.org/rfc/rfc7636#appendix-B)
