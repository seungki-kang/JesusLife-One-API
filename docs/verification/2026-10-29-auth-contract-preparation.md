# 인증 계약·제공자 독립 테스트 준비 결과

기준일: 2026-10-29. 브랜치: `feature/nn-completion-contract`.
사용자 승인 구조를 설계 기준으로 반영했으며 업체 선택·Core DB 적용은 수행하지 않았다.

## 추가 파일

- `docs/architecture/platform-auth-contract-draft.md`: 승인/미확정 구분, Core 소유권,
  별도 DB 후보·스키마·원자적 identity 매핑, 토큰/세션 결합, logout·오류·복구 계약.
- `docs/architecture/managed-oidc-provider-comparison.md`: 공식 자료에 의한 Auth0/Cognito
  비교·비용·제한·미확인 사항, Auth0 우선 PoC 추천. 업체 선정 아님.
- `tests/auth_contract_fixtures.py`: 실행 중에만 생성되는 RSA 키와 합성 JWT 18개.
  테스트 전용 issuer/audience·A/B identity. 운영 검증기/신뢰 설정으로 사용하지 않음.
- `tests/test_auth_contract_preparation.py`: 새 테스트 4개. 실제 인증 dependency를
  override하지 않고 JWT·계정·세션 입력이 현재의 인증 401을 우회하지 못함을 검증.
- 이 검증 기록.

기존 파일은 편집하지 않았다. 시작 시 존재한 미커밋 변경과 미추적 MySQL 구현을 보존했다.
app·requirements·compose·환경 파일·migration·Flutter 변경 없음.

## 실행과 결과

실행 Python은 기존 `.venv\Scripts\python.exe`, 모든 Python 검사에 `-B` 사용.

| 상태 | 명령·범위 | 결과 |
|---|---|---|
| PASS | `python -B -c "import os,unittest; os.environ['RUN_MYSQL_TESTS']='0'; suite=unittest.defaultTestLoader.discover('tests'); result=unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())"` | 48개 중 39개 성공, MySQL 통합 9개 skip, 종료 0 |
| PASS | `python -B -m pip check` | 의존성 충돌 없음, 종료 0 |
| PASS | app/tests의 `ast.parse` 및 신규 문서의 상대 파일 링크 검사 | 종료 0 |
| PASS | `git diff --check`, 새 파일 공백 검사 | 종료 0 |

전체 테스트는 공개 경로·OpenAPI·기존 소유권/완료 API 메모리 회귀를 포함한다.
새 테스트는 18개 JWT 입력 × 기록 API 5개 동작의 401, DB 연결 미호출,
위조 owner/session 입력 거부, 미구현 auth 경로 404, 합성 서명 fixture를 검사한다.
이것은 실제 JWT validator·세션 상태 검증의 성공 증거가 아니다.

NOT_RUN: 실제 JWT 허용/거부 판정, Core 원자적 매핑·세션 폐기·동시 refresh,
제공자 sandbox·복구 이벤트·SSO, MySQL 통합·migration·백업 복원,
Flutter 빌드·계정 전환, 운영 로그/APM. 업체/DB 미선정 또는 이번 범위 밖이다.
formatter·linter·type checker는 프로젝트 설정이 없어 추가 설치하지 않았다.

AUTHOR_REVIEW_REQUIRED: 업체/플랜/region·정확한 토큰 프로파일, Core DB 엔진·스키마
적용, Core broker·모바일 인계/웹 BFF 세부안. 이미 승인된 구조의 재승인은 요구하지 않는다.

비밀값 출력·패키지 설치·IdP 연결·MySQL 접속·사용자 자료 조회/변경·owner 재귀속·
기록 이전/삭제·서비스 시작/정지·배포·git add/commit/push는 하지 않았다.
되돌리기는 이번 신규 문서·테스트 파일만 대상으로 검토하면 되며 DB rollback은 필요 없다.
