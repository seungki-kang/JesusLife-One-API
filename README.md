# JesusLife One API

PostgreSQL 역할 분리·RLS 합성 검증과 롤백·복구 절차는
[로컬 PostgreSQL RLS 기반](docs/local-postgres-rls.md)을 참조하세요.
실제 API 연결과 원격 적용은 보류 상태입니다.

현재 FastAPI 시작 골격이며 앱 버전은 0.1.0입니다.

## 현재 기능

- GET /: 실행 안내 메시지
- GET /health: status, service, version 반환
- GET /api/v1/neorang-narang/health: 너랑나랑 모듈 상태 반환
- /docs, /redoc, /openapi.json: FastAPI 기본 API 문서

너랑나랑 완료 메타데이터는 개발용 메모리 저장소 또는 로컬 MySQL에 저장할 수 있습니다.
이번 로컬 환경의 `.env`는 MySQL을 선택합니다. `.env`나 명시적 설정이 없으면 기존 메모리
모드이며, 메모리 모드는 재시작 시 자료가 사라지고 다중 worker에서 공유되지 않습니다.
계약과 제한은 [정책 문서 14절](docs/architecture/nn-auth-ownership-sync-policy.md),
구성과 migration·백업·복구는 [로컬 MySQL 안내](docs/local-mysql.md)를 참조하세요.
모바일 migration 전후의 전체 백업·격리 복원 도구와 실제 실행 전 조건은
[모바일 백업 리허설](docs/mobile-backup-rehearsal.md)에 정리했습니다. 실제 MySQL 리허설은 NOT_RUN입니다.
기본 `app.main:app`의 기록 API 인증은 항상 401입니다. 별도 개발 진입점
`app.auth0_pc:app`은 Core 영속 세션과 실제 Auth0 PC 연결을 제공합니다.
[실행 안내](docs/local-core-auth.md)와 [사용자 전달 A/B 인수 PASS](docs/verification/2026-10-30-auth0-ab-acceptance.md)를 참조하세요.
[API 재시작 세션 복원·MySQL 체크포인트 비교](docs/verification/2026-10-30-restart-verification.md)는 사용자 전달 PASS입니다.
MySQL 실제 중지·재시작은 실행 로그 미확인이며, 모바일·운영 배포는 NOT_RUN입니다.

`app/core/auth.py`는 공통 계정 UUID `sub`만 보유하는 불변 `AuthContext`,
기본 앱에서는 401을 반환하고 별도 PC 앱에서는 검증된 runtime을 사용하는 `get_current_user`, 서버가 보유한 owner sub와
현재 sub가 다르면 403을 반환하는 `require_record_owner` 기반을 제공합니다.
본문·쿼리·미검증 헤더로 인증하거나 소유자를 결정하지 않습니다. 새 기록의 소유자는
향후 검증된 `current_user.sub`에서 정해야 합니다. 인증 오류는 고정 메시지만 반환하며
이 코드에서 사용자 ID나 민감 원문을 로깅하지 않습니다. 모델 검증 오류를 외부에
반환할 때에도 입력을 포함한 오류 자료를 직렬화하지 않아야 합니다.

기존 공개 경로에는 인증을 추가하지 않았습니다. 테스트에서는 dependency
override와 합성 UUID로 401·403·동일 소유자 통과를 검증합니다. 운영 제공자 검증,
세션·scope·동의와 운영 로그 보호는 별도 AUTHOR_REVIEW_REQUIRED입니다.
설계 초안의 향후 조회 API 404 정책과 이번 공통 guard의 403은 구분하며,
완료 기록 API는 소유자 필터를 적용하고 guard 거부도 동일한 404로 변환합니다.

너랑나랑 상태 응답은 `{"status":"ok","service":"neorang-narang","version":"0.1.0"}`입니다.
`app/modules/neorang_narang/router.py`에서 모듈 경로를 정의하고 `app/main.py`에서 등록합니다.
이 상태 경로는 DB나 외부 서비스의 가용성을 검사하지 않습니다.

## 로컬 실행

PostgreSQL 설정 계약은 `app/core/postgres_settings.py`의
`load_postgres_runtime_settings()`와 `load_postgres_migration_settings()`로 분리합니다.
각각 `JESUSLIFE_POSTGRES_RUNTIME_DSN`, `JESUSLIFE_POSTGRES_MIGRATION_DSN`을
프로세스 환경(또는 명시적으로 전달한 매핑)에서 검증하며 `.env`를 자동으로 읽지 않습니다.
`app/core/postgres.py`의 `connect_runtime()`과 `connect_migration()`을 명시적으로
호출할 때만 독점 연결을 생성합니다. import·FastAPI 시작·기존 요청에는 연결하지 않습니다.
`psycopg[binary]==3.3.8`을 사용하며 Python 3.14 Windows binary wheel을 검증합니다.
두 함수는 기존 설정 검증 후 `connect_timeout=5`, 목적별 `application_name`
(`jesuslife_runtime`, `jesuslife_migration`), UTC 세션을 적용합니다.
기본 `autocommit=False`를 유지하며 반환 연결의 transaction·종료는 호출자 책임입니다.
연결 오류는 고정 `PostgresConnectionError`로 변환합니다. 반환 연결로 수행하는 업무
쿼리·commit 오류도 호출 계층에서 비밀정보 없는 오류로 변환해야 합니다.
`probe_runtime()`은 명시적 호출 시 `SELECT 1`만 실행하고 commit 없이 cursor와 연결을
닫습니다. 쿼리·정리 실패도 고정 오류로 처리하며 자동 재시도는 없습니다.
실제 Supabase 접속과 migration 실행은 검증하지 않았습니다. pool은 배포 형태와
session/direct mode 확정 후 별도 작업입니다.
runtime 환경에는 runtime 자격증명만, 별도 migration 환경에는 migration 자격증명만
제공합니다. 두 값이 함께 있으면 같은 서버·포트·DB·사용자 조합은 거부합니다.
이는 실제 DB 역할·권한 분리 검증을 대신하지 않습니다.
URI는 `postgresql` 또는 `postgres` 스킴, 사용자·비밀번호·호스트·DB를 요구합니다.
쿼리 옵션은 `sslmode` 하나만 허용하며 원격은 `require`, `verify-ca`, `verify-full`을
요구합니다. TLS 생략은 정확한 loopback 호스트에서만 허용합니다.
설정 객체의 repr/str과 고정 오류 메시지는 DSN을 숨기지만 `.dsn`은 비밀값이므로
직렬화·로그 출력하지 않습니다. `.env.example`은 합성 placeholder입니다.
**Flutter에 DSN을 넣지 않습니다.** Flutter → FastAPI → PostgreSQL 경계를 유지하며
실제 비밀정보 저장 위치·역할 생성·연결은
[전환 결정서](docs/architecture/postgres-transition-decision.md)의 후속 승인 범위입니다.

현재 보존된 .venv는 Python 3.14.8 환경입니다. 프로젝트 루트에서 PowerShell로 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000/health 또는 http://127.0.0.1:8000/docs를 확인합니다.

requirements.txt에는 FastAPI·Uvicorn·MySQL 드라이버와 환경 파일 로더를 명시합니다. 전체 전이 의존성 lock 파일은 아닙니다.

## 검증과 관리

현재 환경의 설치된 패키지를 사용하여 먼저 검사합니다. 테스트는 표준 `unittest`와
FastAPI `TestClient`를 사용하며 실제 네트워크 서버를 열지 않습니다.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B -c "import ast; from pathlib import Path; files = sorted(Path('app').rglob('*.py')) + sorted(Path('tests').rglob('*.py')); [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in files]; print(f'{len(files)} Python files: syntax OK')"
.\.venv\Scripts\python.exe -B -m pip check
git diff --check
git status --short
```

테스트는 GET /, GET /health, GET /api/v1/neorang-narang/health의 정확한 응답,
GET /openapi.json의 경로·메타데이터, 잘못된 경로의 404를 검증합니다.
문법 검사는 바이트코드 파일을 생성하지 않는 `ast.parse` 방식입니다.

`requirements-dev.txt`는 실행 의존성과 테스트용 `httpx` 및 전이 의존성의 버전을
검증 환경 기준으로 고정합니다. 테스트 실행기는 Python 내장 모듈이므로 pytest는 필요하지 않습니다.
새 개발 환경에서는 Python 3.14.8 가상환경을 준비한 후, 패키지 설치가 승인된 경우에만 실행합니다.

```powershell
.\.venv\Scripts\python.exe -B -m pip install -r requirements-dev.txt
```

이는 해시를 포함한 배포용 lock 파일은 아니며, 다른 운영체제·Python 버전이나
새 환경에서의 설치 재현 검증은 별도로 필요합니다.

### 오프라인 CI

`.github/workflows/offline-tests.yml`은 main 대상 PR(초안 포함)과 main 및
feature/nn-completion-contract push에서 Ubuntu 24.04·Python 3.14.8로 실행합니다.
제한 시간은 10분, 권한은 `contents: read`이며 `requirements-dev.txt`의 기존
고정 의존성을 설치한 뒤 `python -B -m pip check`와
`python -B -m scripts.test_offline`을 실행합니다. 로컬 명령은
`.\.venv\Scripts\python.exe -B -m scripts.test_offline`입니다.
러너는 테스트 import 전에 상속 환경을 정리하고 환경 파일·MySQL·외부 네트워크를
차단합니다. 합성 임시 SQLite와 mock만 사용하며 실제 DB·Docker·Auth0·비밀정보는
필요하지 않습니다. 기존 opt-in skip과 unittest의 전체/skip 집계를 유지합니다.
로컬 검증은 134개 중 112개 PASS·22개 SKIP이며, GitHub에서의 실행 결과는 별도입니다.
액션 SHA는 공식 [checkout v4.2.2](https://github.com/actions/checkout/releases/tag/v4.2.2)와
[setup-python v5.6.0](https://github.com/actions/setup-python/releases/tag/v5.6.0)의
커밋 링크에서 확인했습니다.

이 폴더는 독립 Git 저장소입니다. 상위 저장소는 수정하지 않습니다. .env·가상환경·캐시를 추적하지 않으며, .env.example을 만들 경우 비밀정보 없는 예시만 넣습니다.
