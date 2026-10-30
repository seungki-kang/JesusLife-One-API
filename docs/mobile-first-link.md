# 모바일 첫 연결: 현재 코드 기준 안내

2026-10-30 작업 트리 기준. Android 로컬 합성 자료 PoC의 준비 안내이며 연결 완료 보고가 아니다. DB 구조·인증 경계 적용은 **AUTHOR_REVIEW_REQUIRED**이다. 아래 apply·서버 실행·ADB 명령은 후속 승인 작업용이며 이번 문서 작성에서는 실행하지 않았다.

후속 [Android 모바일 인수 기록 (USER-REPORTED)](verification/2026-10-30-android-mobile-acceptance.md)에 실제 기기 로그인·합성 항목 재전송·철회 재개에 대한 사용자 보고와 한계를 별도로 기록했다. 아래 준비 단계의 실패·미실행 이력은 당시 기록으로 유지한다.

## 범위와 선행 조건

- API 루트: `D:\CHGO-VibeCodeing\JesusLife-One-API`. 보존된 `.venv`의 Python은 3.14.8이다. `requirements.txt`와 `requirements-dev.txt`를 기준으로 기존 환경을 확인한다. 자동 설치하지 않는다. 암호화 구현은 `cryptography`를 사용하며 현재 이 패키지는 개발 의존성 명세에 있다.
- 기존 별도 로컬 MySQL `127.0.0.1:3307`에 `platform_core.core_schema_version`과 `neorang_narang.nn_schema_version`의 version 목록이 각각 정확히 `[1]`이어야 한다. 신규 빈 DB 초기화 도구가 아니다. MariaDB 3306이나 원격 DB는 지원하지 않는다.
- Core v1 계정·외부 ID·로그인·세션 테이블, 기존 `platform_core_app` 계정과 권한이 필요하다. 모바일 적용 도구는 계정이나 암호를 생성·변경하지 않는다.
- API와 다른 쓰기 주체를 중지하고 두 DB 전체의 보호된 백업 및 격리 복원 리허설을 먼저 완료해야 한다. 스크립트의 확인 플래그는 실제 중지나 리허설 성공을 검사하지 않는다.
- 코드상 migration 관리 연결은 `app.core.database.connect(admin=True)`이며 `.env` 설정과 프로세스 환경을 사용한다. 기본 관리 사용자는 `root`, 암호 설정 이름은 `MYSQL_ROOT_PASSWORD`이다. 기존 Core migrator 전용 계정 경로를 사용하지 않는다. 관리자는 테이블 조회·생성, 임시 layout DB 생성, 지정 테이블 GRANT 권한이 필요하다.
- 모바일 런타임은 별도 `.env.mobile` 없이 `.env.auth0-pc`를 재사용한다. `AUTH0_ISSUER`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `CORE_DB_PASSWORD`, 서로 다른 32바이트 Base64 `CORE_TOKEN_HMAC_KEY`·`CORE_TOKEN_ENCRYPTION_KEY`가 필요하다. 값은 문서·채팅·로그에 넣지 않는다.
- 설정 검증의 고정값은 `AUTH0_AUDIENCE=https://api.jesuslife.example/poc`, `AUTH0_CALLBACK_URL=http://127.0.0.1:8000/api/v1/auth/callback/web`, `CORE_DB_HOST=127.0.0.1`, `CORE_DB_PORT=3307`, `CORE_DB_NAME=platform_core`, `CORE_DB_USER=platform_core_app`이다. Android를 위해 이 설정의 callback을 android로 바꾸면 현재 validator가 거부한다.

설정 파일의 존재·값·실제 권한은 이번 작업에서 확인하지 않았다. `.env` 계열과 비밀정보를 읽지 않았다.

## 지원되는 migration 명령

프로젝트 루트 PowerShell에서 사용하는 정확한 CLI는 다음과 같다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.mobile_mysql plan
```

action 생략도 `plan`이다. plan은 DB 연결 없이 두 SQL 경로와 선행 조건만 출력한다. 실제 DB 상태 검사나 SQL 실행 시뮬레이션은 아니다.

별도 승인과 선행 조건 충족 후에만 다음 형태로 적용한다. 예시 경로는 아직 존재하지 않는 새 디렉터리로 교체해야 한다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.mobile_mysql apply --backup-directory 'D:\JesusLife-Backups\mobile-before-001' --ack-stopped-api-and-restore-rehearsal
```

지원 action은 `plan`, `apply`뿐이다. `migrate`, `rollback`, `restore`, `--dry-run` 옵션은 없다. SQL을 직접 실행하는 절차로 대체하지 않는다.

| 파일 | 추가 대상 |
|---|---|
| `migrations/platform_core/002_mobile_broker.sql` | `mobile_schema_version`, `mobile_logins`, `mobile_consents` |
| `migrations/neorang_narang/002_mobile_synthetic.sql` | `nn_mobile_synthetic` |

파일명은 002이지만 모바일 marker는 `mobile_schema_version.version=1`이다. 기존 Core·제품 version을 2로 올리지 않는다. runner는 다음 순서로 처리한다.

1. 새 백업 디렉터리 생성·접근 제한 후 관리 연결과 `jesuslife.mobile.migration` advisory lock을 획득한다.
2. 두 DB의 모든 테이블 DDL과 행을 inventory로 읽고 기존 v1 marker와 모바일 marker를 확인한다. 모바일 marker는 없거나 빈 목록 또는 정확히 version 1만 허용한다. 미래/알 수 없는 버전은 layout 생성 전 거부한다. 테이블 이름은 `[a-z_]+`만 허용한다.
3. `snapshot.json`을 독점 생성하고 접근 제한 후 JSON 재읽기 동등성을 검사한다.
4. 새 `core_mobile_layout_<12자리 hex>` DB에서 두 제품의 기존 001 SQL과 모바일 002 SQL 중 CREATE TABLE만 실행하여 MySQL의 정규화된 shape을 구한다. 대상 accounts의 DDL을 정본으로 복사하지 않는다. layout DB는 보존한다.
5. **대상 DB에 DDL을 실행하기 전에 양쪽 DB의 필수 v1 테이블 존재·shape 및 이미 존재하는 모든 모바일 테이블 shape을 비교한다.** 불일치하면 대상 DDL 없이 중단한다. 이후 없는 모바일 테이블만 생성하고 신규 shape도 확인한다. canonical shape 확보에는 별도 layout DB의 DDL이 필요하므로 이 사전 검사는 모든 DB 변경보다 앞서는 검사는 아니다.
6. 양쪽 테이블 shape 확인 후 Core 모바일 marker 1을 기록한다. SQL 파일의 INSERT를 그대로 실행하지 않는다.
7. `platform_core_app`@`%`에 marker는 SELECT, 나머지 새 테이블은 SELECT·INSERT·UPDATE를 부여한다. 기존 권한을 제거하거나 계정 전체 권한을 감사하지 않는다.
8. 기존 비모바일 테이블의 DDL·행이 최초 inventory와 같은지 비교한다. 백업과 layout DB를 남긴다.

Core marker 기록 뒤 GRANT나 최종 비교가 실패할 수 있다. marker 존재만으로 적용 성공을 판단하면 안 된다. 새 테이블은 ALTER·DROP·DELETE하지 않지만 MySQL DDL과 GRANT의 자동 commit 때문에 전체 원자적 rollback은 보장하지 않는다.

부분 DDL 실패 시 올바른 기존 테이블은 재생성하지 않고 누락 테이블만 생성한다. GRANT 중 실패하면 marker와 일부 권한이 남을 수 있으며 성공 출력 없이 실패한다. 새 보호 백업 디렉터리를 지정한 재시도에서 전체 사전 검사와 모든 GRANT를 다시 수행한다. 이는 모의 테스트로만 확인했으며 실제 권한·DDL 재시도는 미검증이다.

## 백업·복구 요구 사항과 미구현 부분

`snapshot.json`은 두 DB 테이블의 schema와 rows를 담으며 binary·datetime을 변환한다. 암호화 백업이 아니라 파일 접근 제한과 재읽기 검사다. 사용자·GRANT·서버 설정·키 보관이나 완전한 DB 객체 복구를 제공하는 범용 백업이 아니다. 이 파일의 재읽기 성공은 격리 DB 복원 성공과 다르다.

적용 전 관리자가 두 DB 전체 및 필요한 권한·키 복구 절차를 확보하고 격리 환경에서 복원을 검증해야 한다. 복원 후 DDL·행·권한·암호화 세션 읽기와 기존 PC/제품 동작을 비교해야 한다. 백업에 포함된 민감 자료와 암호화 키는 저장소 밖에서 보호하고, 값을 출력하지 않는다.

기존 `scripts.core_mysql.py`는 고정 `TABLES`만 백업·복원하며 새 모바일 테이블을 포함하지 않는다. 기존 migrate는 알 수 없는 추가 테이블을 거부하는 경로도 있다. 기존 `scripts.local_mysql.py`의 제품 백업 역시 Core 모바일 전체 복구 수단이 아니다. 모바일 적용 후에는 **모바일 테이블까지 포함하는 전체 DB 백업·복원**이 필요하다.

전용 `scripts.mobile_backup`의 전체 백업·새 격리 DB 복원 리허설 CLI와 offline mock을 추가했다. [백업 리허설 절차](mobile-backup-rehearsal.md)를 따른다. 실제 MySQL 리허설과 실제 복호화는 NOT_RUN이므로 복구 준비 완료로 판단하지 않는다. 기존 snapshot을 원본에 복원하는 명령과 자동 rollback은 제공하지 않는다. 실패하면 API를 중지한 상태로 백업·부분 생성 테이블·layout DB를 보존하고 shape·marker·GRANT와 원본 불변 여부를 조사한다. 재시도는 shape 확인 후 새 백업 디렉터리로만 검토한다. 사용자 기록 초기화나 테이블 삭제로 해결하지 않는다. 이전 코드로 복귀하더라도 추가 테이블·권한은 자동으로 되돌아가지 않는다.

## Auth0 callback과 앱 복귀

| 역할 | 코드의 고정 URI |
|---|---|
| API origin 및 Android 브라우저 시작 | `http://127.0.0.1:8000/api/v1/mobile/authorize` |
| Auth0 authorization/token 교환 callback | `http://127.0.0.1:8000/api/v1/auth/callback/android` |
| 앱 복귀 | `jesuslife-poc://auth/complete/android` |
| 보존되는 PC callback | `http://127.0.0.1:8000/api/v1/auth/callback/web` |

관리자가 별도 승인 아래 기존 Auth0 client의 Allowed Callback URLs에 Android HTTP callback이 허용되는지 확인해야 한다. 앱 custom URI를 Auth0 redirect_uri로 보내는 구현이 아니다. 기존 PC callback도 필요하다. 이번 작업에서는 Auth0 설정을 조회·변경하지 않았다.

앱은 PKCE challenge와 return URI로 `POST /api/v1/mobile/login-transactions`를 호출하고 시스템 브라우저를 연다. 서버는 브라우저 cookie·state·nonce·서버 PKCE로 Auth0와 연결한다. scope는 `openid neorang-narang:read neorang-narang:write`, `prompt=login`이며 `offline_access`는 요청하지 않는다.

서버 callback은 앱 URI에 `transaction`과 일회용 `code`만 붙인다. 앱은 메모리의 transaction·verifier로 `POST /api/v1/mobile/session-exchange`를 호출한다. 로그인 transaction은 최초 300초, handoff는 callback 후 60초이며 일회 소비한다. 반환 `access_token`은 서버 세션용 opaque credential이며 앱은 메모리에만 보관한다. refresh token·앱 재시작 후 자동 세션 복원은 없다. cold start 복귀 intent는 Kotlin에서 버리므로 앱이 종료되면 재로그인이 필요하다.

## API 시작

설정·DB·권한 준비와 실행 승인을 확인한 후 API 루트에서:

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn app.auth0_mobile:app --host 127.0.0.1 --port 8000 --no-access-log
```

모바일 진입점은 `MobileCoreStore`를 주입하고 PC 경로도 유지한다. `app.main:app`은 모바일 진입점이 아니다. `app.auth0_pc:app`에도 모바일 경로는 등록되지만 기본 CoreStore에는 모바일 기능이 없어 모바일 요청은 사용할 수 없다.

startup/import에서 DB 연결이나 migration, Auth0 요청은 하지 않지만 `.env.auth0-pc`를 읽는다. 설정 오류는 runtime 없는 앱으로 조용히 대체되어 인증 요청이 503이 될 수 있다. `/health`의 `jesuslife-pc-poc` 응답은 DB·Auth0·모바일 schema 준비를 검사하지 않는다. 별도 앱에는 기본 `app.main`의 GET `/`가 없으므로 동일 공개 경로 보존을 가정하지 않는다.

## Flutter/Android 구성

모바일 소스의 정본은 실제 Flutter 저장소 `D:\CHGO-VibeCodeing\neorang_narang_app`이다. API 저장소에 남은 `.mobile-stage` 파일은 오래된 자료이며 **적용하면 안 된다**. 이번 작업에서는 Flutter 파일과 stage 내용을 읽거나 수정하지 않았다.

`scripts/stage_mobile_client.py`는 폐기되었다. 기본 실행과 `--apply`를 포함한 모든 실행은 target 파일 접근 전에 안내와 종료 코드 2로 거부된다. stage 준비나 적용 절차로 사용하지 않는다. 잔존 stage 파일은 Git에서 제외하며 최신 수정의 근거가 아니다.

아래 구성 설명은 당시 PoC의 이력이다. 현재 Flutter 소스와의 일치 여부를 이번 작업에서 검증하지 않았으며, 변경·검토·검증은 실제 Flutter 저장소에서 진행한다.
- API origin은 Dart와 Kotlin에서 `http://127.0.0.1:8000`으로 고정되어 있다. `--dart-define`이나 LAN 주소 구성 기능은 없다.
- Android main manifest는 INTERNET, custom URI VIEW/BROWSABLE intent filter, `singleTop`, `flutter_deeplinking_enabled=false`를 설정한다. Kotlin MethodChannel `jesuslife/mobile_browser`의 `open`, `ready`, `returnUri`가 Dart와 맞아야 한다.
- debug에서만 network security XML이 `127.0.0.1`의 HTTP를 허용한다. release·iOS·Web 연결 지원으로 확대 해석하지 않는다. 홈 버튼은 Android에서만 노출된다.
- USB 디버깅·승인된 기기·기존 ADB가 준비된 후 loopback을 PC로 전달하는 후속 명령은 `adb -s <기기ID> reverse tcp:8000 tcp:8000`이다. 앱과 기기의 시스템 브라우저 모두 같은 loopback 경로가 필요하다. 이번에는 실행하지 않았다.

합성 시험 UI의 흐름은 브라우저 로그인 → 별도 동의 저장 → 신규 합성 완료 1건 선택 → 수동 전송/재시도이다. 기존 완료 기록·이름·문답·서명을 읽어 전송하지 않는다. 과정 번호 1/2를 선택하고 현재 UI는 `participation_mode=solo`로 생성한다.

별도 SQLite `neorang_mobile_poc.db`에 계정·generation별 queue와 삭제 대기를 저장한다. 업로드는 수동이며 자동 백그라운드 재시도는 없다. 서버는 동의 세대당 한 건만 허용하고 같은 UUID·동일 payload 재전송을 처리한다. 철회는 서버 metadata를 NULL로 지우고 UUID·owner·generation 장벽을 남긴다. 로컬 queue는 cancelled로 표시하며 payload 자체를 지우지는 않는다. 삭제 대기는 같은 계정 재로그인 후 재개한다. 로그아웃 네트워크 실패 시 서버 세션은 만료 전까지 남을 수 있다.

## 확인된 공백과 검증 한계

- **AUTHOR_REVIEW_REQUIRED**: DB 구조·cross-schema GRANT·인증 경계 및 동의/삭제 의미는 적용 전 사람 검토 대상이다. Core가 제품 adapter와 내부 `CompletionRecordMetadata`를 직접 import하고 같은 connection으로 제품 테이블을 수정한다. 모듈 계약 경계와 cross-schema 결합도 검토가 필요하다.
- **NOT_RUN**: 실제 MySQL DDL·GRANT·부분 실패/재실행·동시성·전체 백업 복원, 실제 Auth0, API startup, ADB, 기기 설치·브라우저·deep link 종단 연결. 모의 검사 성공을 실제 적용 PASS로 처리하지 않는다.
- **사용자 보고 PASS (별도 Flutter 저장소 실행, 이번 작업에서 재실행하지 않음)**: 모바일 테스트 7개, 전체 테스트 198개, Android debug 빌드. 최종 analyze와 실제 모바일 로그인·전송은 **미확인/NOT_RUN**이다.
- `tests/test_mobile_broker.py`는 합성 Auth0와 SQLite dialect adapter를 사용한다. `FOR UPDATE`를 제거하고 SQLite transaction으로 대체하므로 MySQL 잠금·DDL·권한을 입증하지 않는다. `.mobile-stage/test/mobile_sync_test.dart`도 가짜 서버 기반이며 시스템 브라우저·Kotlin·실제 네트워크 검증과 다르다.
- stage 존재는 대상 Flutter 앱 반영 완료 증거가 아니다. 전체 복구 CLI 부재, 실제 설정/권한 미확인, 기기 왕복 미검증이 남아 있어 첫 연결 완료를 주장할 수 없다.

## 삭제 응답 계약

GET/POST `/api/v1/mobile/consent`와 POST `/consent/revoke`는 기존 `generation`, `active`, `deletion_through`, `deletion_status`의 값과 의미를 유지한다. `deletion_status=complete`는 **`deletion_through` 이하 세대의 서버 합성 metadata 삭제 완료**이며 현재 세대나 기기 로컬 payload 전체 삭제를 뜻하지 않는다. UUID·owner·generation 장벽은 남는다.

추가 boolean `current_generation_deletion_complete`는 generation이 1 이상이고 비활성이며, `deletion_status=complete`이고 `deletion_through >= generation`일 때만 true다. 예를 들어 1세대 철회 후 2세대 재동의 응답은 `generation=2, active=true, deletion_through=1, deletion_status=complete, current_generation_deletion_complete=false`다. 기존 필드를 제거하거나 complete를 다른 값으로 바꾸지 않는다. 클라이언트는 삭제 대기의 세대가 deletion_through 이하인지 확인해야 하며 complete만으로 현재 동의의 삭제 완료를 표시하면 안 된다.

이전 세대 철회 재전송은 이전 범위만 지우고 새 동의를 비활성화하지 않는다. 철회된/오래된 세대 전송은 410, 현재 세대 동일 UUID·동일 본문 재전송은 stored/replayed=true, 본문 변경·다른 계정 UUID 사용은 원문이나 소유자를 노출하지 않는 409다.

## Cross-schema 결합 추적과 별도 후속안

현재 경로는 `mobile_routes.install_mobile` → Core `MobileCoreStore.mobile_status` → 제품 `MobileProjectionStore.create/erase`다. Core transaction의 cursor로 `neorang_narang.nn_mobile_synthetic`에 SELECT/INSERT/UPDATE하고 동의 변경과 metadata 삭제를 같은 transaction으로 묶는다. `scripts.mobile_mysql`의 product table GRANT가 `platform_core_app`에 이 접근을 부여한다. 제품 adapter라는 파일 경계만으로 DB 소유권이 분리되지는 않는다. Core route는 제품 내부 `CompletionRecordMetadata`도 직접 import한다.

이번 보완은 권한을 늘리거나 위 원자성을 제거하지 않는다. **후속 변경안/AUTHOR_REVIEW_REQUIRED**: 제품이 소유하는 명시적 명령 계약(계정, generation, idempotency UUID, 합성 payload)을 정의하고 제품 전용 자격으로 실행한다. 동의 철회는 outbox/삭제 작업과 세대 장벽을 통해 전달하며 제품 확인 전에는 pending, 확인된 범위만 complete로 표시한다. 재시도·계정 격리·새 세대 업로드/철회 경쟁을 검증한 다음 Core의 cross-schema GRANT 제거 및 내부 모델 import 교체를 별도 migration/rollback 계획으로 검토한다. 실제 적용에는 계약·권한·최종 일관성 정책의 사람 승인이 필요하다.

## 이번 API 오프라인 검증

`.\.venv\Scripts\python.exe -B -m scripts.test_offline`은 상속 환경을 정리하고 dotenv를 빈 합성 설정으로 대체한 뒤 환경 파일 open, MySQL 연결, 외부 socket 연결/DNS를 차단하고 테스트를 import한다. Windows asyncio의 표준 socketpair 내부 loopback 연결만 예외다. 실제 서버는 열지 않는다. 기존 API 응답·OpenAPI·PC 인증 회귀와 모바일 회귀를 포함한다.

최종 결과: 114개 중 **92 PASS, 22 SKIP**(실제 MySQL/Core opt-in). 모바일 migration 모의 테스트 8개는 부분 DDL 후 재시도, 양쪽 모바일/기존 v1 형태 불일치·필수 테이블 누락·미래 버전, GRANT 실패 후 재시도를 확인한다. 파일 백업 재읽기는 복구 검증이 아니다. 실제 복원은 NOT_RUN이며 복구 도구 공백은 그대로 남는다. 첫 실행은 Windows 내부 socketpair까지 차단하여 FAIL했고 가드를 좁혀 수정한 후 위 결과를 얻었다.

`pip check`와 `git diff --check`는 환경/패치 검사이며 외부 연동 성공과 별개다. 음성 검증 테스트의 `auth_callback ... result=FAIL` 로그는 의도된 거부 시나리오이며 unittest 실패 수와 구분한다.

실행 결과는 `.\.venv\Scripts\python.exe -B -m pip check` PASS, `git diff --check` PASS, app/tests/scripts의 Python 49개 `ast.parse` PASS이며 각각 종료 코드 0이다. 미추적 보완 파일 9개는 `git -c core.autocrlf=false -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --no-index --check -- NUL <파일>`로도 공백 오류를 검사했다(PASS). 일반 diff 검사는 미추적 파일을 포함하지 않는다. no-index의 새 파일 차이 종료 코드 1은 공백 오류와 구분하고, 진단 출력이 비어 있는지 확인했다. 최초 보조 검사에서는 이를 실패로 판정했으나 판정 기준을 바로잡고 CRLF 줄 끝을 허용하여 재검사했다.

근거: `scripts/mobile_mysql.py`, 두 `002_*.sql`, `app/auth0_mobile.py`, `app/auth0_pc.py`, `app/core/{mobile_routes,mobile_store,core_store,database,auth0_provider}.py`, `app/modules/neorang_narang/mobile_store.py`, `scripts/{auth0_pc_settings,core_mysql,local_mysql,stage_mobile_client}.py`, `.mobile-stage`의 Dart/Kotlin/manifest/XML 및 모바일 테스트, 대상 앱 `pubspec.yaml`.
