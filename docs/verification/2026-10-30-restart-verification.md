# API 재시작 세션 복원 및 MySQL 체크포인트 검증 기록

2026-10-30. 브랜치 `feature/nn-completion-contract`.

## 범위와 증거

실행 주체는 사용자다. 사용자가 직접 실행하고 이 대화에 전달한 결과를 기록한다.
Codex가 서버 재시작·로그인·DB 검증을 직접 실행하거나 관찰한 결과가 아니다.
기존 [A/B 인수 검증 PASS](2026-10-30-auth0-ab-acceptance.md)는 보존한다.

| 구분 | 결과 | 사용자 전달 근거 |
|---|---|---|
| API 프로세스 재시작 후 기존 로그인 세션 복원 | PASS (사용자 전달) | 기존 프로세스 28400 종료, 새 프로세스 33564 실행 후 재로그인 없이 기존 브라우저 새로고침. 화면은 로그인됨 / 세션 유효, page HTTP 200 |
| MySQL 체크포인트 생성 | PASS (사용자 전달) | `python -B -m scripts.verify_mysql checkpoint` → `PASS: checkpoint` |
| MySQL 체크포인트 비교 | PASS (사용자 전달) | `python -B -m scripts.verify_mysql verify-checkpoint` → `PASS: verify-checkpoint` |
| MySQL 실제 중지·재시작 | NOT_RUN (실행 로그 미확인) | 중간에 `docker compose stop mysql` 및 `docker compose start --wait mysql` 실행을 안내했으나 두 명령의 실행 출력은 전달받지 못함 |

재시작 후 사용자 전달 로그의 다음 단계는 모두 PASS였다.
`cookie_present`, DB connect/schema, `cookie_lookup`, `cookie_session_validation`,
`token_decrypt`, `cookie_token`, `jwks_fetch`, access_profile/signature/claims/time,
`access_verify`, `session_lookup`, `session_binding`.
로그 원문이나 인증값은 첨부하지 않는다.

API 재시작 PASS는 **유효한 토큰과 기존 브라우저 쿠키를 사용한 API 프로세스 재시작 후
세션 복원**에 한정한다. 토큰 만료 뒤 처리나 PC 재부팅까지 입증하지 않는다.
MySQL 비교 성공은 확정하되, 실제 MySQL 중지·재시작 여부는 미확인이다.

## 체크포인트 대상과 검증 범위 (코드 확인)

Codex는 [verify_mysql.py](../../scripts/verify_mysql.py)와 이 코드가 호출하는
[local_mysql.py의 snapshot](../../scripts/local_mysql.py)을 읽어 다음 범위를 확인했다.
검증 명령 자체는 이번 문서 작업에서 재실행하지 않았다.

- 대상 DB는 `neorang_narang`이다. `nn_schema_version`은 version 순,
  `nn_completion_owners`는 owner_sub 순, `nn_completion_records`는 owner_sub, record_id 순으로
  `SELECT *`한 전체 행을 snapshot으로 만든다.
- `checkpoint`는 완료 기록이 존재하고 삭제 표시(`deleted_at`)된 행이 하나 이상인지 확인한다.
  snapshot의 `repr`을 UTF-8로 인코딩한 SHA-256 digest만 Git 제외 체크포인트 파일에 기록한다.
  해당 파일과 digest 값은 이 문서나 커밋에 포함하지 않는다.
- `verify-checkpoint`는 새 snapshot의 digest와 저장된 digest의 동일성을 검사한다.
  별도 Python 실행에서 새 저장소·연결을 사용하여 각 완료 기록을 소유자 문맥의
  `CompletionService(MySQLCompletionStore(), AuthContext(...))`로 조회한다.
  미삭제 행은 revision과 completed_at(DB 비교 시 timezone 제거)의 일치를,
  삭제 표시 행은 조회 시 HTTPException 404를 확인한다.
- 이 검사는 Core 인증 DB·다른 DB·다른 테이블·인덱스/DDL·권한·볼륨 전체를 비교하지 않는다.
  실제 HTTP 인증 흐름이나 전체 DB 백업·복원 검사도 아니다.
  체크포인트 사이 쓰기가 발생하면 digest가 달라질 수 있다.

## 남은 확인 항목과 한계

이번 결과로 다음 항목을 PASS로 변경하지 않는다.

| 항목 | 상태 |
|---|---|
| PC 또는 Docker Desktop 재부팅 | NOT_RUN |
| 토큰 만료 후 세션 처리 | NOT_RUN |
| 운영 배포와 모바일 연동 | NOT_RUN |
| 전체 DB 백업·복원 | NOT_RUN |
| 체크포인트 범위 밖 데이터 보존 | NOT_RUN |
| MySQL 실제 중지·재시작 | NOT_RUN (실행 로그 미확인) |

DB 구조·인증 경계의 운영 적용 승인은 기존 AUTHOR_REVIEW_REQUIRED를 유지한다.

## 문서 작업 검사 (Codex 직접 실행)

서버·컨테이너 재시작, DB·볼륨·환경 파일·키 변경은 수행하지 않았다.
비밀번호·토큰·쿠키·체크포인트 파일은 문서와 Git에 포함하지 않는다.
앱 코드 변경이 없어 API 회귀·DB 통합 검사는 NOT_RUN이며 기존 PASS를 재실행 결과로 사용하지 않는다.

| 상태 | 검사 | 범위 |
|---|---|---|
| PASS | 변경 문서의 Markdown 상대 링크 검사 | README, Core 실행 안내, 이 기록의 로컬 파일 링크 존재 확인 |
| PASS | `git diff --check` | 문서 변경의 공백 오류 없음 |

관련 문서만 파일명을 명시해 스테이징하고 사용자 요청에 따라 커밋한다.
push·merge는 수행하지 않는다.
