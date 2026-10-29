# 로컬 MySQL 영속화 검증 기록

2026-10-29, `feature/nn-completion-contract`. 사용자 승인: 기존 MariaDB·3306·자료 유지,
별도 루프백 3307 MySQL·전용 volume, 제품별 DB·계정, 너랑나랑만 업무 테이블 구현,
드라이버 설치·초기화·migration·합성 자료 검증. 운영 배포·commit·push는 제외.

## 구현 결과

| 범위 | 파일 |
|---|---|
| 독립 MySQL·전용 volume·비밀 설정 예시 | `compose.yaml`, `.env.example` |
| 로컬 연결 설정·3306 연결 거부 | `app/core/database.py` |
| 저장소 계약·명시적 모드 선택 | `app/modules/neorang_narang/store.py` |
| 소유자 잠금·commit·rollback·고정 503 | `app/modules/neorang_narang/mysql_store.py` |
| 트랜잭션에 검증된 소유자 전달 | `app/modules/neorang_narang/service.py` |
| additive migration 001 | `migrations/neorang_narang/001_initial.sql` |
| 초기화·migration·접근 제한 백업·별도 복원 | `scripts/local_mysql.py` |
| 자료를 출력하지 않는 검증 실행기 | `scripts/verify_mysql.py`, `scripts/__init__.py` |
| 합성 자료·권한·동시성·설정 회귀 | `tests/test_mysql_persistence.py`, `tests/test_database_configuration.py`, `tests/test_completions.py` |
| 의존성 | `requirements.txt`, `requirements-dev.txt` |
| 계약·실행·복구 문서 | `README.md`, `docs/local-mysql.md`, `docs/architecture/nn-mysql-persistence-plan.md`, `docs/architecture/nn-auth-ownership-sync-policy.md` |

기존 Python 3.14.8 가상환경을 유지했다. PyMySQL 1.1.2와 RSA 인증 의존성을 설치했고
MySQL 이미지는 검증한 digest로 고정했다. 비밀번호는 로컬 무작위 생성하며 `.env`는
Git 제외 및 파일 생성자·프로젝트 폴더 소유자 접근으로 제한했다.

앱 인증 코드는 변경하지 않았다. 실제 요청은 기존과 같이 401이며 합성 인증은 격리된
테스트 프로세스에서만 사용하고 정리했다. 생명일기는 DB와 별도 계정만 만들고 업무
테이블·API는 추가하지 않았다. 실제 사용자 자료·MariaDB DB 파일은 읽거나 이전하지 않았다.

## 실행 결과

아래 성공 명령의 종료 코드는 모두 0이다. 검증 출력에 비밀번호·토큰·행 본문은 포함하지 않았다.

| 상태 | 명령·확인 | 증거 |
|---|---|---|
| PASS | `docker version`, `docker compose version` | Linux 엔진 연결 정상, Compose 사용 가능 |
| PASS | `docker compose up -d --wait --wait-timeout 180` | 새 MySQL healthy, 루프백 3307, 전용 volume |
| PASS | `python -B -m scripts.local_mysql bootstrap` 반복 | 두 DB·계정 생성, 너랑나랑만 업무 테이블·버전 1, 반복 무삭제 |
| PASS | `python -B -m scripts.local_mysql migrate` | 명시적 migration 재실행 성공 |
| PASS | `python -B -m scripts.verify_mysql tests` | 전체 44개, 실패 0·오류 0·skip 0 |
| PASS | `python -B -m scripts.verify_mysql migration-retry` | 부분 DDL 재개, 반복 동일, 상위 버전 무변경 거부 |
| PASS | `checkpoint` → 별도 `verify-checkpoint` 프로세스 | 연결·앱 프로세스 재생성 후 값·revision·tombstone 보존 |
| PASS | `docker compose stop mysql` → `python -B -m scripts.verify_mysql outage` | 실제 DB 중지 시 고정 503, 공개 health 유지 |
| PASS | `docker compose start --wait mysql` → `verify-checkpoint` | DB 재시작 뒤 snapshot 동일 및 앱 저장소 조회 확인 |
| PASS | `docker compose up -d --force-recreate --wait --wait-timeout 120 mysql` → `verify-checkpoint` | 컨테이너 재생성 후 전용 volume에서 동일 자료 보존 |
| PASS | `python -B -m scripts.local_mysql backup-verify` | 외부 임시 폴더 접근 제한, 별도 DB 복원 후 전체 행·버전·tombstone 동일 |
| PASS | `python -B -m scripts.verify_mysql rollback-mode` | 프로세스만 메모리 모드 복귀, 인증 401 유지, MySQL snapshot 무변경 |
| PASS | `python -B -m pip check` | 의존성 불일치 없음 |
| PASS | Python AST 문법 검사, `git diff --check` | 문법·공백 오류 없음 |
| PASS | Git 표시 대상 파일에서 생성 비밀번호 포함 여부 검사 | 비밀번호 없음, 로컬 비밀 파일은 제외 |
| PASS | Windows 서비스·TCP·Docker 바인딩 확인 | MariaDB Running, 기존 3306 유지, 새 MySQL 127.0.0.1:3307 |

실제 실행한 `python`은 모두 `.venv\Scripts\python.exe`이며 `-B`를 사용했다.
전체 테스트에는 기존 공개 경로·OpenAPI, 인증 거부, UUID·UTC 계약, 생성 재시도·
수정 충돌·삭제 재시도, MySQL 연결 재생성, 서로 다른 연결의 동시 생성·수정,
타 소유자 조회·수정·삭제 차단, DB 계정 교차 접근·DDL·물리 삭제 거부,
commit 실패·rollback·안전한 503, 연도 1~9999와 마이크로초 보존이 포함된다.

동시성 검증 중 기본 REPEATABLE READ snapshot이 잠금 이전 스키마 조회에서 고정되어
생성 결과가 중복 성공으로 보이는 문제를 발견했다. READ COMMITTED를 명시하고
잠금 획득 뒤 읽도록 수정했으며 barrier로 두 연결을 동시에 시작하는 회귀 검증을 통과했다.
설계 근거는 MySQL의 [격리 수준](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html)과
[잠금 읽기](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html),
드라이버의 [연결·트랜잭션 API](https://pymysql.readthedocs.io/en/latest/modules/connections.html)다.

## 보존과 한계

백업 경로는 Git 제외 `.env.backup-location`에서 확인한다. 검증용 `nn_restore_*`,
`nn_migration_check_*` DB와 합성 fixture는 보존했다. 자동 DROP·물리 자료 삭제·
volume 삭제를 하지 않았다. 신규 DB 버전 0→1과 부분 초기화 재시도만 검증했으며,
향후 버전 간 upgrade·down migration은 이번에 존재하지 않는다. 롤백은 DB를
보존한 설정 전환이며 과거 바이너리 설치나 자료 자동 이전을 의미하지 않는다.

NOT_RUN: 실제 인증 제공자·사용자 동의·Flutter 동기화·운영 APM/프록시·운영 백업
보유·암호화·부하/장기 장애 검증. 이번 승인 범위 밖이다. 서버 access log는 로컬 실행
안내에서 끄며 운영 로그 보호 전체를 검증했다고 주장하지 않는다.
formatter·linter·type checker는 프로젝트에 설정이 없어 추가 설치·실행하지 않았다.

운영 DB·인증 경계·개인정보 공유·후속 migration에는 해당 변경의 별도 검토가 필요하다.
이번에 승인된 로컬 구성·DB 구조·migration에 대한 추가 승인은 요구하지 않는다.
