# 관리형 OIDC 제공자 비교

확인일: 2026-10-29. 공식 공개 자료만 사용. 업체 선택·계정 생성·외부 인증 연결은 하지 않았다.
가격은 USD 공개 표시 기준이며 세금·환율·계약 할인·향후 변경을 포함하지 않는다.
예상 MAU·MFA·메시지 수·기업 federation 수가 없어 확정 견적은 아니다.

## 후보 비교

| 항목 | Auth0 | Amazon Cognito User Pools |
|---|---|---|
| Flutter Android/iOS/웹 | 공식 Flutter SDK와 모바일·웹 quickstart [A1][A2]. callback·플랫폼별 앱 등록 필요 | Amplify Flutter가 Android/iOS와 웹 설정 제공 [C1][C2]. Cognito 기존 자원 연결 가능 |
| API access JWT | custom API 등록, API audience로 JWT 수신. RS256 및 허용 client 검증 [A3] | RS256, `token_use=access`, client_id·scope. **aud는 resource binding 요청 시 존재**하므로 일반 로그인 token을 그대로 받으면 이 계약에 부족 [C3][C4] |
| SSO | 같은 tenant의 Universal Login/browser session 공유. 앱·IdP·외부 소셜 세션은 구분 [A4] | managed login의 브라우저 cookie 재사용과 외부 SAML/OIDC federation [C5]. 브라우저 cookie는 1시간이며 기기 간 cookie 공유를 뜻하지 않음 |
| 현재 앱 logout | 로컬/Core 세션 폐기와 refresh 폐기 범위를 분리. JWT 서명 검증만으로 기존 token 차단 불가 [A5][A6] | 해당 refresh token 계열 revoke와 GlobalSignOut 별도. 일반 JWT 검증기는 폐기를 알지 못하므로 Core 검사 필요 [C6] |
| IdP SSO 종료 | OIDC RP-Initiated Logout 지원 [A7]. 기본 앱 logout에는 자동 호출하지 않음 | managed login 종료와 token revoke를 분리 [C6][C7]. `/logout`은 외부 OIDC/소셜 IdP 세션을 종료하지 않음 |
| 계정 복구 | DB connection 비밀번호 재설정; 소셜/기업 계정은 원래 IdP에서 복구 [A8] | 검증 email/phone으로 ForgotPassword. MFA와 같은 수단 사용 제한, 복구 설정·메시지 전송 준비 필요 [C8] |
| 공개 비용 | Free 최대 25,000 MAU, 표시된 B2C 500 MAU 기준 Essentials $35/월·Professional $240/월. 유료 플랜은 해당 MAU 견적과 기능 포함 여부 재확인 [A9] | Essentials 직접/소셜 로그인 10,000 MAU 무료 후 공개 예시 $0.015/MAU. SAML/OIDC federation은 50 MAU 무료 후 $0.015/MAU. SMS/SES 등 별도 [C9] |
| 운영 부담 (평가) | 로그인 UI·API 등록 중심. Core broker·세션 DB·비밀·감사 운영은 여전히 필요. 플랜별 API 제한·기능 비용 검토 | AWS 계정/IAM·pool/client/resource server·SES/SMS·필요한 Lambda 운영. AWS 숙련도가 있으면 비용·운영 통합에 유리 |

## 추천

**Auth0를 우선 PoC 후보로 추천한다. 업체 선택은 아직 하지 않는다.**
이 프로젝트의 custom API audience, Flutter 3개 플랫폼, 다중 앱 SSO에 직접 대응하는
공식 안내가 있고 별도 AWS 운영 전제가 확인되지 않아 초기 구성 부담이 낮을 것으로 평가한다.
이는 공식 자료를 바탕으로 한 설계 판단이며 실제 연동 성공이나 최저 비용을 뜻하지 않는다.
Cognito는 AWS 기반 운영이 확정되거나 MAU 증가에 따른 종량 비용을 중시할 때 대안이다.
resource-bound access token을 broker 흐름에서 안정적으로 발급/갱신하는지 선행 검증한다.

두 후보 모두 [Core 인증 계약](platform-auth-contract-draft.md)의 현재 앱 세션 폐기를
대신해 주지는 않는다. 단순 SDK `logout`·JWT 서명 검사만으로 요구사항을 충족했다고 보지 않는다.
SDK 직접 token 관리 예제와 Core 중개 모델의 차이를 PoC에 포함한다.

## 미확인·선정 전 확인

- 실제 tenant/region·데이터 저장 위치·국외 이전/처리 계약·조직의 규정 적합성.
- 실제 Flutter 버전·Android/iOS 최소 버전과 최신 안정 SDK 호환성, 웹 Safari/cookie 정책,
  앱 간 시스템 브라우저 SSO 및 Core callback/일회용 인계 동작. SDK·디바이스 실행은 하지 않았다.
- 정확한 issuer/audience/client/JWKS, 토큰 기간·scope·프로파일. Auth0/Cognito의 실제
  토큰 표본을 수집하지 않았으며 provider subject를 Core UUID로 직접 쓰지 않는다.
- 앱 세션별 refresh family 분리, Auth0 revoke가 tenant 설정에 따라 grant 전체에 미치는
  영향, SDK 자동 refresh 우회 차단. Auth0의 세부 세션/refresh 관리 API는 플랜 제한 확인 필요 [A6].
- 복구·계정 정지·침해 이벤트를 Core로 전달하는 수단, 서명·지연·재생 방지·API rate limit.
  어느 후보도 Core 상태의 즉시 갱신을 이번 조사로 입증하지 않았다.
- 분실 MFA/복구 수단 부재에 대한 지원 절차, 이메일 전달률·SMTP/SES 운영 및 보안 비용.
- 같은 규모·기능의 총비용. Auth0 가격의 무료/유료 MAU 한도를 같은 조건으로 보지 않으며
  Cognito도 메시지·Lambda·DB·모니터링을 포함해야 한다. 규모 입력 후 재산정한다.

## 공식 근거

- [A1 Auth0 Flutter 모바일](https://auth0.com/docs/quickstart/native/flutter)
- [A2 Auth0 Flutter 웹](https://auth0.com/docs/quickstart/spa/flutter)
- [A3 Auth0 access token](https://auth0.com/docs/secure/tokens/access-tokens)
- [A4 Auth0 SSO](https://auth0.com/docs/authenticate/single-sign-on)
- [A5 Auth0 logout 후 access token 한계](https://support.auth0.com/center/s/article/Invalidate-the-API-token-after-user-logout)
- [A6 Auth0 refresh 폐기와 grant 설정](https://auth0.com/docs/secure/tokens/refresh-tokens/revoke-refresh-tokens)
- [A7 Auth0 OIDC logout](https://auth0.com/docs/authenticate/login/logout/log-users-out-of-auth0)
- [A8 Auth0 비밀번호 복구 공식 문서 원본](https://github.com/auth0/docs/blob/master/articles/connections/database/password-change.md)
- [A9 Auth0 가격](https://auth0.com/pricing)
- [C1 Amplify Flutter 플랫폼 설정](https://docs.amplify.aws/flutter/start/platform-setup/)
- [C2 Amplify Flutter 웹 quickstart](https://docs.amplify.aws/flutter/start/quickstart/)
- [C3 Cognito access token](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html)
- [C4 Cognito resource binding](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html)
- [C5 Cognito managed login](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-managed-login.html)
- [C6 Cognito token 폐기의 범위와 JWT 검증 한계](https://docs.aws.amazon.com/cognito/latest/developerguide/token-revocation.html)
- [C7 Cognito logout endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/logout-endpoint.html)
- [C8 Cognito 계정 복구](https://docs.aws.amazon.com/cognito/latest/developerguide/managing-users-passwords.html)
- [C9 Cognito 가격](https://aws.amazon.com/cognito/pricing/)
