# Callback 401 진단 (2026-10-29)

대상은 `app.auth0_pc:app`이다. 기존 미커밋 작업을 보존했다.
실제 토큰/인가 코드 재생, 설정 변경, DB 쓰기·migration, commit·push는 수행하지 않았다.

## 확인된 사실과 한계

- 로컬 설정 형식 검사와 의존성 일관성 검사는 PASS다. 실제 Auth0 설정과 일치함을 뜻하지 않는다.
- Core DB의 상태별 건수만 조회했다. `exchanging` 거래가 있어 state/browser 결합을
  통과한 거래가 있었음은 확인했다. 해당 거래를 사용자의 실패 시도와 확정적으로 연결할 수는 없다.
- 기존 코드는 모든 인증 거부를 같은 401로 반환하므로 기존 응답만으로 실패 단계를
  복원할 수 없다. 실제 실패 원인은 새 로그인 진단 전까지 미확정이다.
- 합성 테스트는 정상 로그인, state/browser 거부, token endpoint 거부, 프로파일 불일치,
  nonce 불일치, 세션 저장 실패를 구분한다. 실제 Auth0 성공의 증거가 아니다.

## 재현

기존 서버를 사용자가 재시작한다. 이미 사용 중인 서버를 자동 종료하지 않는다.

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn app.auth0_pc:app --host 127.0.0.1 --port 8000 --no-access-log
```

`http://127.0.0.1:8000/auth/poc/login`에서 새 로그인을 시작한다.
이전 callback을 새로고침/재사용하지 않는다. 거래는 단일 소비이며 실패 후 자동 재교환하지 않는다.
진단은 `auth_callback stage=고정단계 result=PASS/FAIL`만 남긴다.
예외 본문, JWT/claim 값, 사용자 ID, code, state, cookie, secret은 기록하지 않는다.
Uvicorn 기본 access logger에도 callback 쿼리 전체를 제거하는 필터를 설치했다.
외부 프록시/별도 수집기의 로그 설정은 이번 로컬 앱 필터의 적용 대상이 아니다.

| 단계 | 확인 내용 / 실패 시 비교할 계약 |
|---|---|
| callback_input | code/state 존재·중복·길이·provider error 여부 |
| state_browser_pkce | 5분 거래, browser 결합, 단일 claim, 저장 verifier 복호화, client/callback 일치 |
| token_exchange_pkce | 서버 code 교환; PKCE S256, client secret post, 고정 callback |
| token_response | Bearer access/ID token 응답, refresh 부재 |
| jwks_fetch | 고정 issuer의 JWKS 요청 |
| access_profile | RS256, RFC9068 `at+jwt`, 금지 header 부재 |
| access_signature | 신뢰하는 JWKS key의 RSA 서명 |
| access_claims | 정확한 issuer/API audience/client_id, sub/jti 및 사용자 grant |
| access_time | exp/iat/nbf, 최대 600초 수명, 기존 clock skew |
| id_signature | ID token RS256 서명 |
| nonce | 로그인 거래에 저장된 nonce hash와 일치 |
| id_jwt_nonce | ID token 전체 검증: issuer/sub/client aud/azp/시간/nonce/at_hash |
| core_session | 검증 token과 로그인 거래 결합, 활성 계정, 영속 세션 트랜잭션 |

상위 `provider`/`access_jwt` 실패도 함께 기록된다. 가장 구체적인 하위 FAIL을 먼저 확인한다.
Access profile PASS는 header 형식 통과를 뜻하며 서명 검증 완료를 뜻하지 않는다.

## Auth0 설정 비교

코드 계약: Regular Web Application, Authorization Code, Client Secret Post,
PKCE S256, ID/access RS256, API RFC9068, token expiration 및 browser flow 600초,
API audience와 callback은 `scripts/auth0_pc_settings.py`의 고정값이다.
실제 Dashboard 설정은 아직 직접 확인하지 못했다. 기본 프로파일로의 자동 fallback은 없다.
기본 Auth0 프로파일의 `azp`를 RFC9068 `client_id` 대신 허용하지 않는다.
서명·issuer·audience·만료·nonce 검증은 유지했다.

근거: [Auth0 프로파일 설명](https://auth0.com/blog/jwt-access-tokens-profiles-now-in-ga/),
[Auth0 client_id/azp 비교](https://support.auth0.com/center/s/article/receive-the-client-id-claim-instead-of-the-azp-claim-in-an-auth0-access-token).

2026-10-30 후속 결과: 실제 A 재로그인과 A/B PC 인수는 **PASS (사용자 전달)**다.
중지된 MySQL 서비스 시작, API scope 등록, User-Delegated Access의 두 권한 명시 허용
(2/2 저장) 후 통과했다고 전달받았다. Always grant all permissions는 사용하지 않았다.
이 조치를 과거 callback 401의 단일 원인으로 확정하지 않는다.
상세는 [최종 인수 기록](2026-10-30-auth0-ab-acceptance.md)을 따른다.
인증 계약 자체를 변경할 필요가 확인되면 **AUTHOR_REVIEW_REQUIRED**로 별도 검토한다.

## 실행한 검증

- **PASS** `.venv/Scripts/python.exe -B -m unittest discover -s tests -q`:
  92개 중 71개 통과, opt-in DB 통합 21개 skip. 기존 공개 경로 회귀 포함.
- **PASS** `.venv/Scripts/python.exe -B -m pip check`: 의존성 충돌 없음.
- **PASS** `git diff --check` 및 app/tests `ast.parse` 문법 검사.
- **PASS (사용자 전달, 2026-10-30)** 실제 Auth0 재로그인과 A/B PC 인수.
- **NOT_RUN (이 진단 작업)** 에이전트의 실제 Dashboard 설정 직접 확인, DB 통합 테스트.

이번 변경: `app/auth0_pc.py`, `app/core/auth0_provider.py`, `app/core/auth0_poc.py`,
신규 `app/core/auth_diagnostics.py`, `tests/test_auth0_diagnostics.py`, 이 문서.
인증 보호 조건과 DB schema는 변경하지 않았다. 진단 코드를 되돌리면 기존 동작으로 복귀하며
DB 자료나 암호키 복구는 필요 없다. 실제 401 해결 완료로 보고하지 않는다.
