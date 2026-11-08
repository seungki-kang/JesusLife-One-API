# 생명일기 Android 공통 로그인 초안

상태: **AUTHOR_REVIEW_REQUIRED** (인증 경계·추가 DB 구조). 서버 코드와 migration
초안 작성만 수행했다. 서비스 활성화·Auth0 등록·DB 적용 승인을 뜻하지 않는다.
일기 업로드·동의·제품 데이터 API는 이 변경의 범위 밖이다.

## 등록과 계약

서버 등록 항목은 `app/core/life_diary_login.py`의 불변 `Registration`이다.
`app_id=life_diary`, 복귀 URI 후보
`jesuslife-life-diary-poc://auth/complete/android`, scope `openid`만 허용한다.
기본 `enabled=False`이며 기존 진입점은 등록 항목이나 생명일기 runtime을 생성하지
않으므로 503으로 닫혀 있다. 환경 파일이나 비밀정보를 추가하거나 조회하지 않았다.

후속 승인 후 서버 구성 코드에서 부모 runtime의 `life_diary_registration`과
`life_diary_runtime`을 명시적으로 연결해야 한다. runtime은 전용 개발 Auth0
클라이언트 하나만 신뢰해야 하며 너랑나랑/PC 클라이언트와 달라야 한다. issuer와
API audience는 부모와 같고 같은 Core store 및 동일한 키 버전을 사용해야 한다.
전용 클라이언트 비밀은 서버 외부 비밀 관리로 공급한다. 요청으로 runtime이나
제공자 설정을 선택하지 않는다. Auth0 실제 client/RS256 access token profile,
audience, callback 허용 목록과 scope 발급 가능성은 아직 확인하지 않았다.

경로는 `/api/v1/mobile/life-diary` 아래 `login-transactions`, `authorize`,
`session-exchange`, `session`, `logout`이다. 서버 callback은
`http://127.0.0.1:8000/api/v1/auth/callback/life-diary/android`이다.
이는 기존 ADB reverse 로컬 개발 조건을 따르며 운영 주소가 아니다.
start는 `app_id`, `client_id`, `return_uri`, S256 `challenge`를 받는다.
exchange는 같은 결합 값과 `transaction`, 일회용 `code`, `verifier`를 받는다.
결합 누락은 422, 불일치·만료·재사용은 401, 비활성·구성 오류는 503이다.
일회용 거래의 실패는 자동 재시도하지 않고 새 로그인부터 시작한다. 성공한 교환
응답을 잃은 경우에도 거래를 재사용하지 않는다.

## 저장·인증 경계

`mobile_logins`에 app/client 결합을 저장하고 authorize/callback/exchange에서
서버 등록과 비교한다. callback의 기존 `login_transactions` client/callback,
브라우저 결합, state 일회 사용, nonce, 두 단계 S256 PKCE, access/ID token
서명·issuer·audience·client·유효기간·at_hash 검증을 그대로 사용한다.
callback의 세션 INSERT에 app_id/client_id를 함께 저장하고 handoff 작성까지 같은
트랜잭션으로 커밋한다. 실패하면 신규 세션·토큰·완료 표시가 롤백된다. 이미 claim된
login은 exchanging 상태로 남아 재사용되지 않으며 새 로그인이 필요하다.
handoff와 전달 가능한 credential은 남지 않는다. 교환은 잠금
내에서 저장된 거래와 세션의 앱·클라이언트·계정을 비교하고 한 번만 소비한다.
세션 인증은 토큰 검증 및 Core 세션/계정 상태 검증을 거친다.

기존 `(issuer, provider_subject)` → 공통 계정 매핑을 그대로 사용한다. 앱별로
계정을 만들거나 이메일로 병합하지 않는다. 앱 간 동의나 기록 접근 권한을
부여하지 않는다. openid는 너랑나랑 읽기/쓰기 scope를 대신하지 않는다.
생명일기 logout은 저장된 현재 session_id와 앱/client를 조건으로 해당 세션만
철회한다. 다른 앱·동일 앱의 다른 세션·Auth0 SSO·공통 계정은 종료하지 않는다.

앱 정보가 없는 기존 행은 NULL 그대로 유지한다. 기존 너랑나랑 경로만 이를
처리하며 새 경로에서는 거부한다. 너랑나랑 경로는 앱 결합이 있는 행을 거부한다.
기존 PC/너랑나랑 제공자의 허용 클라이언트 집합도 확대하지 않는다.

## Migration 및 복구

기존 001/002는 수정하지 않았다. 다른 작업공간의 독립 003 백업 초안과 번호가
겹치지 않도록 `004_life_diary_login.DRAFT.sql`을 추가했다. nullable 열 추가만
포함하고 기존 행·계정·동의·버전 표를 재분류하거나 수정하지 않는다.
기존 exact-shape preflight/백업 도구는 새 열을 승인하기 전까지 그대로 사용하면
안 된다. 이 초안은 기존 migration 실행기에 연결하지 않았다.

SQL 주석의 중지·전체 백업·키 버전 보존·격리 복원 증명·부분 DDL 점검·행 비교
조건을 모두 만족한 후 사람 검토가 필요하다. MySQL DDL은 자동 commit이므로
transaction rollback을 복구로 간주하지 않는다. 코드 rollback은 LD를 먼저
비활성화하고 추가 열과 행을 보존한다. 열 삭제/사용자 행 삭제로 되돌리지 않는다.
실제 rollback 대상 `b4e5111`의 `exchange_mobile`에는 app_id/client_id 검사가 없다.
새 코드의 NN 결합 차단은 rollback 후 사라진다. 구버전은 URI·handoff 코드·PKCE·만료·소비
여부를 검사하므로 LD callback을 포함한 쓰기를 중단하고 모든 LD handoff가 만료된 후
재개해야 한다. 구버전 provider의 전용 LD client 거부는 allowlist에서 LD를 제외할 때만
성립하며 교환 단계의 결합 차단과 다르다.
구버전 NN 경로도 고정 `jesuslife-poc://auth/complete/android` URI를 전달하므로
별도 LD URI가 보존된 거래는 URI 불일치로 거부한다. 다만 URI가 NN과 일치하면
저장된 app_id/client_id만으로는 차단하지 않는다. 새 코드는 URI·코드·PKCE가
유효해도 저장된 앱 또는 클라이언트 결합이 다르면 소비 전에 거부한다.
전체 복원이 필요하면 백업 이후 쓰기 조정과 별도 승인을 거친다.

## 오프라인 검증

Python은 이 worktree에 가상환경이 없어 기존 작업공간의 보존된
`.venv/Scripts/python.exe` (3.14.8)를 `-B`로 실행했다. 다른 작업공간은 Git 상태와
겹치는 추적 파일의 diff만 읽었고 파일·Git 설정은 변경하지 않았다.

`python -B -m scripts.test_offline`은 환경 파일·MySQL·외부 네트워크를 차단하고
합성 임시 SQLite 및 mock Auth0 RSA 서명만 사용한다. 신규 테스트는 기본 비활성,
등록 오류, 결합 누락/불일치, 저장 결합 손상, 잘못된 nonce/PKCE, 앱 간 교환과
세션 사용 거부, callback/거래 재사용, 동일 합성 계정, 양방향 로그아웃 격리,
기존 NULL 행 보존을 검증한다. 기존 너랑나랑 회귀도 함께 실행한다.
SQLite 검증은 실제 MySQL 잠금·DDL·권한·업그레이드·복구를 증명하지 않는다.

NOT_RUN: 실제 Auth0/DB, 비밀 조회, migration 실행·업그레이드·백업·복원 리허설,
Flutter, Android 실기기, 배포, commit/push. 실제 활성화와 독립 003 결합 검증은
후속 검토 범위다.
