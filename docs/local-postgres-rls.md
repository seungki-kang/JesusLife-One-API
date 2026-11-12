# PostgreSQL 역할·RLS 로컬 기반

상태: **AUTHOR_REVIEW_REQUIRED** (DB 구조·인증 경계). 시작 기준 `fe0e42c`,
브랜치 `feature/postgres-role-rls-foundation`. 이번 사용자 요청의 로컬 합성 검증 범위다.
Supabase·원격 SQL·실제 사용자 자료·제품 스키마 적용은 포함하지 않는다.

## 변경과 경계

- `migrations/postgres/001_role_rls_foundation.sql`: 별도 합성 schema와 두 테이블,
  migration 소유 역할과 runtime 역할. 기존 MySQL migration은 그대로 보존한다.
- `scripts/verify_postgres_rls.py`: 설치된 PostgreSQL 도구로만 임시 클러스터를
  생성하고 폐기한다. PG 환경을 제거한 Python 자식에서 검증하며 기존 서비스·DB·자격증명을 사용하지 않는다.
- `scripts/postgres_rls_support.py`: 검증 전용 환경 allowlist와 루프백 TCP connector.
  부모의 모든 `PG*` 변수를 제외하고, worker에 남아 있으면 접속 전에 거부한다.
  Python 연결은 `host=hostaddr=127.0.0.1` 및 생성한 임시 포트를 명시한다.
- `tests/test_postgres_rls.py`: 실제 DB에서 정책·권한·트랜잭션 경계를 검사한다.
  최초 빈 DB에만 fixture를 한 번 주입한다. 복원 DB에서는 재생성하지 않는다.
  일반 테스트 탐색에서는 명시적으로 skip한다.
- `tests/test_postgres_rls_isolation.py`: 부모 PG 환경 제거, TCP 인자 고정,
  비격리 연결의 사전 거부를 mock으로 검사한다. 외부 접속은 수행하지 않는다.
- 설정, PostgreSQL 어댑터, FastAPI 경로와 기존 오류·연결 계약은 변경하지 않는다.

`app/core/auth.py`와 별도 `app/auth0_pc.py`에는 검증된 계정 인증 경로가 있다.
그러나 교회 소속 검증 경로는 없다. **실제 API 연결은 보류**한다. 요청 body,
query, header의 교회 ID를 PostgreSQL 문맥으로 전달하는 경로를 추가하지 않았다.
향후 서버에서 계정·교회·제품 권한·동의를 검증한 뒤 요청 transaction 안에서만
`set_config(..., true)`를 사용해야 한다. 테스트의 문맥 주입은 인증 구현이 아니다.

## 권한과 정책

`jl_migration_owner`는 합성 schema와 table을 소유하고 DDL을 수행한다.
`jl_api_runtime`은 schema USAGE, 소속 SELECT, 합성 기록 CRUD만 갖는다.
두 역할 모두 SUPERUSER, CREATEDB, CREATEROLE, REPLICATION, BYPASSRLS,
INHERIT가 없고 역할 멤버십도 부여하지 않는다. NOINHERIT만으로 SET ROLE을
차단할 수 없으므로 runtime의 outbound membership이 **0개**인지 검사한다.
로그인은 허용하되 SQL에는 비밀번호가 없다. 실제 자격증명 발급은 별도 작업이다.

소속은 `(account_id, church_id, can_write)` 합성 자료이며 runtime은 변경하지
못한다. 현재 계정·교회에 해당하는 소속만 볼 수 있고, 기록 정책은 그 소속을
다시 요구한다. 읽기는 소속, 쓰기는 `can_write`가 추가로 필요하다. 개인 원문,
공유 동의 또는 ChurchOS의 최종 소속 모델을 정의하지 않는다.

두 테이블 모두 ENABLE/FORCE RLS를 적용한다. owner도 일반 조회 시 기본
거부되지만 owner는 DDL로 정책을 바꿀 수 있다. 따라서 owner 자격증명을 API에
제공해서는 안 된다. 관리자는 합성 fixture 주입·백업에만 사용한다.
Custom GUC는 runtime 자체도 설정 가능하므로 SQL injection이나 위조된 계정을
막는 인증 수단이 아니다. FastAPI 인증·소속 검증이 완료되어야 연결할 수 있다.

## 실행

```powershell
.\.venv\Scripts\python.exe -B -m scripts.verify_postgres_rls --pg-bin 'C:/Program Files/PostgreSQL/16/bin'
.\.venv\Scripts\python.exe -B -m scripts.test_offline
.\.venv\Scripts\python.exe -B -m pip check
git diff --check
```

P2 환경 상속 회귀를 포함해 실제 실행한 명령은 아래와 같다. 외부 주소 모양의
`192.0.2.1`은 부모 환경과 mock 입력에만 넣으며, 접속하는 자식은 PG 환경이
없음을 검사하고 모든 연결을 루프백에 고정한다. 서버 버전·실제 서버 주소·포트와
runtime 연결의 host/hostaddr/port도 검사한다.

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_postgres_rls_isolation -v
.\.venv\Scripts\python.exe -B -c "import os,sys; os.environ.update(PGHOSTADDR='192.0.2.1', PGSERVICE='synthetic_missing_service', PGOPTIONS='-c role=synthetic_invalid_role'); sys.argv=['verify_postgres_rls','--pg-bin','C:/Program Files/PostgreSQL/16/bin']; from scripts.verify_postgres_rls import main; raise SystemExit(main())"
.\.venv\Scripts\python.exe -B -c "import ast; from pathlib import Path; files = sorted(Path('app').rglob('*.py')) + sorted(Path('tests').rglob('*.py')) + sorted(Path('scripts').rglob('*.py')); [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in files]; print(f'{len(files)} Python files: syntax OK')"
```

검증기는 임시 디렉터리, 임의 loopback 포트, 합성 관리자 이름을 사용한다.
임시 클러스터의 trust 인증은 짧은 로컬 시험 전용이다. 다른 로컬 프로세스도
접속할 수 있으므로 실제 데이터와 함께 사용하지 않는다. Windows 샌드박스에서
서버 실행이 차단되면 해당 로컬 명령의 실행 권한이 필요하다. 설치는 하지 않는다.

## 적용·롤백·복구

이 SQL은 **최초 설치용 검토 산출물**이며 운영 migration runner가 아니다.
관리자가 빈 격리 DB에서 한 transaction으로 실행한다. 같은 이름의 role/schema가
이미 있으면 실패하며 기존 객체를 덮어쓰거나 권한을 수정하지 않는다. 기존 버전은
PostgreSQL 기반이 없는 상태이며 기존 MySQL 데이터의 업그레이드·이관은 수행하지 않는다.
재실행 실패 후에는 rollback하고 기존 구조·역할·version을 조사한다. 향후 운영
runner에는 DB 식별·잠금·version/checksum·구조 확인을 먼저 구현해야 한다.

- commit 전 실패: 전체 transaction rollback. 역할·schema·권한이 함께 취소되는지
  마지막 단계 강제 오류로 검사한다. 부분 성공을 version으로 기록하지 않는다.
- commit 후 문제: API 연결·쓰기를 중지하고 runtime 접근을 통제한다. 기존 DB의
  사용자 기록이나 공유 역할을 DROP하지 않는다. 검토된 순방향 보완 migration 또는
  격리 복원을 선택한다. 이 산출물에는 파괴적 down SQL을 제공하지 않는다.
- 적용 전 backup: 기존 대상이라면 DB의 일관된 dump와 별도 보호된 global role/ACL
  백업을 확보하고 대상·버전·소유권을 검토한다. 이 최초 설치 SQL을 기존 대상에
  자동 재시도하지 않는다. 비밀정보가 포함될 수 있는 global backup은 저장소 밖에서 보호한다.
- 로컬 DB 복구: 백업 직전 repeatable-read 읽기 transaction에서 memberships의
  `(account_id, church_id, can_write)` 전체와 synthetic_records의
  `(record_id, church_id, marker)` 전체를 PK 순서로 snapshot한다.
  `pg_dump -Fc` → 같은 클러스터의 별도 합성 DB에 `pg_restore --exit-on-error` 후,
  전체 값·역할·소유권·DB/schema/table ACL을 원본과 비교한다. 복원 후 권한을
  보정하거나 데이터를 초기화하지 않는다. RLS 검증 전후 모두 같은 snapshot을 요구한다.
- 새 클러스터 복구: `pg_dumpall --roles-only --no-role-passwords`로 합성 역할을
  별도 백업한다. 다른 bootstrap 역할로 두 번째 PostgreSQL 16 클러스터를 초기화하고,
  원본 역할이 없음을 확인한 뒤 `psql -X -v ON_ERROR_STOP=1 -1`로 역할을 복원한다.
  원본 소유자의 별도 DB를 생성하고 DB dump를 복원한다. 역할 속성·멤버십과
  DB/schema/table의 소유권·ACL, ENABLE/FORCE RLS를 OID 대신 이름·권한으로 비교한다.
  이어 동일한 전체 행 비교와 8개 RLS 검증을 수행한다. 비밀번호 hash는 백업하지 않는다.
- 복원 RLS 검사에는 fixture 생성·정리용 TRUNCATE가 없다. runtime의 TRUNCATE
  **권한 거부 검사**만 있다. CRUD 및 migration DDL 검사는 rollback하고, commit/rollback
  문맥 소멸 검사는 자료를 변경하지 않는다. 테스트 전후 전체 행 동일성을 다시 확인한다.
- 검증 종료: 이번 검증기가 만든 임시 클러스터만 중지하고 해당 임시 파일을 폐기한다.

## 2026-11-12 검증 결과

| 상태 | 검증 |
|---|---|
| PASS | PostgreSQL 16.15 격리 설치, migration 마지막 단계 실패 시 원자적 rollback, 재실행 충돌 시 원본 보존 |
| PASS | P2 환경 격리: 부모 PGHOSTADDR/PGSERVICE/PGOPTIONS가 있는 실제 실행에서도 PG-free worker와 루프백 주소·포트 확인. mock 회귀 3개 통과 |
| PASS | 실제 runtime 로그인, 동일 교회 허용 CRUD, 다른 교회 조회·쓰기·행 이동 차단 |
| PASS | 소속 없음·계정/교회 범위 없음·잘못된 범위 거부, 읽기 전용 소속 쓰기 차단 |
| PASS | 두 교회 쓰기 소속 계정도 현재 교회 밖으로 양방향 행 이동 불가, memberships 직접 조회는 현재 계정·교회 행만 반환 |
| PASS | runtime 금지 속성·소유권·멤버십 부재, SET ROLE·권한 변경·DDL·TRUNCATE·RLS 해제 차단 |
| PASS | 같은 물리 연결에서 commit/rollback 뒤 범위 소멸과 새 transaction 기본 거부 |
| PASS | P2 복원 보존: UUID·교회 매핑·can_write 포함 전체 행 snapshot 비교, fixture 재생성 없이 복원 자료에서 검사, 검사 후 전체 행 동일 |
| PASS | 원본 DB 8개 + 같은 클러스터 DB 복원 8개 + 새 클러스터 역할·ACL 복원 8개: 총 24회 DB 테스트 통과 |
| PASS | 오프라인 회귀 238개: 215 통과, 23 skip. 기존 공개 경로와 PostgreSQL 어댑터 계약 포함 |
| PASS | pip check, app/tests/scripts 68개 Python 파일 ast.parse, git diff --check. 최종 명령 종료 코드 모두 0 |
| NOT_RUN | 기존 opt-in 실제 MySQL 검증(이번 변경 대상 아님), 실제 API RLS 연결(교회 소속 검증 경로 없음), formatter/linter/type checker(설정 없음) |
| NOT_RUN | 역할 비밀번호·운영 자격증명 복구, tablespace/확장/다른 PostgreSQL 버전·운영 규모 복구: 합성 PostgreSQL 16 역할·ACL 검증 밖 |
| NOT_RUN | Supabase·원격 SQL·원격 migration·실제 사용자 저장·배포: 요청 제외 |
| AUTHOR_REVIEW_REQUIRED | DB 구조·역할·정책 및 향후 인증/소속 경계의 실제 적용 |

최종 실제 PostgreSQL 검증은 BLOCKED가 아니다. 샌드박스의 프로세스 시작 차단은 권한을
확장한 로컬 실행으로 검증했고, inet 주소 표기 비교 실패는 host(inet_server_addr())로
보정 후 재검증했다. 최종 FAIL은 없으며 임시 클러스터는 중지·정리한다.
운영 migration/출시 PASS를 뜻하지 않는다. 패키지 설치와 git add/commit/push는 하지 않았다.

## FastAPI 합성 요청 검증

`test_fastapi_synthetic_church_read`는 임시 PostgreSQL 클러스터와 격리된
FastAPI 테스트 앱에서 인증 누락, 소속 확인 후 RLS 조회, 다른 교회 접근 거부,
소속 조회 장애와 업무 SQL 미실행, 트랜잭션 종료 후 범위 제거를 확인한다.
실제 교회 소속 원본과 운영 API 연결은 후속 작업이다.
