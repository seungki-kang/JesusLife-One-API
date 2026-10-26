# JesusLife One API

현재 FastAPI 시작 골격이며 앱 버전은 0.1.0입니다.

## 현재 기능

- GET /: 실행 안내 메시지
- GET /health: status, service, version 반환
- /docs, /redoc, /openapi.json: FastAPI 기본 API 문서

DB, 인증, 너랑나랑을 포함한 제품별 업무 API는 아직 구현하지 않았습니다.

## 로컬 실행

현재 보존된 .venv는 Python 3.14.8 환경입니다. 프로젝트 루트에서 PowerShell로 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000/health 또는 http://127.0.0.1:8000/docs를 확인합니다.

requirements.txt에는 현재 실행에 직접 필요한 FastAPI와 Uvicorn만 명시합니다. 전체 전이 의존성 lock 파일은 아닙니다.

## 검증과 관리

```powershell
.\.venv\Scripts\python.exe -B -m pip check
```

기존 자동 테스트 스위트는 아직 없습니다. 변경 시 GET /, GET /health, GET /openapi.json을 회귀 확인합니다.

이 폴더는 독립 Git 저장소입니다. 상위 저장소는 수정하지 않습니다. .env·가상환경·캐시를 추적하지 않으며, .env.example을 만들 경우 비밀정보 없는 예시만 넣습니다.
