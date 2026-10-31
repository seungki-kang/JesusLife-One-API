# 너랑나랑 실제 완료 메타데이터 선택 동기화 제안

기준일: 2026-10-31. 상태: PROPOSED / AUTHOR_REVIEW_REQUIRED. 실제 수집 활성화: BLOCKED.
모든 권고·계약·예시는 PROPOSED이며 보호 경계 결정은 AUTHOR_REVIEW_REQUIRED다.
최초 요청은 문서 작성만 승인했으며, 이번 보정은 이 제안서와 `tools/sync_model/`의 독립 실행 명세·시험·검토 기록만 승인한다. 설계 승인, 구현, 스키마 migration, 실제 개인정보 수집,
외부 연결, 배포·활성화의 승인을 받은 것으로 해석하지 않는다.

## 1. 목적·범위·확인 근거

가장 작은 유용한 첫 릴리스는 **새로 완료하여 로컬 저장이 확인된 기록 한 건을 사용자가
명시적으로 선택하여, 자기 계정에 최소 완료 메타데이터만 전송**하는 것이다.
자동 전송, 과거 일괄 업로드, 원문 백업, 공유, 교회 통계, CHGO 전송, 기기 간 원문 복원은 제외한다.
성공 조건은 서버 장애·취소·철회·계정 전환에도 로컬 완료 기록과 과정별 완료 횟수가 그대로이며,
선택한 계정의 선택한 한 건만 중복 없이 반영되고 삭제 후 재등장하지 않는 것이다.
완료 횟수는 학습 표시이며 영적 성숙 점수가 아니다.

이전 문서 작성 시 확인한 근거(이번 재검증 결과가 아님):

| 저장소 | 실제 Git 루트 | 브랜치 | 시작 상태 |
|---|---|---|---|
| API | `D:/CHGO-VibeCodeing/JesusLife-One-API` | `main` | clean |
| Flutter | `D:/CHGO-VibeCodeing/neorang_narang_app` | `main` | `macos/Flutter/GeneratedPluginRegistrant.swift` 수정됨 |

Flutter는 읽기 전용으로 조사했다. 소유권 경고는 명령별 `git -c safe.directory=...`로만 처리했고
전역·저장소 Git 설정은 바꾸지 않았다. 기존 변경은 보존한다. 공통 스킬의 main 수정 제한에 대해
이번 문서 경로 작성의 명시적 사용자 지시 범위만 수행하며 코드나 브랜치는 변경하지 않는다.
실제 DB·기록·환경 파일·비밀·백업은 열지 않았고 앱 import·기기 흐름·외부 서비스 실행도 없다.

읽은 주요 근거(현재 소스 관찰이며 실행 검증과 구분):

- API [지침](../../AGENTS.md), [README](../../README.md), `requirements.txt`, `requirements-dev.txt`.
- [기존 소유권·동기화 정책](../architecture/nn-auth-ownership-sync-policy.md),
  [Core 계약](../architecture/platform-auth-contract-draft.md), [모바일 PoC 안내](../mobile-first-link.md).
- [완료 스키마](../../app/modules/neorang_narang/schemas.py),
  [서비스](../../app/modules/neorang_narang/service.py), [라우터](../../app/modules/neorang_narang/router.py),
  [Core 모바일 조정](../../app/core/mobile_store.py), [모바일 경로](../../app/core/mobile_routes.py),
  [제품 합성 저장 adapter](../../app/modules/neorang_narang/mobile_store.py), `tests/test_completions.py`.
- Flutter `AGENTS.md`, `docs/governance/{COMMON_PRINCIPLES,PROJECT_CONTEXT,CHECKLIST}.md`,
  `pubspec.yaml`, `lib/models/completion_record.dart`, `lib/database/app_database.dart`,
  `lib/repositories/sqlite_completion_repository.dart`, `lib/pages/completion_signature_page.dart`,
  `lib/mobile/mobile_sync.dart` (경로는 위 Flutter 루트 기준).
- 적용 규칙: `jesuslife-platform-development`의 common-rules, project-boundaries,
  design-workflow, quality-gate 및 `jesuslife-platform-design`의 workflow.

## 2. 기존 구현과 제안의 차이

| 현재 소스에 존재 | 이번 제안: 아직 구현되지 않음 |
|---|---|
| API AGENTS의 초기 설명보다 코드가 진행됨. v1 완료 CRUD, 메모리/MySQL 저장 adapter가 있음 | 실제 데이터 전용 독립 버전 계약과 실사용 수집 gate |
| 기본 앱 인증은 fail-closed. 별도 PC/모바일 개발 인증 진입점이 있음 | 검증된 세션·scope·현재 동의·계정 상태를 실제 데이터 쓰기 commit까지 검사 |
| v1 metadata는 UUID, course_number, participation_mode, completed_at, revision, deleted_at | 최소 필드 projection만 선택 전송; 기존 v1 의미 변경 없음 |
| v1 create 동일 활성 payload 재시도, 버전 조건 수정·삭제. 과거 operation receipt·cursor·복원 없음 | 영속 operation receipt와 삭제 장벽, 계정 귀속, 불변 outbox |
| Flutter CompletionRecord에는 계정, sync UUID, revision이 없음. 완료 ID는 과정 번호+microseconds 시각 기반 | 로컬 ID 유지, 별도 account binding·sync identity 연결 |
| SQLite 완료·복구·삭제 ID와 과정별 COUNT가 있음. 정책상 웹 등은 SharedPreferences 경로 | 서버 사본·ACK가 원래 기록이나 COUNT를 수정하지 않음 |
| mobile_sync는 별도 보조 SQLite queue에 새 합성 payload만 저장, 수동 전송 | 실제 완료 저장 성공 후 사용자 선택으로만 새 실제-data 큐 생성 |
| 합성 API `/api/v1/mobile/synthetic-completion`, synthetic=true, 동의 generation당 한 건 | 별도 실제-data scope·동의·경로. synthetic=false 전환이나 기존 endpoint 재사용 금지 |
| PoC 철회는 서버 합성 metadata를 NULL 처리하고 UUID/owner/generation 장벽 유지. 로컬 cancelled payload는 남음 | 실제-data payload 정리·보유기간·백업 한계를 별도 승인; PoC 삭제 완료와 혼동 금지 |

현재 코드 존재나 과거 정책의 승인 이력은 실제 완료 자료 수집 승인이 아니다.
소스 조사로 MySQL 잠금·실제 인증·운영 권한의 안전성을 입증했다고 주장하지 않는다.

## 3. 실제 데이터 최소 허용목록

계정에 연결된 완료 사실·날짜·과정은 개인 데이터다. 이름을 빼도 익명 자료가 아니다.
합성 자료 시험 동의, 로그인, 교회 소속, 함께하기, 로컬 서명은 업로드 동의를 대신하지 않는다.

| 필드 후보 | 실제 모델 근거 / 필요 | 첫 릴리스 판단 |
|---|---|---|
| `sync_id` UUID | 기존 로컬 id는 시각 기반; 안정된 중복 방지 키 필요 | 새 매핑으로 생성, 로컬 원래 ID 전송 금지 |
| `course_number` 정수 1 또는 2 | CompletionRecord.courseNumber / 과정별 완료 확인 | 포함; 엄격한 enum, bool·그 외 값 거부 |
| `completed_on` 엄격한 YYYY-MM-DD 달력 날짜 | 같은 완료 사건의 기기 로컬 날짜를 한 번 캡처 | 포함 권고; 정확 시각·시간대·offset 제외 |
| `participation_mode` solo 또는 together | participationMode / 기존 계약에는 있으나 첫 릴리스의 단건 완료 확인에는 불필요 | 초기 제외 권고; 필요성이 승인되면 후속 계약에서 추가 |

요청 envelope의 `operation_id`, `base_revision`, `consent_generation`, `policy_version`은
동기화 제어 항목이다. 서버 `revision`, `received_at`, 삭제 장벽은 제품 원문 필드가 아니다.
`consent_generation`은 권한 폐기 세대이며 **기록 revision과 별개**다. 한 동의 세대에
여러 기록이 가능하고 각 기록 revision은 독립적이다. PoC의 세대당 한 건 제약을 복제하지 않는다.

처음부터 거부할 값: 이름, 과정 제목 등 자유 문자열, 문답·답변, 은혜 원문과 pending 표시,
서명 및 서명 시각, 음성, 참여자 ID·이메일·상대 이름, 교회/역할/기기 식별자,
전체 CompletionRecord JSON, 민감 원문의 hash. 소유자 ID는 본문에 받지 않는다.
허용목록 전용 DTO로 직접 구성하고 알 수 없는 필드는 고정 422로 거부한다.
로그·APM·추적·예외에 payload·계정·토큰·기록 식별자를 노출하지 않는다.

최소 metadata는 sync_id, course_number, completed_on이다. completed_on은 같은 완료 사건에서
기기 로컬 날짜를 한 번 캡처하며 이후 시간대 변경·재시도 때 재계산하지 않는다.
유효한 달력 날짜만 허용한다. 정확한 완료 시각·시간대·offset·참여자·이름·원문·서명은 전송하지 않는다.
원래 로컬 timestamp는 수정하지 않는다. 날짜 근거가 불확실한 레거시는 부적격이며 추론하지 않는다.
날짜는 신뢰할 완료 증명도 중복 제거 키도 아니다. 같은 날짜·과정의 별도 기록은 병합하지 않는다.
권한·충돌·보유기간은 기기 날짜가 아닌 서버 버전과 서버 시각으로 판단한다.

## 4. 소유권·계정 귀속·사용자 흐름

Core가 검증한 세션에서 불변 공통 계정 UUID를 얻는다. issuer/audience/자격 종류·만료,
세션 폐기·계정 상태를 확인한다. 업로드는 전용 업로드 권한과 현재 유효 동의를 요구한다.
철회·삭제·상태 조정은 같은 검증 계정의 제한된 본인 관리 권한으로 수행하며 업로드 재동의를 요구하지 않는다. 이메일·본문 owner·미검증
헤더로 귀속하지 않는다. 서버 키는 `(verified account, sync_id)`이며 모든 조회·재시도·삭제에
같은 소유자 조건을 적용한다. 타 계정·없음·삭제 기록의 일반 조회는 동일 404다.
관리자·교회 리더·함께한 상대에게 묵시적 접근 권한은 없다.

1. 로그인 없이도 기존 완료 저장·열람을 계속한다. 로컬 저장 확인 전 완료나 전송을 표시하지 않는다.
2. Android에서 13.1의 신규 선택 창 안에서 사용자가 전송 버튼을 선택한다. 계정 표시, 전송 필드, 목적, 제외 자료,
   서버 사본의 한계, 철회·삭제·백업 잔존 안내와 실제-data 동의를 별도로 확인한다.
3. 이 로컬 기록을 현재 계정에 귀속한다는 기록별 확인을 받는다. 로그인 자체로 귀속하지 않는다.
   공유 기기에서 본인의 권한을 확인할 수 없으면 전송하지 않는다.
4. binding(account, local reference, sync_id, 확인 시각/정책), 선택 의도, 최소 payload를
   영속화한 뒤 전송한다. 중간 실패 시 로컬 완료는 유지하고 미전송 상태를 표시한다.
5. ACK를 확인한 경우에만 서버 반영 완료로 표시한다. 취소·네트워크 실패는 로컬 완료와 별개다.

계정이 없는 기존·가져온 기록은 `unbound`로 유지한다. 앱 시작·로그인·업데이트·백업 복원 시
현재 계정으로 자동 배정하거나 과거 큐를 만들지 않는다. 첫 릴리스에서는 과거 기록 선택도
지원하지 않는다. 새 기록을 선택하지 않고 화면을 떠나면 로컬 전용으로 남긴다.
후속 과거 선택 기능은 별도 승인된 권한 확인·날짜 근거·중복 검토 절차가 필요하다.
한 번 A에 묶인 기록은 B로 재귀속·이전·병합하지 않는다. 이름 비교로 소유권을 추론하지 않는다.
binding 저장소 유실·복원 충돌 시 unbound처럼 새 UUID를 발급하여 재전송하지 말고 격리한다.

## 5. 독립 버전 실제-data 계약 초안

경로 후보는 `/api/nn-real/v1`이다. 제품 실제-data 계약 버전으로 관리하며 기존 v1 CRUD와
mobile synthetic 경로·동의·테이블의 의미를 보존한다. 미지원 버전은 명시적으로 거부한다.
아래 이름과 shape는 승인 전 초안이다.

| API 후보 | 의미 |
|---|---|
| Core `PUT /api/core/v1/me/consents/nn-real-completion` | 목적 `nn.real-completion.sync`, 정책 버전 확인 후 별도 동의. 멱등 동의 명령 ID 필요 |
| Core `POST .../nn-real-completion/withdrawals` | 철회 명령 ID와 대상 동의 세대. 신규 admission 즉시 차단·제품 Close/drain 및 삭제 접수; 기존 ticket은 Close 전 commit 가능 |
| Core `GET .../nn-real-completion` | 현재 동의와 세대별 삭제 진행·장벽, live 삭제와 backup 만료 상태 구분 |
| `POST /api/nn-real/v1/completions` | 선택한 한 건 생성 전용. upsert 아님 |
| `GET /api/nn-real/v1/completions/{sync_id}` | 본인 활성 최소 metadata와 revision 조회, 응답 유실 조정용 |
| `POST /api/nn-real/v1/completions/{sync_id}/deletions` | 본인 서버 사본 삭제, operation_id와 base_revision 조건; 부재 ID에도 삭제 장벽 생성. 로컬 삭제 연계는 13절 |

업로드와 일반 활성 metadata 조회에는 실제-data 전용 write/read scope 후보
`nn-real-completion:write`, `nn-real-completion:read`와 활성 목적별 동의를 둘 다 요구한다.
scope만으로 동의를 대신하지 않는다. 철회·삭제·상태 조정(멱등 재시도·receipt/장벽 진행 조회 포함)은
같은 검증 계정과 별도의 제한된 본인 관리 권한을 요구하며, 현재 업로드 동의나 업로드 scope,
재동의를 요구하지 않는다. 관리 응답은 최소 제어 상태만 제공하고 과거 metadata를 재노출하지 않는다.
권한의 구체 scope·자격·만료 정책은 AUTHOR_REVIEW_REQUIRED다.

생성 요청 예시(전부 합성 값):

```json
{
  "operation_id": "10000000-0000-4000-8000-000000000001",
  "consent_generation": 3,
  "policy_version": "nn-real-completion-v1-draft",
  "base_revision": 0,
  "metadata": {
    "sync_id": "20000000-0000-4000-8000-000000000001",
    "course_number": 1,
    "completed_on": "2026-10-31"
  }
}
```

서버는 실제 세션 계정과 Core의 현재 세대·정책 및 아래 13절 admission/commit fence를 검증한다. 사전 동의 조회만으로 충분하지 않으며 요청 세대를 신뢰하지 않는다.
서버가 revision=1을 정하며 성공 응답은 `operation_id`, `sync_id`, `applied_revision`,
`current_revision`, `replayed`, `received_at`만 반환하도록 최소화한다. 성공 ACK에 course_number/completed_on을 복제하지 않는다. 활성 metadata는 권한 확인 GET에서만 반환하며 응답 캐시 저장을 금지하고 내부 사본도 정리한다. 삭제·철회 뒤 과거 성공 응답 재생은 금지하며 13.4의 장벽을 먼저 판정한다. 소유자·원문은 반환하지 않는다.
201 신규, 200 동일 명령 ACK, 401 재로그인, 403 scope/계정 거부, 404 비공개 존재 여부,
409 충돌, 410 철회 세대/삭제 장벽, 422 고정 검증 오류, 429 Retry-After, 503 권한 확인 불가를
구분한다. 오류는 입력을 반사하지 않는 고정 code와 불투명 request ID만 제공한다.

## 6. 안정된 ID·재시도·revision·충돌·오프라인 복구

- 원래 완료 ID·원문을 바꾸지 않고 임의 UUID를 한 번 생성·영속화한다. 내용·시각 hash로 만들지
  않는다. 선택 연타·재시작·응답 유실에도 같은 binding/sync_id를 사용한다.
- 각 명령에 별도 operation UUID를 부여하고 계정·동의 세대·base·허용 payload를 불변 snapshot으로
  보관한다. 불변성은 활성 재시도 중 명령 변경 금지이며 삭제 시 payload 제거를 막지 않는다. 이미 송신한 명령은 재시도 중 변경하지 않는다. 계정 변경으로 payload를 다시 만들지 않는다.
- 서버는 owner+operation ID의 receipt와 정규화된 명령 비교, owner+sync_id 유일성, revision CAS,
  권한 fencing 및 저장을 하나의 일관된 commit 절차로 처리한다. 동일 operation/동일 내용은 재생,
  동일 operation/다른 내용은 활성 receipt에서 409 `idempotency_key_reused`다. 삭제 후에는 13.4처럼 원문 비교 없이 erased receipt/장벽으로 410을 반환한다.
- 다른 operation으로 같은 sync_id가 오면 같은 활성 최소 내용인 경우에만 기존 생성 결과를
  확인 응답하고 새 기록을 만들지 않는다. 내용이 다르거나 삭제됐으면 409/410이다.
  내용이 같은 다른 UUID 기록을 시각·과정만으로 자동 병합하지 않는다.
- 첫 릴리스는 생성·조회·서버 사본 삭제만 허용한다. 일반 수정·복원·다기기 merge는 보류한다.
  생성 revision=1, 삭제는 base=current에서 서버 revision+1이다. 향후 수정도 CAS와 별도 operation을
  사용하며 consent_generation 증가로 revision을 초기화하거나 올리지 않는다.
- 충돌 후보와 로컬 원본을 보존하고 조회 후 사용자 판단을 기다린다. revision만 올려 재전송하거나
  last-write-wins를 쓰지 않는다. 과거 receipt의 applied_revision으로 최신 상태를 덮어쓰지 않는다.
- 큐 상태는 selected/pending/in_flight/acked/conflict/paused/cancelled로 구분한다. ACK와 receipt
  참조를 원자 저장한다. 재시작의 in_flight는 동일 명령으로 확인·재시도한다. timeout/5xx는 제한된
  backoff+jitter, 429는 Retry-After, 401은 같은 계정 재로그인 대기, 403/409/410/422는 자동 반복 금지다.
- receipt 만료·매핑 유실·지원되지 않는 버전이면 새 create를 생성하지 않는다. 본인 상태와 장벽을
  조회하여 조정하고 확인 불가능하면 paused로 남긴다. 일반 목록·cursor 기반 전체 복원은 후속 범위다.

기존 완료 DB와 별도 보조 저장소를 쓴다면 양쪽 저장의 원자성을 가정할 수 없다. 삭제·복구의 구체 후보와 미해결 전제는 13.2를 따른다. 먼저 로컬 완료가
저장된 후 13.2의 원본 선택 매핑을 commit하고 선택 의도·큐를 보조 저장소 transaction에 넣는다. 송신 직전 원래 기록의 존재와
삭제 여부를 다시 확인한다. 그 사이 원본 삭제와 송신이 경합할 때의 잠금/취소 fencing 또는
서버 사본 삭제 보상 절차를 구현 승인 전에 확정해야 한다. 보조 저장 실패는 업로드를 막고 원본을 유지한다.

## 7. 철회·진행 중 요청·로그아웃·삭제·보유

철회는 기본적으로 해당 목적의 활성 서버 metadata 삭제 접수까지 포함하는 후보 정책이다.
클라이언트는 네트워크 호출보다 먼저 계정/세대별 철회 의도를 영속화하고 큐를 차단한다.
늦게 도착한 ACK는 철회·계정 변경 epoch를 확인하여 성공 표시나 큐 재활성화에 사용하지 않는다.
오프라인 철회는 기기 전송을 즉시 멈추지만 서버 철회 완료는 아니다. 같은 검증 계정 재로그인과 제한된 본인 관리 권한 확인 후 철회 접수·삭제·상태 조정을 재개한다. 업로드 재동의는 요구하지 않는다.

세 선형화 지점을 구별한다. A는 Core Withdraw transaction commit(철회 접수), F는 제품
Close fence commit(폐기 세대 쓰기 차단), D는 13.4 live inventory 삭제 ACK를 Core가 내구 저장하는
지점이다. Admit와 A는 Core에서 직렬화한다. A 이후 새 admission은 거부하지만 A 전 admission된
요청은 F 전 제품 commit이 가능하며 반드시 삭제 집합에 포함한다. F와 제품 commit은 같은 세대
gate에서 전역 직렬화하여 F 이후 옛 세대 commit을 금지한다. Close/drain은 삭제 완료가 아니다.

API 후보: A 이후만 202 `withdrawal_accepted`, 불투명 작업 참조, `admissions_blocked=true`,
`product_writes_fenced=false`, `live_deletion=pending`을 반환한다. 후속 상태 조회는
ClosedAndDrained 확인 뒤에만 product_writes_fenced=true, D 뒤에만 live_deletion=completed와
inventory_version/확인 범위를 반환한다. 응답은 관측된 단조 상태이며 접수를 완료 차단·완료 삭제로
해석하지 않는다. timeout은 결과 불명/pending이다.
UI 후보는 “철회 접수: 새 전송 승인 중단, 기존 처리와 서버 삭제 대기”, “제품 쓰기 차단 확인:
서버 정보 삭제 중”, “확인 범위의 live 사본 삭제 완료: 최소 장벽 잔존, 백업 만료 별도”다.
오프라인은 “이 기기 전송 중단, 서버 철회 접수 대기”다. 재동의는 D와 장벽 내구 확인 후 더 큰
세대의 Open ACK 및 Core ACTIVE까지 확인해야 한다. 옛 명령·ticket·선택은 이월하지 않는다.
중복·역순·장애 순서는 13.3을 따른다.

로그아웃은 즉시 송신 중단·클라이언트 자격 제거·서버 세션 폐기를 시도한다. 네트워크 실패 시
서버 세션이 남을 가능성과 재인증 후 확인 절차를 표시한다. 로그아웃은 철회·삭제와 다른 행위다.
A계정의 큐·binding·삭제 의도는 B계정의 자격으로 보내거나 보여주지 않는다.
업로드 재개는 같은 검증 A계정, 현재 유효 업로드 동의, 업로드 권한 및 폐기되지 않은 선택 자격을
모두 확인해야 한다. 철회·삭제·상태 조정 재개는 같은 검증 A계정과 제한된 본인 관리 권한만 요구하며
업로드 재동의를 요구하지 않는다. 철회된 세대·삭제된 sync_id는 재동의로 업로드 자격을 회복하지 않는다. 로컬 기존 기록은 보존하되 계정별 동기화 자료는 분리·잠근다.
공유 기기의 기존 로컬 화면 개인정보 보호는 별도 제품 결정이며 서버 격리만으로 해결됐다고 하지 않는다.

서버 사본만 삭제하는 명령은 원문·로컬 COUNT를 바꾸지 않는다. 사용자 로컬 삭제는 13.2처럼 서버 삭제도 요청하며 기존 로컬 삭제·COUNT 규칙을 따른다. 최소 UUID/계정/폐기 세대 장벽은 늦은 요청과
백업 복원에 의한 부활 방지를 위해 남길 필요가 있으며 이것도 개인 데이터다. 서버 수신·처리 상태,
live metadata 삭제, 장벽 잔존, backup 만료를 구분하여 안내한다. 계정 탈퇴 시 같은 목적의 전체 삭제와
폐기 subject 차단이 필요하며 계정 UUID는 재사용하지 않는다.

미승인 비교 대안: 활성 metadata는 동의 유지 중, 철회 후 live metadata는 최대 30일 내 삭제,
receipt/최소 감사는 90일, backup은 최대 90일 순환 만료. 이는 기존 정책의 후보를 비교하기 위한
초안이지 확정 SLA가 아니다. live 삭제를 지연 없이 시도하고 내구 재처리를 요구하되 성공이나 완료 시한은 보장하지 않는다.
장벽은 최대 큐 유효기간·backup 수명보다 길어야 하며 기간 만료 후 옛 세대를 영구 거부할 수 있는
계정별 최소 fence를 승인해야 한다. 수치·목적·접근자·정리 담당 확정 전 실제 수집 금지다.

불변 backup에서 개별 행 즉시 삭제를 보장하지 않는다. 만료까지 접근 제한·일반 서비스 복원 금지,
복원 시 삭제 원장/세대 fence를 먼저 적용한 후 검증해야 한다. 원장 유실 시 복원 서비스를 격리한다.
장벽을 포함한 잔존 범위와 최종 만료를 안내하고 live 삭제 완료를 모든 복사본 삭제라고 말하지 않는다.
실제 삭제가 끝난 metadata의 복구를 약속하지 않는다. 철회는 로컬 원본을 유지하고 사용자 로컬 삭제는 기존 복구 규칙을 따른다.

## 8. 제품과 Core의 운영 경계

너랑나랑은 완료 원본·projection·revision·receipt·삭제 장벽과 제품 삭제 작업을 소유한다.
Core는 계정·세션·동의·정책 세대·권한 폐기와 전체 삭제 진행 조정을 소유한다.
ChurchOS 소속·역할은 개인 기록 권한이 아니며 CHGO·다른 제품에 자동 발행하지 않는다.

현재 Core 모바일 코드가 제품 내부 schema/adapter를 import하고 같은 DB connection으로
제품 테이블을 쓰는 방식과 cross-schema 권한은 **개발 예외**다. 목표 운영 구조로 승격하지 않는다.
단일 FastAPI 모듈형 모놀리스는 유지할 수 있으나 제품 공개 command interface와 불변 권한 context,
목적/세대별 철회 command·삭제 ACK 계약으로 연결하고 각 repository는 자기 저장소만 쓴다.
Core가 제품 DB 자격·내부 모델을 보유하거나 교차 JOIN/FK/cascade로 소유권을 정하지 않는다.

분리된 commit에서는 단순 이벤트 전달만으로 철회 경합을 해결할 수 없다. 13.3의 후보도 미입증이므로 활성화 BLOCKED다. 내구 outbox/inbox,
멱등 삭제, 단조 fence, 진행 중 commit 조정과 실패 시 fail-closed를 명시한 구현 설계가 필요하다.
대안은 경계 밖 DB 공유 transaction이지만 권한 결합이 커지므로 실제-data 첫 릴리스의 목표로 권고하지 않는다.
기존 PoC 제거·권한 축소도 별도 승인·회귀·복구 계획 후 수행한다. 이번 문서는 권한을 변경하지 않는다.

## 9. 합성 fixture 검증 계획 (이번에는 NOT_RUN)

| 시나리오 | 반드시 확인할 결과 |
|---|---|
| allowlist·오류 | 이름/원문/참여자/owner/알 수 없는 필드 422, 응답·로그·추적 입력 비노출 |
| 교차 계정 | A ID를 B가 조회/쓰기/삭제/receipt 조회해도 내용·존재·revision 비노출; B 큐에 A 자료 없음 |
| binding | 로그인·재시작·업데이트는 기존 기록을 unbound 유지; 명시 선택만 귀속; A→B 변경 거부 |
| 로컬 저장 실패·연타 | 저장 실패는 큐 없음; 선택 연타는 매핑 한 개; COUNT와 기존 ID·필드 불변 |
| 응답 유실·프로세스 종료 | commit 뒤 timeout, ACK 저장 실패, in_flight 재시작에서도 동일 UUID/operation/payload; 서버 행 한 개 |
| 충돌 | 같은 operation 다른 payload 409, 같은 ID 다른 내용 409, stale base 거부; 두 후보 보존 |
| 동의와 revision | 동의 세대당 여러 기록 가능; 동의 갱신은 record revision 변경 없음; 합성 동의로 실제 경로 거부 |
| 철회 경합 | Admit/제품 commit 전후 철회; A 이후 신규 admission 거부, F 전 commit도 삭제, F 이후 commit 금지·늦은 ACK 무효 |
| 계정 전환·로그아웃 | 요청 진행 중 전환/세션 폐기 시 잘못된 ACK 적용 없음; 오프라인 A계정 삭제 의도 B계정으로 재개 불가; 같은 검증 A계정+관리 권한이면 업로드 동의 없이 삭제·상태 조정 가능, 업로드는 동의+업로드 권한 필요 |
| 삭제 장벽·재동의 | 삭제 뒤 오래된 create·backup 복원·새 동의에서도 같은 기록 자동 부활 없음 |
| 시간·손상·복원 | 불확실 날짜·매핑 유실·손상 큐는 보류; 새 ID 자동 발급/원본 덮어쓰기 없음 |
| migration 후보 | 합성 구버전 fixture 업그레이드·중간 실패·재실행·격리 복원에서 기록/COUNT 불변; 자동 역사 큐 없음 |
| 운영 저장소 | 실제-data 없이 격리 DB에서 CAS·잠금·철회 fencing·삭제 복원 검증; SQLite mock만으로 MySQL 증명 금지 |

기존 GET `/`, `/health`, `/openapi.json` 및 모듈 경로·v1 CRUD·합성 API 계약 회귀도 유지한다.
패키지는 자동 설치하지 않는다. 이 표의 제품 검증 계획은 실행 증거가 아니다. 독립 추상 모델의 한정 검증은 12절과 모델 README로 구분한다.

## 10. 저자 결정표·대안·영향·복구

아래 보호 경계는 모두 AUTHOR_REVIEW_REQUIRED이며 승인되었다고 주장하지 않는다.

| 결정 대상 | 권고 / 대안 | 영향·복구 계획 |
|---|---|---|
| 실제 수집 목적·allowlist | sync_id+course_number+completed_on만 / 더 적은 필드 또는 수집 보류 | 정밀도·재식별 위험 비교. 승인 범위 축소 시 새 버전, 수집 중단 후 불필요 사본 삭제 절차 |
| 계정 binding·신규 판정 | PROPOSED: 13.1의 Android 신규 선택 창만 / 과거 선택은 후속 별도 승인 | 공유 기기 오귀속 위험. 잘못 귀속하면 송신 정지·해당 서버 사본 삭제; B 자동 이전 금지 |
| 로컬 삭제·undo | PROPOSED: 업로드 취소+서버 삭제, undo는 서버 재전송 금지 | 원본-store 원자 삭제 표식·독립 journal 조정 입증 전 BLOCKED; 기존 로컬 삭제/COUNT 유지 |
| 동의 문구·철회 의미 | 실제-data 목적 동의와 철회 시 서버 삭제 / 동기화 중단·삭제 분리 | 사용자 기대·보유 영향. 정책 변경 시 재동의, 기존 세대 재사용 금지 |
| 독립 API와 권한 | nn-real/v1 및 전용 scope / 기존 버전 확장 | 호환·노출 영향. 새 경로 flag off, 기존 synthetic/v1 보존 |
| 저장 구조·migration | 원본 DB 선택 매핑·삭제 표식 + 별도 보조 outbox / 다른 내구 증거 설계는 재검토 | DB 구조 보호 대상. 합성 upgrade·중간 실패·백업/격리 복원 증명 후 별도 적용; 원본 초기화 금지 |
| revision·receipt·삭제 fence | 서버 CAS와 내구 receipt / 생성 전용 단순 dedupe | 첫 릴리스도 삭제·응답 유실 장벽 필요. 실패 명령 격리, 원본 유지; 새 ID 재생성 금지 |
| Core 경계·경합 프로토콜 | 공개 command+fencing / 개발 공유 transaction 유지 | 인증·권한·DB 경계 보호 대상. 미증명 시 실데이터 차단; PoC 자격/경로로 fallback 전송 금지 |
| 보유·backup·장벽 수명 | 위 후보를 담당자·기간별 확정 / 더 짧은 보유 | 삭제 한계와 비용 영향. 삭제 원장 우선 복원·격리 검증; 영구 삭제 복구 불가 안내 |
| 지원 플랫폼·계정별 로컬 보호 | Android만, flag disabled / 다른 플랫폼은 후속 별도 설계 | 저장소·세션 방식별 증명 필요. 미지원 플랫폼은 로컬 전용, 다른 플랫폼 큐 복제 금지 |

## 11. 승인 단계와 활성화 전 필수 변경

1. **설계 승인**: 위 결정, 최소 목적·필드·문구·보유·운영 책임을 사람이 확정한다. 구현 허가는 별도다.
2. **구현 승인**: API 전용 DTO·경로·권한, 제품/Core command 및 race 차단, Flutter 선택·binding·불변 큐,
   로컬 보존 UX와 삭제 진행 표시를 승인 범위 안에서 구현하고 합성 테스트를 통과시킨다.
3. **스키마 migration 승인**: 원본 선택 매핑/삭제 표식·binding/outbox/receipt/동의/장벽 후보의 DDL·권한과 upgrade·rollback·backup·복원
   계획을 별도 검토한다. 기존 migration을 수정하지 않고 추가한다. 이번에 migration·권한 변경은 없다.
4. **실제-data 수집 승인**: 목적·동의·보유·삭제 한계·보안/지원 책임·로그 비노출과 운영 복구 증거 확인 뒤
   별도 승인한다. 승인 후에도 개별 사용자의 명시적 동의와 기록 선택이 필요하다.
5. **배포·활성화 승인**: 환경·외부 연결·대상 플랫폼·릴리스·기능 flag 승인을 따로 받는다.
   앞 단계 승인이나 합성 시험 성공으로 대체하지 않는다.

현재 합성 버튼을 실제 기록 조회로 연결하거나 synthetic=false로 바꾸는 것만으로 활성화할 수 없다.
신규 판정·binding과 권한 경합 차단, 전용 실제 계약/동의, 큐·receipt·삭제 장벽,
보유·backup 정책, 합성 회귀와 격리 복원 증거가 선행되어야 한다. 첫 릴리스는 Android만, flag 기본값 disabled를 권고한다.
중단 시 송신만 멈추고 로컬 기록·COUNT를 유지한다. 스키마 적용 뒤 이전 바이너리만 설치하는 것은
데이터 rollback 증거가 아니다. 보호 backup과 미처리 삭제 원장을 보존하고 승인된 격리 복구 후 조정한다.
이번에 역사 업로드·migration·reset·삭제를 실행하거나 예약하지 않는다.

## 12. 이번 문서 작업의 검증 범위

이번 PR은 제안 설계, [독립 합성 모델과 테스트](../../tools/sync_model/README.md),
전용 sync-model workflow(`.github/workflows/sync-model.yml`)를 포함한다.
모델은 표준 라이브러리와 메모리의 합성 계정·ID·metadata 존재 추상값만 사용한다.
새 전용 CI는 모델 테스트와 탐색을 실행하며, 기존 API CI와 API offline runner는 변경하지 않는다.
모델은 앱 import나 기존 API offline runner 연결 없이 실행하며 DB·파일 영속화·네트워크·환경 설정을 사용하지 않는다.
실행 명령·unittest 수·고유 상태 수·검사 전이 수·한계와 음성 대조군 최단 반례는 모델 README와
작업 보고에 기록한다. 선택 trace와 유한 탐색은 전체 증명이나 실제 transaction 검증이 아니다.
일반 `git diff --check`와 별도로 미추적 제안서·모델 파일의 whitespace를 검사한다.
제품 테스트 suite·실제 SQLite/MySQL transaction/잠금·기기·외부 인증·백업 복원·배포 검증은 NOT_RUN이다.
독립 모델 성공은 실제-data 활성화 BLOCKED 및 AUTHOR_REVIEW_REQUIRED를 해제하지 않는다.

## 13. 일관된 세부 후보 계약 (PROPOSED / AUTHOR_REVIEW_REQUIRED)

이 절은 앞 절의 미확정 표현을 구체화하며 모든 DTO·API·시험·결정표에 함께 적용한다.
문서 수정 지시는 설계·스키마·구현·실데이터 수집·배포 승인으로 해석하지 않는다.
기존 로컬 기록·COUNT·PoC 동작과 기존 NOT_RUN 한계를 유지한다.

### 13.1 신규 선택 창

Android만, feature disabled가 기본이다. “새 완료”는 승인된 활성화 이후 현재 프로세스에서
성공한 단일 완료 저장 사건이다. 목록 조회·가져오기·복구·백업 복원·재시작에서 읽은 기록은 제외한다.
“즉시”는 저장 성공 뒤 동일 완료 확인 화면의 연속 흐름에서 다른 화면 이동·뒤로가기·닫기·
계정 전환·프로세스 종료 전에 선택하는 것이다. 초 단위 유예로 과거 선택을 허용하지 않는다.
로그인·동의·귀속 확인은 해당 화면의 하위 흐름으로만 진행하며 취소·이탈 시 미선택 자격을 닫는다.
선택 transaction 완료 전 프로세스 종료는 재시작 후 선택 불가다. 완료된 선택은 영속 재시도 가능하다.
local reference 유일 매핑과 원자 선택 전이로 연타를 합쳐 같은 sync_id/operation_id를 유지한다.
저장 결과 불명은 조정 후 판단하고 새 identity를 발급하지 않는다. 자동 계정 귀속·이전·역사 업로드·
합성 endpoint 재사용은 없다. 재동의도 과거 기록에 새 선택 자격을 부여하지 않는다.

### 13.2 로컬 삭제와 복구

선택/귀속된 로컬 완료의 사용자 삭제는 업로드 취소와 서버 metadata 삭제도 요청하도록 권고한다.
동의 철회는 목적 전체 서버 삭제이며 로컬 원본은 보존한다. 기존 로컬 삭제·복구 보관함·undo와
그에 따른 COUNT 규칙은 유지한다. 서버 불가로 삭제를 막거나 COUNT를 별도 보정하지 않는다.
서버 사본만 삭제하는 명령은 로컬 원본·COUNT를 바꾸지 않는다.

확인 문구 후보: “로컬 저장이 성공하면 이 기기 기록을 기존 복구 보관함으로 이동하고 새 전송을 중단합니다. 이미 전송 중인 요청은 서버에 반영될 수 있어 삭제 확인이 필요합니다.
연결된 서버 완료 정보도 삭제 요청합니다. 오프라인이면 서버 삭제는 대기합니다.
기기에서 복구해도 서버 정보는 복구하거나 다시 전송하지 않습니다.”
철회 문구 후보: “이 기기 새 전송을 중단하고 서버 철회와 삭제를 요청합니다. 서버 접수·제품 쓰기 차단·live 삭제 완료는 각각 확인해 표시합니다.
이 기기의 원본과 완료 횟수는 유지됩니다. 백업 잔존과 삭제 진행은 별도로 안내합니다.”

구체 후보는 **기존 원본 SQLite DB 안의 별도 `completion_sync_retirements` 표식 테이블**이다.
소스 `lib/repositories/sqlite_completion_repository.dart`의 deleteById는 deleted ID 삽입,
완료 행 제거, trash 복구 행 저장을 같은 transaction으로 처리한다. restoreTrash는 deleted ID를
제거하며 permanentlyDeleteTrash는 trash를 제거한다. 기존 deleted ID나 복구 payload만으로는
undo 뒤 삭제 증거를 보존할 수 없다. 이는 소스 관찰이며 실행 검증·안전성 증명이 아니다.

표식 후보는 local reference, 단조 deletion epoch, 삭제 intent UUID, 선택 매핑 참조,
retired/조정 상태만 보유한다. course_number/completed_on·원문·서명은 넣지 않는다.
원본 DB의 별도 선택 매핑 후보에 account/generation/sync_id를 선택 시 내구 저장하여 보조
queue/journal이 유실돼도 삭제 대상을 식별한다. 매핑 commit 전 송신을 금지한다. 이 스키마와
접근 보호·잔존 정보 최소화는 AUTHOR_REVIEW_REQUIRED다.

로컬 선형화 지점 L은 기존 삭제/복구 전이와 표식 insert/epoch 갱신을 **동일 원본 DB
transaction으로 commit**하는 지점이다. 이미 trash인 중복 삭제의 조기 return도 표식을 확인해야
한다. undo/복구 보관함 정리/영구 삭제는 표식·retired 매핑을 cascade 삭제하지 않는다.
undo는 원본과 기존 COUNT만 복원하고 서버 대상 retired 상태는 유지한다. L 뒤 process death나
보조 journal 실패에도 원본 표식은 남아야 한다.

원본 DB가 정상이고 서버/보조 store만 불가하면 L과 기존 사용자 삭제·COUNT 전이를 진행한다.
보조 journal 성공을 로컬 삭제의 전제로 삼지 않는다. 서버 삭제는 pending, upload만 차단한다.
반면 원본 DB 자체가 읽기 전용/공간 부족/commit 실패로 필요한 전이를 저장할 수 없으면 이는
서버 장애가 아닌 **로컬 저장 실패**다. transaction rollback 뒤 삭제 완료를 표시하지 않고 실제
원본/COUNT 상태를 재확인한다. 표식만 생략한 삭제로 우회하거나 동기화 안전성을 약속하지 않는다.

시작/재시작 시 어떤 upload worker보다 먼저 원본 DB의 표식 전체와 선택 매핑을 스캔한다.
보조 resolved 상태만 믿지 않고 원본 retired 상태와 대조한다. 미조정 표식은 같은 계정의 보조
journal에 멱등 복제하고 queue를 retired 처리하며 서버 삭제를 재개한다(같은 검증 계정+제한된 관리 권한, 업로드 동의 불필요). 원본 읽기/매핑/보조
조정 실패는 모든 upload를 paused로 유지한다. 다른 계정 자격으로 삭제하지 않는다.

모든 선택·송신 claim·삭제·undo·ACK 적용·재시도·백그라운드 worker는 단일 제품 coordinator를
통과한다. 후보는 원본 DB의 내구 claim/epoch와 local-reference별 transaction gate다.
다중 isolate/process도 같은 DB gate를 사용해야 하며 메모리 mutex만으로는 부족하다.
네트워크 동안 DB transaction은 유지하지 않는다. claim 전 L이면 송신 금지, claim 후 L이면
이미 송신됐을 수 있으므로 취소 성공으로 간주하지 않고 서버 삭제 보상 대상에 포함한다.
서버 삭제 worker도 같은 coordinator에서 claim하고 서버 응답 뒤 gate를 다시 획득한다.
ACK 적용 전 계정/generation/epoch/표식을 재검사하여 늦은 성공이 retired를 되돌리지 못한다.
worker 종료 뒤 claim 회수도 표식 조정 이후에만 허용한다.

보조 journal은 account/generation/sync_id, intent UUID, 알려진 revision, epoch와 pending/장벽 ACK를
복제한다. 원본-store와 보조-store 사이 **cross-store 원자성은 없다**. 원본 표식을 권위 있는
삭제 증거로 반복 조정한다. 서버 삭제 선도착도 sync_id 장벽을 만들어 늦은 create를 410으로
거부한다. base 불명/충돌은 본인 관리 조회로 조정하며 새 삭제 operation이 필요하면 원 intent에
연결하고 sync_id는 유지한다. timeout은 pending이다. undo/재동의는 재업로드 자격이 아니다.

모든 삭제 진입점·COUNT 경로의 L 참여, 원본 매핑/표식 내구성, worker 전역 gate, 구버전 앱·복원에
의한 표식 유실 방지, migration/rollback·잔존 정보 정책은 미입증이다. 원본 표식을 보존할 수 없는
저장 경로는 지원할 수 없다. 모두 활성화 BLOCKED / AUTHOR_REVIEW_REQUIRED이며 이번 작업은
표식·스키마·Flutter 구현을 승인하거나 수행하지 않는다.

### 13.3 Core–제품 후보 프로토콜: 활성화 BLOCKED

| 소유자 | 내구 상태·계약 |
|---|---|
| Core | 목적별 단조 generation, retired high-water fence, ACTIVE/REVOKING/DRAINING/PRODUCT_DELETED, command receipt·outbox |
| 제품 command 처리기 | 세대별 OPEN/CLOSED/DELETED gate, admission ticket ledger, inbox/outbox, metadata·receipt·sync_id 장벽 |
| 클라이언트 | 선택/철회/삭제 journal, 불변 큐, local epoch, 확인한 ACK |

1. Core가 새 g를 예약하고 OpenGeneration(command_id,g,policy)을 발행한다. 제품 OPEN ACK 후에만
   Core ACTIVE를 확정한다. retired fence 이하 Open은 영구 거부하며 철회 중 ACK로 재활성화하지 않는다.
2. Core Admit(operation_id,g)는 ACTIVE 검사·ticket 발급을 철회 전이와 직렬화해 영속한다.
   ticket은 검증된 계정/목적/g/operation/불변 명령에 묶인다. 제품은 OPEN gate 아래
   ticket 소비·metadata·receipt를 하나의 제품 transaction으로 commit한다.
3. Withdraw(withdrawal_id,g)는 Core의 REVOKING·retired fence·receipt·CloseGeneration outbox를
   원자 commit한다. 신규 admission은 즉시 차단한다. 제품 close 전 기존 ticket commit 가능성은
   남으므로 응답은 “철회 접수”이며 삭제 완료가 아니다.
4. 제품 Close는 모든 worker의 commit과 같은 gate 잠금/직렬화 지점에서 CLOSED·fence를 영속한다.
   이전 commit은 삭제 집합에 포함하고 이후 commit은 거부한다. 진행 transaction 종료와 미사용
   ticket 무효화 후 ClosedAndDrained(g,command_id) ACK를 발행하고 Core가 DRAINING을 기록한다.
5. DeleteGeneration은 CLOSED/drain 확인 후 live metadata를 삭제하고 장벽을 보존한다.
   13.4 inventory별 제거 ACK, 최종 sweep과 진행 transaction 부재 확인 뒤
   ProductDeleted(g,command_id,barrier_version,inventory_version)를
   내구 outbox에 기록한다. Core가 일치 ACK를 내구 저장하는 D에서만 PRODUCT_DELETED다. 선언된 live inventory 범위이며 backup 만료·오프라인 기기 정리는 별도다.
6. 재동의는 제품 삭제·장벽 확인 후 더 큰 g로만 허용한다. 옛 ticket·큐·선택을 이월하지 않는다.

A는 Core의 ACTIVE 검사/Admit commit과 같은 잠금 순서에서 직렬화한다. F는 모든 제품 instance의
쓰기 commit이 공유하는 gate 행 잠금 아래 commit하며 먼저 잠근 write의 commit/rollback 종료를
기다린다. F 전 commit은 A 전후와 무관하게 삭제 집합이다. F 뒤에는 기존 ticket도 commit 불가다.
drain ACK는 F 내구 확인·진행 transaction 종료·미사용 ticket 폐기 후에만 발행한다.
Delete가 Close보다 먼저 오면 prerequisite_pending으로 내구 보류하며 완료 ACK를 만들지 않는다.
늦은 Open은 retired high-water 이하에서 거부한다. 중복 Withdraw/Close/Delete는 현재 단조 상태만
반환하고 다시 열거나 행을 만들지 않는다. D 전 재동의는 pending/거부한다. 새 세대 예약 중 옛 ACK도
현재 generation/phase를 되돌리지 못한다. 실제 잠금·격리 구현은 미확정이다.

명령 ID는 계정/목적/g에 묶인 멱등 키다. 활성 키의 다른 내용은 거부한다. erased 키는 원문 비교 없이 retired 결과만 반환한다(13.4). ACK는 원 command_id,
g, 단조 phase, barrier version을 포함한다. 중복 재생·역순 ACK가 상태를 되돌릴 수 없다.
Core/제품 crash는 내구 inbox/outbox와 상태 조회로 재개한다. timeout/partition은 pending이며
ACK를 추정하지 않는다. Core 불가 시 신규 admission 차단, 제품 불가 시 A가 commit된 경우만 접수 후 대기한다. Core commit 여부 불명은 접수 성공으로 표시하지 않고 같은 withdrawal_id로 조회/재시도한다. Close/삭제 timeout도 완료로 승격하지 않는다.
이미 발급한 ticket의 close 전 commit은 반드시 drain/삭제에 포함한다. 무기한 partition의 완료 시한은
보장하지 않는다. 철회·삭제·상태 조정은 같은 검증 계정과 upload scope에서 분리한 제한된 본인 관리 권한을 요구한다. 업로드 동의가 없어도 수행하며 재동의를 조건으로 삼지 않는다.
Core는 공개 command/ACK만 사용하며 제품 테이블을 직접 쓰지 않는다.

미해결 원자성: Core 상태/receipt/outbox 단일 commit, 제품 gate/ticket/행/receipt 단일 commit,
다중 worker commit과 Close의 전역 직렬화, 로컬 두 store의 삭제 증거 보존이 필요하다.
격리 수준·잠금 순서·deadlock 재시도·ticket 회수·다중 instance 설계는 미확정이다.
사전 동의 조회 뒤 독립 commit, 비동기 이벤트만 전달, ticket TTL만으로 폐기는 충분하지 않다.
안전한 프로토콜이 아직 확립·입증되지 않았으므로 실패 주입 증거와 저자 검토 전 활성화 BLOCKED다.

### 13.4 보유 결정 행렬

앞 절의 30일/90일은 비교용 미승인 대안이며 확정 SLA나 약속이 아니다. 임의 최종 기간을 선택하거나
법적 적합성을 주장하지 않는다. 아래 owner는 실제 담당자를 지정해야 할 역할이다.

| 자료·목적 | 삭제 trigger 후보 | owner 역할 | 정리 실패 | 복원 | 활성화 전제 |
|---|---|---|---|---|---|
| 활성 metadata·완료 확인 | 삭제/철회/탈퇴/승인된 만료 | 제품 데이터 책임자 | pending 재처리·경보 | 최신 장벽 우선 제거 | 목적·기간·삭제 목표 승인 |
| 로컬 queued payload·재시도 | ACK 후 불필요/취소/철회/queue 만료 | 모바일 책임자 | 송신 잠금·정리 재시도 | 자동 송신 금지·조정 | 최대 queue 수명 승인 |
| operation receipt·멱등 조정 | 삭제/철회 때 즉시 payload 제거, 조정 창 종료 때 최소 제어 정보 추가 정리 | 제품 API 운영자 | 새 create 금지·보류 | 최신 장벽보다 우선 금지 | queue/backup과 기간 정합 |
| 삭제 장벽·fence·journal·부활 방지 | 상세 자료 최소화 후에도 영구 거부 유지 | Core/제품 각 원장 책임자 | 원장 불명 시 admission 차단 | 최신 원장 선적용 | 영구 거부·원장 복구 승인 |
| 최소 감사·처리 추적 | 승인 목적/기간 종료 | 보안·개인정보 운영자 | 접근 제한·경보 | 만료 자료 정리 재적용 | 항목·기간·비노출 승인 |
| backup·장애 복구 | 승인된 순환 만료/매체 폐기 | 백업 운영자 | 격리·지연 안내 | 원장/fence 먼저, 검증 전 서비스 금지 | 최장 수명·격리 복원 증거 |

queue 만료는 로컬 원본 삭제나 새 identity 발급 근거가 아니다. receipt 선만료 시 상태/장벽으로
조정하거나 paused로 둔다. queue 최대 수명·receipt 조정 창·backup 최장 수명을 함께 결정한다.
상세 장벽을 먼저 없애지 않으며 압축해도 retired generation은 Core와 제품에서 영구 거부한다.
활성 세대의 단건 삭제는 세대 fence만으로 보호되지 않으므로 sync_id 장벽 또는 동등한 영구 거부
증거가 필요하다. 그 수명·압축 방식 미정도 BLOCKED다. 원장 유실 시 backup 복원 서비스를 격리한다.

#### 13.4.1 삭제 사본 inventory와 완료 경계

아래 inventory v1은 제안이며 실제 구성 확인·owner 지정·누락 사본 검토 전 활성화 BLOCKED다.
삭제 범위는 단건 sync_id 또는 철회 generation 전체다. 제거 대상 metadata는 course_number,
completed_on 및 이를 담은 정규화 명령/JSON/응답 사본이다. 원본 Flutter 완료·복구 자료는
서버 metadata 사본 삭제 범위 밖이며 사용자 로컬 삭제·복구 정책을 그대로 따른다.

| 사본/owner 후보 | 삭제·최소화 및 보유 이유 | 확인/ACK 경계 |
|---|---|---|
| 제품 main row·복제본·조회 캐시 / 제품 | 두 metadata 필드와 projection 제거; sync_id/계정/g/최소 장벽만 부활 방지용 분리 | 모든 서비스 read replica·캐시 무효화/삭제 ACK·sweep |
| operation receipt·캐시된 성공 응답 / 제품 API | 원명령·정규화 payload·응답 body 및 metadata 비교값 제거; erased 상태·불투명 operation ID·장벽 참조만 | receipt 전환과 장벽 commit; 캐시 제거 ACK |
| admission ticket / Core·제품 각 소유 | 미사용 ticket 폐기, payload/명령 snapshot 제거; g/operation/소비·폐기 상태 최소화 | Core/제품 각 ledger 정리 ACK |
| inbox/outbox·재시도·dead-letter / 각 메시지 소유자 | 처리/미처리 payload·성공 응답 제거/최소 제어 envelope로 교체; retired 메시지는 적용 금지 | durable queue·DLQ·전달 중 메시지 drain 및 소비자 ACK |
| 클라이언트 로컬 queue·응답 캐시 / 모바일 | selected/in_flight/cancelled/acked 모두 최소 metadata payload·성공 body 제거; retired 매핑만 조정용 | 연결된 기기별 정리 ACK; 오프라인 기기는 별도 pending |
| 원본 표식·보조 journal / 모바일 | 원문·두 metadata 필드 금지; local ref/계정/g/sync_id/intent/epoch/최소 상태를 부활 방지용 보유·점진 최소화 | L과 재시작 스캔·표식/매핑 검증; undo로 제거 금지 |
| 로그·APM·추적·오류·감사 / 운영 | 처음부터 payload·식별자 비노출; 발견된 사본은 별도 삭제/사고 조정, 최소 고정 code·집계만 | sink별 검토/정리 ACK 없으면 해당 범위 완료 주장 금지 |
| backup·snapshot·스토리지 WAL/복구 로그 / 저장소 운영 | live API로 재생 금지; 승인된 순환 만료·접근 제한, 최신 장벽 선적용 | live ACK와 별도 만료/격리 복원 증거; 최종 기간 미정 |

ProductDeleted는 inventory_version과 제품 소유 live 저장소·replica·receipt·캐시·ticket·메시지의
각 durable 제거/최소화 ACK와 로그·추적 sink의 비노출/정리 확인을 묶는다. Core는 자신의 ledger/outbox live 정리 ACK와 제품 ACK가
같은 g/장벽 버전에 도달한 뒤 D를 기록한다. 전달 중 payload가 sweep 뒤 다시 유입될 수 있으면
D를 발행하지 않는다. 모든 worker는 장벽 우선 검사로 재적용·성공 body 재생을 금지한다.
오프라인 기기·로컬 원본·backup/WAL은 이 서버 live 경계에 포함되지 않는다. 상태 응답은
`server_live_inventory`, `device_cleanup=pending/acknowledged`, `backup_expiry=pending/confirmed`,
`anti_resurrection_evidence=retained`를 분리한다. 기기까지 포함한 완료 표현은 필요한 기기 ACK 전
사용하지 않는다. 알 수 없는 사본은 완료 범위를 넓혀 추정하지 않고 blocker로 남긴다.

#### 13.4.2 erased receipt와 재생 거부

활성 receipt에서만 동일 명령 비교를 수행한다. 삭제 transaction은 sync_id 장벽과 관련 receipt의
erased 전환·원명령/응답 제거를 함께 commit해야 한다. 이후 인증·소유자 조건 확인 뒤 retired g,
sync_id 장벽, erased operation ID를 **원문 비교보다 먼저** 판정한다. 같은 operation의 동일/변조
본문 모두 고정 410 `operation_retired`이며 원래 성공 body·course_number·completed_on을 반환하지
않는다. 다른 operation으로 같은 sync_id도 410, 일반 GET은 동일 404다. 중복 삭제는 최소 장벽
진행 상태만 반환하며 erased create의 과거 200 성공을 복구하지 않는다. 철회 접수 후에는 기존
성공 receipt 재생도 차단하고 pending/retired 제어 결과만 반환한다. 기존 ticket의 F 전 commit
허용과 사용자에게 과거 metadata를 재노출하는 권한은 별개다.

erased operation ID→장벽 참조와 sync_id 장벽은 원문 없이 옛 요청을 거부하는 후보이나,
계정 연결·기록 존재·작업 순서 자체가 잔존 개인 정보다. g 전체 폐기는 단조 high-water로 상세
receipt를 압축할 수 있지만 활성 g의 단건 삭제는 그것만으로 보호되지 않는다. 무작위 새 operation
ID만으로 과거 sync_id 부활을 막을 수 없으므로 단건 거부 증거도 필요하다.

영구 metadata hash는 도입하지 않는다. 과정은 두 값이고 날짜 범위도 작아 hash는 사전 대입·연결
위험이 있으며 삭제 대체가 아니다. 대안은 최소 불투명 ID 장벽 유지, 해당 세대 전체 폐기 후
high-water로 압축(다른 활성 기록에 영향), 서버 발급/인증된 create 자격을 유한 재생 창과 키 폐기로
무효화하는 별도 계약이다. keyed digest도 키 보유 중 연결 가능성·키 유실/회전·복원 실패 위험이
있어 자동 대안이 아니다. 원문 없는 키 충돌 판정은 erased 뒤 포기하고 전부 거부한다.
단건 장벽의 수명/압축, ID 연결 최소화와 백업·queue 최장 수명의 정합은 미결정이며
AUTHOR_REVIEW_REQUIRED / 활성화 BLOCKED다. 기간을 임의 확정하거나 법적 적합성을 주장하지 않는다.

### 13.5 제품 합성 검증 행렬 — 계획만, 전 항목 NOT_RUN

A/F/D/L은 7·13.2·13.3의 선형화 지점이다. 아래는 제품 통합 테스트 코드나 실행 결과가 아니다. 독립 모델 결과는 12절의 별도 검토 기록을 따른다.
증거는 향후 합성 fixture의 순서 추적·장애 주입·저장 상태 비교이며 실제 사용자 자료를 사용하지 않는다.

| 요구사항 | 합성 setup | 순서·crash/실패 지점 | 기대 불변식 | 필요한 증거 | 현재 상태 |
|---|---|---|---|---|---|
| admission 전 철회 | 합성 계정/g OPEN | A → Admit; A commit 직후 종료·응답 유실 | 새 ticket 없음; 같은 withdrawal_id 재조회는 접수, F/D 추정 없음 | Core transaction 순서·outbox/상태 | NOT_RUN |
| admission 후 철회 | ticket 발급 후 write 대기 | Admit → A → 제품 commit → F → drain → D; Close 전달 실패 | F 전 commit 허용, 그 행도 삭제 집합; 접수와 차단 구별 | gate 잠금 순서·삭제 inventory ACK | NOT_RUN |
| 제품 commit 후 철회 | 합성 행·응답 미전달 | commit → A → F → D → 늦은 ACK | 행/응답 사본 제거; ACK로 UI·queue 부활 없음 | epoch 비교·사본별 조회 결과 | NOT_RUN |
| F 경합 | 두 worker/instance와 ticket | write 잠금/Close 양 순서; deadlock·worker 종료 | F 전 commit/rollback 종료 후 drain; F 이후 어떤 옛 write도 commit 불가 | 격리 수준·잠금/commit 추적 | NOT_RUN |
| 업로드 중 로컬 삭제 | 선택 매핑·in-flight claim | claim → L → 서버 create/삭제 양 순서; L 뒤 종료 | 로컬 기존 삭제/COUNT, 서버 삭제 장벽·보상, stale ACK 무효 | 원본 표식·queue·서버 장벽 비교 | NOT_RUN |
| 보조 store 실패 | 정상 원본·고장 journal | journal 실패 → L → process death → startup 스캔 실패/재조정 | L·COUNT 유지; 표식 생존; 조정 전 모든 upload 차단 | 원본 transaction·시작 gate·재조정 멱등 증거 | NOT_RUN |
| 원본 저장 실패 | 합성 원본 commit 실패 주입 | 삭제/표식 transaction 실패·rollback | 삭제 성공 표시 없음; 실제 원본/COUNT 확인; 안전 동기화 주장 없음 | rollback·UI 상태·송신 gate | NOT_RUN |
| undo/복구 정리 | L 완료·서버 pending | undo → trash 정리 → 종료/재시작; 보조 유실 | 기존 COUNT 복원 규칙, 표식/retired 매핑 유지, 재업로드 없음 | 각 전이 전후 원본-store 상태 | NOT_RUN |
| stale ACK·계정 전환 | A계정 삭제 intent·B 로그인 | L/철회 후 옛 생성 ACK; B worker 재개 | epoch 불일치 ACK 무시, A intent를 B로 송신 안 함 | coordinator/자격/epoch 추적 | NOT_RUN |
| 관리·업로드 권한 분리 | 업로드 동의 없음·만료/철회, 같은 검증 계정 | 업로드/철회/삭제/상태 조정 각각 재시도; 관리 권한 없음·타 계정도 비교 | 동의 없는 업로드 거부; 본인 관리 권한으로 철회·삭제·상태 조정 허용, 재동의 불필요; 타 계정/관리 권한 없음은 거부 | 자격별 허용·거부와 metadata 비노출 | NOT_RUN |
| 중복·역순 명령 | 같은 ID 및 변경된 합성 명령 | Delete→Close, 중복 Withdraw/Delete, 늦은 Open/ACK; commit/ACK 사이 종료 | prerequisite_pending·단조 phase, 재개 멱등, 옛 세대 재활성화 없음 | inbox/outbox·receipt·gate 기록 | NOT_RUN |
| erasure 뒤 receipt 재생 | 생성 성공 receipt/캐시·활성 세대 단건 삭제 | 삭제 → 같은 operation의 동일/변조 payload 및 새 operation·같은 sync_id | 모두 장벽 410, 원문 비교·성공 body 재생·행 재생성 없음 | receipt 최소화·캐시/메시지 사본 검사 | NOT_RUN |
| inventory ACK 실패 | 사본별 합성 metadata | main row 삭제 → cache/message purge 실패 → 재시도 | D 없음, pending 유지; 모든 선언 ACK 후만 D | inventory_version별 ACK·최종 sweep | NOT_RUN |
| 재동의 | 폐기 g와 옛 선택/큐 | D 전 재동의; D 뒤 g+1 Open ACK 전후; 옛 ticket 재생 | D·장벽·새 Open/ACTIVE 전 upload 불가, 과거 선택 이월 없음 | Core/제품 phase 및 신규 자격 기록 | NOT_RUN |
| backup 복원 | 삭제 전 합성 snapshot·최신 원장 | 격리 복원 → 최신 fence 적용 → sweep; 원장 누락/구버전 복원 | 검증 전 서비스 금지; 원장 불명 격리; 옛 metadata 재생·송신 없음 | 복원 절차·원장 버전·사본 검사·서비스 gate | NOT_RUN |
| 최소 범위 유지 | 합성 신규/과거·타 플랫폼·날짜 DTO | disabled/Android 외·이탈·재시작·잘못된 필드 입력 | 명시 신규 선택만, 세 최소 필드, 원문/신원 제외·날짜 불변 | DTO/선택 gate·비노출 검증 | NOT_RUN |

추가 저자 결정: 원본 표식/선택 매핑·worker gate·원자성, 삭제 inventory와 ACK 책임,
receipt 최소화·잔존 식별자 대안, 각 보유 owner·기간·복원 정책이다. 모두
AUTHOR_REVIEW_REQUIRED이며 실제-data 활성화 BLOCKED를 유지한다.
