# 모바일 migration 전후 전체 백업과 격리 복원

이번 범위는 코드·합성 offline mock·절차 문서다. 실제 MySQL 백업·복원·DDL·GRANT,
키 조회·복사·변경, 서비스 조작은 수행하지 않았다. 실제 리허설은 NOT_RUN이며 별도 실행 승인이 필요하다.
기존 백업/migration 명령의 동작은 변경하지 않았다.

## 기존 도구 점검

| 도구 | 포함 범위와 공백 |
|---|---|
| `scripts.core_mysql`의 `backup-verify` | 고정 7개: core_schema_version, accounts, external_identities, login_transactions, app_sessions, session_access_tokens, product_consents. 별도 manifest의 v1 DDL과 데이터로 복원하며 모바일 3개 테이블·별도 권한 목록은 제외된다. |
| `scripts.local_mysql`의 `backup-verify` | neorang_narang mysqldump는 당시 전체 테이블의 DDL·데이터·FK를 포함하지만 비교는 nn_schema_version, nn_completion_owners, nn_completion_records의 데이터만 한다. Core와 모바일 전체 복구·권한·키 검증이 아니다. |
| `scripts.mobile_mysql`의 `apply` | 두 DB의 발견 테이블 DDL·데이터 snapshot과 layout 검증을 제공하지만 snapshot 파일 복원 CLI와 전체 복원 비교는 없다. 확인 플래그는 운영 쓰기 중단 증거가 아니다. |

v1 FK는 Core 계정→외부 identity→세션→token, 계정→동의 및 제품 owner→완료 기록이다.
모바일의 mobile_consents는 accounts를 참조한다. mobile_logins의 account_id 및
nn_mobile_synthetic의 owner_sub에는 선언된 FK가 없다. 선언되지 않은 관계의 의미적
무결성은 FK PASS에 포함되지 않는다. v1 테이블은 반드시 보존해야 한다.

## 전용 도구의 계약

`scripts.mobile_backup`은 기본 plan에서 설정 파일·DB·키를 열지 않는다. `rehearse`에서만
기존 제한된 로컬 connector(127.0.0.1:3307)의 관리자 자격을 내부에서 읽는다.
비밀번호·자료·토큰·키·SQL·예외 세부를 명령 인자나 stdout에 내보내지 않는다.
기존 백업을 입력받아 임의 대상에 복원하는 명령은 제공하지 않는다.

대상 원본은 platform_core, neorang_narang 두 개로 고정한다. 발견된 모든 기본 테이블의
SHOW CREATE TABLE, 전체 행(중복·NULL·binary·시간·암호문 포함), FK 열/순서를 백업한다.
모바일 적용 전에는 v1 전체, 적용 후에는 mobile_schema_version, mobile_logins,
mobile_consents, nn_mobile_synthetic을 포함해 실제 존재하는 전체 테이블을 수집한다.
InnoDB 외 엔진, view·trigger·routine·event, 교차 DB FK, 순환 FK는 조용히 제외하지 않고 실패한다.

별도 권한 목록은 platform_core_app, platform_core_migrator, nn_app의 계정명/host,
전역·DB·테이블·열 권한과 role/default role이다. 계정 누락·예상 밖 host·role 사용은
검토가 필요하므로 실패한다. 비밀번호 hash나 인증 문자열은 수집하지 않는다.
이 목록은 원본 전후 불변 여부를 검증한다. 새 DB에 계정을 생성하거나 권한을 재현하지 않으며,
최소 권한 정책 승인 또는 깨끗한 서버에서의 계정 복구 성공을 뜻하지 않는다.

한 연결의 REPEATABLE READ/consistent read-only transaction으로 두 InnoDB DB의 행을
같은 snapshot에서 수집한다. DDL·계정 권한은 이 snapshot만으로 일관성을 보장할 수 없으므로
아래 쓰기 중단 절차가 필수다. 복원 후 원본 데이터·DDL·FK와 권한을 다시 비교하지만,
전후 비교 일치는 사이에 쓰기가 전혀 없었다는 증거가 아니다.

## 실제 리허설 전 쓰기 중단과 키 준비

운영 담당자가 별도 승인 아래 다음 사항을 수행하고, 접근 제한된 증거 파일에 기록한다.
민감 원문·사용자 ID·자격증명을 증거에 넣지 않는다.

1. 두 DB의 모든 writer를 목록화한다. PC/모바일 API worker, callback, 동기화·삭제 작업,
   scheduler, 수동 SQL, migration 및 권한 관리 작업까지 포함한다.
2. 신규 요청 유입을 차단하고 worker/작업을 정지하거나 쓰기를 차단한다. 진행 중 transaction을
   종료·drain하고 연결/transaction 상태와 쓰기 지표를 담당자가 확인한다. 방법·시각·검토자를 기록한다.
3. 백업 시작부터 복원 비교와 원본 재비교가 끝날 때까지 두 DB를 같은 중단 구간에 둔다.
   모바일 migration 적용 전 백업/리허설과 적용 후 백업/리허설은 서로 다른 새 디렉터리로 수행한다.
   각 단계에서 승인된 schema version과 예상 전체 테이블 목록도 사람이 확인한다.
4. 작업 중단이 풀리거나 증거가 불충분하면 결과를 복구 준비 완료로 승인하지 않는다.
   `--write-stop-evidence`는 파일 존재만 검사한다. 내용을 해석하거나 실제 정지를 입증하지 않는다.

키 관리자는 기존 승인된 비밀 저장소에서 복구 가능한 키 버전과 접근 절차를 별도로 확인한다.
`CORE_TOKEN_ENCRYPTION_KEY`는 PC verifier/JWT 및 모바일 browser/credential 암호문 복구에,
`CORE_TOKEN_HMAC_KEY`는 token fingerprint와 기존 세션 상호운용에 필요하다.
key_version/encryption_key_version/fingerprint_key_version와 대응되는 과거 키도 보존해야 한다.
모바일 ciphertext에는 별도 키 버전 열이 없으므로 해당 백업 시점의 배포 키 매핑을 보관해야 한다.
키 관리자·대체 담당자·승인 경로·버전 매핑·보존 기간을 확인하고 키는 DB 백업과 분리해 관리한다.
이 도구는 키를 백업·복사·변경하거나 rotation 도구를 호출하지 않는다.

실제 복호화 인수는 별도 승인된 격리 환경에서 기존 키 저장소의 통제된 접근으로 수행한다.
원본 DB나 Auth0에 연결하지 않고 복원한 암호문의 인증 태그/AAD 검증 및 HMAC 대응을
검사하고 결과만 남겨야 한다. 평문은 로그·파일·인자에 저장하지 않는다.
그 검증 CLI는 이번 범위에 구현하지 않았으므로 실행 명령을 제시하지 않는다.

## 구현·오프라인 검증한 CLI

프로젝트 루트의 PowerShell에서 plan은 실제 실행해도 설정·DB에 접근하지 않는다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.mobile_backup
.\.venv\Scripts\python.exe -B -m scripts.mobile_backup plan
```

아래는 **별도 승인·쓰기 중단 증거 준비 이후** 사용할 구현된 CLI 예시다.
CLI 분기·전용 함수는 mock으로 검증했으며 실제 MySQL 실행 호환성은 NOT_RUN이다.
증거 파일 경로는 해당 운영 기록의 경로로 바꾼다. 디렉터리는 매번 새 이름이어야 한다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.mobile_backup rehearse --directory .mobile-backups/before-unique-run --write-stop-evidence .mobile-backups/write-stop-evidence.txt
.\.venv\Scripts\python.exe -B -m scripts.mobile_backup rehearse --directory .mobile-backups/after-unique-run --write-stop-evidence .mobile-backups/write-stop-evidence.txt
```

도구는 새 디렉터리와 파일의 접근을 기존 protect 함수로 제한한다. Windows에서는 상속 ACL을
제거하고 실행 identity/작업공간 owner에만 허용하며 POSIX는 디렉터리 0700/파일 0600이다.
보호 실패는 중단하며 snapshot은 보호 이후 기록한다. Git의 `.mobile-backups/` 제외 여부도
쓰기 전에 확인한다. 실제 운영 계정의 최종 ACL 적정성은 별도 확인해야 한다.
백업은 저장 매체에서 자동 암호화되지 않으므로 승인된 암호화 저장소·보존 정책이 필요하다.

새 128-bit 무작위 실행명으로 격리 DB 두 개를 생성한다. `IF NOT EXISTS`나 사용자 지정 대상은
허용하지 않는다. 두 CREATE가 모두 성공 응답을 반환하기 전에는 USE/테이블 복원을 시작하지 않는다.
FK를 활성화한 채 의존 순서로 DDL·행을 적재하고 재조회해 schema/data/FK를 비교한다.
결과는 schema/data/FK, 원본 계정 권한 불변, decrypt NOT_RUN을 구분한다.
암호문 byte 일치 PASS는 키 가용성·실제 복호화·세션 사용 가능·로그인 성공 PASS가 아니다.
실제 리허설의 FK 적재 검사는 선언된 FK 위반 여부를 확인하지만 offline mock은 MySQL 엔진을 검증하지 않는다.

## 부분 실패·재실행·롤백 경계

시도명은 CREATE 이전 `attempt.json`에 기록한다. CREATE 응답 유실·이름 충돌·DDL/INSERT 실패·
commit 응답 유실·원본/권한 비교 실패 시 결과는 FAIL이며 기존 DB에 복원·DROP하지 않는다.
`result.json`이 없는 시도는 완료 미확인이다. 보유한 snapshot/attempt와 부분 격리 DB를 유지하고
담당자가 조사한다. 재실행은 새 디렉터리·새 무작위 격리 DB로 처음부터 수행한다.
기존 attempt 재개, 자동 cleanup, 자동 rollback, 원본 복원은 제공하지 않는다.
원본으로의 복귀가 필요하면 쓰기 중단 유지 상태에서 별도 복구 계획과 AUTHOR_REVIEW_REQUIRED 검토를 받는다.
구버전 코드 복귀만으로 DB schema·권한이 되돌아가지는 않는다.

현재 mobile Core adapter는 같은 Core 연결/unit of work로 nn_mobile_synthetic에 직접 쓴다.
이 결합과 기존 모바일 GRANT 설계는 그대로 두며 이번 도구는 Core의 제품 DB 쓰기 권한을 확대하지 않는다.
후속 분리안은 제품 소유 서비스/API 또는 outbox·멱등 이벤트 계약으로 쓰기를 이전하고,
동의 generation·삭제 barrier·재시도 의미를 보존한 뒤 Core 직접 쓰기 권한을 별도 승인 아래 축소하는 것이다.

## 검증 범위

```powershell
.\.venv\Scripts\python.exe -B -m scripts.test_offline
.\.venv\Scripts\python.exe -B -m pip check
git diff --check
git check-ignore .mobile-backups/probe/snapshot.json
```

offline runner는 환경 파일·외부 네트워크·실제 MySQL을 차단한다. mock에서는 plan 무접근,
전체 백업 readback/결과 기록, FK 순서, 행 중복/DDL/FK 불일치, 권한 변경 실패, Git 제외 실패,
이름 충돌, 응답 유실, 부분 실패와 재실행 보호 및 예외 출력 억제를 검증한다.
실제 MySQL restore, 계정 재구성, 실제 ACL, 쓰기 중단 관측, 실제 키 접근/복호화는 NOT_RUN이다.

2026-10-30 검증 결과: offline 128개 중 106개 PASS, 실제 DB opt-in 22개 SKIP.
위 offline/pip check/diff check 명령은 종료 코드 0이며 Git 제외 확인도 PASS다.
기본/명시적 plan CLI 및 신규 Python 2개 파일 AST 문법 검사는 PASS다.
테스트 중 인증 거부를 의도한 진단 로그의 FAIL 표시는 테스트 실패가 아니다.
최종 FAIL 검사는 없으며 이 결과를 실제 MySQL 복원 PASS로 확대하지 않는다.
