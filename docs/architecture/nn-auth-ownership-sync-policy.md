# JesusLife One 공통 인증과 너랑나랑 소유권·동기화 정책

상태: 설계 초안 / AUTHOR_REVIEW_REQUIRED. 기준일: 2026-10-26.
작업 순서: 설계 → API 계약 초안 → 문서 품질 검토. 구현 승인을 의미하지 않는다.

## 1. 목적과 범위

JesusLife One 전체 제품이 공유하는 계정과 너랑나랑 개인 완료 기록의 선택적 동기화 경계를 정한다. 로그인 없이 로컬 문답 완료·열람을 계속할 수 있고, 서버 장애도 로컬 저장 성공을 막지 않아야 한다. 로컬 저장 성공과 서버 동기화 성공은 별도로 표시한다.

이번 산출물은 문서뿐이다. 인증 코드, DB, migration, 기록 API, Flutter 변경, 패키지 설치, 외부 인증 서비스 연결은 포함하지 않는다. 아래 경로·스키마·기간·동작은 모두 제안이며 현재 구현 사실이 아니다.

확인한 근거:

- API [AGENTS.md](../../AGENTS.md), [README](../../README.md), [실행 의존성](../../requirements.txt), [검증 의존성](../../requirements-dev.txt).
- [CompletionRecordMetadata](../../app/modules/neorang_narang/schemas.py), [계약 테스트](../../tests/test_neorang_narang_schemas.py), [경로 테스트](../../tests/test_api_routes.py).
- Flutter [AGENTS.md](../../../neorang_narang_app/AGENTS.md), [공통 원칙](../../../neorang_narang_app/docs/governance/COMMON_PRINCIPLES.md), [프로젝트 기준](../../../neorang_narang_app/docs/governance/PROJECT_CONTEXT.md), [점검표](../../../neorang_narang_app/docs/governance/CHECKLIST.md).
- Flutter [기록 모델](../../../neorang_narang_app/lib/models/completion_record.dart), [SQLite 저장소 코드](../../../neorang_narang_app/lib/repositories/sqlite_completion_repository.dart), [완료 화면](../../../neorang_narang_app/lib/pages/completion_signature_page.dart), [완료 회귀 테스트](../../../neorang_narang_app/test/completion_flow_regression_test.dart), [완료 흐름 검토](../../../neorang_narang_app/docs/reviews/2026-10-10-completion-flow-1.6.md).

Flutter 링크는 두 저장소가 같은 상위 폴더에 있을 때 해석된다. 실제 DB 파일·사용자 기록은 읽지 않았다. API 브랜치는 `feature/nn-completion-contract`, Flutter는 `main`이며 시작 시 두 작업 트리가 깨끗했다. API AGENTS의 초기 상태 설명과 달리 현재 README·코드에는 모듈 health와 계약 테스트도 있다. 현재 동작은 코드를 근거로 판단했다.

## 2. 데이터 원본과 소유 제품

| 데이터 | 원본 책임 | 경계 |
|---|---|---|
| 불변 사용자 UUID·세션·동의 | JesusLife One core | 제품 전용 계정 생성 금지. ChurchOS 통합 경험과 인증 책임 구분 |
| 교회·조직·소속·역할 | ChurchOS | 개인 기록 소유자를 결정하지 않음 |
| 문답·완료·개인 원문 | 너랑나랑 | 기기 원본 보존, 다른 제품의 내부 모델 직접 참조 금지 |
| 서버 최소 메타데이터와 revision | 너랑나랑 동기화 경계 | 서버에 승인된 메타데이터 사본과 동기화 버전의 기준 |
| 의미·추론 | CHGO | 개인 기록 자동 전송·공용 지식 승격 금지 |

현재 모바일 SQLite가 기록 원본이며 웹·기타 플랫폼은 기존 SharedPreferences 경로가 있다. 동기화하지 않는 모바일 사용자는 기존 SQLite만 사용한다. 동기화를 켜도 서버는 전체 기록 백업이 아니다. 이름·은혜 원문·서명을 서버 메타데이터로 복원할 수 없다. 향후 서버 업무 저장소를 정하더라도 개인 원문을 자동 이전하지 않는다.

현재 계약의 허용 필드는 `id`, `course_number`(1·2), `participation_mode`(solo·together), `completed_at`, `revision`(엄격한 정수, 1 이상), `deleted_at`뿐이다. UUID, 시간대 필수·UTC 정규화, 추가 필드 거부가 테스트된다. 소유권·인증·영속화·revision 증가 규칙은 아직 없다. Flutter 모델의 기존 ID는 시각 기반이며 revision·서버 tombstone 필드는 없다.

## 3. 로그인하지 않은 사용자 흐름

앱 시작 → 로컬 이어하기·문답 → 로컬 저장 확인 → 완료·열람. 로그인 유도 때문에 완료를 막지 않는다. 동기화 기본값은 꺼짐이며 백그라운드 계정 생성·업로드·CHGO 전송은 없다. 실패한 로컬 저장은 기존 복구 흐름으로 남기며 서버 성공으로 대체하지 않는다.

기존 ID와 원문을 유지한다. 향후 동기화를 선택할 때만 승인된 변환 절차로 기존 ID↔sync UUID 매핑을 한 번 영속화한다. 매핑 실패 시 전송을 시작하지 않는다. 기록 내용·시각을 이용해 매번 UUID를 재생성하지 않는다.

## 4. 로그인·동기화 사용자 흐름

1. 사용자가 동기화를 선택하면 전송 필드, 제외 원문, 보유·철회·삭제 범위를 보여준다.
2. 공통 계정 로그인 후 너랑나랑 동기화 동의를 별도로 받는다. 로그인·교회 가입만으로 켜지지 않는다.
3. 사용자가 동기화할 로컬 기록을 선택하고 현재 계정 귀속을 확인한다. 과거 로컬 기록이 로그인 계정의 기록이라고 자동 단정하지 않는다.
4. 선택 기록의 UUID 매핑·계정별 대기열을 저장하고 서버 변경을 먼저 조회한 뒤 충돌 없는 작업만 보낸다.
5. 서버 응답 확인 후 승인 revision·cursor·대기열 상태를 원자적으로 저장한다. 응답 유실은 동일 작업 재시도로 복구한다.
6. 만료·장애·충돌은 동기화 상태로 표시한다. 로컬 완료·열람은 계속된다. 취소하면 업로드하지 않는다.

로그아웃은 전송을 멈추고 토큰을 제거한다. 기존 로컬 기록은 사용자 선택 없이 지우지 않는다. 계정 A의 UUID·대기열·서버 사본을 B에 보내지 않으며, 계정 전환 시 A 자료 접근을 분리·잠근다. 잠긴 자료 때문에 새로운 로컬 사용까지 막지 않는다. 재로그인 시 같은 계정과 유효한 동의를 확인한다.

## 5. 토큰과 사용자 식별 규칙

공통 계정의 JWT `sub`는 불변 사용자 UUID다. 이메일·이름·교회·기기 ID는 대체키가 아니며 탈퇴 후 UUID를 재사용하지 않는다. 외부 제공자를 선택하면 `(issuer, provider subject)`를 core UUID에 매핑하고 이메일 일치만으로 계정을 병합하지 않는다.

제안: access token 유효기간 10분, refresh token 비활성 만료 30일·절대 만료 90일. 수치는 승인 전 후보이며 운영값이 아니다. access token은 메모리 중심, refresh token은 지원 플랫폼의 안전한 기기 저장소에 보관한다. 일반 SQLite·SharedPreferences·소스·로그에 저장하지 않는다. 웹 보안 저장·세션 방식은 별도 승인하며 모바일 저장 방식을 그대로 복제하지 않는다.

공통 인증은 Authorization Code + PKCE 후보, refresh 회전·재사용 탐지·세션 폐기, 서버측 refresh 검증값 보호를 포함한다. 이는 [OAuth 보안 권고 RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html)의 인증 흐름·refresh 보호 원칙을 참고한 제안이다. JWT는 서명 알고리즘 허용목록, 신뢰한 키·issuer·audience·토큰 종류·만료와 subject를 검증한다. [JWT 보안 권고 RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html)를 참고한다. 공통 계정이어도 제품별 scope와 동의는 분리한다.

서버는 검증된 `sub`에서만 owner를 주입한다. 본문·쿼리·헤더의 `user_id`, `owner_id`는 소유권 증거가 아니며 요청 스키마에 두지 않는다. 추가 필드는 422로 거부한다. ID token을 업무 API access token으로 받지 않는다. 로그아웃·철회·탈퇴를 즉시 반영하려면 매 요청의 계정·세션·동의 상태를 서버에서 확인한다. 짧은 JWT 만료만으로 즉시 폐기를 주장하지 않는다. 이 확인이 불가능하면 서버 동기화는 실패 처리하고 로컬 사용을 유지한다.

## 6. 개인 기록 소유권

서버 권한의 기본키는 `(owner subject, record UUID)`다. 조회·수정·삭제·복원·변경목록·재시도 모두 동일한 소유자 필터를 적용한다. UUID를 알아도 접근할 수 없다. 다른 소유자의 UUID 조회는 존재 여부를 숨기는 404이며 그 revision도 반환하지 않는다. 같은 UUID가 다른 계정에 있더라도 레코드를 연결하거나 이전하지 않는다.

로컬 소유와 서버 계정 귀속은 다르다. 공유 기기의 기록은 사용자가 업로드할 권한이 있는지 확인해야 한다. 최초 계정 귀속 후 계정 간 이전·병합은 이번 API에서 지원하지 않는다. 서버 메타데이터 소유권은 함께한 상대방의 원문·서명에 대한 처분권을 뜻하지 않는다.

## 7. 함께하기 참여자의 권리와 한계

상대방 이름은 표시용 로컬 값이며 공동소유권·계정 연결·공유 동의가 아니다. `together`는 참여 방식만 나타내며 상대방의 신원·실제 확인·서명을 서버가 인증했다는 뜻이 아니다. 현재 로컬 완료 확인은 인증된 전자서명이 아니다.

상대방의 확인·서명·동의는 그 당사자만 할 수 있다. AI, 기록 소유자, 관리자 모두 대신 생성할 수 없다. 현 단계에서는 상대 계정 초대·자동 열람·서명 동기화를 제공하지 않는다. 향후 공유는 당사자별 독립 인증·목적별 명시적 동의·철회·최소 공유 계약을 별도 설계한다. 상대방의 개인정보 처리·삭제 요청 통로도 그 단계에서 정하며 이름만으로 원격 소유권을 부여하지 않는다.

## 8. 교회·테넌트·관리자 권한 경계

개인 기록에는 교회 소속을 소유권 조건으로 사용하지 않는다. 교회 이동·탈퇴·리더 교체로 개인 기록 owner가 바뀌지 않는다. church UUID, role UUID, user UUID를 분리한다. 개인 API는 테넌트 헤더·관리자 role만으로 열람 권한을 부여하지 않는다.

교회 관리자·소그룹 리더·운영 지원자에게 기본 열람·대리 수정 권한은 없다. 향후 지원 접근도 별도 승인·목적·시간 제한·감사 절차가 필요하며 현재 제공되는 권한으로 표현하지 않는다. 교회용 통계·공유 API는 별도 동의와 재식별 위험 검토 전 범위 밖이다.

## 9. revision 충돌 상태표

초안은 서버 승인 revision을 채택한다. 요청의 `revision = r`은 반영하려는 **결과 버전**, 별도 명령 envelope의 `base_revision = b`는 마지막으로 확인한 서버 버전이다. 신규 b=0, r=1; 이후 r=b+1. 기존 Metadata 모델은 그대로 두고 envelope는 향후 별도 계약으로 검토한다. 로컬 편집 횟수를 서버 revision으로 보내지 않는다.

서버 현재 버전을 s라 한다. 아래 비교는 인증·동의·소유자 검사 후, UUID별 원자적 비교·저장으로 수행한다. 동일 작업 receipt 재생을 먼저 검사한다. 정상 JSON 정규화(UTC·null 포함) 후 허용 필드 전체와 작업 종류·base를 비교하며 민감 원문 해시는 만들지 않는다.

| 서버 상태 / 요청 | 결과 초안 | revision 변화 |
|---|---|---|
| 없음, create b=0 r=1 | 201 생성 | 1 |
| 없음, update/delete/restore 또는 잘못된 최초 버전 | 404 또는 잘못된 create 버전 409 | 없음 |
| 동일 operation UUID와 동일 명령 재시도 | 200 receipt 재생, replayed=true | 없음 |
| 동일 operation UUID인데 명령 내용 다름 | 409 idempotency_key_reused | 없음 |
| r=s, 마지막 승인 명령과 동일 | 200 이미 반영됨 | 없음 |
| r=s, 내용·종류·base가 다름 | 409 revision_conflict | 없음 |
| r<s, 재생 가능한 receipt 없음 | 409 stale_revision, 낮은 revision 쓰기 거부 | 없음 |
| 활성 상태, b=s r=s+1, 정상 update/delete | 200 반영 | s+1 |
| b<s 또는 r>s+1 또는 r≠b+1 | 409 revision_conflict 또는 revision_gap | 없음 |
| tombstone, 일반 create/update | 409 deleted_record, 암묵적 부활 금지 | 없음 |
| tombstone, 명시적 restore b=s r=s+1 | 200 복원 | s+1 |
| 활성 상태, 명시적 restore | 409 not_deleted (동일 receipt 재생 제외) | 없음 |

이미 승인된 과거 명령의 receipt 재생은 낮은 revision의 새 쓰기가 아니다. 응답의 `applied_revision`은 과거 승인 버전, `current_revision`은 응답 시점의 현재 버전으로 구분한다. 클라이언트는 과거 receipt로 현재 상태를 덮어쓰지 않는다. receipt가 만료되면 낮은 revision은 409로 반환하고 현재 상태를 조회한다.

두 기기가 s=3에서 각각 b=3 r=4로 수정하면 하나만 반영된다. 나머지는 같은 r이라도 내용이 다르므로 409다. 충돌 시 서버·로컬 후보를 보존하고 사용자 선택을 기다린다. 자동 덮어쓰기·시각 기반 승자 선택은 금지한다. 사용자가 현재 s=4를 확인하고 선택한 새 명령 b=4 r=5를 생성하거나 서버본을 수용한다.

409 응답 초안:

```json
{
  "error": {"code": "revision_conflict", "request_id": "opaque-request-id"},
  "record_id": "d752bfee-2574-4be4-9fa5-e3475958aeb2",
  "current_revision": 4,
  "current_deleted_at": null,
  "retryable": false
}
```

현재 메타데이터 본문은 소유자 인증 GET으로 다시 얻는다. 모든 성공 응답에도 `current_revision`, `applied_revision`, `replayed`, 서버 `updated_at`을 envelope로 반환한다. 이 값들은 기존 Metadata 필드 추가가 아니다. 409 후 내용을 확인하지 않고 revision만 올려 재시도해서는 안 된다.

## 10. 등록·수정·삭제·복원·재시도 흐름

### UUID와 명령

sync UUID는 기기에서 한 번 생성해 저장하고 완료 재시도·재시작·기기 이전·복원에서 유지한다. 기존 로컬 ID는 바꾸지 않고 매핑한다. 백업·내보내기도 매핑을 보존해야 하며, 매핑 유실 시 같은 기록을 새 UUID로 자동 업로드하지 않는다. 신규 기록 역시 로컬 저장과 UUID·대기열 연결의 원자성을 검증한 뒤 도입한다. 내용이 비슷한 기록을 자동 병합하지 않는다.

명령 envelope 후보는 `operation_id`(기기 생성 UUID), `base_revision`, `metadata`다. operation은 create/update/delete/restore 경로로 구분한다. path UUID와 metadata.id 불일치는 422다. 계정·동의 generation은 서버 세션에 결합하며 클라이언트 주장을 신뢰하지 않는다. UUID별 단일 진행 명령을 사용한다.

### 등록과 수정

등록은 create b=0 r=1, deleted_at=null로 시작한다. 수정은 마지막 승인본 s를 기반으로 전체 허용 메타데이터를 r=s+1로 보낸다. 서버는 owner·UUID 유일성, 버전 검사, 저장, receipt, 변경 이벤트를 한 트랜잭션으로 처리한다. 통신 응답 전 끊겨도 같은 UUID·operation_id·본문 재전송으로 중복 생성되지 않는다.

completed_at은 최초 완료 사건의 기기 보고 시각으로 보존한다. 일반 수정·삭제·복원으로 바꾸지 않는다. 실제 시각 정정이 필요하면 원래 값을 남기는 별도 정정 계약을 승인받는다. 은혜 원문만 바뀌어 메타데이터가 같으면 서버에 그 원문이나 원문 변경 사실을 보내기 위해 revision을 올리지 않는다.

### 삭제와 복원

삭제는 b=s r=s+1이며 서버가 UTC deleted_at을 부여한 tombstone으로 남긴다. 삭제 명령의 metadata.deleted_at은 null로 제한하고 작업 종류로 의도를 표현하는 초안이다. 클라이언트의 삭제 시도 시각은 로컬 큐에만 남긴다. 응답 Metadata.deleted_at은 서버 삭제 승인 시각이다. 기존 계약은 null과 timestamp를 모두 허용하지만 명령별 제한은 향후 검증을 추가해야 한다.

복원은 사용자 명시 선택 후 최신 tombstone을 조회하고 restore b=s r=s+1로 보낸다. 서버는 deleted_at=null로 만들고 UUID·completed_at을 유지한다. 서버 메타데이터 복원이 로컬 원문·서명 복원을 보장하지 않는다. 로컬 휴지통·복구 보관함과 서버 tombstone은 별개 상태이며 기존 로컬 영구 삭제가 서버 삭제 완료를 뜻하지 않는다.

늦은 기기의 create/update는 tombstone을 지울 수 없다. 삭제·복원이 경합해도 revision 검사를 따른다. tombstone 보유기간 만료 후에는 구형 큐를 바로 재생하지 않고 전체 재조정을 요구한다. 최소 삭제 UUID 차단목록 또는 계정별 동기화 generation을 보존하여 오래된 create가 부활시키지 못하게 한다. 계정 최종 삭제 후에는 폐기된 subject와 동의 generation으로 재전송을 막는다.

### 오프라인 대기열과 시간

큐에는 계정, sync UUID, operation UUID, 작업 종류, 승인 base, 최소 메타데이터, 상태만 둔다. 원문·이름·서명은 넣지 않는다. pending/in_flight/acked/conflict/paused를 구분하고 재시작 후 in_flight는 동일 명령으로 조회·재시도한다. 이미 보낸 명령은 내용·operation UUID를 바꾸지 않는다. ACK 후 후속 편집을 새 base로 전송하며, 미전송 편집을 합쳐도 삭제·복원 의도를 지우지 않는다.

네트워크 실패·5xx는 지수 backoff와 jitter, 429는 Retry-After를 따른다. 401은 한 번의 refresh 조정 후 실패하면 로그인 대기, 403·409·422는 무한 재시도하지 않는다. 계정별 큐를 분리하고 동의 철회·로그아웃 시 중단한다. 서버 미등록 상태에서 로컬 삭제된 기록은 자동 create하지 않는다.

서버 UTC는 received_at/updated_at/deleted_at·세션 만료·보유기간 기준이다. 순서는 revision과 서버 변경 cursor로 정한다. 클라이언트 시계는 완료 사건의 보고값이며 충돌 순서·권한·보유기간 판단에 사용하지 않는다. completed_at을 수신 시각으로 치환하거나 과거/미래라는 이유만으로 원본을 고치지 않는다. 시간대 없는 기존 값은 기기 환경을 추측해 변환하지 않고 원문을 로컬에 보존한 채 사용자 확인 전 동기화를 보류한다. 알려진 offset은 UTC로 정규화하되 로컬 원래 표현·offset을 유지한다. 기기 시계가 틀린 값도 인증된 실제 완료 시각이라고 주장하지 않는다.

변경 GET은 owner 전용 불투명 cursor·서버 단조 순서·페이지로 활성과 tombstone을 모두 전달한다. 클라이언트는 페이지 반영과 cursor 저장을 원자화한다. cursor 만료는 410 sync_reset_required이며 전체 재조정 후 사용자 미반영 후보를 보존한다. 서버 메타데이터를 내려받았다고 빠진 원문을 빈 값으로 덮어쓰지 않는다.

## 11. HTTP 상태 코드 초안

| 코드 | 용도 / 클라이언트 조치 |
|---|---|
| 200 | 조회·수정·삭제·복원·중복 명령 ACK. revision 확인 |
| 201 | 최초 생성 |
| 202 | 철회 후 서버 삭제·계정 탈퇴 삭제 접수. 완료 상태와 구분 |
| 401 | 토큰 누락·만료·잘못된 issuer/audience. refresh 또는 로그인 |
| 403 | 유효 계정이나 동의·scope 없음, 계정 정지. 자동 재시도 중단 |
| 404 | 현재 소유자의 기록 없음 또는 접근할 수 없는 다른 소유자 기록 |
| 409 | revision·멱등키·삭제 상태 충돌. 현재본 조회 후 명시적 해결 |
| 410 | cursor/generation 만료. 동기화 재조정 필요 |
| 422 | UUID·시간대·revision 타입·추가 금지 필드·명령 형식 오류 |
| 429 | 전송 제한. Retry-After 적용 |
| 500/503 | 서버 오류·필수 검증 서비스 불가. 같은 명령으로 제한적 재시도 |

오류는 정해진 code·안전한 request_id만 기본 제공한다. 요청 body·토큰·검증 input·임의 필드명·예외 원문을 오류 응답·로그에 반사하지 않는다. 현재 모델의 hide_input_in_errors만으로 HTTP 오류·관측 도구까지 안전하다고 간주하지 않는다.

## 12. 개인정보 최소수집과 로그 금지 항목

현재 전송 허용목록은 2절의 여섯 Metadata 필드 및 승인될 최소 명령 필드뿐이다. user_id/owner_id·실제 이름·상대방 이름·은혜 기록 본문·서명 이미지·좌표·서명 시각·문답 본문·교재 제목·주소록은 전송하지 않는다. 허용 메타데이터도 개인 신앙 활동을 나타낼 수 있으므로 동의·접근통제·암호화·삭제 대상이다. CHGO·AI 분석·광고·교회 통계로 자동 전달하지 않는다.

감사 허용 후보: 서버 시각, 고정 이벤트 코드, 결과 코드, 요청 상관 ID, 최소 권한 판단 결과, 필요성이 승인된 가명 actor 참조, revision 전후 값. 기록 UUID·operation UUID는 조사에 필요한 제한된 감사 저장소에서만 가명 참조로 사용하며 일반 액세스 로그에는 원시 경로 식별자를 남기지 않는다. 가명값도 개인정보처럼 통제한다.

절대 금지: 이름·은혜·문답·서명 원문과 이미지/좌표, 비밀번호, access/refresh token, Authorization·Cookie, 전체 요청/응답 body, SQLite 행·덤프, 원문 해시·미리보기, 검증 입력·예외 원문. IP·정밀 기기정보는 기본 수집하지 않고 별도 목적·보유 승인 없이는 감사 필드로 추가하지 않는다. 프록시·APM·오류수집·백업에도 동일 원칙을 적용한다. 삭제 처리 증거는 식별 원문 없이 이벤트·건수·완료 상태로 남긴다.

## 13. 탈퇴·동의 철회·보유기간 원칙

아래 기간은 정책 후보이며 법정 기간을 단정하지 않는다. 실제 운영·개인정보 처리방침·백업 환경을 검토해 승인 전 확정하지 않는다.

| 사건 | 즉시 동작 | 데이터 처리 후보 |
|---|---|---|
| 동기화 일시정지 | 업로드·다운로드 중지 | 기존 동의·서버 사본 유지 여부를 화면에 명시, 철회와 구별 |
| 로그아웃 | 세션 폐기·큐 중지 | 로컬 원문 자동 삭제 없음, 계정 자료 접근 분리 |
| 동기화 동의 철회 | 서버도 동의 generation 폐기·전송 차단 | 해당 제품 서버 사본 삭제 접수, 30일 이내 제거 후보. 로컬 원문 유지 |
| 교회 탈퇴·이동 | 교회 역할만 종료·변경 | 개인 owner·기록 유지, 이전/새 관리자 접근 없음 |
| 공통 계정 탈퇴 | 재인증 후 모든 제품 세션 폐기·동기화 차단 | 제품별 삭제 작업 추적, 공통 계정과 관련 사본 30일 이내 제거 후보 |
| 로컬 자료 삭제 선택 | 영향·동기화 미완료 안내 | 계정 탈퇴와 별도 명시 동작, 기존 자료 임의 초기화 금지 |

복구 가능 tombstone·receipt 보유는 90일 후보, 최소 감사는 90일 후보, 삭제된 자료가 든 백업은 최대 90일 만료 후보다. 정상 활성 사본은 동의가 유효하고 계정이 유지되는 기간에만 보유한다. 무기한 휴면 보유를 피할 주기·통지 기준은 승인 항목이다. receipt 보유 종료 후에도 UUID 유일성·tombstone 또는 generation 차단으로 중복·부활을 방지한다.

백업은 일반 조회에 쓰지 않고 복원 시 삭제 원장을 먼저 적용해 철회·탈퇴 자료가 재등장하지 않도록 한다. 법적 보존 필요가 확인되면 근거·대상·기간을 별도 승인하고 격리·접근 제한하며 재동기화하지 않는다. 서버 삭제 완료와 백업 만료 완료를 각각 알린다. 오프라인 기기 원문은 서버가 원격 삭제했다고 보장할 수 없음을 명시한다. 재동의는 새 generation으로 시작하며 구형 큐를 자동 재생하지 않는다. 탈퇴 후 재가입은 새 subject이며 과거 소유권을 자동 승계하지 않는다.

## 14. 향후 API 경로 초안

모두 미구현이다. 실제 인증 제공자 확정에 따라 core 경로는 변경될 수 있다. 기존 `/`, `/health`, `/api/v1/neorang-narang/health`, `/docs`, `/redoc`, `/openapi.json`은 보존한다.

| 경로 후보 | 계약 요점 |
|---|---|
| `GET /api/v1/auth/authorize`, `GET /api/v1/auth/callback` | 공통 인증 흐름, PKCE·redirect 검증 |
| `POST /api/v1/auth/token`, `POST /api/v1/auth/logout` | code/refresh 교환·세션 폐기, 기록 owner 입력 없음 |
| `GET /api/v1/me` | 검증된 subject의 최소 계정 정보 |
| `PUT /api/v1/me/consents/neorang-narang-sync` | 목적·정책 버전 확인 후 동의; 명령 멱등성 별도 정의 |
| `DELETE /api/v1/me/consents/neorang-narang-sync` | 철회·삭제 접수, generation 폐기 |
| `DELETE /api/v1/me`, `GET /api/v1/me/deletion-status` | 재인증 탈퇴·삭제 진행 조회용 제한 자격 설계 필요 |
| `PUT /api/v1/neorang-narang/completion-records/{id}` | create 전용 b=0 r=1 envelope, upsert 금지 |
| `GET /api/v1/neorang-narang/completion-records/{id}` | 소유자만 Metadata·현재 revision 조회, tombstone 포함 |
| `POST /api/v1/neorang-narang/completion-records/{id}/updates` | b=s r=s+1 envelope |
| `POST /api/v1/neorang-narang/completion-records/{id}/deletions` | 버전 있는 삭제 명령, 서버 tombstone |
| `POST /api/v1/neorang-narang/completion-records/{id}/restorations` | 명시적 복원 명령 |
| `GET /api/v1/neorang-narang/completion-record-changes?cursor=...` | 소유자별 변경·삭제 페이지와 next_cursor |

모든 기록 경로는 access token·제품 scope·유효 동의가 필요하다. 성공 envelope는 Metadata와 서버 시각·revision 상태를 반환하며 owner_id를 요청에 추가하지 않는다. 메타데이터 계약은 현재 snake_case 형식을 재사용하고 명령·응답 envelope는 별도 버전 계약과 테스트로 확정한다. 지원하지 않는 계약 버전은 명시적으로 거부하고 기존 로컬 기록을 변경하지 않는다.

## 15. 구현 전 AUTHOR_REVIEW_REQUIRED 결정사항

| 검토 대상 | 제안·영향 | 대안·되돌리기 |
|---|---|---|
| 공통 인증 경계·공급자·계정 복구/연결 | core UUID·짧은 JWT·회전 refresh, 제품 scope 분리 | 자체/외부 제공자 비교 후 선택. 공급자 변경에도 core UUID 유지, 로그인 기능을 끄고 로컬 사용 보존 |
| 토큰 기간·플랫폼 저장·즉시 폐기 | 10분/30일/90일 후보, 매 요청 상태 검사 | 기간 조정·서버 세션 대안. 토큰 폐기 후 로컬 사용 유지 |
| 동기화 동의·계정 귀속·공유 경계 | 기록별 선택과 계정 분리, 공동소유·교회 접근 없음 | 계속 로컬만 사용. 이전·공유 기능은 별도 심사 |
| DB 구조·UUID 매핑·큐·삭제 차단 | 기존 ID·원문 보존, 서버 CAS/receipt/generation 원자성 | 별도 매핑 우선 vs 모델 확장 비교. 합성 fixture 업그레이드·백업·복구·롤백 계획 승인 전 migration 금지 |
| revision·명령·시각 계약 | 결과 revision + base_revision, 동일 명령 재생, 서버 삭제 시각 | base-only 요청 대안은 기존 Metadata와 어댑터 필요. API 활성화 전 계약 확정·버전 관리 |
| 보유·탈퇴·백업·감사 | 30일 삭제, 90일 tombstone/receipt/감사/백업 후보 | 실제 운영 제약·근거에 따라 조정. 삭제 실행 전 복구 검증, 완료된 영구 삭제는 롤백 불가 |
| 시간대 없는 레거시·기기 시계 정정 | 보류·로컬 원본 유지, 사용자 확인 | 추측 변환 금지. 정정 이력 계약 없으면 서버 전송 보류 |
| 계정 탈퇴 상태 조회·지원 접근·휴면 | 제한 자격·최소 감사·기간 통지 설계 필요 | 인증 없이 개인정보 노출 금지, 설계 완료 전 기능 활성화 금지 |

설계 초안을 승인한 것과 실제 DB·인증·개인정보 처리 변경을 승인한 것은 구분한다. 미결정 사항은 구현자가 임의의 운영 기본값으로 확정하지 않는다.

## 16. 단계별 구현 순서와 완료 조건

| 단계 | 선행 조건·작업 범위 | 완료 증거 |
|---|---|---|
| 0. 설계 검토 | 이 문서의 중요 경계·기간·API 의미 승인 | 검토자·승인 범위·미결정 기록, 코드 변경 없음 |
| 1. 계약 확정 | 승인 후 명령/응답·오류·버전 스키마만 | UUID·추가 owner/민감 필드 거부, timezone·기존 Metadata 회귀, 기존 health/OpenAPI 보존 |
| 2. 공통 인증 | 별도 구현 승인·제공자/비밀 관리 확정 | issuer/audience/서명·만료·refresh 재사용·세션 폐기·제품 scope·타 계정 접근 차단 합성 테스트 |
| 3. 서버 동기화 저장 | DB/migration·보유 승인 | CAS 동시 쓰기 한 건 성공/한 건 409, 동일 명령 재시도·충돌, tombstone·복원·cursor 만료·삭제 후 부활 차단, 백업/복구/롤백 검증 |
| 4. Flutter 선택 동기화 | 별도 Flutter 변경 승인·UUID/queue migration 승인 | ID/시각/원문 보존, 재시작·응답 유실·오프라인·두 기기·계정 전환·철회 경합 테스트 |
| 5. 운영 품질 | 보유기간·감사·장애 대응 승인 | 프록시/APM 포함 민감 로그 부재, 탈퇴·백업 만료·삭제 원장 복원 증거, 서버 장애 중 로컬 완료/열람 유지 |

각 단계는 승인 범위만 진행한다. 기능 flag로 서버 동기화를 중지해도 로컬 기록을 유지해야 한다. DB 변경 후 이전 바이너리 설치만으로 롤백 성공을 주장하지 않는다. 실제 사용자 DB 대신 합성 자료로 검증한다. 배포·실제 외부 연결은 별도 승인 대상이다.

문서 단계 품질 범위는 링크·경로, 필수 정책의 일관성, `git diff --check`, 두 저장소 status와 코드 무변경 확인이다. 인증 보안·동시성·DB·Flutter 실행·보유기간 운영 효과는 이 문서만으로 검증된 것이 아니며 NOT_RUN이다.
