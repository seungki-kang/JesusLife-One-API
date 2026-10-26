# JesusLife API Codex 작업 지침

출처: JesusLife_Auto_Agents_v1.5/templates/jesuslife-api.AGENTS.md를 현재 프로젝트에 맞게 적용.

## 현재 프로젝트와 작업 범위

- 프로젝트 루트는 D:\CHGO-VibeCodeing\JesusLife-One-API이다. 상위 D:\CHGO-VibeCodeing 저장소와 별도로 관리한다.
- 모든 작업에 jesuslife-platform-development 공통 보호 규칙을 적용한다. 설계는 jesuslife-platform-design, 구현·검증은 jesuslife-platform-implementation으로 분류한다.
- 현재 app/main.py는 GET /와 GET /health만 구현한다. FastAPI 기본 문서는 /docs, /redoc, /openapi.json에서 제공된다.
- 현재 DB, 인증, 제품별 업무 API는 구현되지 않았다. 모듈 추가는 별도 승인된 범위에서 진행한다.
- 기존 app 코드와 가상환경을 보존한다. 상위 저장소의 파일·Git 설정·.gitignore를 수정하지 않는다.

## 향후 모듈 경계

초기 구조는 하나의 FastAPI 배포 안에서 제품별 경계를 지키는 모듈형 모놀리스다. 아래는 향후 책임 구분이며 현재 구현을 뜻하지 않는다.

- core: 설정, 인증, 동의, 권한, 오류, 감사
- churchos: 교회, 조직, 역할, 화이트라벨
- bible: 성경 읽기와 통독
- prayer: 기도와 중보
- neorang_narang: 문답 세션과 완료
- life_diary: 일기와 음성 전사
- academy: 교육 과정과 수료
- chgo: 의미·근거·추론 연동

## 작업 시작

1. 현재 경로, git rev-parse --show-toplevel, 브랜치, Git 상태를 확인한다.
2. AGENTS.md, README.md, 의존성 명세와 대상 코드를 읽는다.
3. Python·의존성·검증 명령을 확인하고 기존 변경을 보존한다.
4. 대상 모듈, 데이터 원본, API 계약, 권한, 실패·재시도 정책을 먼저 정한다.
5. 제품 내부 모델을 다른 모듈에서 직접 참조하지 않도록 계약 경계를 유지한다.

## 보호 규칙

- 토큰, 비밀키, 실제 비밀번호와 실제 사용자 자료를 저장소·로그·추적·예외에 넣지 않는다.
- .env와 가상환경을 추적하지 않는다. .env.example에는 비밀정보 없는 예시만 허용한다.
- 사용자·교회·역할 ID를 구분한다. 함께 참여나 소속은 개인 기록 공유 동의가 아니다.
- 이름·기도문·은혜 기록·일기·서명은 민감 자료로 다루며 합성 자료로 검증한다.
- 승인된 교재·신학 문구와 학습 표시를 임의로 바꾸지 않는다.
- DB 구조·인증 경계·개인정보 공유 변경은 AUTHOR_REVIEW_REQUIRED로 분류한다.
- migration은 이전 버전 업그레이드·롤백·백업·복구 계획과 함께 검증한다. 사용자 기록을 임의로 초기화하거나 영구 삭제하지 않는다.
- 패키지 설치, 외부 API 연결, 실제 개인정보 수집과 배포는 승인 범위를 먼저 확인한다.
- 이번 저장소 분리 작업에서는 git add, commit, push, merge, tag, release, 배포를 하지 않는다. 후속 작업도 해당 행동의 사용자 승인을 확인한다.

## 검증

- 현재 기존 테스트 스위트와 formatter·linter·type checker 설정은 없다. 설치되지 않은 도구를 자동 설치하지 않는다.
- 현재 환경은 .venv의 Python 3.14.8이다. 바이트코드 생성을 막는 검사에는 .venv\Scripts\python.exe -B를 사용한다.
- 현재 최소 회귀 범위는 GET /, GET /health, GET /openapi.json의 응답과 경로 보존이다.
- 패키지 일관성은 .venv\Scripts\python.exe -B -m pip check로 확인한다.
- 후속 변경은 관련 회귀 테스트와 프로젝트에 정의된 검증 절차를 적용한다. 실행하지 않은 검사는 NOT_RUN으로 보고한다.
- 결과를 PASS, FAIL, NOT_RUN, BLOCKED, AUTHOR_REVIEW_REQUIRED로 구분하고 변경 파일·검증 명령·한계를 보고한다.
