# JesusLife One API

현재 FastAPI 시작 골격이며 앱 버전은 0.1.0입니다.

## 현재 기능

- GET /: 실행 안내 메시지
- GET /health: status, service, version 반환
- GET /api/v1/neorang-narang/health: 너랑나랑 모듈 상태 반환
- /docs, /redoc, /openapi.json: FastAPI 기본 API 문서

DB, 실제 인증 제공자 연결, 너랑나랑을 포함한 제품별 업무 API는 아직 구현하지 않았습니다.

`app/core/auth.py`는 공통 계정 UUID `sub`만 보유하는 불변 `AuthContext`,
기본적으로 항상 401을 반환하는 `get_current_user`, 서버가 보유한 owner sub와
현재 sub가 다르면 403을 반환하는 `require_record_owner` 기반을 제공합니다.
본문·쿼리·미검증 헤더로 인증하거나 소유자를 결정하지 않습니다. 새 기록의 소유자는
향후 검증된 `current_user.sub`에서 정해야 합니다. 인증 오류는 고정 메시지만 반환하며
이 코드에서 사용자 ID나 민감 원문을 로깅하지 않습니다. 모델 검증 오류를 외부에
반환할 때에도 입력을 포함한 오류 자료를 직렬화하지 않아야 합니다.

기존 공개 경로에는 인증을 추가하지 않았습니다. 테스트 전용 앱에서만 dependency
override와 합성 UUID로 401·403·동일 소유자 통과를 검증합니다. 실제 제공자 검증,
세션·scope·동의와 운영 로그 보호는 별도 AUTHOR_REVIEW_REQUIRED입니다.
설계 초안의 향후 조회 API 404 정책과 이번 공통 guard의 403은 구분하며,
기록 API를 연결하기 전에 외부 오류 계약을 검토해야 합니다.

너랑나랑 상태 응답은 `{"status":"ok","service":"neorang-narang","version":"0.1.0"}`입니다.
`app/modules/neorang_narang/router.py`에서 모듈 경로를 정의하고 `app/main.py`에서 등록합니다.
이 상태 경로는 DB나 외부 서비스의 가용성을 검사하지 않습니다.

## 로컬 실행

현재 보존된 .venv는 Python 3.14.8 환경입니다. 프로젝트 루트에서 PowerShell로 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000/health 또는 http://127.0.0.1:8000/docs를 확인합니다.

requirements.txt에는 현재 실행에 직접 필요한 FastAPI와 Uvicorn만 명시합니다. 전체 전이 의존성 lock 파일은 아닙니다.

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

이 폴더는 독립 Git 저장소입니다. 상위 저장소는 수정하지 않습니다. .env·가상환경·캐시를 추적하지 않으며, .env.example을 만들 경우 비밀정보 없는 예시만 넣습니다.
