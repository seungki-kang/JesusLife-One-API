# Platform Core 인증 계약 초안

기준일: 2026-10-29. 상태: 승인된 구조를 반영한 계약 초안.
제공자 선택·DB 구조 적용·실제 인증 활성화는 AUTHOR_REVIEW_REQUIRED.
이번 산출물은 문서와 제공자 독립 테스트 준비이며 운영 인증 구현이 아니다.

## 1. 승인된 기준과 미확정 값

사용자 승인: 관리형 OIDC, 서명된 access JWT와 서버 세션 상태의 결합,
Platform Core의 공통 UUID 발급·관리, 검증된 `(issuer, subject)`의 원자적 매핑,
이메일 기반 자동 병합 금지, 현재 앱 세션의 로그아웃과 그 세션의 기존 토큰 차단.
전체 기기 로그아웃·IdP SSO 종료는 별도 동작이다. 기존 MySQL owner와 로컬 기록은
자동 변경·이전하지 않는다. 이 승인은 아래 세부 스키마·경로·업체의 확정이 아니다.

미확정: 업체·tenant/region·정확한 issuer·API audience·클라이언트 허용목록·JWKS,
토큰 프로파일·수명·clock skew, 세션 수명, 웹 BFF 방식, DB 엔진·배치·보유기간,
복구/보안 이벤트 연동. 값이 없으면 인증을 활성화하지 않는다. 기본값으로 추측하지 않는다.
RS256 단일 허용목록을 최초 프로파일 후보로 제안한다. 확정 전 운영 설정은 만들지 않는다.

근거: [프로젝트 지침](../../AGENTS.md), [현재 인증](../../app/core/auth.py),
[기록 서비스](../../app/modules/neorang_narang/service.py),
[MySQL 저장소](../../app/modules/neorang_narang/mysql_store.py),
[현재 DB 계획](nn-mysql-persistence-plan.md), [기존 정책 초안](nn-auth-ownership-sync-policy.md).
기존 정책의 미승인 토큰 기간과 향후 API 제안은 이번 구조 승인으로 확정되지 않는다.

## 2. 소유 위치와 제품 경계

| 소유자 | 책임과 접근 계약 |
|---|---|
| Platform Core (`app/core`의 향후 공통 계정·인증 경계) | 공통 계정 UUID, 외부 identity 매핑, 앱 세션, 토큰 결합, 계정 상태, 동의·폐기 상태 |
| 관리형 IdP | 자격 증명, OIDC 인증, 제공자 토큰·SSO 세션, 제공자 계정 복구 |
| ChurchOS | 교회·조직·역할·통합 UX. 개인 기록 owner를 발급하거나 바꾸지 않음 |
| 너랑나랑 | 완료 메타데이터·revision·tombstone. 검증된 `AuthContext.sub`로 기록 제한 |
| 생명일기 등 다른 제품 | 각 제품 기록 원본. Core 내부 테이블을 직접 조회하지 않음 |

추천 저장 위치는 **별도 논리 DB `platform_core`와 전용 서비스 계정**이다.
초기 단일 FastAPI 배포를 유지해도 업무 DB `neorang_narang`·`life_diary`와 분리한다.
`nn_completion_owners`는 소유자 잠금 표이지 공통 사용자 명부가 아니다.
`nn_app`·`life_diary_app`에 Core DB 권한을 부여하지 않는다. Core repository만 Core
자격으로 접근하고 제품에는 불변 인증 context/권한 결정 계약을 제공한다.
제품 DB와 Core DB 사이에 교차 DB FK·JOIN·cascade를 추가하지 않는다.

현재 로컬 MySQL 승인은 두 제품 DB에 한정되어 Core DB 생성 승인이 아니다.
공통 스킬의 일반 PostgreSQL 원칙과 현재 프로젝트의 승인된 로컬 MySQL 구성은 별개다.
Core의 엔진은 추가 결정 대상이다. 대안은 같은 MySQL 인스턴스의 별도 DB(운영 단순),
별도 인스턴스/관리형 PostgreSQL(장애·권한 격리, 추가 운영 비용)이다.
논리 소유권은 엔진 선택과 무관하며 어느 쪽도 이번에 생성하지 않는다.

## 3. 제안하는 Core DB 변경 (DDL 미작성·미적용)

| 후보 테이블 | 최소 항목·제약 |
|---|---|
| `accounts` | `account_id` UUID PK, status, created_at, 보안 상태 버전. UUID 재사용·이메일 PK 금지 |
| `external_identities` | issuer, provider_subject, account_id FK, status, created_at. `(issuer, provider_subject)` 정확 비교 UNIQUE |
| `app_sessions` | session UUID PK, account_id FK, identity 참조, app/client 식별자, 상태, 생성·만료·폐기 시각, 버전, refresh 보관소 참조 |
| `session_access_tokens` | token fingerprint+key version UNIQUE, session FK, expires_at. 한 토큰을 다른 세션에 재결합 금지 |
| `login_transactions` | 일회용 state/nonce/PKCE 관련 보호값, client/redirect 결합, 만료·소비 상태 |
| `product_consents` | account/product/purpose/policy version, 상태·generation. 로그인이나 교회 소속은 동의가 아님 |
| `auth_outbox` | 제공자 refresh 폐기·보안 이벤트 작업, 멱등 키, 재시도 상태. 원문 토큰 대신 비밀 보관소 참조 |
| `core_schema_version` | Core만의 migration 버전. 너랑나랑 버전과 독립 |

issuer는 신뢰 설정에 있는 정확한 문자열로만 사용하고 요청 URL로 discovery하지 않는다.
subject는 대소문자·문자열을 보존하며 UUID로 강제 해석하지 않는다.
인덱스 길이·collation·시간 정밀도·암호화·백업·보유기간은 엔진 선정 후 확정한다.
비밀번호·이름·교회·기록 원문은 이 최소 계정/매핑 스키마에 넣지 않는다.
refresh token이 필요하면 비밀 보관소 또는 암호화 저장을 쓰고 암호키를 DB와 분리한다.
단순 hash만으로는 IdP에 refresh/revoke 요청을 보낼 수 없다.

최초 매핑은 검증 완료 후 단일 Core 트랜잭션에서 identity를 조회하고 없으면
계정과 identity를 함께 생성한다. UNIQUE 경합의 패배자는 전체 삽입을 rollback하고
이미 commit된 매핑을 다시 읽는다. 고아 계정·중복 UUID를 남기지 않는다.
실패 시 사용자에게 identity/SQL 원문을 반환하지 않는다. 이메일·이름·기기·교회로
기존 계정을 찾거나 합치지 않는다. 계정 연결/병합은 이 계약에서 제공하지 않는다.
동일 subject라도 issuer가 다르면 별개 identity다.

기존 업무 owner를 Core 계정으로 자동 등록하거나 실제 사용자에게 연결하지 않는다.
신규 로그인으로 발급된 UUID가 기존 owner와 다르면 기존 자료는 그대로 남는다.
기존 합성 fixture도 보존한다. 향후 귀속 이관은 별도 소유 증명·승인 범위다.

## 4. 로그인·토큰·앱 세션의 결합 초안

핵심: JWT 서명과 계정 UUID만으로는 **현재 앱 세션** 폐기를 표현할 수 없다.
OIDC `sid`는 IdP SSO 세션일 수 있으므로 Core 앱 세션과 동일시하지 않는다.
클라이언트가 보낸 session ID나 미검증 custom claim으로 결합하지 않는다.

제공자 독립 초기 후보는 **Core가 code 교환·refresh를 중개하고 토큰을 등록하는 방식**이다.

1. Core가 고정 허용 client/redirect, state, nonce, PKCE S256으로 로그인 거래를 만든다.
2. 시스템 브라우저로 IdP 인증. Core의 고정 callback이 code를 한 번만 교환하고
   ID token은 로그인 용도로 nonce/audience 등을 검증한다. 업무 API에는 받지 않는다.
3. API용 access JWT를 별도로 검증한다. ID/access identity 일치 확인 후 공통 UUID를
   원자적으로 매핑하고 새로운 앱 세션을 만든다. SSO 재로그인도 명시적 새 거래가 필요하다.
4. 검증된 access JWT 원문에 서버키 HMAC fingerprint를 만들고 그 세션에 한 번 결합한다.
   bearer 원문은 DB·로그에 남기지 않는다. fingerprint도 보호 대상이다.
5. 모바일은 일회용 인계 코드+앱의 PKCE/거래 결합으로 자격을 받는다. URL에 access/refresh를
   넣지 않는다. 갱신용 Core session credential은 별도 고엔트로피 비밀이며 서버는 hash만 저장한다.
   클라이언트가 제시하는 단순 session UUID는 자격이 아니다.
6. refresh는 같은 활성 Core 세션에서만 수행한다. IdP refresh 자격은 Core의 보호 저장소에서
   사용하고 클라이언트에 직접 배포하지 않는다. 회전/재사용 처리와 등록을 직렬화한다.
   새 토큰도 해당 세션에 결합한 뒤 반환한다. 로그아웃과 경합하면 반환·등록을 거부한다.
7. API는 매번 JWT 검증 후 fingerprint로 세션을 찾고 identity/account/client 일치,
   계정·세션 상태/만료·제품 scope·동의를 확인한 뒤 `AuthContext(sub=core UUID)`를 만든다.

이 방식은 업체 SDK의 직접 로그인·자동 refresh 예제를 그대로 사용하는 방식과 다르다.
모바일 인계/웹 BFF, 제공자 code 교환·refresh 지원 및 부하를 PoC로 검증해야 한다.
유효 JWT만 가져와 새 세션에 등록하는 공개 endpoint는 금지한다. 폐기 토큰 재등록도 금지한다.
Core를 거치지 않고 발급/갱신된 미등록 JWT는 서명이 맞아도 거부한다.
동일 토큰의 다중 세션 결합은 충돌로 거부한다. client 단위 세션/refresh grant 격리도 확인한다.

대안은 IdP가 서명한 Core 앱 세션 claim을 발급·갱신에도 안정적으로 유지하는 방식이다.
hook의 신뢰·회전·폐기 후 재발급 차단을 업체별로 입증해야 하며 현재 채택하지 않는다.
Core가 자체 access JWT를 추가 발급하는 token broker 대안도 있지만 별도 signing authority·
키 운영을 도입하므로 이번 초안의 기본안으로 선택하지 않는다.

## 5. access JWT 검증 계약

- 신뢰 설정으로 issuer, API audience, 앱 client, 알고리즘, JWKS origin과 프로파일을 고정한다.
  header의 `alg`나 `jku`/`x5u`가 신뢰 설정을 바꾸지 못한다. `none`, 대칭키 혼동,
  미지원 JWE/opaque token, ID token, M2M token은 개인 기록 API에서 거부한다.
- 서명과 정확한 issuer, audience(문자열 또는 배열에 API 대상 포함), 필수 exp/iat/sub,
  존재하는 nbf, 확정된 clock skew/최대 수명, 제품 scope를 검증한다. 빈 subject 거부.
  provider subject는 UUID일 필요가 없고 공통 UUID와 혼동하지 않는다.
- access token 구분은 업체 프로파일로 확정한다. 모든 제공자가 `typ=at+jwt`나
  `token_use`를 발급한다고 가정하지 않는다. Auth0는 custom API audience/허용 client,
  Cognito는 resource-bound audience + `token_use=access` + 허용 client를 확인해야 한다.
- 키 회전 시 신뢰 JWKS에서만 제한적으로 갱신한다. unknown kid는 갱신 후에도 없으면 401.
  네트워크 실패 시 유효한 캐시 정책이 충족되지 않으면 503이며 미검증 통과는 없다.
- 검증 완료 전 claims로 계정·업무 DB를 조회하거나 owner를 생성하지 않는다.
  키·세션 확인에 실패하면 메모리 저장소/가짜 사용자로 대체하지 않는다.
- Core 세션 검사는 권위 저장소를 사용한다. 초기안은 positive cache 없음으로 제안한다.
  향후 cache 도입은 폐기 일관성/장애 시 거부를 별도 입증한다.

## 6. 외부 API 후보 (미구현)

| 후보 경로 | 요청·결과와 안전 조건 |
|---|---|
| `POST /api/v1/auth/login-transactions` | 허용된 app/redirect와 인계 challenge만. authorize URL/거래 결과, owner 입력 없음 |
| `GET /api/v1/auth/callback` | state/code 검증·소비 후 일회용 앱 인계 또는 웹 세션 설정. 민감 query를 access log에서 제외 |
| `POST /api/v1/auth/session-exchange` | 일회용 인계 코드와 verifier. no-store, 모바일에 access JWT와 보호된 갱신 자격 |
| `POST /api/v1/auth/refresh` | 해당 세션의 보호 자격/웹 cookie+CSRF. 서버 세션 확인 후 갱신, 재사용은 거부 |
| `GET /api/v1/me` | Core UUID와 최소 승인 정보. provider subject/토큰/기록은 반환하지 않음 |
| `POST /api/v1/auth/logout` | 현재 자격으로 현재 앱 세션만 멱등 폐기. 폐기 후 같은 logout만 재시도 허용; 업무 API는 불가 |
| `POST /api/v1/auth/logout-all` | 별도 사용자 동작·최근 재인증. 계정의 Core 세션 전체 폐기 |
| `POST /api/v1/auth/idp-logout` | 별도 사용자 동작. IdP SSO 종료 redirect를 허용목록으로 제한 |

오류 후보: 자격 누락/위조/만료·폐기·미등록 401 + Bearer challenge, 인증 후 scope/동의
부족 403, 타인/없음/삭제 기록은 현재와 동일한 404, 안전한 요청 오류 422,
제한 429, 필수 JWKS/Core 장애 503. 기존 API 오류 envelope는 임의 변경하지 않는다.
5xx/429만 제한적 backoff, refresh는 세션별 single-flight. 실패한 회전 응답에 구 refresh를
맹목 재사용하지 않는다. 상태가 불명확하면 재로그인하며 로컬 기록은 유지한다.

현재 공개 `/`, `/health`, 모듈 health, `/docs`, `/redoc`, `/openapi.json`은 보존한다.
기록 Metadata와 revision 계약에 owner/client/session 필드를 추가하지 않는다.
Authorization·Cookie·code·verifier·토큰·원문 body·외부 subject·사용자 기록·예외 원문은
응답·일반 로그·추적에 반사하지 않는다. 고정 오류와 안전한 상관 ID만 사용한다.
callback query와 credential 처리 경로는 프록시/APM까지 별도 로그 차단 검증을 거친다.

## 7. 로그아웃과 실패·경합 의미

현재 앱 로그아웃은 Core 세션을 원자적으로 폐기하고 commit 후 성공한다.
그 시점 이후 시작되는 모든 API 인증 판단은 그 세션의 구/신규 JWT를 거부한다.
계정의 다른 앱/기기 세션은 유지한다. 먼저 인증을 통과해 진행 중인 요청은 완료될 수 있다.
이미 commit된 기록을 취소한다고 보장하지 않는다. 진행 중 쓰기까지 취소해야 한다면
제품 DB와 Core 사이의 추가 직렬화 계약이 필요하며 별도 결정한다.

Core 폐기와 제공자 refresh 폐기 작업을 outbox로 함께 기록한다. IdP 장애여도 Core 폐기가
commit되면 해당 앱의 API 차단은 즉시 유효하다. IdP 작업은 재시도하고 완료 상태를 구분한다.
Core commit 실패는 503이며 서버 로그아웃 성공이라고 표시하지 않는다. 클라이언트는
로컬 토큰 제거·전송 정지는 수행하되 서버 폐기 미확인 상태를 알리고 안전하게 재시도한다.
IdP의 grant 전체 폐기가 다른 기기에 영향을 주는지 PoC로 확인한다. 현재 앱 logout을
구현하려고 user-global revoke 또는 IdP SSO 종료를 자동 호출하지 않는다.

전체 기기 logout은 Core 계정 상태 버전과 세션 전체 폐기를 원자적으로 처리한다.
IdP SSO 종료는 외부 cookie/session 종료이며 그 자체로 Core 전체 세션 폐기를 뜻하지 않는다.
복구·계정 정지·침해 이벤트는 검증된 서버 연동으로 Core에도 반영해야 한다. webhook의
지원 플랜·서명·지연·재생 방지는 아직 미확인이다. 이 연동 전 즉시 반영을 주장하지 않는다.

Flutter는 logout/계정 전환 시 업로드·refresh 중지, 계정별 큐·캐시·매핑·revision 격리,
로컬 session generation 변경으로 늦은 A 응답 폐기를 수행해야 한다. B로 A의 큐를 재생하지
않는다. A의 로컬 원문을 자동 삭제하지 않고 잠근다. 기존 무로그인 로컬 사용은 유지한다.
모바일 갱신 자격은 Keychain/Keystore 기반 보관, access JWT는 메모리 중심이다.
웹은 same-origin BFF+HttpOnly/Secure/SameSite cookie와 CSRF/Origin 검사를 우선 제안한다.
웹 BFF가 API 호출에 JWT를 붙이며 브라우저 영속 저장소에 refresh를 두지 않는다.
플랫폼별 실제 구현·계정 전환 UX는 Flutter 변경 승인 후 검증한다.

## 8. 적용·롤백·테스트 준비

업체/프로파일·Core DB 설계 확정 → 별도 Core migration 작성·검토 → 합성 환경에서
신규 설치·기존 Core 버전 업그레이드·부분 실패·동시 매핑·백업 복원 → 인증 어댑터 구현 →
별도 제공자 sandbox PoC → Flutter 연결 순서다. 코드가 준비되어도 자동 DDL은 하지 않는다.
너랑나랑/생명일기 DB 계정 교차 접근 금지와 기존 owner/revision/tombstone 보존을 검증한다.
rollback은 신규 로그인/갱신 차단과 fail-closed 복귀, Core DB·업무 DB 보존이다.
DROP·자료 재귀속·down migration으로 복구를 대신하지 않는다. 복원 후 폐기 세션이
살아나지 않게 폐기 원장/세션 버전 처리 계획을 먼저 승인한다.

이번 준비물: [합성 JWT fixture](../../tests/auth_contract_fixtures.py),
[미설정 인증 경계 테스트](../../tests/test_auth_contract_preparation.py),
[제공자 비교](managed-oidc-provider-comparison.md).
fixture의 issuer/audience/RS256은 테스트 전용이며 운영 선택이 아니다.
현재 전부 401인 검사는 JWT validator 성공을 의미하지 않는다.

| 향후 합성 인수 테스트 | 이번 상태 |
|---|---|
| A/B의 올바른 access JWT + 활성 세션 허용 | NOT_RUN: 실제 validator·Core 저장소 미구현 |
| 변조/알고리즘 혼동/issuer/audience/종류/시간/subject/kid 거부 | JWT 입력 fixture 준비. 실제 validator 판정 NOT_RUN |
| 동시 최초 로그인 1 UUID, 다른 issuer의 동일 sub 격리, 이메일 자동 병합 없음 | NOT_RUN: Core DB 미적용 |
| A1 logout 후 A1 구/갱신 토큰 차단, A2·B1 유지 | NOT_RUN: 세션 저장소 미구현 |
| 폐기 JWT 재등록·세션 header 교체·refresh 경합·Core/IdP 장애 | 우회 거부 회귀만 실행 가능. 실제 세션 경합 NOT_RUN |
| A/B 목록·조회·수정·삭제·재시도 격리 | 기존 메모리 합성 회귀 재사용. 실제 JWT→MySQL 연결 NOT_RUN |
| Flutter A→B 늦은 응답·큐 격리, 오프라인 logout | NOT_RUN: Flutter 변경 없음 |
| 로그/프록시/APM에 credential·원문 부재, 키 교체·복구 이벤트 | 애플리케이션 합성 응답 검사만 가능. 운영 연동 NOT_RUN |

미확정 업체·DB 적용은 이번 사용자 지시에 따라 보류한다. 승인된 구조를 다시 승인받는
절차는 추가하지 않는다. 다음 결정은 업체/플랜/region, 정확한 토큰 프로파일,
Core DB 엔진·스키마와 broker/플랫폼 인계 방식의 구체화다.
