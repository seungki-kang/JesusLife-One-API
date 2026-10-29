# 노출 자격 교체 결과

2026-10-29. 사용자 요청 범위에서 로컬 Core DB 비밀번호와 HMAC/AES-GCM 키를 교체했다.
값·암호문·사용자 자료·SQL 예외 원문은 출력하지 않았다. 기존 미커밋 변경을 보존했다.

- PASS: HTTP 8000 서버 미실행 확인 후 대상 앱 DB 계정 잠금 및 기존 DB 연결 종료.
- PASS: 기존 access token과 PKCE 암호문 전체를 이전 키로 인증 복호화. token의 기존 HMAC 결합 확인.
- PASS: 모든 암호문을 새 키로 재암호화하고 token fingerprint도 새 HMAC으로 변경, 새 결합 검증.
- PASS: 모든 기존 세션 폐기, pending/exchanging 로그인 failed 처리. token 행은 삭제하지 않음.
- PASS: DB 계정 비밀번호와 설정 일치, 새 비밀번호 접속 및 기존 비밀번호 1045 거부 확인.
- PASS: Core 모든 표 행 수 보존. 계정·외부 identity·동의·schema 행 동일. 제품 DB 모든 행 동일.
- PASS: `python -B -m unittest discover -s tests`: 80건 중 59 실행 성공, 21 skip.
- PASS: `python -B -m pip check`, `git diff --check`.
- NOT_RUN: opt-in DB 통합 suite, 외부 Auth0 tenant, 브라우저 재로그인.

변경 파일: `.env.auth0-pc`(Git 제외), `scripts/rotate_core_secrets.py`, 이 기록.
실행 명령: `.venv\Scripts\python.exe -B -m scripts.rotate_core_secrets`.
AUTHOR_REVIEW_REQUIRED에 해당하는 자격/세션 조치는 이번 사용자의 명시적 교체 요청 범위로 실행했다.
DB 구조·제품 소유권·동의 내용은 변경하지 않았다. 서비스 시작/배포는 하지 않았다.

복구 자료는 Git 밖 접근 제한 폴더에 보관했다. 로컬 `.env.core-rotation-location`이 위치를 가리킨다.
`recovery.json`은 이전/신규 설정과 교체 직전 Core 행을 포함하며 `COMPLETE`가 성공 확인이다.
이전 키는 과거 백업 복구를 위해 보존하며 노출된 키를 다시 활성화하지 않는다.
기존 백업의 복호화에는 이전 키가 필요하다. 복원 시 새 키로 재암호화하고 전체 세션을 폐기해야 한다.
이 복구 bundle은 접근 제한 JSON이며 별도 암호화나 독립 저장장치 복원 실험은 하지 않았다.
실패 시 자동 롤백하지 않는다. 보호 bundle과 실제 DB/설정 단계를 확인하고 수동 복구한다.
도구는 기존 receipt가 있으면 재실행을 거부한다. 새 사고의 반복 실행 도구로 사용하지 않는다.
Auth0 SSO 세션/발급 JWT의 IdP 전역 취소는 수행하지 않았다. 로컬 세션만 모두 폐기했다.
