# 실제 계정 A/B PC 브라우저 인수 검증 완료 기록

2026-10-30. 브랜치 `feature/nn-completion-contract`. 기존 미커밋 변경 보존.

## 범위와 증거

| 구분 | 결과 | 근거 |
|---|---|---|
| 실제 Auth0 로그인 → Core 세션, 로그인/로그아웃 표시 | PASS (사용자 확인) | 이번 작업 시작 전 사용자의 브라우저 확인. 에이전트 재실행과 구분 |
| 자동 A/B 계약·실제 로컬 MySQL | PASS | `python -B -m scripts.verify_core tests`: 94 tests, 실패/오류/skip 0 |
| 기존 제품 자료 보존 | PASS | 위 runner의 기존 제품 snapshot 보존 검사 |
| Python 문법·의존성·diff 공백 | PASS | 아래 검증 명령, 종료 코드 0 |
| 실제 A 재로그인 UUID 내부 비교 | PASS (사용자 전달) | same_account_relogin: true |
| 실제 B의 별도 계정 확인·별도 동의·양방향 격리 | PASS (사용자 전달) | distinct_b: true, acceptance: PASS, A/B 각 19개 PASS |

자동 검증은 합성 서명 JWT/Auth0 교환과 실제 로컬 Core·제품 MySQL을 사용했다.
위 자동 검증 자체를 실제 Auth0 A/B 인수 PASS의 근거로 사용하지 않는다. 음성 테스트의 `stage=... result=FAIL`은
잘못된 인증 입력 거부 증거이며 suite 실패와 구분한다. 준비 중 새 테스트의 로그아웃 후
CSRF 헤더 구성 오류 1건을 수정했고, 최종 전체 suite는 위와 같이 통과했다.

## 2026-10-30 사용자 전달 최종 결과

실행 주체는 사용자다. 사용자가 실제 Auth0 전용 테스트 계정 A/B로 PC 브라우저에서
실행하고 전달한 결과를 기록한다. 에이전트가 실제 로그인이나 Dashboard 조작을
직접 실행·관찰하거나 이번 문서 작업에서 재실행한 결과가 아니다.

- `same_account_relogin: true`
- `distinct_b: true`
- `acceptance: PASS`
- A 19개, B 19개 검사 모두 PASS (총 38개).

| 검사 항목 | A | B |
|---|---|---|
| fresh_id | PASS | PASS |
| create | PASS | PASS |
| own_get | PASS | PASS |
| own_create_retry | PASS | PASS |
| list | PASS | PASS |
| foreign_get | PASS | PASS |
| foreign_update_retry_0 | PASS | PASS |
| foreign_delete_retry_0 | PASS | PASS |
| foreign_update_retry_1 | PASS | PASS |
| foreign_delete_retry_1 | PASS | PASS |
| shared_fresh | PASS | PASS |
| shared_create | PASS | PASS |
| shared_create_retry | PASS | PASS |
| update | PASS | PASS |
| stale_update_retry | PASS | PASS |
| delete | PASS | PASS |
| delete_retry | PASS | PASS |
| deleted_get | PASS | PASS |
| deleted_create_retry | PASS | PASS |

### 사용자 전달 장애 및 조치

1. 기존 MySQL 컨테이너가 중지되어 `127.0.0.1:3307` 연결에 실패했다.
   기존 mysql 서비스를 시작한 후 연결 및 인증 DB 검증이 통과했다.
2. API에 미등록된 `neorang-narang:read`, `neorang-narang:write`를 추가했다.
3. `jl-core-poc-pc`의 User-Delegated Access에서 두 권한을 명시적으로 허용하고
   2/2 저장을 확인했다. A 재로그인 후 검사가 통과했다.
   **Always grant all permissions는 사용하지 않았다.**

위 조치는 사용자가 전달한 완료 사실이다. 이번 기록 작업에서는 서비스 시작/중단/재시작,
DB·볼륨·사용자 자료·인증 키·환경 파일·Auth0 설정 변경을 수행하지 않는다.

### 범위와 한계

PASS는 로컬 PC 브라우저의 실제 Auth0 A/B와 합성 완료 메타데이터 인수 범위다.
개별 JWT claim 원문 확인이나 독립 보안 감사까지 입증하는 결과는 아니다.
계정 식별자·이메일·비밀번호·토큰·쿠키·code·state·실제 개인 기록은 수집하거나 기록하지 않는다.

NOT_RUN: 모바일/Flutter 연동, 운영 배포, 실행 중인 실제 서버 중단·재시작 검증,
운영 TLS/Secure cookie·다중 worker·SSO 전체 종료·부하/장애 검증.
기존 합성 새 Python 프로세스 검증은 실제 서버 재시작 인수와 구분한다.
DB 구조·인증 경계의 운영 적용 승인은 여전히 AUTHOR_REVIEW_REQUIRED다.

## 추가한 동작

- `app/core/ab_acceptance.py`: 임의 실행 cookie에 결합된 서버 메모리 상태, 1시간 만료,
  최대 32개 실행. UUID·세션 비교값·합성 ID는 서버에만 보유한다.
- `app/auth0_pc.py`: 기존 인증 검사를 그대로 사용한 PoC 전용 POST 도우미·화면.
  최초 A 세션의 실제 로그아웃 뒤 다른 세션에서 UUID 동일 여부만 반환한다.
  A 재로그인 확인 전에는 B를 등록하지 않는다. 자동 SSO로 A가 돌아오면 B가 아니다.
  B 등록 후 세 번째 계정은 검사 거부. 각 계정은 이번 실행의 저장 동의를 직접 눌러야 한다.
- `tests/test_core_persistence.py`: A 로그아웃/재로그인, 자동 A 복귀 오판 방지,
  B 미동의 차단, CSRF 거부, 양방향 검사·원본 보존·최종 결과 회귀.

제품 API를 내부 HTTP로 호출하며 각 요청의 서명·세션·scope·동의·owner 검증을 유지한다.
이번 실행에서 무작위 생성한 ID만 쓰며 기존 기록을 수정 대상으로 선택하지 않는다.
목록 응답은 외부로 출력하지 않고 자체 합성 ID의 포함/미포함만 비교한다.
같은 ID를 A/B가 각자 생성한 경우의 독립성, 동일 create 재시도 200/replayed,
수정 재시도 409, 삭제 재시도 200/replayed, 삭제 후 create 재시도 409도 확인한다.
상대 기록 GET/PUT/DELETE와 반복 요청은 404여야 한다.
양쪽에 대한 교차 시도 이후 각 소유자로 돌아와 합성 원본 유지까지 확인해야 최종 PASS다.
당시 준비 단계에서는 새 DB/schema·owner 이전·영구 삭제·인증 우회·패키지 설치·commit·push·배포를 하지 않았다.

## 브라우저 진행 절차

한 단계씩 안내하며 각 결과를 확인한 후 다음 단계로 이동한다. 이메일·암호·token·cookie·
code·state·계정 UUID·실제 원문은 대화·스크린샷·보고서에 붙여 넣지 않는다.

1. `http://127.0.0.1:8000/auth/poc/`를 연다. 전용 테스트 계정 A인지 본인이 확인한다.
   실제 개인 계정이거나 불확실하면 등록/동의/검사를 누르지 않는다.
2. 로그인되지 않았다면 `Auth0 합성 계정 로그인`을 누르고 A로 직접 로그인한다.
3. `현재 계정이 전용 A임을 확인하고 등록`을 누른다. A_registered true만 확인한다.
4. `현재 앱 로그아웃`을 누르고 로그인되지 않음/세션 유효하지 않음을 확인한다.
5. 로그인 링크를 눌러 동일한 A로 직접 로그인한다.
6. `재로그인 계정 서버 비교`를 누른다. same_account true, distinct_b false여야 한다.
7. A 본인이 `현재 테스트 계정의 합성 메타데이터 저장에 별도 동의`를 누른다.
8. `현재 계정 격리 검사`를 누른다. A 검사 PASS를 확인한다. 아직 전체 PASS는 아니다.
9. 앱 로그아웃 후 로그인 링크를 누른다. Auth0 화면에서 다른 계정 사용/계정 변경 선택이
   보이면 선택하고 본인이 관리하는 별도 테스트 B로 직접 로그인한다.
   앱 로그아웃은 Auth0 SSO 종료가 아니다. `prompt=login`도 다른 계정 선택 증거가 아니다.
   A로 자동 복귀하거나 계정 변경이 불가능하면 검사하지 않고 중단해 화면 상황만 알려준다.
   필요하면 사용자가 별도 브라우저 프로필에서 B 로그인을 확인할 수 있으나 실행 cookie는
   프로필 간 공유하지 않는다. 이 인수 흐름은 원래 프로필에서 B로 전환해야 계속할 수 있다.
   cookie 복사, token 이동, 임의 logout URL 호출, 인증 설정 완화는 하지 않는다.
10. 서버 비교에서 same_account false, distinct_b true를 확인한다. 이 두 값 전에는 B로 판단하지 않는다.
11. B 본인이 별도 동의 버튼을 누른 뒤 검사한다. A와 B는 동의를 대신하지 않는다.
12. 앱 로그아웃 → A 로그인 → 서버 비교 → 검사. B 자료에 대한 반대 방향 거부와 A 원본 유지 확인.
13. 앱 로그아웃 → B 로그인 → 서버 비교 → 검사. B 원본 유지 확인.
14. `이번 실행 결과만 확인`에서 최종 acceptance PASS와 항목별 PASS/FAIL만 기록한다.

서버 재시작·1시간 만료 시 실행 비교 상태는 소실되어 새 실행이 필요하다.
기존 Core 계정/동의·세션 폐기 상태와 생성된 합성 제품 자료는 DB에 남긴다.
이 임시 인수 도우미는 운영 다중 worker·보유기간·SSO 전체 종료 검증을 대신하지 않는다.

## 실행 명령

프로젝트 `.venv\Scripts\python.exe -B`를 사용했다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.verify_core tests
.\.venv\Scripts\python.exe -B -m pip check
git diff --check
```

`ast.parse`로 app/tests의 32개 Python 파일을 검사했다. 설치된 formatter/type checker가
없으므로 별도 도구 검사는 NOT_RUN. 실행 중 서버의 중단/재시작과 실제 외부 A/B 로그인은
자동 회귀 suite에 포함하지 않는다.

## 최종 문서화 및 커밋 전 검사 (2026-10-30, 에이전트 실행)

이 절만 이번 에이전트의 직접 실행 결과다. 앞선 자동 검사 수치는 기존 기록이며 재실행하지 않았다.
`verify_core tests`/`verify_mysql tests`는 opt-in 통합 테스트를 켜 DB에 합성 자료를 쓴다.
관리 도구에는 migration·복원 DB 생성·환경 파일 기록·키 교체 동작도 있어 실행하지 않았다.
테스트 소스를 먼저 확인하고 별도 Python 프로세스의 메모리 저장소·TestClient만 사용했다.
실행 중 서버에 요청하거나 서버를 시작/종료/재시작하지 않았다.

회귀 명령은 `.venv\Scripts\python.exe -B -`에 다음 Python을 표준 입력으로 전달했다.
출력은 테스트 이름·건수만 사용하고 실패 상세는 출력하지 않았다.

```python
import io, logging, os, unittest
from unittest.mock import patch
os.environ['RUN_MYSQL_TESTS']='0'
os.environ['RUN_CORE_TESTS']='0'
os.environ['COMPLETION_STORE']='memory'
logging.getLogger('uvicorn.error').addHandler(logging.NullHandler())
logging.getLogger('uvicorn.error').propagate=False
with patch('pymysql.connect', side_effect=AssertionError('Database access forbidden')) as db, patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('External HTTP forbidden')) as http:
    suite=unittest.defaultTestLoader.discover('tests')
    result=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(suite)
    for case,_ in result.failures+result.errors:
        print('FAIL:',case.id())
    print('Tests:',result.testsRun,'passed:',result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),'failures:',len(result.failures),'errors:',len(result.errors),'skipped:',len(result.skipped))
    print('Real DB attempts:',db.call_count,'external HTTP attempts:',http.call_count)
    raise SystemExit(not result.wasSuccessful() or bool(db.call_count) or bool(http.call_count))
```

| 상태 | 검사 | 결과 |
|---|---|---|
| PASS | 위 격리 회귀 검사 | 99개 중 77개 통과, DB 통합 22개 skip, 실패/오류 0, 종료 0 |
| PASS | 실제 DB/외부 HTTP transport 호출 방지 | 두 호출 시도 모두 0 |
| PASS | `.venv\Scripts\python.exe -B -m pip check` | 의존성 충돌 없음, 종료 0 |
| PASS | Python 버전 확인 | 기존 Python 3.14.8 |
| PASS | `ast.parse` 문법 검사 (app/tests/scripts) | Python 40개 파일, bytecode 생성 없음 |
| PASS | 변경 문서 상대 링크 검사 | 50개, 누락 0 |
| PASS | 커밋 후보 정적 민감정보 패턴 검사 | 52개 경로에서 private key/JWT/email 패턴 발견 0; 완전한 비밀 탐지 보장은 아님 |
| PASS | `git diff --check` | 공백 오류 없음, 종료 0 |
| NOT_RUN | DB 통합·migration·백업/복원·키 교체 재실행 | DB/환경 파일/서버 보존 지시로 실행 제외 |
| NOT_RUN | formatter/linter/type checker | 프로젝트 설정 없음, 설치하지 않음 |

전체 미커밋 경로를 검토했다. 기존 변경은 API/MySQL/Core Auth0 구현·테스트·실행 도구·
설계/검증 문서와 비밀값 없는 `.env.example`로 이번 커밋 범위에 해당한다.
실제 `.env` 및 `.env.*` 비밀 설정·가상환경은 포함하지 않는다.
커밋은 이번 사용자의 명시적 지시로 수행하며 push·merge·배포는 수행하지 않는다.
DB 구조·인증 경계의 운영 적용은 AUTHOR_REVIEW_REQUIRED를 유지한다.
