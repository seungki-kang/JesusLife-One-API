# Auth0 개발 PoC 오프라인 준비·MySQL 재검증

2026-10-29, `feature/nn-completion-contract`. 사용자 승인 범위는 Auth0 최종 채택 전
개발 PoC 준비와 기존 MySQL 통합 재검증이다. 유료/운영 적용은 제외한다.

## 이번 추가 파일

- `docs/architecture/auth0-development-poc.md`: Core/Flutter의 두 PKCE 역할과 보관 위치,
  세션 결합·재등록 금지·경합·로그아웃 계약, 별도 Core DB 소유권, Auth0 Free/JP 추천,
  tenant/app/API 설정·고정 audience·개발 callback·사용자 설정 순서·미확정 값.
- `app/core/auth0_poc.py`: HTTP 경로에 연결하지 않은 S256, 명시적 신뢰키 기반
  RS256/RFC9068 verifier, 세션 결합 후보 검사, 권위 registry 기반 gate.
- `tests/test_auth0_poc.py`: 14개 오프라인 테스트와 테스트 전용 원자적 세션 reference model.
- 이 검증 기록.

실행 앱의 `get_current_user`는 계속 401이다. fake user·특수 헤더·환경 인증 우회를
추가하지 않았다. 실제 JWT→HTTP 인증 활성화·Auth0 code/ID token 교환·JWKS 취득·
Core DB·세션 자격/refresh 보관·Flutter는 미구현이다. 새 parser는 제한된 PoC로만
사용하며 운영 JWT 라이브러리/보안 검토를 대신하지 않는다.

## 실행 결과

모든 Python 명령은 기존 `.venv\Scripts\python.exe -B`를 사용했다.

| 상태 | 명령/범위 | 결과 |
|---|---|---|
| PASS | `docker version --format '{{.Server.Version}}'` | Docker Engine 29.9.2 확인. 최초 sandbox 접근 거부 후 승인된 실행으로 확인 |
| PASS | `python -B -m scripts.verify_mysql tests` (변경 전) | 48개, 실패/오류/skip 0. 기존 MySQL 9개 포함 |
| PASS | `python -B -m unittest tests.test_auth0_poc -v` (초기 11개 버전) | 11개 성공. 이후 추가 검사는 전체 suite에서 확인 |
| PASS | `python -B -m scripts.verify_mysql tests` (최종) | 62개, 실패/오류/skip 0. 신규 14개·기존 MySQL 통합 9개 포함 |
| PASS | `python -B -m pip check` | 의존성 불일치 없음 |
| PASS | app/tests Python AST·신규 문서 상대 링크·신규 파일 공백 검사 | 종료 0 |
| PASS | `git diff --check`, 시작 시 소스 fingerprint 대조 | 종료 0, 기존 파일 내용 변경 없음 |

신규 테스트: PKCE 공식 벡터·잘못된 verifier, 실제 RSA 서명과 필수 claims/algorithm/
audience/client/시간·key URL 주입 거부, 서명된 미등록 token 거부, A/B Core UUID 전달과
실제 메모리 완료 서비스의 본인 기록 격리, 현재 앱 logout의 old/refreshed token 차단과
A2/B1 유지, 같은 계정 재로그인 시 구 token 재결합 금지, proof 재생 거부, logout 중
refresh 응답 지연, 동시 CAS 1건만 성공, logout 후 병렬 API 판단 거부, scope/동의/
계정/세션 만료·registry 장애 처리. 합성 key/token은 실행 중에만 생성하고 출력하지 않았다.

reference registry의 lock/CAS는 인수 조건을 실행하는 **테스트 모델**이다. 영속 DB의
원자성·다중 worker·실제 Auth0 refresh 병렬 호출 차단을 증명한 것은 아니다.

MySQL 검증기는 새 UUID의 합성 fixture만 추가/수정/soft-delete하며 보존한다.
기존 사용자의 owner·행을 이전/재귀속/물리 삭제하지 않는다. DB 초기화/migration,
컨테이너 재시작, MariaDB:3306 변경, Core DB 생성은 하지 않았다.

## 미확인과 다음 단계

- NOT_RUN: 실제 Auth0 tenant 로그인/code 교환·nonce/ID token·인계 단일 소비,
  JWKS 회전/장애·네트워크, refresh family revoke·SSO·계정 복구, Android/iOS/웹 실행.
- NOT_RUN: 영속 Core schema·원자적 identity 매핑·lease/CAS·암호화/보관소·outbox,
  다중 worker/재시작/백업 복원·폐기 보존, 운영 proxy/APM 전체 로그 보호.
- 미확정: 실제 tenant Domain/issuer/client IDs, Free 화면의 JP·프로파일 설정 가용성,
  실기기용 HTTPS origin·callback과 앱별 검증 가능한 return link.
- AUTHOR_REVIEW_REQUIRED: Core DB 엔진/DDL 적용, 실제 broker/영속 registry 구현과
  상호운용 검증 후 인증 연결. 승인된 개발 PoC 구조를 다시 승인받는 절차는 추가하지 않는다.

기존 미커밋 코드·문서·환경 파일과 사용자 기록을 보존했다. 새 패키지 설치,
Auth0 계정 생성/외부 설정, 유료 가입, 기록 이전/삭제, 운영 배포, commit/push는 하지 않았다.
