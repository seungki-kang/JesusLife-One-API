# Core DB 적용·PC callback·영속 세션 검증

2026-10-29, `feature/nn-completion-contract`. 사용자 명시 승인: 별도 Core DB·전용 계정·
migration 적용/합성 검증, callback/영속 세션 구현. 유료·운영·실제 기록 이전/삭제는 제외.

## 변경과 적용

- `migrations/platform_core/001_pc_auth.sql`: 재검토한 Core 7개 표. binary identity UNIQUE,
  identity/account 일치 FK, token fingerprint UNIQUE, 세션 폐기·동의·로그인 단일 소비.
- `scripts/core_mysql.py`: 충돌 거부 bootstrap, 관리/실행 계정 분리, canonical schema 비교,
  named lock·상위 버전 거부·부분 DDL 재개, 제품 기존 행 보존, 접근 제한 백업/별도 복원.
- `app/core/core_store.py`: 실제 MySQL 트랜잭션, 원자적 identity 매핑, 암호화 token/verifier,
  hash cookie/state/nonce/CSRF, 영속 세션·동의·폐기. product DB 접근 없음.
- `app/core/auth0_provider.py`: 고정 Auth0 HTTPS origin, RS256 JWKS·제한된 cache/unknown kid 갱신,
  code+PKCE 교환, ID nonce/issuer/client audience/서명/시간/선택 at_hash, RFC9068 access 검증.
- `app/auth0_pc.py`: 별도 loopback PoC 진입점, 로그인/callback/me/동의/logout/최소 PC 화면,
  Host·Origin·CSRF·no-store·no-referrer. token/secret은 브라우저에 반환하지 않음.
- `app/core/auth.py`: 명시적으로 설치된 PC runtime만 인증에 사용. 기존 main은 계속 401.
- `requirements.txt`: 이미 설치된 httpx 0.28.1을 실제 runtime 의존성에 명시. 설치 작업 없음.
- `scripts/auth0_pc_settings.py`: PC 진입점의 설정 소비 상태 설명 갱신.
- `tests/test_core_persistence.py`, `tests/test_auth0_pc_http.py`, `scripts/verify_core.py`:
  실제 MySQL + 합성 HTTP/JWT, 새 Python 프로세스 재시작 증거, 비밀 비출력 실행기.
- `docs/local-core-auth.md`, 첫 PC 안내 갱신, 이 결과 문서.

적용 전 root 읽기 전용 점검에서 `platform_core`와 같은 이름의 두 계정이 없음을 확인했다.
새 이름으로만 생성했다. 재실행/동일 이름 collision은 덮어쓰지 않고 거부한다.

역할:

| 계정 | 최종 권한 |
|---|---|
| `platform_core_app` | Core 6개 자료 표 SELECT/INSERT/UPDATE, version 표 SELECT. DDL/DELETE/제품 DB 거부 |
| `platform_core_migrator` | Core CREATE/INDEX/REFERENCES, version 표 SELECT/INSERT. 자료 SELECT/INSERT/UPDATE/DELETE·제품 DB 거부 |
| 기존 제품 계정 | 변경 없음. Core 접근 거부 |
| 기존 root | bootstrap/백업 등 명시적 관리만. runtime 사용 안 함 |

최초 bootstrap에서 버전 receipt의 불필요한 ON DUPLICATE KEY UPDATE가 migrator에
UPDATE를 요구하여 1142로 중단됐다. INSERT SELECT WHERE NOT EXISTS로 수정했다.
표·계정·암호를 재생성하지 않고 own manifest/credential로 부분 지점에서 재개했다.
bootstrap 동안 schema 생성에 사용한 넓은 SELECT/INSERT 권한도 제거하고 최종 권한을 검증했다.
동의 INSERT alias의 generation 모호성(1052)도 명시적인 표 이름으로 수정 후 회귀를 통과했다.
오류 원문·SQL·자격은 출력하지 않았다.

## 실제 실행 결과

Python은 기존 `.venv\Scripts\python.exe -B`를 사용했다. 최종 성공 명령은 종료 코드 0이다.

| 상태 | 명령/범위 | 증거 |
|---|---|---|
| PASS | `python -B -m scripts.core_mysql preflight` | 적용 전 대상 이름 없음, 적용 후 Core 존재. Auth0 configured=False |
| PASS | `bootstrap` → `finish-bootstrap` | 위 receipt 권한 문제 수정 후 비파괴 재개·역할 권한 축소 완료 |
| PASS | `python -B -m scripts.core_mysql migrate` 반복 | canonical 표 구조/버전 일치, 데이터 무변경 재실행 |
| PASS | `python -B -m scripts.verify_core tests` 최종 | **80개, failures=0, errors=0, skipped=0** |
| PASS | 기존 MySQL suite | 9개 포함. 새 Core 통합 12개·미설정 PC HTTP 2개 포함 |
| PASS | 실제 MySQL 동시 최초 code callback | 새 두 연결/세션에 공통 UUID 1개, 고아 account 없음 |
| PASS | identity 구분 | 동일 sub의 다른 issuer, 대소문자 다른 sub는 별개 UUID. 이메일 병합 코드/열 없음 |
| PASS | 트랜잭션·단일 소비·재등록 차단 | 실패 후 rollback, callback 재생/만료/nonce/cookie/중복 query 거부, 폐기 JWT 재결합 거부 |
| PASS | 실제 JWT crypto + 모의 Auth0 HTTP | RSA 서명/JWKS, PKCE, nonce·ID/access identity·audience·scope 등. 실제 Auth0 접속 아님 |
| PASS | 합성 A/B 제품 API | 별도 동의 전 403, 본인만 접근. B의 A 단건/수정/삭제 404, CSRF·Origin 거부 |
| PASS | logout·새 앱/새 Python 프로세스 | A 구 bearer 401, B/다른 활성 세션 유지, 프로세스 재생성 후 활성/폐기 상태 동일 |
| PASS | migration collision/부분 설치/상위 버전/다른 표 구조 | 별도 check DB에서 검증. mismatch·future version 변경 없이 거부, 반복 동일 |
| PASS | 권한 격리 | app DDL/DELETE/version UPDATE 거부, migrator 업무 read/write 거부, 양쪽 제품↔Core 접근 거부 |
| PASS | `python -B -m scripts.verify_core backup-verify` | 접근 제한 외부 JSON 백업 → 새 Core restore DB에 복원, 모든 표/행·폐기/암호문 상태 동일 |
| PASS | `python -B -m scripts.core_mysql verify-products` | 시작 시 기존 제품 모든 행의 digest와 표 목록 보존. 신규 합성 행 추가는 허용 |
| PASS | `python -B -m pip check` | 의존성 충돌 없음 |
| PASS | Python AST·문서 상대 링크·공백, `git diff --check` | 문법/링크/공백 검사 통과 |
| PASS | `Get-Service *maria*`, `Get-NetTCPConnection ...` | MariaDB Running, 기존 3306, 새 MySQL 127.0.0.1:3307 유지 |

TCP 조회는 최초 sandbox 접근 거부 후 승인된 읽기 전용 실행으로 확인했다.
기존 공개 경로·OpenAPI·401·owner/revision·메모리/API 회귀도 전체 suite에 포함된다.
백업 검사는 지금의 합성 Core 자료에 대한 복원이며 실제 원본 DB에 restore하지 않았다.
민감자료가 든 운영 백업·PITR·보유기간·부하 검증 성공을 뜻하지 않는다.

## 실제 Auth0 연결: NOT_RUN

`AUTH0_ISSUER`·`AUTH0_CLIENT_ID`·`AUTH0_CLIENT_SECRET`이 비어 있어 실제 연결은 하지 않았다.
따라서 실제 tenant의 profile/claim, key rotation, 실제 A/B 로그인/SSO/로그아웃은 NOT_RUN이다.
합성 server token을 실제 Auth0 성공으로 보고하지 않는다. mocked transport는 테스트 파일에만
있고 앱의 요청·헤더·설정에서 켤 수 없다. 앱은 실제 provider 검증 또는 fail-closed만 수행한다.

로컬 `.env.auth0-pc`에 공개 issuer/client ID와 secret을 입력한 뒤
`python -B -m scripts.auth0_pc_settings check`로 형식을 확인한다. 값은 출력하지 않는다.
실행은 [로컬 Core 안내](../local-core-auth.md)의 별도 `app.auth0_pc:app`, loopback 8000,
`--no-access-log`를 사용한다. 기존 `app.main:app`은 그대로 닫혀 있다.

## 보존·복구·한계

- `.env`/제품 암호/제품 SQL·service/store 기존 수정은 보존했다. `.env.auth0-pc`의 빈 Core DB
  비밀번호만 새 암호로 채우고 접근 제한을 재적용했다. Auth0 값·기존 key는 변경하지 않았다.
- 합성 fixture·신규 layout/check/restore DB를 보존했다. DROP·TRUNCATE·사용자 기록 물리 삭제,
  owner 자동 매핑/이전·MariaDB 재설정·컨테이너/volume 삭제 없음.
- 별도 접근 제한 `.env.core-admin`, `.env.core-schema`, 제품 digest baseline과 backup-location은
  Git 제외다. key/암호/행/claim/code 원문을 로그·결과에 출력하지 않았다.
- rollback은 PoC 진입점을 중지하고 기존 main의 401로 복귀한다. DB/세션/기록은 보존한다.
  원본 Core 백업 복원 시에는 세션 전체 폐기·재로그인 계획이 필요하며 자동 복원하지 않았다.
- 단일 schema 0→1·부분 실패 재개만 대상이다. 미래 버전 upgrade/down migration은 미존재다.
- 자체 제한형 JWT parser는 개발 PoC다. 운영 라이브러리/보안 검토, TLS/Secure cookie,
  rate limit·IdP 복구/보안 이벤트·세션 정리/보유기간·운영 모니터링은 별도 검증 대상이다.
- 패키지 설치·유료 가입·운영 배포·git add/commit/push는 하지 않았다.
