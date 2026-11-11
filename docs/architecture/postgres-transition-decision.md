# JesusLife One API PostgreSQL 전환 결정서

## 1. 문서 상태

- 상태: **설계 초안 / 구현 전 승인 필요 / 실제 운영 적용이 아님**.
- 작성일: 2026-11-12. 작업 브랜치: `architecture/postgres-transition`.
- **확정 결정**은 이번 요청으로 정한 기술 방향과 보존 원칙을 뜻한다. DB 구조·인증 경계·개인정보 정책의 실제 적용 승인까지 뜻하지 않는다.
- **제안 / AUTHOR_REVIEW_REQUIRED**는 후속 설계·시험·사람의 승인이 필요한 사항이다. 이 문서는 코드, DB, 환경 설정을 변경하지 않는다.

## 2. 전환 목적

JesusLife 전체 플랫폼의 공통 업무 DB 기반을 마련한다. 향후 ChurchOS, JLBible, JLPrayer, JesusLifeAcademy, 너랑나랑, 생명일기, CHGO 연동을 준비한다. Supabase는 관리형 PostgreSQL과 Storage 용도로 사용하며 pgvector 확장 가능성을 확보한다.

제품별 데이터 원본 소유권은 유지한다. PostgreSQL 도입이 제품 간 개인 기록 공유를 허용하거나 모든 제품을 이번에 구현한다는 뜻은 아니다. 파일은 Storage, 업무 상태와 파일 참조·권한 메타데이터는 PostgreSQL이 담당한다. Storage 연동과 실제 파일 수집은 후속 승인 대상이다.

## 3. 현재 기준

- main 기준 커밋은 `b4e5111`이다. 작업 시작 시 main 참조도 해당 커밋이며 작업 트리는 깨끗했다.
- 비교·복구 기준은 `test/nn-real-sync-mysql-harness`와 `ee3f7dc`이다. 시작 시 이 브랜치가 해당 커밋을 가리킴을 확인했다. 참조 이동·삭제·checkout·reset은 하지 않는다.
- 기존 PyMySQL 기반이며 `requirements.txt`는 `PyMySQL[rsa]==1.1.2`를 명시한다. `requirements-dev.txt`는 실행 의존성과 시험 의존성을 고정한다. psycopg는 이번에 추가하지 않는다.
- `app/core/database.py`는 로컬 MySQL `127.0.0.1:3307`만 허용한다. `autocommit=False`, dictionary cursor, UTC 세션, 접속·읽기·쓰기 timeout을 사용한다. 환경 파일 로딩 코드를 읽었으나 `.env` 파일 자체와 실제 설정값은 열지 않았다.
- `mysql_store.py`의 완료 메타데이터 저장소는 READ COMMITTED와 소유자 행 잠금으로 명령을 직렬화한다. schema version 1을 검사하고 revision, deleted_at, delete_base를 보존한다. UUID는 CHAR(36), 시각은 UTC로 해석하는 naive DATETIME(6)이다.
- `mobile_store.py`는 Core transaction 안에서 모바일 인계 코드의 일회 소비와 동의 generation 행 잠금을 처리한다. 철회는 `deletion_through`를 단조 증가시키고 제품 projection 삭제를 같은 transaction에서 수행한다. 과거 철회 재전송은 이후 재동의를 철회하지 않는다. `current_generation_deletion_complete`와 기존 응답 필드를 함께 유지한다.
- `mobile_routes.py`는 서버 세션·검증된 토큰·scope에서 소유자를 정한다. 합성 완료 경로는 `synthetic=true`만 허용한다. 이 경로의 `generation`/`completed_at` 계약과 real sync 후보의 `consent_generation`/`completed_on` 계약을 혼동하거나 자동 통합하지 않는다.
- `real_sync_mysql.py`는 **FastAPI에 미연결인 합성자료 전용 후보 구현**이다. connector를 주입받으며 인증·Core 동의 권한을 부여하지 않는다. 명령마다 독점 비풀링 연결과 READ COMMITTED transaction을 사용한다. 잠금 순서는 gate → operation_id 순 receipts → sync_id 순 records → sync_id 순 barriers다. 테이블별 소유자 최대 10,000행 및 삭제 장벽 예약 한도는 후보 제약이며 운영 용량 보장이 아니다.
- `real_sync_repository.py`는 고정 오류, outcome과 cleanup_failed 구분, 동일 명령 재시도 계약을 정의한다. `real_sync_schemas.py`는 create/ACK 형태만 검증하며 실제 인증·동의·정책 승인을 증명하지 않는다.
- 순수 SQL migration을 사용한다. `migrations/neorang_narang/001_initial.sql`은 소유자·완료 기록·버전, `002_mobile_synthetic.sql`은 삭제 후에도 sync_id 장벽을 남기는 합성 projection을 정의한다. `migrations/platform_core/001_pc_auth.sql`은 계정·외부 신원·로그인·세션·토큰·동의, `002_mobile_broker.sql`은 모바일 로그인·동의 세대를 정의한다. 이 두 경로에는 real sync 후보의 `nn_real_*` 테이블 migration이 없으며 이를 기존 적용 스키마로 간주하지 않는다.
- README에는 메모리/로컬 MySQL 모드, 별도 Auth0 PC 개발 진입점, 오프라인 시험 절차가 있다. AGENTS.md의 초기 골격 설명보다 현재 코드 범위가 확장되어 있으므로 현재 구조 판단에는 읽은 코드를 함께 사용한다. 문서에 적힌 과거 PASS를 이번 실행 결과로 재사용하지 않는다.
- 합성자료 중심 검증을 유지한다. 실제 개인정보 수집은 승인되지 않았다. 실제 DB·사용자 기록은 열거나 수정하지 않았다.

기존 MySQL 구현은 로컬 시험과 계약 검증을 위한 유효한 작업이며, PostgreSQL 전환의 비교·회귀 기준으로 보존한다.

## 4. 확정할 기술 방향

다음은 **확정 결정**이다. 구현·운영 적용은 별도 승인 후 진행한다.

- Supabase PostgreSQL을 업무 데이터 원본으로 사용한다.
- 초기 Supabase 조직은 개인 계정의 개발 전용 임시 구조로 시작한다. 시작 요금제는 Free, 개발 단계 월 비용 한도는 **USD 0**이며 운영 원본을 소유하지 않는다. 소유권·비용·자료 제한과 다섯 번째 승인 기록은 21절을 따른다. 실제 조직·프로젝트 생성은 미승인이다.
- 개발·시험·스테이징·운영 환경은 단계적으로 분리한다. 지금은 `local-test`와 Supabase 서울 `development` 준비부터 시작하며, 베타 전에 별도 `staging`, 정식 출시 전에 별도 `production` 프로젝트를 마련한다. 환경별 역할·격리·승격 원칙과 네 번째 승인 기록은 20절을 따른다. 실제 프로젝트 생성과 연결은 미승인이다.
- Auth0를 공통 인증 제공자로 유지하며 Supabase Auth를 동시에 도입하지 않는다.
- Auth0의 검증된 `(issuer, provider_subject)`는 외부 신원 식별자이며, 제품 데이터의 소유자 키는 내부 `accounts.account_id` UUID로 한다. 구체적인 확정 매핑 원칙은 11절과 두 번째 승인 기록인 18절을 따른다.
- Flutter 앱은 Supabase DB에 직접 연결하지 않는다. 접근 구조는 **Flutter → FastAPI → PostgreSQL**이다.
- 일반 FastAPI 업무 요청은 최소 권한 `jl_api_runtime`을 사용하고 **FastAPI 권한 검사 + PostgreSQL RLS**를 함께 통과해야 한다. RLS는 인증·동의·제품 권한 검사를 대신하지 않는 추가 방어선이며 사용자 또는 tenant 문맥이 없으면 기본 거부한다. 상세 원칙과 세 번째 승인 기록은 11절·19절을 따른다.
- PostgreSQL 드라이버는 psycopg 3으로 한다. 첫 전환에서는 SQLAlchemy와 Alembic을 도입하지 않는다.
- 순수 SQL migration 원칙을 PostgreSQL용으로 유지한다. 기존 MySQL migration은 수정하지 않고 PostgreSQL migration은 별도 경로에 추가한다.
- MySQL과 PostgreSQL의 장기 이중 쓰기 및 자동 양방향 동기화를 금지한다. 운영 전환 시 쓰기 원본은 하나여야 한다.
- pgvector는 업무 데이터 원본이 아닌 파생 검색 색인이다. 원본에서 재생성 가능해야 하고 동의 철회·삭제를 색인에도 반영해야 한다. 확장 활성화와 색인 수집은 이번 범위가 아니다.
- GraphDB는 이번 전환 범위에 포함하지 않는다.

대안 비교: MySQL 유지는 기존 시험 자산 재사용과 단기 비용에 유리하지만 이번 플랫폼 기반 방향은 PostgreSQL로 정한다. ORM·Alembic 동시 도입은 변경 축을 늘리므로 유보한다. 장기 이중 쓰기는 멱등성과 삭제 장벽의 원자성을 DB 간에 확장해야 하므로 채택하지 않는다. 영향은 connector·SQL·자료형·오류 처리의 교체이며 외부 계약은 유지한다.

## 5. 보존할 계약

| 계약 | 보존 조건 |
|---|---|
| sync_id | 같은 논리 기록의 안정된 UUID. 삭제 후 새 동의로 재전송되어도 장벽을 우회하지 못한다. |
| operation_id / idempotency | 소유자 안에서 같은 명령의 식별자. 동일 ID·동일 내용은 저장된 최초 receipt로 replay하고, 다른 내용은 IdempotencyKeyReused로 거부한다. |
| consent_generation | 서버가 확인한 열린 세대와 일치해야 한다. 클라이언트 값 자체가 동의 권한은 아니다. |
| policy_version | 정확한 버전 비교를 보존하며 Core 정책 승인·동의 확인을 별도로 요구한다. |
| revision | 후보 create는 base_revision=0, 최초 applied/current revision=1. replay의 최초 applied_revision·received_at을 유지하고 current_revision은 applied_revision 이상이어야 한다. |
| generation fence | retired_through 이하 명령과 닫힌 세대를 거부한다. 이후 재동의가 이전 세대 명령을 살리지 않는다. |
| tombstone 또는 삭제 장벽 | 삭제된 operation receipt와 sync_id 장벽을 유지한다. 거부 장벽을 ACK 구성보다 먼저 확인한다. |
| 같은 명령 재시도 | operation_id, sync_id, generation, policy, payload를 그대로 재사용한다. 새 ID로 대체하지 않는다. |
| 응답 유실 | 성공을 가정하지 않고 같은 명령으로 receipt를 확인한다. 장벽이 생겼다면 성공 ACK 대신 철회·삭제 거부를 유지한다. |
| transaction outcome unknown | commit 도중 연결 유실 또는 rollback 실패는 결과 불명으로 취급한다. 새 연결에서 같은 명령으로 조정하며 단순 실패·자동 성공으로 바꾸지 않는다. |
| cleanup | commit 확인 후 정리 실패는 CleanupFailed/outcome=committed로 구별한다. outcome(not_started/rolled_back/unknown/committed)과 cleanup_failed를 유지한다. |
| 정보 보호 | 고정 오류만 외부에 반환한다. 민감정보, SQL 인자, DTO, driver 예외, traceback locals를 로그에 넣지 않는다. 합성자료만 검증한다. |

후보 repository의 자동 retry 없음, 원자적 create/retire/close, 부분 chunk commit 금지도 보존한다. 기존 모바일 응답과 공개 API 경로를 DB 교체만으로 변경하지 않는다. 후보 오류를 HTTP 상태로 매핑하는 작업과 real sync API 연결은 별도 계약 검토 대상이다.

## 6. 교체할 구현

| 현재 | 전환 대상 |
|---|---|
| PyMySQL | psycopg 3 |
| MySQL connector | PostgreSQL connector: TLS·timeout·UTC·transaction 경계 검증 |
| MySQL repository | PostgreSQL repository: 기존 Protocol과 계약 유지 |
| MySQL 전용 SQL | PostgreSQL SQL과 명시적 schema 한정 이름 |
| MySQL 오류 번호 | PostgreSQL SQLSTATE 기반 고정 오류 분류 |
| 로컬 MySQL 설정 | Supabase PostgreSQL 환경 설정과 비밀정보 관리 |

설정 이름·접속 방식·TLS 검증·pooler 사용 여부·psycopg 배포 옵션과 버전은 **제안 / AUTHOR_REVIEW_REQUIRED**다. 기존 로컬 connector의 제한을 완화해 Supabase에 연결하는 방식은 사용하지 않는다. 첫 후보는 독점 연결의 폐기 보장을 유지하며 pooling은 별도 검증 전 허용하지 않는 방안을 제안한다. 실제 endpoint·비밀번호·DSN은 문서나 로그에 기록하지 않는다.

## 7. SQL 매핑표

아래는 **구현을 위한 제안**이며 SQLSTATE와 자료형만 기계적으로 치환하지 않고 contract test로 의미를 증명한다.

| MySQL | PostgreSQL 제안 및 정책 |
|---|---|
| UUID인 BINARY(16), UUID인 CHAR(36) | UUID. UUID bytes 의미·canonical JSON 문자열·정렬 순서 회귀 검증. Auth0 subject 원문은 UUID로 강제 변환하지 않는다. |
| DATETIME(6) | TIMESTAMPTZ(6). 모든 시각은 UTC timezone-aware로 처리한다. 기존 UTC naive 자료의 해석은 명시적으로 UTC로 고정한다. |
| ON DUPLICATE KEY UPDATE | ON CONFLICT (명시한 unique key) DO UPDATE 또는 의미상 무변경인 경우 DO NOTHING. 갱신 필드·충돌 대상·동시성 의미 검증. |
| utf8mb4 / ascii_bin / VARBINARY 문자열 | PostgreSQL UTF-8. policy·신원 비교의 대소문자·byte 의미를 보존할 collation/자료형을 검토한다. UTF-8 설정만으로 기존 비교 의미가 보장되지는 않는다. |
| 1205 lock wait timeout | 55P03(lock_not_available, lock_timeout 포함)을 중심으로 분류한다. 57014(query_canceled)는 statement timeout·취소 원인을 구별하고 무조건 retry하지 않는다. |
| 1213 deadlock | 40P01(deadlock_detected). 40001(serialization_failure)도 rollback 확인 후 동일 명령의 제한된 retry 후보로 처리한다. |
| 1062 duplicate | 23505(unique_violation). 예상된 키 경쟁은 전체 rollback 후 같은 명령 재확인 대상으로 분류한다. 내용 불일치·예상 밖 제약 위반을 성공 ACK로 바꾸거나 무한 retry하지 않는다. |
| SELECT ... FOR UPDATE | READ COMMITTED와 소유자 gate 잠금, receipts/records/barriers의 결정적 순서 유지. 없는 행은 unique insert와 gate로 직렬화하며 DB별 gap lock 동작을 가정하지 않는다. |
| UNSIGNED BIGINT | BIGINT + CHECK 범위 제약. 후보 상한 2^63−1을 유지하고 기존 unsigned 범위 차이를 검사한다. |
| BINARY(32), 암호문 BLOB/VARBINARY | BYTEA와 필요한 길이 제약. 해시·암호문을 UUID나 일반 텍스트로 바꾸지 않는다. |
| completed_on 문자열 | 날짜만 뜻하는 YYYY-MM-DD 계약 유지. DATE 채택 시 왕복 동일성 검증. 시각으로 변환하지 않는다. |

repository 내부 자동 retry는 도입하지 않는다. rollback 확인, 새 연결, 같은 명령, 제한 횟수·backoff를 호출 계층에서 보장한다. commit 예외는 SQLSTATE가 retry 후보처럼 보여도 TransactionOutcomeUnknown 처리를 우선한다. PostgreSQL의 실패 transaction을 그대로 재사용하지 않는다.

시간은 접속 TimeZone도 UTC로 고정하고 API UTC Z 직렬화를 보존한다. naive datetime을 받아 자동으로 로컬 시간으로 해석하지 않는다. TIMESTAMPTZ는 원래 timezone 이름을 보관하는 자료형이 아니다. 근거: [psycopg 3 자료형 변환](https://www.psycopg.org/psycopg3/docs/basic/adapt.html), [PostgreSQL SQLSTATE](https://www.postgresql.org/docs/current/errcodes-appendix.html).

## 8. PostgreSQL 스키마 초안

아래는 **제안 / AUTHOR_REVIEW_REQUIRED**이며 schema 생성 승인이나 DDL이 아니다. 같은 배포·DB 안에서도 원본 소유 제품은 하나이며 타 제품은 계약/API/이벤트와 안정된 ID로 참조한다.

| schema | 책임 제안 |
|---|---|
| platform | 공통 동의·정책·동기화 조정·schema version 기반 |
| identity | Auth0 issuer/subject와 내부 account UUID 연결, 계정·세션 권한 경계 |
| neorang_narang | 완료 메타데이터, receipt, gate, 삭제 장벽 |
| life_diary | 생명일기 소유 경계 예약; 이번에는 원문·음성 미수집 |
| church_os | 교회·조직·역할·화이트라벨과 tenant 경계 |
| jl_bible | 성경 읽기·통독 업무 기록 |
| jl_prayer | 기도·중보 업무 기록 |
| academy | 교육 과정·진도·수료; 신학 정본 임의 변경 금지 |
| chgo_registry | CHGO 연동 ID·출처·상태 참조; 정본 발급·GraphDB 구현 제외 |
| audit | 민감 원문을 제외한 허용 목록 기반 감사 이벤트 |

첫 단계는 platform 또는 공통 동기화 기반과 neorang_narang에 한정한다. 나머지 schema를 선제 생성하지 않는다. 공통 fence와 제품 receipt 사이의 권한·transaction 소유권, FK 범위, tenant key와 인덱스는 후속 설계에서 승인받는다. schema 분리 자체는 사용자·테넌트 격리 증명이 아니다.

## 9. 첫 구현 범위

**확정 범위 제한:** platform 또는 공통 동기화 기반과 neorang_narang 완료 메타데이터만 대상으로 한다. sync_id, operation_id, 검증된 소유자 참조, consent_generation, policy_version, 과정 번호, 완료일, revision, receipt·삭제 장벽에 필요한 최소 자료를 검토한다.

이름, 상대방 이름, 은혜 원문, 서명 원문은 제외한다. 실제 생명일기 원문과 음성도 제외한다. 후보의 SyntheticAccountContext를 실제 인증 결과로 승격하지 않는다. 기존 모바일 합성 경로와 real sync 후보를 연결하는 Core 권한 계약은 별도 승인 대상이다.

## 10. migration 전략

**제안 / AUTHOR_REVIEW_REQUIRED:** `migrations/postgres` 아래 공통·제품별 순수 SQL migration을 둔다. 기존 MySQL 경로와 파일은 불변으로 보존한다.

- 적용된 migration은 수정하지 않는다. 수정은 순방향 추가 migration으로 표현한다.
- 실행기는 대상 DB·schema·권한, migration 잠금, version·checksum·실제 구조를 확인한다. 미지·미래 버전 또는 구조 불일치 시 중단한다.
- migration별 transaction 가능 여부를 명시한다. 모든 DDL이 같은 transaction 정책을 따를 것으로 가정하지 않는다. 성공한 전체 구조 검증 뒤 version을 기록한다.
- 빈 DB 설치 시험, 재실행 안전성 시험(중복 적용 방지와 부분 실패 복구 포함), 이전 지원 버전 업그레이드 시험을 합성 DB에서 수행한다. IF NOT EXISTS만으로 구조 적합성을 인정하지 않는다.
- 백업·복원 시험은 격리된 대상으로 수행하고 version, 제약, row 수, receipt, 삭제 장벽 및 복원 후 retry 의미까지 비교한다.
- 백업 시점 이후 삭제·철회가 복원으로 부활하지 않도록 삭제 장벽 재적용 또는 쓰기 차단·조정 절차를 검증한다. 복원 완료만으로 서비스를 재개하지 않는다.

현재 단계는 SQL 작성·실행·실제 데이터 이전을 포함하지 않는다.

## 11. 보안과 권한

**확정 결정 — Auth0와 내부 계정 연결:**

- Auth0의 검증된 `(issuer, provider_subject)`는 외부 신원 식별자다. `provider_subject`는 Auth0의 `sub`에 해당하며, 제품 데이터의 소유자 키는 내부 `accounts.account_id` UUID다.
- Auth0 `sub`를 제품 테이블의 PK나 직접 소유자 키로 사용하지 않는다. 모든 제품 테이블은 내부 `account_id` UUID를 참조한다.
- `external_identities`는 `(issuer, provider_subject)`를 고유 키로 하고 `accounts.account_id`를 참조하는 `account_id`를 가진다.
- 최초 검증 로그인에서 해당 외부 신원에 대응하는 계정이 없으면 `accounts`와 `external_identities`를 같은 트랜잭션으로 생성한다.
- 이메일을 신원 고유키로 사용하지 않으며 이메일 일치만으로 계정을 자동 병합하지 않는다.
- 한 내부 계정에 여러 외부 신원을 연결할 수 있는 구조는 허용한다. 실제 연결에는 재인증과 별도 승인 흐름이 필요하며, 추가 로그인 제공자 연결이나 외부 신원 재연결을 이번 결정으로 승인하지 않는다.
- 요청 body, query, 임의 header의 `user_id`를 소유권 근거로 신뢰하지 않는다. 검증된 외부 신원을 내부 계정으로 매핑한 결과에서 소유자를 정한다.
- 기존 MySQL CoreStore의 외부 신원→내부 계정 매핑과 기존 API `sub`가 내부 계정 UUID를 뜻하는 의미를 PostgreSQL에서도 보존한다.

**AUTHOR_REVIEW_REQUIRED:** Auth0 운영 tenant 설정, 계정 병합·분리, 추가 로그인 제공자 연결, 계정 탈퇴 후 보유기간, 탈퇴 계정 복원, 외부 신원 재연결, 관리자에 의한 계정 수정은 미승인이다. 신원 매핑과 제품 소유자 키의 확정은 이 정책이나 실제 DB·인증 경계의 적용 승인을 대신하지 않는다.

교회 소속은 개인 기록 공유 동의가 아니다. FastAPI가 검증된 신원, scope, 소유자, tenant, 동의 세대와 정책을 검사한다. 토큰, 이름, 은혜 원문, 일기, 서명을 로그·추적·예외에 넣지 않는다. 감사 기록도 원문과 SQL 인자를 제외한다.

### 11.1. 확정 결정 — 최소 권한 역할과 이중 권한 검사

일반 FastAPI 업무 요청은 최소 권한 PostgreSQL 역할을 사용한다. **FastAPI 권한 검사와 PostgreSQL RLS를 함께 사용**하며 application authorization과 RLS를 둘 다 통과해야 한다. RLS는 추가 방어선이며 인증·동의·제품 권한 검사를 대신하지 않는다. 사용자 또는 tenant 문맥이 없으면 기본 거부한다.

아래 역할 이름은 승인된 책임 구분을 설명하는 설계 명칭이다. 실제 role 이름 최종 확정과 생성·권한 적용은 15절의 별도 승인 대상이다.

| 역할 | 사용 범위와 제한 |
|---|---|
| `jl_migration_owner` | schema와 table을 소유하며 migration·DDL에만 사용한다. 일반 FastAPI 런타임에서 사용하지 않는다. 비밀번호와 접속정보를 런타임 환경과 분리한다. |
| `jl_api_runtime` | FastAPI 업무 요청 전용이다. SUPERUSER, CREATEDB, CREATEROLE, REPLICATION, BYPASSRLS를 금지하며 table·schema owner가 아니어야 한다. 승인된 schema와 table에 필요한 SELECT·INSERT·UPDATE·DELETE만 부여한다. `anon`, `authenticated` 같은 Supabase 기본 역할에 업무 테이블 접근을 자동 허용하지 않는다. |
| `jl_backup_operator` | 백업·복원 전용 후보 역할이다. 구체적 권한과 사용 시점은 **AUTHOR_REVIEW_REQUIRED**이며 일반 API 요청에 사용하지 않는다. |
| Supabase `service_role` | 일반 사용자 요청의 데이터 접근에 사용하지 않으며 Flutter 앱에 포함하지 않는다. 관리 작업에도 별도 승인·감사·최소 범위를 적용한다. |

직접 PostgreSQL 접속 역할은 DB 연결에서 사용하는 역할이며, Supabase API의 `service_role` 키는 Supabase API 요청에 사용하는 자격증명이다. 둘을 같은 접속정보로 취급하지 않는다. Supabase API의 `service_role` 권한은 RLS 우회가 가능하므로 서버에 키가 있다는 이유만으로 권한 검사가 충족되지 않는다.

### 11.2. 확정 RLS 원칙

- 개인·교회·제품 데이터 테이블에 `ENABLE ROW LEVEL SECURITY`를 적용하고 필요한 테이블에는 `FORCE ROW LEVEL SECURITY`를 적용한다. `jl_api_runtime`은 table owner나 BYPASSRLS 역할이 아니어야 한다.
- 정책이 없거나 `account_id`·`tenant_id` 문맥이 없으면 **default deny**다.
- 개인 기록은 내부 `account_id`를 기준으로 격리한다. ChurchOS 데이터는 `tenant_id`와 역할을 함께 검사한다.
- 교회 소속은 생명일기·은혜 원문 공유 동의가 아니다. 공유 기록은 별도 `share_grant` 또는 `consent` 계약을 검사한다.
- identity·migration·관리 schema는 Supabase Data API에 노출하지 않는다. 실제 노출 schema 설정은 15절의 별도 승인 대상이다.

### 11.3. 확정 요청 문맥 원칙

- Auth0 검증 후 `external_identities`를 통해 내부 `account_id`를 얻는다. 요청 body/query/header의 `user_id` 또는 `tenant_id`를 신뢰하지 않으며 tenant는 서버에서 검증한 권한으로 정한다.
- PostgreSQL transaction을 시작한 뒤 검증된 `account_id`·`tenant_id`를 transaction-local 값으로 설정한다. `SET LOCAL` 또는 `set_config(..., true)` 같은 transaction-local 방식을 사용한다.
- plain `SET`으로 pool connection에 사용자 문맥을 남기지 않는다. commit·rollback 뒤 문맥이 제거되는지 시험한다.
- connection pool을 도입하기 전에는 독점 연결로 의미를 먼저 검증한다. 나중에 pool을 도입하면 다른 사용자 문맥이 재사용 연결에 남지 않는지 회귀 테스트한다. pooler 사용 여부는 미승인이다.
- Supabase Auth의 `auth.uid()`가 자동으로 현재 Auth0/Core 계정을 제공한다고 가정하지 않는다.

### 11.4. RLS 한계와 후속 승인

RLS는 SQL injection, 잘못 검증한 Auth0 토큰, 잘못 선택한 `account_id`를 자동 해결하지 않는다. application authorization과 RLS를 모두 통과하도록 유지하고 service 역할이나 table owner 우회를 정기적으로 시험한다.

위 원칙의 승인은 실제 role 생성, GRANT·REVOKE, 각 테이블 RLS policy SQL, pooler, 백업 역할, 운영 비밀정보 설정의 실행 승인이 아니다. 구체적 DB 권한·RLS·Storage 접근 정책은 승인 전 적용하지 않는다.

## 12. 단계별 전환 순서

각 단계는 승인된 구현 범위에서 진행하며 실패한 관문을 통과하기 전 다음 연결을 활성화하지 않는다.

1. PostgreSQL connector: 비밀정보 비노출, TLS, UTC, timeout, 독점 연결·폐기와 transaction 경계.
2. PostgreSQL migration: 별도 경로, 빈 DB·version·재실행·업그레이드 시험.
3. PostgreSQL repository: 기존 계약·잠금 순서·원자적 삭제 및 receipt 보존.
4. 합성자료 repository contract test: MySQL 기준 및 공통 Protocol의 의미 비교.
5. transaction·lock·retry test: deadlock, 경쟁, commit/rollback/cleanup 실패와 결과 불명 조정.
6. FastAPI 미연결 상태 시험: 기본 앱의 기존 경로·인증 거부·후보 비노출 확인.
7. 합성 API 연결: 별도 승인된 시험 진입점에서 검증된 신원·동의 경계를 통과.
8. 너랑나랑 메타데이터 시험: 최소 필드, 세대 철회, 응답 유실, 삭제 부활 방지.
9. 실제 사용자 자료 전 운영 검토: 14절 관문과 15절 승인 완료 후 별도 수집·전환 승인.

## 13. 롤백 전략

MySQL 시험 브랜치와 `ee3f7dc`, main 기준 `b4e5111`을 비교·복구 기준으로 보존한다. PostgreSQL 도입 전후 API 계약을 유지한다. DB 간 자동 양방향 동기화와 장기 이중 쓰기는 금지하고 운영 전환 전까지 실제 데이터 migration을 하지 않는다.

**제안:** 합성 시험에서 계약 불일치, version·무결성 오류, 장벽 손실, 격리 실패 또는 결과 불명 조정 실패가 나타나면 PostgreSQL 연결 활성화를 중단한다. 실제 데이터가 없는 시험 단계에서는 코드 설정을 검증된 이전 저장소 구현으로 되돌리고 합성 PostgreSQL 환경은 분석을 위해 격리한다. 저장 실패 시 자동 메모리 fallback으로 성공을 표시하지 않는다.

운영 쓰기가 시작된 뒤에는 이전 DB가 최신 원본이라고 가정해 설정만 되돌리지 않는다. 쓰기 중지, 원본·receipt·삭제 장벽의 일관성 확인, 백업 복원 또는 순방향 수정 계획과 사람의 승인이 필요하다. 적용된 DB migration을 파일 수정으로 되돌리지 않는다. 승인된 보완 migration 또는 검증된 격리 복원 절차를 사용한다. 사용자 기록 초기화·영구 삭제는 수행하지 않는다.

## 14. 검증 관문

아래는 후속 구현의 필수 관문이며 **이번 문서 작업에서는 모두 NOT_RUN**이다.

| 관문 | 통과 기준 |
|---|---|
| 기존 전체 테스트 | README의 오프라인 전체 시험과 기존 공개 경로·인증·응답 계약 유지. opt-in skip은 따로 보고하고 전체 DB 검증 PASS로 간주하지 않음. |
| PostgreSQL 전용 contract test | create/open/retire/close, 고정 오류와 outcome, schema version, 시간·UUID·정책 비교 의미 일치 |
| migration test | 빈 DB·재실행·부분 실패·업그레이드·불일치 version 차단 |
| 멱등성 test | 같은 명령은 같은 receipt, 다른 payload의 operation_id 재사용 거부 |
| 동시성 test | 여러 연결·프로세스의 동일 owner 경쟁, 잠금 순서, 동일/다른 ID 경쟁, 다른 owner 독립성 |
| 응답 유실 test | commit 전후 장애, unknown outcome, cleanup 실패 후 같은 명령 조정; 중복 기록 없음 |
| 삭제 부활 방지 test | retire/close와 create/replay 경쟁, 재동의·과거 철회 재전송·복원 뒤에도 장벽 유지 |
| 테넌트·사용자 격리 test | 다른 owner/tenant 접근·조작 거부, 누락 문맥 거부, RLS 우회 권한 및 문맥 재사용 누출 검증 |
| account_id 문맥 누락 | 내부 account_id 문맥이 없으면 접근 거부 |
| tenant_id 문맥 누락 | tenant_id 문맥이 없으면 접근 거부 |
| 다른 account_id 격리 | 다른 account_id의 기록 접근·조작 거부 |
| 다른 tenant_id 격리 | 다른 tenant_id의 데이터 접근·조작 거부 |
| 교회 역할과 개인 원문 | 교회 역할만으로 생명일기·은혜 등 개인 원문 접근 거부; 별도 share_grant 또는 consent 계약 검사 |
| transaction 문맥 제거 | commit과 rollback 각각 종료 후 account_id·tenant_id 문맥 제거 확인; pool 도입 전 독점 연결로 검증 |
| pool 재사용 문맥 격리 | pool 도입 시 재사용 연결에 다른 사용자·tenant 문맥 누출 없음 |
| migration·runtime 역할 분리 | migration role과 runtime role 분리, 런타임의 소유권·금지 권한 부재와 접속정보 분리 확인 |
| service_role·BYPASSRLS 우회 검사 | service_role·BYPASSRLS·table owner 우회 가능성과 일반 요청의 해당 권한 사용 금지를 정기 시험 |
| 백업·복원 test | 격리 복원 후 구조·version·receipt·동의·삭제 장벽 및 쓰기 재개 조건 검증 |
| 개인정보 0건 | 모든 시험 자료가 합성자료이며 실제 개인정보 0건. 운영 자료 복제·덤프 사용 금지 |
| local-test 환경 관문 | 재생성 가능한 격리 PostgreSQL에서 전체 migration 성공 |
| development 환경 관문 | 원격 연결과 합성자료 통합시험 성공 |
| staging 환경 관문 | migration·RLS·백업·복원 리허설 성공; 운영 dump·백업 사용 금지 |
| production 환경 관문 | 배포 승인과 복구계획 확인 |
| 환경별 식별자·비밀정보 격리 | 환경별 프로젝트 ID와 비밀정보가 서로 다름을 비밀값 노출 없이 확인 |
| 운영 데이터 유출 방지 | 운영 데이터와 운영 백업이 개발·스테이징 등 하위환경으로 유출되지 않았음을 확인 |

기존 전체 시험 명령은 `.venv\Scripts\python.exe -B -m scripts.test_offline`이다. PostgreSQL 시험 명령과 지원 서버·드라이버 버전은 구현 승인 후 정의한다. 패키지 설치나 DB 접속을 이번 검증에 포함하지 않는다.

## 15. AUTHOR_REVIEW_REQUIRED

| 승인 대상 | 검토할 구체 사항 |
|---|---|
| Supabase 프로젝트와 리전 | 서울 기본 리전 결정은 17절에서 확정. 실제 Supabase 조직명·프로젝트명, 자료 위치, 연결 방식, 지원 PostgreSQL·확장 버전은 별도 승인 |
| 실제 개발 프로젝트 생성 | 20절·21절은 준비 원칙만 승인하며 실제 Supabase 조직·서울 개발 프로젝트 생성은 미승인 |
| Supabase 조직 소유권과 관리자 | 개인 개발 소유는 21절의 임시 결정. 개인 계정에서 법인·기관 계정으로 운영 소유권 전환, 두 번째 관리자와 복구 담당자, 조직 소유권·결제권·복구권과 개인 단독 소유 제거 계획은 별도 승인 |
| MFA 적용 확인 | 21절의 MFA 의무에 대한 실제 적용 확인. 계정 식별정보·복구 코드는 문서에 기록하지 않음 |
| Pro 전환 시점과 결제 | 개발 Free·월 USD 0은 21절에서 확정. Pro 전환 시점, 결제수단 등록, 비용 발생과 유료 기능은 별도 승인 |
| 스테이징·운영 결제 정책 | 결제 주체·권한·비용 한도와 승인 절차 확정 |
| Auth0 tenant·application 실제 구성 | 비운영 tenant 공유 한계, 환경별 application·API·connection·redirect URI·secret 분리와 운영 tenant 분리 검증; 실제 tenant 생성과 요금제 선택은 미승인 |
| 스테이징 생성 시점 | 베타 전 생성 원칙 안에서 구체적 생성 시점과 실행 승인 |
| 운영 생성·배포 승인 | 정식 출시 전 별도 서울 프로젝트 생성과 운영 배포의 개별 승인 |
| CI 비밀정보 저장 방식 | 사람의 로컬 비밀정보와 분리한 저장·접근·갱신 방식 |
| 백업·PITR 요금제 | 백업·PITR 지원 범위와 요금제·비용 승인 |
| Auth0 운영 tenant | issuer/audience/client/scope와 운영 계정 분리 등 실제 운영 tenant 설정. 외부 신원→내부 account_id UUID 매핑 원칙은 11절·18절에서 확정했으나 운영 설정은 미승인 |
| 계정 병합·분리·탈퇴·복구 정책 | 계정 병합, 계정 분리, 계정 탈퇴 후 보유기간, 탈퇴 계정 복원, 추가 로그인 제공자 연결, 외부 신원 재연결, 관리자에 의한 계정 수정. 실제 신원 연결의 재인증과 별도 승인 흐름 |
| 실제 role 이름 최종 확정 | 11절·19절의 역할 책임 구분은 확정하되 실제 role 이름과 생성은 별도 승인 |
| 실제 GRANT·REVOKE | 승인 schema·table별 최소 권한과 금지 권한, 기본 역할 접근 차단의 실제 적용 |
| 각 테이블 RLS policy SQL | 11절·19절의 격리 원칙에 따른 테이블별 정책, ENABLE·FORCE 적용 대상, BYPASSRLS·소유자 우회와 누락·누출 차단 검증 |
| pooler 사용 여부 | 독점 연결 검증 후 도입 판단, transaction-local 문맥과 재사용 연결 누출 회귀 검증 |
| 백업·복원 역할 | jl_backup_operator 후보의 구체적 권한과 사용 시점, 일반 API 역할과 분리 |
| 운영 비밀정보 저장 위치 | migration·runtime 접속정보 분리, service_role 키를 포함한 운영 자격증명 저장·접근·감사 방식 |
| Supabase Data API 노출 schema 설정 | identity·migration·관리 schema 비노출과 업무 schema의 실제 노출 설정 |
| 백업 보유기간 | 암호화·접근자·복구 목표·복원 리허설·삭제 장벽 보존과 재적용 |
| 실제 데이터 이전 시점 | 시험 관문 완료, 쓰기 중지·컷오버·단일 원본 확인과 롤백 가능 시점 |
| 개인정보 동의와 삭제 정책 | 목적·policy_version·세대 권한, 보유기간, 영구 장벽의 최소 식별자·수명, Storage·색인·백업 삭제 반영 |
| Supabase 장애 시 운영 정책 | 가용성 목표, 쓰기 중지/재시도/결과 불명 대응, 복구·사용자 안내와 담당자 |
| 비용 한도와 사용량 경보 | 개발 월 USD 0 한도를 유지하며 DB·Storage·백업·트래픽·벡터 사용량과 사용량 경보 담당자·한도 초과 대응을 별도 승인 |
| DB 구조와 인증 경계의 적용 | 8절 schema·FK·제약·권한·공통/제품 transaction 계약과 기존 API 호환성 |

확정 기술 방향은 이 승인 항목을 대신하지 않는다. 위 항목을 승인할 수 있는 구체적 후속 초안과 합성자료 시험 근거를 마련한 후 구현·운영 적용 승인을 받는다.

## 16. 이번 문서 작업의 제외 범위

패키지 설치, requirements 수정, 코드 구현, DB 접속, migration 실행, 실제 사용자 데이터 처리, commit, push, merge, 배포는 수행하지 않는다. 코드·requirements·migration·테스트 파일과 MySQL 비교 기준을 변경하지 않는다.

문서 작성 후 검증은 UTF-8 재읽기와 한글 확인, Markdown 상대 링크가 있을 경우 존재 확인, `git diff --check`, `git status --short`로 한정한다. 테스트·pip check·실제 DB 시험은 이번 범위에서 NOT_RUN이며, 문서 검증 PASS는 구현이나 운영 전환 PASS가 아니다.

## 17. 리전 결정 승인 기록

- 승인일: **2026-11-12**.
- 승인 범위: **리전 결정만 승인**한다. 15절의 Supabase 프로젝트와 리전 검토 항목 중 기본 리전 결정에 한해 이 기록을 적용한다.
- Supabase 기본 리전: **Northeast Asia (Seoul)**. AWS 리전 코드는 **`ap-northeast-2`**이다.
- 개발·스테이징·운영 모두 서울 리전을 기본으로 사용한다. 일반 APAC 선택이 아닌 **specific Seoul region**을 선택한다.
- 실제 프로젝트 생성, 결제, 비밀정보 설정, DB 연결은 **미승인**이다. 이 기록은 해당 작업의 실행 승인이 아니다.
- 당시 미확정이던 초기 조직 소유권·개발 프로젝트 수·요금제는 21절의 후속 결정으로 구체화한다. 운영 소유권 전환과 실제 생성·결제 등 15절의 나머지 검토 항목과 구현·운영 적용 승인은 그대로 유지한다.

공식 참고 링크:

- [Supabase Docs — Available regions](https://supabase.com/docs/guides/platform/regions): 일반 리전과 특정 리전 선택 안내.
- [Supabase — Regions](https://supabase.com/regions): Northeast Asia (Seoul) 및 `ap-northeast-2` 표기.

## 18. Auth0와 내부 계정 연결 승인 기록 (두 번째 승인 결정)

- 승인일: **2026-11-12**.
- 결정: **Auth0 (issuer, subject) → 내부 account_id UUID**. 여기서 `subject`는 11절의 `provider_subject`이며 Auth0의 검증된 `sub`다.
- 범위: **신원 매핑과 제품 소유자 키**. 외부 신원은 `(issuer, provider_subject)`로 식별하고 제품 데이터는 내부 `accounts.account_id` UUID를 참조한다. 11절의 연결 원칙을 확정 결정으로 승인한다.
- 미승인: **병합·분리·탈퇴·복구·운영 tenant 설정**. 추가 로그인 제공자 연결, 계정 탈퇴 후 보유기간, 탈퇴 계정 복원, 외부 신원 재연결, 관리자에 의한 계정 수정도 **AUTHOR_REVIEW_REQUIRED**로 유지한다.
- 이 승인은 문서의 신원 매핑과 제품 소유자 키 결정에 한정한다. 코드·DB·migration·운영 설정의 실제 적용 승인은 포함하지 않는다.

## 19. DB 역할과 격리 원칙 승인 기록 (세 번째 승인 결정)

- 승인일: **2026-11-12**.
- 결정: **최소 권한 jl_api_runtime + FastAPI 권한 검사 + PostgreSQL RLS**.
- 범위: **일반 업무 요청의 DB 역할과 격리 원칙**. 11절의 역할 분리, RLS 추가 방어선, 문맥 누락 시 기본 거부와 transaction-local 요청 문맥 원칙을 확정한다.
- 미승인: **실제 role 생성, GRANT, RLS SQL, pooler, 백업 역할, 운영 비밀정보**. 실제 role 이름 최종 확정, GRANT·REVOKE, 각 테이블 RLS policy SQL, pooler 사용 여부, 백업·복원 역할, 운영 비밀정보 저장 위치, Supabase Data API 노출 schema 설정은 15절의 **AUTHOR_REVIEW_REQUIRED**로 유지한다.
- 이 승인은 설계 결정 기록에 한정한다. 실제 DB 접속·role 생성·RLS 실행이나 코드·migration·운영 설정의 적용 승인은 포함하지 않는다.

## 20. 환경 분리 승인 기록 (네 번째 승인 결정)

- 승인일: **2026-11-12**.
- 결정: **local-test + development부터 시작하고 staging과 production은 단계적으로 분리**한다.
- 범위: **환경 분리 원칙과 생성 시점**. 지금은 로컬 시험 PostgreSQL과 Supabase 서울 개발 프로젝트만 준비 대상으로 삼는다.
- 지금 승인되지 않은 것: **실제 Supabase 프로젝트 생성, 결제, Auth0 tenant 생성, 비밀정보 설정, DB 연결**. 이 기록은 환경 생성·설정·접속의 실행 승인이 아니다.

### 20.1. 환경별 역할과 데이터 격리

| 환경 | 구성·생성 시점 | 역할과 자료 제한 |
|---|---|---|
| `local-test` | Docker 또는 격리 PostgreSQL. 실제 Supabase 프로젝트가 아님 | migration, repository contract, 동시성, 장애, 백업·복원 시험. 합성자료만 사용하며 언제든 재생성 가능 |
| `development` | Supabase `ap-northeast-2` Seoul. 지금 생성 검토 대상 | FastAPI 원격 연결과 통합시험. 합성자료와 명시된 비민감 개발자료만 사용하며 실제 교인·일기·은혜·기도 원문 사용 금지. 21절의 개발 전용 Free·월 USD 0 원칙 적용 |
| `staging` | 베타 시험 전에 생성. development 및 production과 별도 Supabase 서울 프로젝트 | 운영과 같은 migration·역할·RLS·배포 절차 검증. 합성자료를 기본으로 사용하며 운영 DB dump 또는 백업 복원 금지 |
| `production` | 정식 출시 전에 생성하는 별도 Supabase 서울 프로젝트 | 실제 사용자 자료의 유일한 운영 원본. Dashboard에서 임의 schema 변경 금지. 승인된 version-controlled migration과 배포 절차만 사용 |

- 개발·스테이징·운영 프로젝트는 **DB, Storage, URL, 프로젝트 ID, 비밀번호, 역할 자격증명을 공유하지 않는다**.
- 운영 데이터와 운영 백업을 개발·스테이징 환경으로 복사하지 않는다. local-test를 포함한 하위환경 시험에 운영 자료를 사용하지 않는다.
- **모든 자동 시험은 합성자료를 사용한다**. development의 명시된 비민감 개발자료 허용은 실제 민감 원문 사용이나 자동 시험 자료 범위 확대를 뜻하지 않는다.

### 20.2. Auth0 환경 원칙

- 현재 PoC Auth0 설정은 비운영 개발 환경으로 취급한다.
- 운영 Auth0 tenant는 비운영 tenant와 분리한다.
- 비용 또는 요금제 제약으로 개발·스테이징 tenant를 바로 분리하지 못하면 비운영 tenant 안에서 application, API, connection, redirect URI, secret을 환경별로 분리한다.
- 비운영 tenant 공유에는 한계가 있다. 일부 Auth0 설정은 tenant 전체에 적용되므로 application 등을 나누어도 해당 설정의 변경 영향은 환경 간 공유된다. tenant 공유 시 해당 설정과 영향 범위를 후속 실제 구성 문서에 명시한다.
- 정식 출시 전에 운영 tenant 분리를 필수 검증한다.
- 실제 tenant 생성과 요금제 선택은 아직 미승인이다. tenant·application 실제 구성은 15절의 **AUTHOR_REVIEW_REQUIRED**로 유지한다.

### 20.3. 비밀정보 원칙

- 환경별 DSN, 비밀번호, Auth0 secret, Supabase 키를 공유하지 않는다.
- 비밀정보를 Git, 문서, 로그, Flutter 앱에 넣지 않는다.
- `.env.example`에는 변수 이름과 비밀이 아닌 예시만 둔다.
- CI 비밀정보와 사람의 로컬 비밀정보를 분리한다.
- 운영 비밀정보를 개발자 로컬 파일로 복사하지 않는다.

### 20.4. 배포와 승격 원칙

- migration은 **로컬 시험 → 개발 → 스테이징 → 운영** 순서로 승격한다.
- 같은 migration 파일을 환경별로 수정하지 않는다. 적용된 migration의 불변 원칙과 순방향 추가 원칙은 10절을 따른다.
- 이전 환경 관문이 실패하면 다음 환경에 적용하지 않는다. 14절의 환경별 검증 관문을 적용한다.
- production에 `supabase db reset` 같은 파괴적 초기화를 사용하지 않는다.
- 개발환경 초기화 명령도 연결된 프로젝트를 확인하고 명시적으로 승인한 경우에만 실행한다.
- 지금의 단계적 준비 결정은 스테이징·운영 관문을 생략하거나 개발환경을 운영 원본으로 사용하는 승인이 아니다.

### 20.5. 공식 참고 링크

아래는 환경·배포 설계 참고 자료다. 이 프로젝트의 확정 범위와 미승인 실행 경계는 위 승인 기록을 따른다.

- [Supabase Docs — Deployment](https://supabase.com/docs/guides/deployment)
- [Supabase Docs — Managing environments](https://supabase.com/docs/guides/deployment/managing-environments)
- [Supabase Docs — Maturity model](https://supabase.com/docs/guides/deployment/maturity-model)
- [Auth0 Docs — Set Up Multiple Environments](https://auth0.com/docs/get-started/auth0-overview/create-tenants/set-up-multiple-environments)

## 21. Supabase 초기 소유권·요금제·비용 승인 기록 (다섯 번째 승인 결정)

### 21.1. 승인 기록과 확정 범위

- 승인일: **2026-11-12**.
- 결정: **개인 계정으로 개발 전용 Supabase 조직 시작**. 개인 소유는 개발 단계의 임시 구조다. 이 조직과 프로젝트는 개발 전용이며 실제 운영 원본을 소유하지 않는다.
- 요금제: **Free**.
- 개발 단계 월 비용 한도: **USD 0**.
- 데이터 범위: **합성자료와 명시된 비민감 개발자료**만 허용한다.
- 미승인: **실제 프로젝트 생성, 결제수단 등록, Pro 전환, 유료 기능, 실제 개인정보 저장, 스테이징·운영 소유권**. 실제 조직 생성도 실행 승인에 포함하지 않는다.
- 이 기록은 초기 소유권·요금제·비용 정책의 문서 결정이다. Supabase 가입·조직 및 프로젝트 생성·비밀정보 설정·DB 접속의 실행 승인이 아니다.

### 21.2. 개인 소유 보호 원칙

- Supabase 계정에 MFA를 적용한다. 실제 적용 확인은 15절의 AUTHOR_REVIEW_REQUIRED로 유지한다.
- 복구 코드는 오프라인의 안전한 장소에 보관한다.
- 비밀번호와 복구 코드를 Git, 문서, 채팅 로그, `.env.example`에 기록하지 않는다.
- 개인 이메일 주소와 계정 식별정보를 저장소 문서에 기록하지 않는다.
- 프로젝트 비밀번호와 API 키는 환경별 비밀정보 저장소에만 둔다.
- Flutter 앱에 database password, `service_role`, Supabase 관리 키를 넣지 않는다.

### 21.3. Free 사용과 비용 통제 원칙

- 서울 개발 프로젝트 **한 개만 우선 사용**하고 Free 계정의 나머지 프로젝트 자리는 예비로 남긴다. 이는 실제 프로젝트 생성 승인이 아니다.
- Free 프로젝트에는 합성자료와 명시된 비민감 개발자료만 사용한다. **실제 교인 정보, 생명일기 원문, 은혜 기록, 기도 제목, 음성, 서명, 운영 토큰을 저장하지 않는다**.
- 프로젝트 일시정지, DB 크기, Storage, 트래픽과 연결 제한을 개발 제약으로 인정한다. Free 플랜의 백업과 가용성을 운영 수준으로 간주하지 않는다.
- 유료 요금제, 유료 Compute, PITR, Branching, 유료 백업, 유료 add-on을 자동 활성화하지 않는다.
- 한도에 가까워져도 자동으로 Pro로 전환하지 않는다.
- **비용 발생 또는 결제수단 등록 전에 사람의 별도 승인**을 요구한다.
- 월 비용 예상이 **USD 0을 넘기 전에 사용량·필요성·대안·예상 월 비용을 다시 검토**한다. 검토 자체가 유료 전환 승인은 아니다.

### 21.4. 스테이징 전 필수 관문

20절의 환경 분리와 14절의 검증에 더해, 스테이징으로 진행하기 전에 아래 관문을 모두 충족한다.

- 법인 또는 기관 업무 계정을 소유자 또는 공동 관리자로 추가한다.
- 두 번째 복구 관리자를 지정한다.
- 조직 소유권·결제권·복구권을 문서화한다. 개인 이메일·계정 식별정보·비밀정보는 저장소 문서에 넣지 않는다.
- 개인 단독 소유 제거 계획을 승인받는다.
- 스테이징·운영의 별도 프로젝트와 환경별 비밀정보를 확정한다.
- Auth0 운영 tenant 소유권을 확정한다.

개인 계정에서 법인·기관 계정으로 운영 소유권을 전환하는 구체적 절차와 스테이징·운영 결제 정책은 15절의 별도 승인 대상이다.

### 21.5. 운영 전 금지 사항

- 개인 개발 프로젝트를 이름만 바꾸어 운영 DB로 사용하지 않는다.
- 개발 DB에 운영 데이터를 넣지 않는다.
- 운영 백업을 개인 개발 프로젝트에 복원하지 않는다.
- 개인 계정만으로 운영 장애·탈퇴·결제를 처리하지 않는다.

이 금지는 운영 준비 과정에도 적용한다. 실제 운영 자료 수집·이전과 운영 소유권 확정은 기존 관문과 별도 사람의 승인 없이 진행하지 않는다.
