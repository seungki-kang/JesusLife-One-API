# 로컬 개발 MySQL

2026-10-29 사용자 승인 범위: 별도 MySQL, 제품별 DB·계정, 너랑나랑 메타데이터 영속화,
드라이버 설치·초기화·migration·합성 자료 검증. 실제 사용자 자료 이전·삭제·인증 우회·
운영 배포·commit·push는 포함하지 않는다. Windows MariaDB 서비스·3306·기존 데이터는 유지한다.

## 구성

`compose.yaml`은 검증한 MySQL 8.4 이미지 digest를 고정하고 `127.0.0.1:3307`만 공개한다.
컨테이너는 `jesuslife-local-mysql`, volume은 `jesuslife-local-mysql-data`다.
컨테이너 root 계정은 로컬 관리용이며 앱에는 사용하지 않는다. 일반·slow query 로그와
LOCAL INFILE은 끈다. root 비밀번호는 컨테이너 환경에 있으므로 Docker 관리자 권한을 통제한다.

| DB | 앱 계정 | 권한·테이블 |
|---|---|---|
| neorang_narang | nn_app | 소유자 잠금·완료 테이블 SELECT/INSERT/UPDATE, 스키마 버전 SELECT |
| life_diary | life_diary_app | 자기 DB SELECT/INSERT/UPDATE, 현재 업무 테이블 없음 |

앱 계정에는 DDL·물리 DELETE·다른 제품 DB 접근·GRANT 권한이 없다. 행 단위 소유자 분리는
API 저장소에서 수행한다. DB 앱 계정 자체는 너랑나랑 내 모든 행에 접근할 수 있으므로
개인 사용자 자격으로 배포하거나 클라이언트에 배포하지 않는다.

## 새 개발 환경 준비

설치 승인이 있는 환경에서 아래 명령을 프로젝트 루트에서 실행한다. 생성된 `.env`는
덮어쓰지 않으며 비밀번호는 무작위 생성한다. `.env`는 Git에서 제외하고 파일 생성자·작업
폴더 소유자만 접근하도록 제한한다. `.env.example`에는 실제 비밀번호가 없다.

```powershell
.\.venv\Scripts\python.exe -B -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -B -m scripts.local_mysql prepare
docker compose up -d --wait --wait-timeout 180
.\.venv\Scripts\python.exe -B -m scripts.local_mysql bootstrap
.\.venv\Scripts\python.exe -B -m scripts.verify_mysql tests
```

DB 연결 코드도 `127.0.0.1:3307` 이외의 주소를 거부해 설정 오류로 3306에 연결하지 않도록 한다.
3307 충돌 시 기존 서비스를 중지하거나 포트를 바꾸지 말고 충돌을 해소한다. 이번 환경에서는
충돌 없이 전용 volume을 신규 생성했다. `prepare`는 기존 `.env`가 있으면 실패한다.
기존 volume이 있는 상태에서 새 비밀번호로 `.env`를 재생성하면 기존 DB 비밀번호가 바뀌지
않으므로 연결에 실패한다. 기존 비밀 설정을 안전하게 보존한다. 설정·컨테이너 환경 전체를
출력하는 `docker compose config`, 환경 덤프, 원문 DB 덤프 출력은 사용하지 않는다.

`bootstrap`은 두 DB와 전용 계정을 만들고 너랑나랑에만 migration 001을 적용한다.
동일 명령 반복은 비밀번호를 회전시키거나 업무 자료를 삭제하지 않는다.
후속 명시적 migration은 아래 명령이다. 앱 시작 시 자동 DDL은 없다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.local_mysql migrate
```

DDL은 MySQL에서 문장별 commit이므로 migration은 중단 후 재실행 가능하게 작성했다.
버전 표시는 업무 테이블 생성 뒤에 기록하며 동시에 두 migration을 실행하지 않도록
DB advisory lock을 사용한다. 알 수 없는 상위 버전은 변경 전에 거부한다.
이번 작업은 신규 DB의 버전 0→1만 다룬다. 후속 버전은
별도 업그레이드·구버전 호환·복구 검증이 필요하다.

## API 실행과 동작

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

실제 인증은 기존과 같이 401이다. 테스트용 인증 override를 앱 코드나 실행 설정에 넣지
않는다. 공개 health·OpenAPI 경로는 유지하며 health는 DB 가용성 검사가 아니다.
`COMPLETION_STORE=mysql`이면 MySQL만 사용하고 실패 시 고정 503이다. 비밀정보나
드라이버 예외 원문은 응답에 넣지 않으며 저장 성공은 commit 이후에만 반환한다.

기존 경로·메타데이터·동일 생성 재시도·버전 충돌·삭제 재시도·소유자 격리를 유지한다.
완료 시각은 UTC 마이크로초로 보존한다. 소유자 행 잠금과 READ COMMITTED 트랜잭션으로
동시 명령의 읽기·비교·쓰기를 직렬화한다. tombstone은 일반 조회에서 제외하며 물리 삭제하지
않는다. 연결 실패·교착·lock timeout·commit 결과 불명확은 고정 503으로 반환하고 자동
메모리 대체·서버 내부 자동 재시도는 없다. 클라이언트는 같은 명령을 제한적으로 재시도한다.
기존 수정 계약에는 과거 성공 명령 receipt가 없으므로 수정 응답 유실 후 재시도는 409일 수 있다.

## 합성 자료 검증·백업·복원

```powershell
.\.venv\Scripts\python.exe -B -m scripts.verify_mysql tests
.\.venv\Scripts\python.exe -B -m scripts.verify_mysql migration-retry
.\.venv\Scripts\python.exe -B -m scripts.verify_mysql checkpoint
docker compose stop mysql
.\.venv\Scripts\python.exe -B -m scripts.verify_mysql outage
docker compose start --wait mysql
.\.venv\Scripts\python.exe -B -m scripts.verify_mysql verify-checkpoint
.\.venv\Scripts\python.exe -B -m scripts.local_mysql backup-verify
.\.venv\Scripts\python.exe -B -m scripts.verify_mysql rollback-mode
```

통합 테스트는 매번 새 합성 UUID를 사용하며 자료를 출력·물리 삭제하지 않는다.
`verify_mysql tests`는 인증 override를 검증 프로세스 안에서만 사용하고 항상 정리한다.
일반 unittest 실행은 MySQL 테스트를 건너뛰며 위 명령은 전체 테스트를 포함한다.
실패 시 테스트 이름·건수만 출력한다. 상세 검증 오류에는 자료가 들어갈 수 있어 출력하지 않는다.

`checkpoint`는 현재 합성 DB 상태의 해시만 Git 제외 파일에 기록한다. 이후 새 Python
프로세스에서 값 비교와 앱 저장소 조회를 확인한다. checkpoint 사이에 다른 쓰기가 있으면
비교는 실패한다. 자료 내용이나 해시는 콘솔에 출력하지 않는다.

`backup-verify`는 **이번 로컬 합성 자료 전용**이다. 활성 쓰기를 중지한 상태에서 실행한다.
`mysqldump --single-transaction` 결과를 저장소 밖 임시 폴더에 쓰기 전에 접근 권한을
제한하고, 새 `nn_restore_*` DB에 복원해 잠금 행·완료 메타데이터·tombstone·버전을 비교한다.
덤프·비밀번호는 콘솔에 출력하지 않는다. 백업 위치는 로컬 `.env.backup-location`에 저장한다.
검증 DB와 백업은 보존한다. 실제 자료를 저장하기 전 별도 백업·보유·암호화 정책 승인이 필요하다.
합성 DB 안에서만 수행한 검증이며 기존 MariaDB에 연결하거나 그 자료를 백업하지 않는다.

## 롤백

앱 실행 환경의 `COMPLETION_STORE=memory`로 전환하고 앱을 재시작하면 기존 메모리 방식으로
돌아간다. 새 MySQL만 `docker compose stop mysql`로 중지할 수 있다. volume·DB·tombstone은
보존한다. `down -v`, DROP, 기존 MariaDB 중지·재설정은 실행하지 않는다.
메모리 모드는 MySQL 자료를 읽거나 자동 이전하지 않으며 재시작 시 메모리 자료를 잃는다.
검증 명령 `rollback-mode`는 해당 프로세스에서만 메모리 모드로 실행해 DB 무변경을 비교한다.
기본 `.env`는 MySQL 모드로 유지한다. DB 자료를 유지한 채 MySQL 모드로 복귀할 수 있다.
