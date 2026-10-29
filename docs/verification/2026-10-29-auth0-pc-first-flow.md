# PC 단일 Auth0 흐름 준비 결과

2026-10-29. `feature/nn-completion-contract`. 실제 연결 성공 보고가 아닌 설정/적용 전 점검이다.

## 추가 파일

- `docs/architecture/auth0-pc-first-flow.md`: 사용자 클릭 순서, Application/API 각 하나,
  고정 callback·환경변수, Flutter 복귀 제외, Core migration 승인안·실제 검증 순서.
- `migrations/platform_core/001_pc_auth.sql`: 별도 Core DB의 7개 표에 대한 미적용 SQL 초안.
- `scripts/auth0_pc_settings.py`: 값 비출력·비덮어쓰기·접근 제한 로컬 설정 준비/형식 검사.
- `tests/test_auth0_pc_settings.py`: 설정 누락·제품 DB/MariaDB/잘못된 callback·키 오류 보호.
- 이 기록. Git 제외 `.env.auth0-pc`도 새로 준비했으며 실제 issuer/client/secret/DB 비밀번호는 비어 있다.

기존 코드·문서·MySQL `.env`·AGENTS·의존성·제품 migration은 수정하지 않았다.
실행 앱과 get_current_user는 기존 401 경계를 유지한다. DB 생성·DDL 적용·broker 활성화 없음.

## 실제 실행한 합성/회귀 검사

모든 Python은 기존 `.venv\Scripts\python.exe -B`로 실행했다.

| 상태 | 명령 | 결과 |
|---|---|---|
| PASS | `python -B -m scripts.auth0_pc_settings prepare` | 접근 제한 설정 파일 생성, 값 비출력 |
| PASS | `git check-ignore .env.auth0-pc` | Git 제외 확인 |
| PASS | `python -B -m unittest tests.test_auth0_pc_settings -v` | 신규 4개 성공 |
| PASS | `python -B -m scripts.verify_mysql tests` | 전체 66개, 실패/오류/skip 0. 기존 MySQL 통합 9개 포함 |
| PASS | `python -B -m pip check` | 의존성 불일치 없음 |
| PASS | Python AST·신규 문서 상대 링크·신규 파일 공백 검사, `git diff --check` | 종료 0 |
| NOT_RUN | `python -B -m scripts.auth0_pc_settings check`의 연결 검증 | 이 도구는 연결 검사 기능이 없음 |

설정 형식 `check` 자체는 실행했고 예상대로 **NOT_READY / 종료 1**이었다.
실제 tenant·Application 정보와 Core DB 비밀번호가 아직 입력되지 않았기 때문이며
합성 테스트 실패나 Auth0 접속 실패를 의미하지 않는다. 실제 파일 값은 출력하지 않았다.

## 실제 Auth0 연결/새 Core DB 검사

아래는 2026-10-29 준비 시점의 결과다. 2026-10-30 후속 사용자 전달 결과에서는
실제 A 재로그인 UUID 유지·별도 B 구분·업무 기록 양방향 격리가 PASS다.
[최종 인수 기록](2026-10-30-auth0-ab-acceptance.md)에 A/B 각 19개 PASS를 기록했다.
개별 claim 직접 확인·동시 매핑·구 token 차단·실제 서버 재시작을 이번 사용자 결과로
새롭게 PASS 처리하지 않는다. 당시 검사 결과와 최신 인수 범위를 구분한다.

| 항목 | 상태/이유 |
|---|---|
| 사용자 계정 Free/region 드롭다운 실제 선택지 | NOT_RUN: 사용자 계정 UI 미접속. 공식 공개 자료만 재확인 |
| Auth0 로그인·PKCE/state/nonce·실제 token profile/claims | NOT_RUN: 설정 미입력, callback/broker 미구현 |
| 영속 Core UUID 유지·동시 매핑 | NOT_RUN: 새 Core DDL 적용 전 승인 필요 |
| 실제 JWT→업무 기록 A/B 격리 | NOT_RUN: 실 인증 연결 전. 기존 합성 메모리/MySQL 회귀는 PASS |
| 실제 logout 후 구 token 차단·서버 재시작 세션 보존 | NOT_RUN: 영속 Core repository·HTTP broker 구현 전 |
| migration SQL 새 설치·부분 DDL 재개·backup/restore | NOT_RUN: 검토 초안만 준비, DB 적용 승인 전 |

AUTHOR_REVIEW_REQUIRED: 로컬 MySQL `127.0.0.1:3307`에 별도 `platform_core` DB,
`platform_core_app` 계정과 Core SELECT/INSERT/UPDATE 권한, SQL 초안의 7개 표 적용.
실행 runner의 schema/version/lock/중간 실패 검증과 별도 합성 복원 증거도 필요하다.
기존 제품 DB·owner·행·MariaDB:3306은 변경하지 않는다. 승인 전 실행하지 않았다.

기존 MySQL 검사는 새로운 합성 UUID만 추가/수정/soft-delete하며 자료를 보존한다.
실제 사용자 자료 조회·이전·삭제·owner 자동 매핑, 컨테이너 재시작, 유료 가입,
운영 배포·git add/commit/push는 하지 않았다.
