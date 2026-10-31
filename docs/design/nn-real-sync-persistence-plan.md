# 실제 동기화 합성 후보의 MySQL 영속화 계획

2026-10-31. **PROPOSED / AUTHOR_REVIEW_REQUIRED**. 실제 자료 수집은 **BLOCKED**다. 이 파일은 구현 가능한 후보 설계이며 DB 구조·권한·인증 변경, migration 실행, 실제 수집·배포를 승인하지 않는다. 이번 변경은 이 문서 한 파일뿐이다.

## 1. 기준과 현재 구현

시작 상태: 루트 `D:/CHGO-VibeCodeing/JesusLife-One-API`, 브랜치 `docs/nn-real-sync-persistence`, HEAD `527d3d0` (PR #12 merge), clean. 요청된 파일은 없었다. [AGENTS](../../AGENTS.md), `jesuslife-platform-development` 공통 보호·제품 경계·품질 게이트와 `jesuslife-platform-design` 절차를 적용했다. AGENTS의 초기 골격 설명보다 현재 소스가 진행되어 있으므로 아래 정적 소스를 기준으로 한다.

| 근거 | 현재 구현과 목표의 차이 |
|---|---|
| [후보](../../app/modules/neorang_narang/real_sync_candidate.py)의 `RealSyncCandidateService`, `SyntheticMemoryStore._apply/_retire/_open/_close` | 생성/재생·단건 장벽·open·retired-through·close 최소화 구현. 복사 준비 후 상태 참조 한 번 교체는 단일 instance 순차 호출의 메모리 원자성뿐이다. 재진입 시계·동시 worker·내구성·재시작 복구는 지원하지 않는다. 목표는 동일 불변식을 제품 소유 InnoDB commit으로 옮기는 것이다 |
| 같은 파일의 `_Record/_Receipt/_ErasedReceipt`, `_generation` | 활성 명령 JSON이 record와 receipt에 중복된다. erased는 owner/operation 키와 상태만 남긴다. 세대는 서비스에서 양수이나 상한은 없다. 목표는 활성 비교값 단일 저장과 영속 최소 장벽이다 |
| [DTO](../../app/modules/neorang_narang/real_sync_schemas.py)의 `RealCompletionCreate/RealCompletionMetadata/RealCompletionAck` | allowlist·strict 숫자·날짜·UTC ACK 형태 검증. generation DTO는 음수도 형태상 허용, policy는 nonempty만 검사한다. 인증·정책 지원·선택 자격 증거가 아니다. 후보 서비스는 우회 생성 DTO를 재검증한다 |
| [후보 테스트](../../tests/test_nn_real_sync_candidate.py)의 `RealSyncCandidateTests`, [DTO 테스트](../../tests/test_nn_real_sync_dto.py)의 `RealSyncDtoTests/RealSyncAckDtoTests` | 순차 메모리·형태·실패 준비 검증 소스다. `test_current_revision_is_read_from_record_not_receipt`, `test_close_preparation_failure_preserves_single_state_reference_then_retries`는 재사용할 계약이다. 실행 결과를 MySQL 증거로 확대하지 않는다 |
| [기존 adapter](../../app/modules/neorang_narang/mysql_store.py)의 `MySQLCompletionStore.transaction` | 연결 주입·READ COMMITTED·owner 행 upsert 후 FOR UPDATE 패턴 참고. 기존 v1 CRUD용이며 real receipt/gate는 없다. thread-local·HTTP 예외 결합과 finally rollback 처리를 새 repository에 그대로 복사하지 않는다 |
| [Core 합성](../../app/core/mobile_store.py)의 `MobileCoreStore.mobile_status`, [제품 합성](../../app/modules/neorang_narang/mobile_store.py)의 `MobileProjectionStore.create/erase` | Core 동의 행 잠금과 공유 cursor로 cross-schema 제품 쓰기를 수행하는 PoC다. 세대당 한 건·JSON NULL 삭제 구조를 목표 운영 구조로 복제하지 않는다 |
| [구현 계약](nn-sync-implementation-contract.md) 4·6·8절 이후, [원 제안](nn-real-completion-sync-proposal.md) 13.3~13.5절 | 실제 API·현재 권한·Core ticket·inbox/outbox·A/F/D·사본 inventory는 별도 미완성이다. 후보는 Core/API/router/설정/운영 factory와 미연결이며 이 설계도 연결하지 않는다 |

이전 서비스·DTO **48 PASS**, offline **160 PASS·22 SKIP**은 최신 사용자 보고 및 계약의 과거 실행 기록이다. 이번 재실행 결과가 아니다. 현재 조사에서는 앱·설정 로더 import, 테스트·서버·모델 실행, 네트워크·DB·Docker·패키지 설치를 하지 않았다. `.env`·비밀·실제 DB·기기·백업·다른 저장소를 읽지 않았다.

## 2. 불변식과 소유권

기기 원본·COUNT를 바꾸지 않고 선택된 최소 projection만 다룬다. owner는 검증 경계가 제공한 **Core 공개 계정 UUID**이며 요청 본문·교회 ID·외부 IdP subject에서 추론하지 않는다. [Core 계약](../architecture/platform-auth-contract-draft.md) 2절과 [제품 정책](../architecture/nn-auth-ownership-sync-policy.md) 2·12~16절의 경계를 유지한다. 제품 테이블은 `neorang_narang` 소유, Core와 cross-schema FK/JOIN/cascade 및 제품 계정의 Core DB 접근을 금지한다. 제품 owner gate는 계정 명부가 아니다.

1. 모든 쓰기는 해당 owner gate를 먼저 잠근다. 같은 owner는 모든 연결/worker에서 직렬화되고 다른 owner는 독립적이다.
2. erased operation, sync 장벽, retired-through 이하 세대는 내용 비교·과거 성공 ACK보다 먼저 거부한다. 해당 owner의 현재 열린 세대에서만 생성·재생한다.
3. 동일 활성 operation의 정규화된 모든 명령 필드가 같을 때만 재생한다. 날짜·과정이 같은 별개 ID를 합치지 않는다. 다른 operation의 기존 sync는 현 후보처럼 unsupported다.
4. record·receipt·장벽·세대 경계는 하나의 제품 transaction으로 바뀐다. 실패 시 부분 생성·부분 삭제·부분 close가 보이면 안 된다.
5. retire는 존재하지 않는 sync에도 장벽을 남긴다. open/재동의는 장벽·erased 키를 제거하지 않는다. close의 high-water는 감소하지 않고 더 높은 열린 세대/record는 보존한다.
6. commit 확인 전 성공을 반환하지 않는다. commit 뒤 다른 transaction의 retire가 가능하므로 ACK는 영구 활성 보증이 아니다. 클라이언트의 늦은 ACK/epoch 검사는 계속 필요하다.

## 3. 테이블 후보와 데이터 사전

다음은 **새 후보 선택**이다. 기존 승인 제약으로 간주하지 않는다. 이름 접두사 `nn_real_`, InnoDB, 제품 내부 FK도 우선 생략한다. 애플리케이션 불변식 검사와 동일 transaction이 참조 무결성을 책임지며 불일치 시 fail-closed한다. 서버의 CHECK 강제·SQL mode·정확한 버전은 격리 MySQL에서 확인해야 한다.

공통: 아래 `owner`, `sync_id`, `operation_id`는 `BINARY(16)`이다. Python UUID의 network-order `bytes`를 그대로 저장하고 byte swap을 쓰지 않는다. wire는 lowercase hyphenated UUID이며 버전 제한은 추가하지 않는다. UUID 대소문자/입력 표현 차이는 DTO 정규화 후 동일하다. 모든 PK 컬럼 NOT NULL, NULL은 표에서 명시한 컬럼에만 허용한다. ID는 owner와 함께 unique여서 다른 계정의 같은 ID를 허용한다.

| 테이블 | 컬럼·nullability·제약 | PK/unique/index 및 의미 |
|---|---|---|
| `nn_real_gates` | `owner BINARY(16) NOT NULL`; `open_generation BIGINT NULL`; `retired_through BIGINT NOT NULL DEFAULT 0`. CHECK retired 0..M, open NULL 또는 1..M 및 open > retired | PK(owner). 별도 상태/시각/동의 payload 없음. NULL=open 없음, high-water는 제품 폐기 경계 |
| `nn_real_records` | `owner`, `sync_id` NOT NULL; `generation BIGINT NOT NULL` 1..M; `policy_version VARBINARY(256) NOT NULL` 길이 1..256 bytes; `course_number TINYINT NOT NULL` IN(1,2); `completed_on CHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL`; `revision BIGINT NOT NULL` 1..M | PK(owner,sync_id); INDEX(owner,generation,sync_id). 활성 record만 존재. 생성 revision=1, 일반 수정은 지원하지 않음 |
| `nn_real_receipts` | `owner`, `operation_id` NOT NULL; `state TINYINT NOT NULL` IN(0,1), 0=active/1=erased. `sync_id BINARY(16) NULL`; `applied_revision BIGINT NULL`; `received_at_utc DATETIME(6) NULL` | PK(owner,operation_id); INDEX(owner,state,sync_id,operation_id). active는 나머지 세 컬럼 모두 NOT NULL이고 applied 1..M. erased는 세 컬럼 모두 NULL인 CHECK. sync는 UNIQUE로 제한하지 않음: 한 sync의 모든 활성 receipt를 최소화 가능 |
| `nn_real_sync_barriers` | `owner`, `sync_id` NOT NULL, 다른 컬럼 없음 | PK(owner,sync_id). 시각·generation·operation 연결 없이 단건 영구 거부 증거만 보유 |
| `nn_real_schema_version` | `version INT NOT NULL`, `applied_at_utc DATETIME(6) NOT NULL` | PK(version). 별도 real schema marker 후보 1. 기존 v1/mobile version marker를 변경하지 않음 |

`M=9223372036854775807` (signed BIGINT 최대)을 세대·revision 상한 후보로 택한다. bool·float·문자열 숫자는 거부하고 overflow는 저장 전에 고정 오류로 거부한다. 세대/버전을 wrap·초기화하지 않는다. DTO의 무상한 정수와 다르므로 persistence 경계 검사 및 후속 계약 테스트가 필요하다. Core 발급 세대와의 범위 합의 전 실제 연결은 금지한다.

`policy_version`은 UTF-8 strict 인코딩 원래 bytes를 저장하고 binary 정확 비교한다. 대소문자·공백·후행 공백·Unicode 정규화를 하지 않는다. 256 bytes는 후보 상한이며 기존 DTO에 없는 제한이다. 지원 정책 검사는 이 저장 제약과 별개이고 미구현이다. 비어 있지 않은 공백 문자열의 기존 합성 의미는 보존하되 운영 허용목록은 Core 계약으로 확정해야 한다. truncation/대체 문자 인코딩을 금지한다.

`completed_on`은 DTO가 허용하는 0001-01-01..9999-12-31 전체를 보존하기 위해 DATE 대신 ASCII CHAR(10)을 택한다. MySQL 날짜형의 하한과 DTO의 차이를 무음 축소하지 않는다. ASCII `YYYY-MM-DD` 길이·형태 CHECK와 Python calendar 검증을 함께 적용한다. 공백 padding 입력·zero date·잘못된 윤일은 저장 전에 거부한다. wire는 동일 10자이며 시간대 변환을 하지 않는다. SQL CHECK만으로 달력 유효성을 증명하지 않는다.

receipt 시각은 서버 생성 UTC이고 MySQL DATETIME(6)의 지원 범위 1000-01-01..9999-12-31 안에서만 허용한다. UTC aware 값을 UTC naive로 명시 변환해 저장하고 읽을 때 UTC로 해석한다. session timezone에 의존하는 변환을 피한다. 최초 서버 ACK는 항상 `YYYY-MM-DDTHH:MM:SS.ffffffZ` 6자리로 구성하고 재생도 동일하게 구성한다. DB default 시각/ON UPDATE 시각은 사용하지 않는다. DTO가 보존하는 0001년·가변 소수 자릿수와는 다른 **서버 발급 시각 후보 프로파일**이다. 합성 clock의 범위 밖 값은 commit 전 고정 오류이며 자릿수 원문까지 보존할 필요가 생기면 별도 계약 검토한다. `applied_at_utc`도 같은 저장 규칙이다.

## 4. 활성 비교와 erased 최소화

활성 operation 비교값은 `(operation_id, generation, policy_version, base_revision=0, sync_id, course_number, completed_on)`이다. owner는 인증 context와 PK로 결합한다. operation은 receipt PK, sync는 receipt 연결, generation/policy/course/date는 record에 **한 번만** 저장한다. base=0은 이 create-only schema의 불변식으로 비교하고 컬럼/JSON으로 복제하지 않는다. applied_revision·첫 received_at만 receipt에 보유한다. ACK current_revision은 record에서 읽는다. 원명령 JSON·metadata JSON·ACK body·hash·중복 generation을 receipt에 저장하지 않는다.

활성 receipt가 있는데 record가 없거나 장벽과 활성 record가 공존하면 저장소 불일치다. 성공 재생·자동 복구 대신 차단한다. 정상 create-only 경로는 한 record에 한 operation이지만 retire/close는 매칭하는 **모든** 활성 receipt를 정리한다. 미래 update/다른 operation 종류는 이 비교 의미를 재설계해야 하며 지금 지원하지 않는다.

erased 전환은 sync/applied_revision/received_at을 NULL로 만들고 record를 제거한다. 남는 것은 `(owner,operation_id,state=erased)`뿐이다. payload·시각·sync/generation/policy 연결·revision·성공 body를 남기거나 hash로 대체하지 않는다. 별도 sync 장벽에는 `(owner,sync_id)`만 남는다. 계정 연결과 활동 존재 자체는 잔존 개인정보다. 이 최소화는 InnoDB undo/redo/binlog·backup·호출자 ACK·로그의 물리적 즉시 제거를 뜻하지 않는다. 보유기간·장벽 압축·backup 수명은 미정이며 임의 운영 기본값/TTL/청소 작업을 만들지 않는다.

## 5. 제품 transaction과 잠금

다음은 parameter binding을 전제로 한 **SQL 의사코드**이며 실행 migration/스크립트가 아니다. 명령별 독립 제품 연결을 주입한다. Core cursor를 인자로 받지 않는다. transaction 중 네트워크 권한 조회를 하지 않는다. 적법한 내부 context 검증과 DTO 재검증을 먼저 하고 실제 Core 결합은 7절 공백으로 남긴다.

### 5.1 모든 쓰기의 공통 시작/종료

```sql
-- 연결/세션 준비, 지원 schema 확인; 아래 전체는 한 제품 연결
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
BEGIN;
INSERT INTO nn_real_gates(owner,open_generation,retired_through)
 VALUES (:owner,NULL,0) ON DUPLICATE KEY UPDATE owner=owner;
SELECT open_generation,retired_through FROM nn_real_gates
 WHERE owner=:owner FOR UPDATE;
-- 해당 명령 본문
COMMIT;
-- COMMIT 성공이 반환된 뒤에만 준비된 결과를 외부에 반환
```

최초 gate 행이 없을 때 두 연결의 upsert는 PK unique 잠금으로 경합한다. 패자는 선행 commit/rollback을 기다린 뒤 gate를 다시 읽는다. 부재 행의 SELECT FOR UPDATE나 gap lock만으로 안전하다고 가정하지 않는다. gate 없음은 초기 CLOSED이며 open 없이 create를 허용하지 않는다. 성공한 retire/close만 호출돼도 gate를 생성해 장벽을 내구 저장한다.

고정 순서는 **owner gate → receipts(operation_id binary 오름차순) → records(sync_id binary 오름차순) → barriers(sync_id binary 오름차순)**다. 필요한 각 집합을 해당 순서로 잠그고 검사한 후 mutation한다. retire/close의 sync 후보 수집은 gate 아래에서 수행하고 receipt/record 잠금 순서를 지킨다. 아래 선택문은 이 순서를 축약해 표시한다. 한 transaction은 한 owner만 처리한다. 유지보수·삭제·복원 조정·향후 batch도 gate 사용이 필수다. DB 권한만으로 잠금 준수를 강제할 수 없으므로 직접 SQL writer를 허용하지 않고 코드 리뷰와 다중 연결 테스트로 확인한다.

같은 owner의 없던 operation/sync 동시 생성은 gate로 직렬화되고 PK가 마지막 방어선이다. gate 이후 조회에서 다른 operation의 동일 sync는 unsupported, 같은 operation의 다른 명령은 conflict다. 예상 못한 duplicate key는 무조건 성공 처리하거나 INSERT IGNORE로 삼키지 않는다. 전체 rollback 뒤 같은 명령 재조회로 분류한다. 다른 owner의 같은 ID는 충돌하지 않는다.

### 5.2 create / replay

```sql
-- 공통 시작, gate 획득
SELECT * FROM nn_real_receipts WHERE owner=:o AND operation_id=:op FOR UPDATE;
-- 활성 receipt의 연결 sync와 요청 sync에 필요한 records를 정렬하여 잠금
SELECT * FROM nn_real_records WHERE owner=:o AND sync_id IN (:needed_ids)
 ORDER BY sync_id FOR UPDATE;
SELECT sync_id FROM nn_real_sync_barriers WHERE owner=:o AND sync_id=:s FOR UPDATE;
-- erased operation OR 요청 sync 장벽 OR g<=retired_through => operation_retired
-- open_generation != g => generation_not_open
-- 활성 receipt: 연결 record와 정규화 명령 전체 비교
--   다르면 idempotency_key_reused; 같으면 기존 시각/applied + record.current로 ACK 준비
-- receipt 없음 + record 있음 => unsupported_candidate_path
-- 신규 경로만 서버 시계/ACK 구성과 validation을 commit 전에 수행
INSERT INTO nn_real_records VALUES (:o,:s,:g,:policy,:course,:day,1);
INSERT INTO nn_real_receipts VALUES (:o,:op,0,:s,1,:first_utc);
-- 신규/재생 중 선택한 경로만 실행, 공통 COMMIT; 그 뒤 ACK
```

폐기/세대 판정 전에 metadata 동등성 검사·성공 ACK 구성을 하지 않는다. DTO 형태 검증은 그보다 앞서 가능하지만 validation 입력·SQL 예외 원문을 노출하지 않는다. 재생에서 시계를 다시 호출하지 않는다. read-only 재생도 gate를 거쳐 retire/close와 직렬화한다. 일반 GET/관리 조회는 이번 구현 범위 밖이며 향후 활성 owner 필터·장벽과 권한 검사를 따라야 한다.

### 5.3 retire(owner,sync_id)

```sql
-- 공통 시작; gate; 이 sync의 활성 receipts 정렬 잠금; record; barrier 순서
SELECT sync_id FROM nn_real_sync_barriers WHERE owner=:o AND sync_id=:s FOR UPDATE;
-- 위 조회 결과가 없을 때만 다음 INSERT 실행; 기존 장벽은 수정하지 않음
INSERT INTO nn_real_sync_barriers(owner,sync_id) VALUES (:o,:s);
UPDATE nn_real_receipts SET state=1,sync_id=NULL,applied_revision=NULL,received_at_utc=NULL
 WHERE owner=:o AND state=0 AND sync_id=:s;
DELETE FROM nn_real_records WHERE owner=:o AND sync_id=:s;
-- 공통 COMMIT; 내부 완료만, HTTP 삭제 ACK/revision 의미를 추가하지 않음
```

부재 sync도 같은 경로이고 중복 retire는 멱등이다. 폐기한 operation을 새 sync/세대로 재사용해도 erased가 우선 거부한다. 아직 기록된 적 없는 다른 operation은 sync 장벽으로 막는다. retire는 현재 후보처럼 합성 내부 전이이며 실제 본인 관리 권한·delete operation/base 계약을 대신하지 않는다.

### 5.4 open(owner,g)

```sql
-- 공통 시작; 1<=g<=M 검증
-- g<=retired_through => operation_retired
-- open_generation=g => no-op
-- 다른 non-NULL open_generation => unsupported_candidate_path (자동 교체 금지)
UPDATE nn_real_gates SET open_generation=:g WHERE owner=:o;
-- NULL인 경우에만 위 UPDATE, 공통 COMMIT
```

### 5.5 close(owner,g)

우선 **단일 transaction** 후보로 한다. gate를 보유한 채 다음 전체를 commit한다.

```sql
-- 공통 시작; b=max(g,retired_through), g는 1..M
-- owner의 generation<=b records 집합 T 수집
-- T에 연결된 active receipts 정렬 잠금, T records 정렬 잠금, T barriers 정렬 잠금
-- 고아 active receipt는 integrity failure로 rollback, 자동 초기화 금지
INSERT INTO nn_real_sync_barriers(owner,sync_id)
 SELECT r.owner,r.sync_id FROM nn_real_records r
 WHERE r.owner=:o AND r.generation<=:b
 AND NOT EXISTS (
  SELECT 1 FROM nn_real_sync_barriers x
  WHERE x.owner=r.owner AND x.sync_id=r.sync_id
 );
-- 기존 장벽을 제외한 대상만 INSERT; 기존 장벽은 수정하지 않음
UPDATE nn_real_receipts p JOIN nn_real_records r
 ON p.owner=r.owner AND p.sync_id=r.sync_id
 SET p.state=1,p.sync_id=NULL,p.applied_revision=NULL,p.received_at_utc=NULL
 WHERE r.owner=:o AND r.generation<=:b AND p.state=0;
DELETE FROM nn_real_records WHERE owner=:o AND generation<=:b;
UPDATE nn_real_gates SET retired_through=:b,
 open_generation=CASE WHEN open_generation<=:b THEN NULL ELSE open_generation END
 WHERE owner=:o;
-- 공통 COMMIT; 내부 close 완료만
```

JOIN은 제품 내부 테이블에만 사용한다. 실제 SQL은 수집한 잠금 집합과 execution plan을 검증해야 한다. g보다 낮은 close가 늦게 와도 high-water는 줄지 않고 더 큰 열린 세대는 보존한다. close가 open보다 먼저 도착하면 g 이하를 영구 차단한다. 중복 close는 같은 경계를 유지하며 기존 erased/단건 장벽은 지우지 않는다. gate를 먼저 얻은 create는 완료 후 close 삭제 집합에 포함되고 close가 먼저 commit하면 옛 create/replay는 거부된다.

대량 close는 계정 단위 장시간 잠금, undo/redo·replication 부하·packet/메모리·timeout 한계가 있다. 예상 최대량/처리시간은 아직 측정하지 않았다. 후보 목록을 무제한 앱 메모리로 복사하지 않고 정렬된 조회/서버 SQL을 사용하도록 구현한다. 한계를 넘으면 성공을 추정하지 않고 차단/보류한다. chunk commit으로 바꾸려면 CLOSED fence 선행 commit, durable phase/cursor, drain, 재시작 재개, 마지막 sweep·ACK의 **별도 phase/drain 계약**이 필요하다. 현재 단일 commit 의미를 유지한 척 chunking하지 않는다. 이것은 Core의 Close/Drain/Delete 프로토콜 전체 구현이 아니다.

## 6. 실패·재시도·복구

| 상황 | 처리 및 성공 경계 |
|---|---|
| ACK 구성/시계·각 INSERT/UPDATE/DELETE·commit 전 실패 | 전체 rollback. gate 최초 삽입도 함께 취소될 수 있다. 부분 mutation을 성공으로 노출하지 않는다. 고정 storage/preparation 오류만 반환 |
| rollback 실패·연결 손상 | 연결을 pool로 반환하지 않고 폐기한다. rollback 실패는 성공 근거가 아니다. 성공 ACK 금지, 불명 상태로 같은 명령 조정 |
| commit 요청 전송 후 응답 유실 | 결과 불명. 새 연결의 같은 owner gate를 얻어 같은 command를 재시도한다. 활성 receipt이면 재생, 폐기 상태면 retired, commit 안 됐으면 동일 ID로 최초 생성. 새 UUID/시각 덮어쓰기 금지 |
| deadlock / lock timeout | DB 오류 분류 후 명시적 전체 rollback. timeout의 statement rollback만 믿지 않는다. 연결 정상/rollback 확인 시에만 제한된 동일 명령 재시도. 횟수·backoff는 구현에서 명시하고 무한 재시도하지 않는다. commit 불명과 구분 |
| 중복/역순 open·close | 5절 그대로. 낮은 close가 높은 open을 취소하지 않고 같은 open은 no-op, 이미 폐기된 open은 거부. 불명 응답도 같은 owner/g 명령으로 조정 |
| 애플리케이션 재시작 | 연결을 새로 만들고 schema·불변식 확인 후 영속 gate/receipt/장벽을 사용한다. dict 복원·gate 자동 OPEN·메모리 fallback 없음. 진행 중 transaction은 DB 복구 결과를 읽고 같은 명령 조정 |
| DB 재시작/프로세스 강제 종료 | InnoDB crash recovery·durability 설정·commit 전후 행 집합을 실제 합성 MySQL로 증명해야 한다. 서버 설정 미확인/DB unavailable이면 차단. 메모리/SQLite 성공으로 대체 불가 |
| 인증/동의/정책/관리 권한 상태 불명 | 신규 create·과거 ACK 재노출 금지. 실제 관리 권한이 없는 상태에서 retire/open/close 호출도 금지. 기존 upload 동의를 삭제 관리의 전제로 요구하지 않되 검증된 본인 관리 권한 필요 |
| 장벽/receipt/gate 손상·유실 | fail-closed와 운영 조정. 삭제 장벽을 무시한 구형 저장소 fallback·자동 초기화·새 UUID 발급·과거 queue 재귀속 금지 |

**서버 재시작과 과거 backup 복원은 다르다.** 정상 재시작은 최신 영속 원장을 읽지만 과거 snapshot은 삭제 전 metadata와 낮은 fence를 되살릴 수 있다. 복원은 격리 환경에서만 하고 최신 신뢰 가능한 제품 장벽/erased operation/high-water와 Core 철회 원장을 먼저 조정한 뒤 payload 제거·권한·inventory를 검증한다. erased 키를 높은 세대의 새 sync에 재사용하는 경우도 막아야 하므로 high-water만 복구하면 충분하지 않다. 최신 원장의 별도 보존·checkpoint·복원 순서는 운영 책임자가 승인해야 할 미해결 항목이다. 최신 장벽 완전성을 입증할 수 없으면 서비스/수집은 **BLOCKED**다. backup과 현재 값의 단순 동일 비교는 부활 방지 증거가 아니다.

## 7. Core 경계와 남은 공백

제품 gate 영속화는 Core 동의·ticket·A/F/D를 완성하지 않는다. 현 `SyntheticAccountContext`는 인증 결과가 아니며 generation/policy 입력은 권한을 부여하지 않는다. 현재 인증 검사 후 독립 제품 commit 사이에는 세션/계정/동의 철회가 끼어들 수 있다. 사전 조회·ticket TTL·비동기 이벤트만으로 이 공백을 닫았다고 주장하지 않는다.

원 제안 13.3의 Core admission과 A(철회 접수), 제품 F(모든 writer 차단/drain), D(live inventory 삭제 확인)는 별도 내구 상태·명령이다. 다음 repository는 제품 내부 전이만 담당한다. 실제 연결에는 Core 발급 ticket의 owner/purpose/g/operation/명령 binding, 제품의 같은 commit 내 소비/무효화, Core inbox/outbox와 제품 inbox/outbox의 멱등 전달·역순 처리, 분산 철회·관리 권한·로그아웃 후 재생 거부가 필요하다. 이 스키마에는 ticket/inbox/outbox가 없으며 그 ACK도 발행하지 않는다. close 완료를 `ClosedAndDrained`나 `ProductDeleted`로 번역하지 않는다. 캐시·replica·메시지·로그·기기·backup 사본 제거도 별도다.

## 8. migration·최소 권한·중단 준비

참고 소스는 [001](../../migrations/neorang_narang/001_initial.sql), [합성 002](../../migrations/neorang_narang/002_mobile_synthetic.sql), [기존 runner](../../scripts/mobile_mysql.py)의 `apply/validate_existing`, [backup 도구](../../scripts/mobile_backup.py)의 `capture/restore/compare`, [기존 검증](../../scripts/verify_mysql.py)의 `migration_retry`다. 이번에는 어느 도구도 실행/수정하지 않고 migration 파일도 만들지 않는다. 002의 Core 제품 테이블 권한을 새 real 테이블로 확대하지 않는다.

1. 후속 후보 `migrations/neorang_narang/003_real_sync.sql`은 additive 새 테이블만 정의한다. 기존 migration/자료/marker를 수정하지 않는다. 새 설치와 v1+mobile 설치에서 모두 real marker 1을 독립 관리한다. 메모리 dict와 기존 v1/mobile 자료는 자동 이전하지 않는다. 메모리는 신뢰할 수 있는 내구 원장이 아니므로 과거 ACK가 있으면 폐기/조정 문제를 별도 처리한다.
2. 실행 전 대상 식별·schema shape·버전·최소 권한·CHECK/SQL mode·InnoDB/durability 지원 확인, writer 중단, 보호된 전체 backup과 격리 복원 리허설 승인을 요구한다. backup은 접근 제한·저장소 외부에 보관하며 비밀/원문을 로그에 출력하지 않는다. 기간·담당자·암호화/키 관리·폐기 기준은 미정이다.
3. DDL은 implicit commit될 수 있으므로 전체 transactional rollback을 약속하지 않는다. 전용 migration lock 아래 expected shape와 기존 shape를 비교하고 없는 새 테이블만 생성한다. 중간 실패는 부분 테이블/backup을 보존하고 쓰기를 차단한다. 재실행은 모든 기존 신규 테이블의 정확한 shape·제약·index를 검증한 뒤 누락 단계만 수행한다. 다른 shape/모르는 marker는 중단하며 DROP/재생성하지 않는다.
4. marker는 모든 테이블 검증 후 기록한다. marker만으로 runtime ready를 판단하지 않고 권한·schema 검사도 요구한다. DDL 완료/marker 기록/GRANT 중 실패를 각각 재현한다. 기존 v1 adapter가 요구하는 `nn_schema_version=[1]`은 그대로 둔다.
5. 전용 제품 runtime 역할 후보: gates SELECT/INSERT/UPDATE, records SELECT/INSERT/DELETE, receipts SELECT/INSERT/UPDATE, barriers SELECT/INSERT, real version SELECT. 일반 수정이 필요해질 때 records UPDATE는 재검토한다. DDL/GRANT/DROP·Core 권한·장벽 DELETE/UPDATE 권한 없음. migration/backup 관리자는 runtime과 분리한다. gate 준수는 권한만으로 강제되지 않는다.
6. rollback/중단은 신규 기능 비활성·writer 정지·상태 보존이다. 이전 앱은 새 저장소를 우회하여 같은 실제 명령을 처리하면 안 된다. 신규 테이블/장벽을 유지하고 승인된 forward repair 또는 격리 복원으로 조정한다. 실제 자료가 들어간 뒤 메모리 전환·기존 버전 재수집·volume 삭제를 복구 절차로 쓰지 않는다.

기존 실제 DB에 적용하지 않는다. schema/권한 보호 변경 검토, migration **파일 작성 승인**, 격리 합성 DB **실행 승인**, 기존 DB migration **실행 승인**, 실제 수집·배포 승인은 구분한다. 보유기간·장벽 압축/폐기·backup 원장 보존 결정 전 운영 활성화는 BLOCKED다.

5.3의 존재 확인과 5.5의 기존 장벽 제외는 모든 writer가 먼저 같은 owner gate를 잠근다는 전제에 따른다. 기존 장벽은 UPDATE/DELETE하지 않고 중복 retire/close는 멱등으로 유지한다. 예상 밖 duplicate key는 INSERT IGNORE나 성공 처리로 숨기지 않으며, 전체 rollback 후 새 transaction에서 같은 owner gate를 얻어 동일 명령 재조회로 분류한다.

## 9. 검증 행렬과 인수 조건

아래 **모든 새 MySQL 실행 검증은 NOT_RUN**이다. 합성 fixture만 사용하고 내용/ID를 출력하지 않는 상태 비교·순서 신호를 남긴다. SQL mock은 명령/rollback 경로의 단위 증거일 뿐 잠금·crash recovery PASS가 아니다. 메모리·SQLite의 PASS도 MySQL 증거를 대체하지 않는다. [SQLite retire](../../tools/sqlite_retirement/test_retirement.py)의 `retire`와 [강제 종료](../../tools/sqlite_retirement/test_process_crash.py)의 `ProcessCrashTests.probe`는 실패 지점 구성 참고 소스일 뿐이다.

| 시나리오 | 인수 조건/필요 증거 | 상태 |
|---|---|---|
| 동일 명령·응답 유실 | 한 record/receipt, 동일 applied/시각, current는 record에서 읽음. 재생은 clock 미호출 | NOT_RUN |
| 각 명령 필드 변조·UUID 정규화 | 활성은 모든 필드 비교; equivalent UUID는 재생, 다른 값은 conflict, 다른 operation+같은 sync는 unsupported | NOT_RUN |
| 계정 격리·동일 날짜/과정 | 같은 ID를 A/B에서 독립 사용; 타 owner 전이 영향 0; 서로 다른 sync를 병합하지 않음 | NOT_RUN |
| 단건 삭제·부재 삭제 | 데이터 제거+모든 receipt 최소화+장벽 동시 commit. 옛/변조 operation과 새 operation 모두 부활 금지 | NOT_RUN |
| 세대 폐쇄·최소화 | g 이하 정리·high-water 단조·높은 g 및 다른 owner 보존; erased에 허용 세 필드만 잔존 | NOT_RUN |
| 중복·역순 open/close | close 선도착·낮은 close·높은 open·동일 open, 자동 세대 교체/재개 없음 | NOT_RUN |
| 다중 연결 최초 생성 | gate 없음부터 두 연결 동시 시작; 같은 operation/다른 payload, 다른 operation/같은 sync를 양 순서 시험. unique/gate 대기 증거 | NOT_RUN |
| create↔retire/close 경합 | 별도 연결/worker에서 gate 양 순서 강제; 선행 create는 close 집합, close 뒤 create/replay는 거부 | NOT_RUN |
| 각 쓰기/ACK 준비 실패 | gate upsert·record insert·receipt insert·장벽 insert·receipt update·record delete·gate update 직후 및 commit 전 실패: 전 상태 또는 전부 후 상태만 | NOT_RUN |
| deadlock/timeout/rollback 실패 | 전체 rollback·연결 폐기·동일 명령 제한 재시도, 오류/로그에 payload·SQL/ID 노출 없음 | NOT_RUN |
| commit 불명 | commit 전송 전/후 응답 차단, 새 연결 조정: 중복 생성/새 ID 없음; 그 사이 retire/close 시 성공 재생 금지 | NOT_RUN |
| 프로세스·DB 재시작 | commit 전후 강제 종료 뒤 새 연결 상태 집합 비교; gate/erased/장벽 보존, 메모리 fallback 없음 | NOT_RUN |
| 저장 범위·문자열·시각 | M/초과·bool·UTF-8 256bytes/초과·후행 공백·대소문자·0001 날짜/윤일·UTC 6자리 왕복과 잘못된 clock rollback | NOT_RUN |
| migration·권한 | 새 설치/업그레이드/중간 실패/재실행/shape 불일치 중단, 기존 자료 불변, runtime Core/DDL/장벽 제거 거부 | NOT_RUN |
| backup 복원 | 삭제 전 snapshot 격리 복원→최신 원장 선적용→옛/새 operation 부활 거부; 최신 원장 유실이면 서비스 BLOCKED | NOT_RUN |
| Core/권한 불명 | upload/ACK 차단, 제한된 본인 관리 권한 분리; 실제 admission/A/F/D 통합 증거는 별도 보호 변경 이후 | NOT_RUN |

## 10. 다음 구현 묶음과 완료 조건

추가 독립 모델/실험 저장소를 만들지 않고 다음 한 묶음의 **미연결 합성 repository 구현**으로 이어간다. 아래 파일은 후보이며 이번에 만들지 않는다.

| 파일 후보 | 구체 범위와 완료 조건 |
|---|---|
| `app/modules/neorang_narang/real_sync_repository.py` | create/replay/retire/open/close의 좁은 protocol 및 고정 오류 계약. `real_sync_candidate.py`의 DTO 재검증·명시 context·clock 경계를 유지하고 메모리 후보와 같은 계약 실행 가능하게 분리. 실제 권한을 기본 부여하지 않음 |
| `app/modules/neorang_narang/real_sync_mysql.py` | 호출자가 connector/clock을 주입하는 독립 repository. `app.core.database`/설정 로더 기본 import·default connector 없음. 연결당 한 transaction, gate 순서·rollback·commit 불명·연결 폐기·최소화 구현. HTTP 예외/기존 factory 자동 연결 없음 |
| `tests/nn_real_sync_contract.py`, 기존 후보 테스트의 최소 후속 정리 | 기존 테스트의 입력 fixture·관찰 가능한 기대값을 재사용한 공통 계약. 메모리 private dict 참조/생성자 patch 실패 주입은 메모리 전용으로 유지하고 MySQL에는 저장소 상태 비교·DB 실패 지점 fixture 사용. 단순 구현 복제 테스트 금지 |
| `tests/test_nn_real_sync_mysql.py` | 기본 실행은 DB 미접속/skip, 명시 승인된 격리 합성 MySQL에서만 실행. 다중 독립 연결·재시작·commit 불명·최소화·실패 행렬 증거. mock 단위 검사와 실제 InnoDB 검증 집계를 분리 |
| `migrations/neorang_narang/003_real_sync.sql`, `scripts/nn_real_sync_mysql.py` | 보호 변경 검토 후 additive DDL과 plan/apply 분리 runner 후보. 설치·중간 실패 재실행·권한·보호 backup/격리 복원 준비 포함. 이 파일들의 작성과 실행 승인을 분리하며 기존 runner를 자동 수정하지 않음 |

합성 코드 완료는 공통 메모리 계약 보존, DTO/범위 호환 차이 명시, repository 실패/최소화 검증과 미연결 확인이다. 영속화 완료는 여기에 **격리 MySQL 실제** 다중 연결·commit/rollback·재시작·복원·migration 인수 증거를 더해야 한다. 실행이 승인되지 않으면 NOT_RUN으로 남기며 완료로 부풀리지 않는다. 기존 router/factory/운영 설정·Core·Flutter·CI 변경은 이 묶음에서 자동 수행하지 않는다.

미해결 결정: 숫자/문자열 상한·UTC 발급 프로파일 승인, 최대 close 규모와 단일 transaction 한계, Core ticket/현재 권한/분산 철회 결합, live inventory 범위, queue/receipt/장벽/backup 보유기간 및 최신 원장 보호·복원 절차다. 보호 변경·migration 실행·실제 수집 승인과 독립 검토를 각각 기록해야 한다. 실제 수집은 계속 **BLOCKED**, 설계는 **PROPOSED / AUTHOR_REVIEW_REQUIRED**다.

## 11. 기존 문서 작성 시 검사 기록

이번 실행 범위는 소스 읽기와 문서 검사뿐이다. 상대 링크/참조 파일·소스 심볼 존재, UTF-8 strict decode·새 연속 물음표/U+FFFD·whitespace, 상태·잠금 순서·최소화·복구의 정적 일관성을 검사한다. 실제 결과는 아래와 같다.

| 검사 | 결과 |
|---|---|
| 상대 Markdown 링크/참조 소스·심볼 정적 존재 검사 | PASS; 다음 구현 파일 후보는 미존재 제안으로 구분 |
| 상태·transaction 순서·receipt 최소화·복원 구별 수동 대조 | PASS; Core A/F/D 미완성과 실제 수집 BLOCKED 유지 |
| UTF-8·새 연속 물음표/U+FFFD·trailing whitespace·탭·최종 newline | PASS |
| `git diff --check` 및 신규 파일 별도 공백 검사 | PASS |
| 최종 HEAD/branch/status·허용 변경 범위 | PASS: `527d3d0`, `docs/nn-real-sync-persistence` 유지, 이 문서 한 파일만 추가 |
| 서비스·DTO·offline·pip check·DB·migration·backup 복원·CI | NOT_RUN; 사용자 지정 문서 전용 범위 |

commit·push·PR 생성·병합·배포·브랜치 전환·정리는 수행하지 않았다.

## 12. 이번 정적 검토 수정

이번 시작 상태는 `docs/nn-real-sync-persistence`, HEAD `527d3d0`, 이 문서 한 개만 미추적이다. 1절의 최초 작성 시작 상태와 11절의 기존 검사 기록은 과거 기록이며 이번 실행 결과가 아니다. 이번에는 5.3·5.5의 장벽 upsert를 존재 확인/기존 장벽 제외 INSERT로 바꾸고 8절의 최소 권한을 유지한다.

5.1~5.5 의사코드와 8절 runtime 권한을 정적으로 대조했다. gates는 SELECT/INSERT/UPDATE(upsert 포함), records는 SELECT/INSERT/DELETE, receipts는 SELECT/INSERT/UPDATE, barriers는 SELECT/INSERT만 사용한다. real version은 SELECT만 허용하고 marker 기록·DDL은 migration 관리자 경계다. 같은 종류의 추가 불일치는 발견하지 않았다. 실제 MySQL 권한·잠금 동작을 검증한 결과는 아니다.

이번 UTF-8·공백·상대 링크·`git diff --check`·신규 파일 별도 공백 검사와 최종 Git 상태 결과는 이번 작업의 최종 보고에 구분해 기록한다. DB·테스트·migration·서비스·pip check·backup 복원은 사용자 지정 범위에 따라 **NOT_RUN**이다. 실제 수집은 **BLOCKED**, 앱 적용은 **AUTHOR_REVIEW_REQUIRED**를 유지한다.
