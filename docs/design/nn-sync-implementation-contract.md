# 실제 완료 메타데이터 동기화 구현 계약 검토

2026-10-31. **PROPOSED / AUTHOR_REVIEW_REQUIRED**. 실제 자료 수집은 **BLOCKED**, 앱 적용은 **AUTHOR_REVIEW_REQUIRED**다. 이 문서는 조사·문서 작성 결과이며 설계 승인, 구현·migration·실제 수집·배포 허가가 아니다. AI는 저자 승인·독립 검토자 서명·사용자 동의를 대신하지 않는다.

## 1. 현재 상태와 증거 경계

시작 확인: Git 루트 `D:/CHGO-VibeCodeing/JesusLife-One-API`, 브랜치 `docs/nn-sync-implementation-contract`, HEAD `d129e2e` (PR #6 merge), 작업 트리 clean. 대상 파일은 존재하지 않았다. 적용 지침은 [AGENTS.md](../../AGENTS.md), 로컬 `jesuslife-platform-development` 공통 보호·제품 경계·설계 절차·품질 게이트와 `jesuslife-platform-design`이다. 현재 저장소의 문서·소스만 읽었다. 다른 저장소, 실제 DB·기기·백업·비밀·환경 파일은 접근하지 않았다. 앱·설정 로더 import, 테스트·모델 탐색·네트워크·서버 실행은 하지 않았다.

이하 **구현됨**은 정적 소스 존재, **독립 실험됨**은 제품과 분리된 실험 코드 및 과거 결과 기록 존재, **문서 후보**는 미승인 설계, **미구현**은 조사한 제품 경로에 해당 계약이 없음, **미확인**은 이번 범위에서 증거를 확인하지 못했다는 뜻이다. 실행 PASS로 서로 대체하지 않는다.

근거 약칭:

| 약칭 | 저장소 근거 |
|---|---|
| P | [실제 완료 동기화 제안](nn-real-completion-sync-proposal.md), 특히 3~8·10~11·13.1~13.5절 |
| R | [독립 모델 리뷰](../reviews/2026-10-31-real-sync-model-review.md), 발견 사항·커버리지·가정 및 후속 부록 |
| O | [소유권·동기화 정책](../architecture/nn-auth-ownership-sync-policy.md), 13~16절 및 개발용 완료 API 계약 |
| C | [Platform Core 계약](../architecture/platform-auth-contract-draft.md), 1·2·4·5·7절 |
| M | [모바일 PoC 설계](../mobile-first-link.md), 삭제 응답 계약·Cross-schema 결합 추적 |

| 분류 | 판단 | 파일·심볼·절 근거와 한계 |
|---|---|---|
| 구현됨 | 기본 health·OpenAPI 골격과 완료 CRUD·owner 제한·메모리/MySQL adapter 존재 | [main.py](../../app/main.py), [router.py](../../app/modules/neorang_narang/router.py), [service.py](../../app/modules/neorang_narang/service.py)의 `CompletionService`, [store.py](../../app/modules/neorang_narang/store.py)의 `CompletionStore`, [mysql_store.py](../../app/modules/neorang_narang/mysql_store.py)의 `transaction`. AGENTS의 초기 골격 설명보다 진행됨. 이번 회귀 실행은 NOT_RUN |
| 구현됨 | v1은 여섯 metadata 필드·활성 create 재시도·revision 조건 수정/삭제까지 | [schemas.py](../../app/modules/neorang_narang/schemas.py)의 `CompletionRecordMetadata`, `CompletionResult`; `CompletionService.create/update/delete`. operation UUID의 영속 과거 receipt·실제-data 날짜 DTO·복원/cursor 구현으로 해석하지 않음 |
| 구현됨 | 기본 인증 fail-closed, 별도 개발 인증·모바일 합성 경로 존재 | [auth.py](../../app/core/auth.py)의 `AuthContext/get_current_user`, [auth0_mobile.py](../../app/auth0_mobile.py)의 `configured_app`, [mobile_routes.py](../../app/core/mobile_routes.py)의 `identity/Synthetic/install_mobile`. `AuthContext.sub`만으로 실제-data scope·동의·commit 권한을 증명하지 못함 |
| 구현됨 | 합성 동의 세대 직렬화와 삭제 장벽 | [Core mobile_store.py](../../app/core/mobile_store.py)의 `MobileCoreStore.mobile_status`가 동의 행을 잠그고 같은 cursor로 [제품 mobile_store.py](../../app/modules/neorang_narang/mobile_store.py)의 `MobileProjectionStore.create/erase` 호출. 세대당 한 건, metadata NULL 삭제·UUID/owner/generation 잔존. Core가 제품 테이블을 쓰는 개발 예외이며 제품별 독립 commit 해결 아님(M) |
| 독립 실험됨 | A/F/D/L·삭제 장벽·관리 권한을 유한 상태로 탐색하는 명세 존재 | [model.py](../../tools/sync_model/model.py)의 `step/violations`, [explore.py](../../tools/sync_model/explore.py)의 `main`, [모델 README](../../tools/sync_model/README.md). 현재 checker에 state delta·ACK·startup 조건 있고 errors 또는 truncated 시 CLI 실패. R의 초기 지적을 모두 현재 미수정 결함으로 재기재하지 않음. DB·다중 세대·실제 메시지·COUNT는 미입증 |
| 독립 실험됨 | A→B→A와 동일 계정 세션 교체의 stale ACK 차단 | [coordinator.py](../../tools/ack_coordinator/coordinator.py)의 `AckCoordinator.replace_session/logout/accept_ack`, [ACK 테스트](../../tools/ack_coordinator/test_coordinator.py)의 `test_a_to_b_to_a_rejects_first_a`. 메모리·순차·합성 실험이며 영속 queue·실제 인증·동시 worker 증거 아님 |
| 독립 실험됨 | 삭제와 retirement 표식의 동일 SQLite transaction·undo 표식 보존·강제 종료 복구 | [test_retirement.py](../../tools/sqlite_retirement/test_retirement.py)의 `retire/RetirementTests`, [test_process_crash.py](../../tools/sqlite_retirement/test_process_crash.py)의 `ProcessCrashTests.probe`. 임시 합성 DB의 BEGIN IMMEDIATE/DELETE journal/FULL 조건. Android·전원 장애·원본 앱 transaction·물리 삭제 증거 아님 |
| 구현됨 | ACK·SQLite 전용 Windows CI 설정 존재 | [nn-sync-experiments.yml](../../.github/workflows/nn-sync-experiments.yml): windows-2022·Python 3.14.8·10분·contents:read, 버전 보고와 각 discovery 명령, Python 종료 코드 전달. 이번 문서 경로만의 변경은 PR/push path filter 대상이 아님 |
| 문서 후보 | Android 새 완료 한 건의 명시 선택·최소 projection·별도 실제 계약·기본 비활성 | P 1·3~5·11·13절. 이번 요청은 첫 후보 검토를 승인했으며 후보 자체의 수집 정책 승인은 아님 |
| 미구현 | 실제-data 전용 API·동의/scope·영속 receipt·Core/제품 fence·통합 coordinator | 조사한 `app/`의 위 경로와 P 2·11·13절 대조. 독립 실험 코드가 app에 적용된 것으로 간주하지 않음 |
| 미확인 | 현재 Flutter 실제 구현·COUNT·삭제 진입점·운영 환경 안전성 | Flutter 설명은 P 1·2·13.2와 M의 이전 조사 인용일 뿐 이번 직접 확인 아님. 실제 기기·DB·로그·권한·backup 상태 미확인 |

이전 실행 근거: 사용자 전달 Android 합성 자료→FastAPI→MySQL PoC 성공 및 [Android 인수 기록](../verification/2026-10-30-android-mobile-acceptance.md)은 USER-REPORTED다. PR #2 제안·모델, #3 ACK, #4 SQLite rollback, #5 프로세스 종료, #6 CI라는 이력은 전달받은 맥락이다. ACK 8개·SQLite 13개 PASS와 PR #6 화면의 실험 CI·Offline tests·Sync model 성공도 USER-REPORTED이며 이번 독립 실행·원격 확인 결과가 아니다. [ACK README](../../tools/ack_coordinator/README.md)·[SQLite README](../../tools/sqlite_retirement/README.md)의 당시 GitHub NOT_RUN 문구는 당시 범위이고 최신 사용자 보고와 출처·시점이 다르다.

R과 모델 README 후속 부록에는 실제 `??` 손상 문구가 있다. 추정 복원하거나 승인·정확한 실행 의미의 근거로 쓰지 않는다. 현재 소스에서 확인한 checker 보강은 정적 관찰로만 인정한다. R의 crash 단계 내부 원자성·조정 실패·실제 사본 제거 미검증 한계는 여전히 유효하다. 모델의 계정 전환은 session epoch 증가를 구현하지 않으며 별도 ACK 실험이 그 좁은 공백을 다룬다. 어느 쪽도 제품 통합을 증명하지 않는다.

## 2. 첫 구현 범위와 제외 범위

P 1·3·11·13.1에 맞춘 **후보**는 Android에서 새 완료 로컬 저장 성공 직후 같은 완료 확인 흐름에서 사용자가 선택한 한 건을 자기 계정에 보내는 것이다. 기본 feature는 disabled다. 성공은 중복 없는 서버 최소 metadata 반영과 ACK 확인이며 로컬 완료 성공과 별도 표시한다.

P 2·6·13.2 및 O의 원본 소유 원칙에 따라 로컬 ID·원본·기존 COUNT 계산을 보존한다. 서버 ACK·서버 사본 삭제·철회가 COUNT를 수정하지 않는다. 사용자의 기존 로컬 삭제/undo에 따른 COUNT 변화는 기존 규칙을 따른다. 서버 장애 때문에 로컬 완료·열람을 막지 않는다. 이는 이번 Flutter 구현 확인이 아닌 유지해야 할 계약 조건이다.

기존 v1 CRUD와 `/api/v1/mobile/synthetic-completion`은 별개로 보존한다. `synthetic=false` 전환, 합성 동의·테이블·세대당 한 건 제한을 실제 계약으로 전용하지 않는다. 신규 endpoint/DTO/동의 목적을 분리한다(P 5·8). 로그인·앱 업데이트·재시작·복원·재동의에서 과거 기록을 자동 귀속/업로드하지 않는다. 기존 목록 선택도 첫 범위 밖이다.

이름·문답·은혜 본문·서명·음성·상대 정보·원문 hash·전체 CompletionRecord 백업, 교회 통계·공유·CHGO 전송, 기기 간 원문 복원, 일반 수정·서버 복원·전체 cursor 동기화, Android 외 플랫폼은 제외한다. 최소 metadata도 계정에 연결되므로 익명 자료가 아니다.

## 3. 결정표

‘유지’는 기존 승인/보호 원칙을 다시 승인 대기로 돌리지 않는다는 뜻이다. ‘미결정’은 실제-data 후보 적용에 필요한 사람 결정이며 아래 역할의 실제 담당자·결정일·범위를 기록해야 한다. AI가 승인란을 채우지 않는다.

| 항목 | 기존 근거 / 현재 상태 | 권고안 / 대안 | 사용자 영향 | 확정할 사람의 결정 | 구현 의존성 |
|---|---|---|---|---|---|
| 목적·최소 필드 | P 3·10: PROPOSED | 완료 사실 선택 동기화, `sync_id/course_number/completed_on` / 날짜 등 더 축소 또는 수집 보류 | 날짜·과정도 신앙 활동을 드러냄. solo/together·정밀 시각 제외 | 저자·제품/개인정보 책임자가 필요성·문구·허용목록 확정 | 별도 DTO·실제 수집 gate |
| 신규 선택 자격 | P 13.1: 미결정 | 활성화 후 현재 프로세스 저장 사건, 동일 화면 연속 흐름만 / 계속 로컬 전용. 과거 선택은 후속 | 이탈·계정 전환·종료 전 선택하지 않으면 재선택 불가. transaction 완료 선택만 재시도 | 제품·모바일 책임자가 자격/취소 UX 확정 | 완료 저장 결과·매핑 유일성·원자 선택 |
| 계정 binding | C 1 승인 구조 유지; P 4·13.1의 기록별 binding은 미결정 | 검증 Core UUID에 명시 귀속, A→B 이전 금지 / 미귀속 로컬 유지 | 공유 기기 오귀속 방지. 매핑 유실은 격리 | 저자·제품/보안 책임자가 기록별 확인·격리 정책 확정; UUID 구조 재승인 불필요 | account/local reference/sync ID 내구 매핑 |
| 동의·철회 | 로그인·소속≠동의는 O/P/C 공통; P 7·13.3의 실제 목적·흐름 미결정 | 실제-data 별도 동의, 철회는 전송 차단+서버 삭제 접수 / 일시정지와 삭제를 별도 기능으로 분리 | 오프라인 중단·접수 A·차단 F·live 삭제 D·백업 만료를 구별 | 저자·개인정보/제품 책임자가 목적·문구·철회 의미 확정 | 동의 세대·내구 journal·Core command |
| 로컬 삭제·undo | 원본 보존 원칙 유지; P 13.2 후보, 독립 SQLite 실험만 있음 | 삭제와 retirement 표식 동일 원본 transaction, 서버 삭제 보상; undo는 서버 재전송 금지 / 서버 사본 삭제를 명시 별도 선택으로 분리 재설계 | 로컬 복구와 서버 복원은 다름. 원본 저장 실패 시 완료 표시 금지 | 제품·모바일·데이터 책임자가 연계 UX·스키마·복구 계획 확정 | 모든 삭제 진입점·COUNT 경로 확인, migration 별도 승인 |
| 서버 삭제 장벽 | O 14의 활성 일반 GET/타인·없음·삭제 동일 404는 2026-10-26 승인, 유지. P 13.4.2 미결정 | 단건 sync ID 장벽+erased receipt, 세대 retired fence / 세대 전체 폐기로 압축(다른 기록 영향) | 삭제 뒤 옛/새 operation 모두 부활 거부. 최소 잔존 연결정보 있음 | 데이터·보안/개인정보 책임자가 단건 장벽 수명·압축·복구 확정 | 삭제/receipt 원자 commit·원장 선적용 |
| 보유·백업 | O 13/P 13.4: 30일·90일은 미승인 비교값 | queue/receipt/감사/backup 수명과 장벽을 함께 확정 / 더 짧은 보유·기능 보류 | live 삭제가 backup 즉시 제거 아님. 영구 삭제 복구 약속 금지 | 개인정보·제품·백업 운영 책임자가 기간·접근자·삭제 목표 확정 | inventory owner·정리 ACK·격리 복원·만료 증거 |
| 인증·권한 | C 1의 관리형 OIDC+JWT/서버 세션, Core UUID 원자 매핑, 이메일 자동 병합 금지, 현재 세션 로그아웃 승인 유지. Auth0 개발 PoC 한정 | 구조 재사용, 실제 write/read와 본인 관리 권한 분리 / 실제 기능 비활성 유지 | 철회 뒤 삭제·상태 조정에 업로드 재동의 불필요. 타 계정 거부 | 보안/Core 책임자가 실제 scope·자격·수명·commit 시 검사 확정. 운영 Auth0 채택은 별도 | 세션 상태·계정 상태·동의/목적·fence 결합 |
| Core/제품 commit | M 개발 공유 transaction 존재; P 8·13.3 후보 미입증 | 기존 Open/Admit/Close/Delete command 후보 구체화 / 공유 transaction 유지 시 권한 결합을 별도 재검토 | 접수 뒤 잠시 commit 가능, 모두 삭제 집합 포함. 장애는 pending | Core·제품·DB 책임자가 잠금·격리·장애 복구 설계 검토 | 내구 inbox/outbox·gate/ticket·worker 전역 직렬화 |

기존 로컬 MySQL 승인(O 개발용 계약)과 [Auth0 개발 PoC](../architecture/auth0-development-poc.md)·[PC 첫 연결](../architecture/auth0-pc-first-flow.md)의 합성 개발 승인도 취소하거나 운영 승인으로 확대하지 않는다. 일반 스킬의 PostgreSQL 원칙으로 승인된 로컬 MySQL을 바꾸지 않는다. 승인된 인증 구조와 실제-data 적용 세부는 서로 다른 결정이다.

## 4. 최소 구현 계약 후보

아래는 P 5~7·13절을 구현 검토용으로 모은 후보다. 새 프로토콜·추가 독립 실험을 도입하지 않는다. 보호 변경은 AUTHOR_REVIEW_REQUIRED, 활성화는 BLOCKED다.

### 4.1 제품 command·응답·오류

경로 후보 `/api/nn-real/v1`: `POST /completions`, 본인 활성 `GET /completions/{sync_id}`, `POST /completions/{sync_id}/deletions`. Core 목적은 `nn.real-completion.sync`, 동의/철회/상태 경로 후보는 P 5의 `/api/core/v1/me/consents/nn-real-completion` 계열이다. 미지원 버전은 거부한다. 관리 receipt/장벽 상태 조회의 정확한 route·DTO는 구현 전 확정할 공백이다. 기존 합성 상태 응답을 재사용해 완료 의미를 바꾸지 않는다.

생성 envelope는 `operation_id`, `consent_generation`, `policy_version`, `base_revision=0`, `metadata={sync_id,course_number,completed_on}`. UUID는 로컬 원래 ID와 별도 매핑하고 한 번 내구 저장한다. 과정은 bool을 제외한 정수 1/2, 날짜는 엄격한 유효 YYYY-MM-DD다. 같은 완료 사건의 기기 로컬 날짜를 한 번 캡처하고 재시도·시간대 변경 때 재계산하지 않는다. 날짜 근거 불명은 보류하며 시각·내용 hash로 identity를 만들지 않는다. owner는 본문에서 받지 않고 검증 계정에서 정한다.

서버가 최초 revision=1을 부여한다. 성공은 `operation_id/sync_id/applied_revision/current_revision/replayed/received_at`의 최소 ACK이며 metadata·owner를 복제하지 않는다. 201 최초 생성, 200 유효한 동일 명령 재생. revision은 기록별 서버 CAS 버전이고 동의 generation·session epoch·로컬 deletion epoch와 별개다. 삭제는 operation ID와 마지막 승인 base를 사용하고 서버가 버전을 증가시킨다. 부재 ID도 장벽을 만들되 정확한 초기 장벽 버전·base 불명 관리 응답 shape는 미확정이다. 이 공백을 임의 숫자로 채우지 않는다. 일반 수정/restore는 첫 범위 밖이다.

owner+operation ID의 활성 receipt는 정규화된 불변 명령 비교로 동일 내용 재생, 다른 내용은 409 `idempotency_key_reused`. owner+sync ID는 유일하며 다른 operation의 같은 활성 최소 내용은 기존 생성 결과 확인만 허용한다. 내용이 다르면 409, 삭제 장벽이면 410. 같은 날짜/과정의 다른 sync ID 기록은 자동 병합하지 않는다. metadata 저장·revision CAS·receipt·ticket 소비·gate 검사는 같은 제품 commit 경계가 필요하다. 현재 v1 서비스는 이 영속 receipt 계약의 구현이 아니다.

삭제 transaction은 sync ID 장벽·관련 receipt erased 전환·원명령/성공 body 제거를 함께 commit한다. 인증/소유자 확인 뒤 retired generation·sync ID 장벽·erased operation을 원문 비교보다 먼저 판정한다. erased 동일/변조 요청은 모두 고정 410 `operation_retired`, 다른 operation의 같은 ID도 410, 일반 GET은 404다. 철회 접수 뒤 옛 성공 receipt를 재생하지 않는다. 중복 삭제는 최소 진행 상태만 반환한다. 영구 metadata hash를 삭제 대체로 남기지 않는다.

오류 후보: 401 자격 거부→같은 계정 로그인 대기, 403 권한/계정 거부→중지, 404 비공개 존재 여부, 409 충돌→원본/후보 보존·관리 조정, 410 폐기→재create 금지, 422 고정 검증 오류→중지, 429 Retry-After, 5xx/네트워크→같은 명령에 제한된 backoff+jitter. 필수 권한 상태 확인 불가는 503 fail-closed다. timeout은 성공/삭제 완료가 아니다. 오류·로그·APM·추적에 입력·토큰·계정/기록 식별자·원문을 반사하지 않고 고정 code·불투명 request ID만 쓴다. 전체 관측 경로 검증은 NOT_RUN이다.

### 4.2 로컬 coordinator·계정·세션

원본 저장 성공→원본 선택 매핑 commit→보조 선택 의도/불변 queue commit→송신 전 원본/표식 재검사 순서를 지킨다. 매핑 전 송신 금지. 원본과 보조 store 사이 cross-store 원자성은 없으며 반복 조정이 필요하다. 선택 중 실패는 로컬 원본을 유지하고 송신을 막는다. 날짜·operation·계정·동의 세대·base snapshot은 활성 재시도 중 바꾸지 않는다. 삭제 시 payload 제거는 별개다.

모든 선택·claim·삭제·undo·ACK·재시도는 제품 coordinator와 원본 내구 gate/epoch를 통과해야 한다. 네트워크 동안 DB transaction을 잡지 않는다. session 교체·로그아웃 때 session epoch를 증가시키고 ACK의 계정/epoch/operation을 재확인한다. 같은 계정 A로 돌아와도 첫 A의 ACK를 적용하지 않는다. 동의 generation·retired 상태·deletion epoch·표식도 재확인한다. 메모리 ACK 실험의 조건만으로 영속/동시 안전성을 주장하지 않는다.

L은 기존 로컬 삭제/복구 전이와 별도 retirement 표식을 동일 원본 DB transaction으로 commit하는 지점이다. undo·trash 정리로 표식/retired 매핑을 제거하지 않는다. claim 뒤 L이면 이미 송신 가능하므로 서버 삭제 보상과 sync ID 장벽이 필요하다. 보조 store 실패는 로컬 삭제를 막지 않지만 원본 commit 실패는 rollback·삭제 미완료다. 재시작은 자격 재검증과 원본 표식/매핑 스캔·journal 조정을 모든 upload보다 먼저 한다. 접근 실패·손상·매핑 유실은 paused/격리, 새 UUID 자동 발급 금지다. A 의도는 B 자격으로 처리하지 않는다.

### 4.3 Core와 제품 commit·철회

Core는 계정/세션/목적 동의·세대·권한 폐기·삭제 진행을 소유하고 제품은 완료 projection·revision·receipt·장벽을 소유한다. 공개 command/ACK로만 연결하며 실제 계약을 Core의 제품 내부 schema import·제품 DB 직접 쓰기에 의존시키지 않는다. 현재 개발 예외 제거도 별도 승인·회귀·복구 계획 대상이다.

P 13.3의 기존 후보를 유지한다. OpenGeneration→제품 OPEN ACK→Core ACTIVE 후 Admit ticket을 발급한다. ticket은 검증 계정/목적/generation/operation/불변 명령에 묶인다. **A**는 Admit와 직렬화되는 Core Withdraw commit이며 신규 admission을 차단한다. A 전 발급 ticket은 **F**(제품 Close fence commit) 전 commit할 수 있고 삭제 집합에 포함한다. 모든 제품 instance의 write와 F가 같은 gate를 공유해야 한다. F 이후 옛 ticket commit 금지, 진행 transaction 종료·미사용 ticket 폐기 뒤 drain ACK다. Delete가 Close보다 먼저면 prerequisite pending으로 내구 보류한다.

**D**는 제품 live inventory 삭제/최소화·최종 sweep·메시지 drain ACK와 Core 자신의 ledger/outbox 정리 확인을 Core가 내구 저장한 지점이다. A 이후만 202 접수, F 확인 전 쓰기 차단 완료 표시 금지, D 전 live 삭제 완료 표시 금지다. 서버 live, 기기 cleanup, backup expiry, 최소 장벽 잔존을 각각 표시한다. 오프라인 기기·로컬 원본·backup/WAL은 서버 live 완료 밖이다. 재동의는 D/장벽 확인 후 더 큰 g의 Open/ACTIVE를 기다리며 옛 선택·ticket·queue는 이월하지 않는다. 늦은 Open·중복/역순 ACK가 phase나 retired high-water를 되돌리지 못한다.

**해결되지 않은 증거**: 현재 합성 PoC의 한 cursor transaction은 분리된 Core/제품 commit의 증거가 아니다. 모델은 원자 step·공유 gate·정직한 cleanup ACK를 가정한다. Core 상태/receipt/outbox 단일 commit, 제품 gate/ticket/행/receipt 단일 commit, 실제 격리 수준·잠금 순서·deadlock 재시도·다중 worker·내구 메시지 재전달·ticket 회수·장애 후 복구는 미확정/통합 NOT_RUN이다. 사전 동의 조회+별도 쓰기, 비동기 이벤트만, ticket TTL만으로 철회 경합을 해결했다고 하지 않는다. Core 불가 시 신규 admission 차단, commit 결과 불명은 같은 command ID로 조정하며 pending을 유지한다.

## 5. 구현 작업표

아래는 후속 작업 후보이며 이번 실행 항목이 아니다. 각 행은 별도 검토 가능한 단위다. 합성 구현 승인과 DB/인증/개인정보 보호 변경 승인, 실제 수집 승인, 배포 승인을 구별한다.

| 순서·유형 | 작업·후보 경로 | 재사용 가능한 부분 / 새 검토 부분 | 완료 조건·의존성 |
|---|---|---|---|
| 0 추가 조사·문서 | 이 문서 3·4절의 미확정 계약 항목과 담당자/근거를 한 번에 결정 기록 | P/C의 기존 승인 유지 | 부재 삭제 base/장벽 버전·관리 상태 DTO·보유 미결정을 드러내고 승인 범위 명시. 실제 자료 불필요 |
| 1 합성 서버 계약 | `app/modules/neorang_narang/`에 별도 실제 계약 DTO/command 후보, `tests/`에 합성 계약 검증 후보 | strict allowlist·고정 오류·owner 404 패턴 재사용; 기존 schemas/endpoint 의미 변경 금지 | 별도 구현 승인 및 필요한 필드/권한 결정 후, 날짜·금지 필드·응답 비노출·기존 계약 회귀 증거. 설치/수집 없음 |
| 2 보호 변경 설계 | Core/제품 repository의 gate·ticket·receipt·inbox/outbox·장벽 transaction 경계와 DDL/권한/복구 계획 | `CoreStore.transaction`, `MySQLCompletionStore.transaction` 구조 참고; 공유 cursor를 목표 구조로 복제하지 않음 | DB·인증 경계 AUTHOR_REVIEW_REQUIRED 해소 범위 기록, upgrade/중간 실패/rollback/backup 복원 설계. migration 실행 별도 |
| 3 합성 서버 저장 구현 | 승인된 Core command 처리기와 제품 repository를 작은 commit 단위로 구현 | 독립 모델의 A/F/D 요구식은 인수 근거, runtime 의존성 아님 | 먼저 Open/Admit/A, 다음 제품 commit/F/drain, 다음 Delete/D 각각 중복·역순·재시작 증거. 1~2 의존, 실제 수집 계속 BLOCKED |
| 4 앱 조사·보호 승인 | 후속 별도 승인 범위에서 Flutter 완료 저장·모든 삭제/undo/COUNT 진입점과 mapping/retirement migration 확인 | P가 인용한 `lib/repositories/sqlite_completion_repository.dart`, `lib/database/app_database.dart`는 이번 미확인 후보 경로 | 대상 저장소 직접 조사 후 경로 확정. 원본 보존·표식 내구성·구버전/복원 위험 검토, 앱 적용 AUTHOR_REVIEW_REQUIRED |
| 5 합성 앱 구현 | 원본 선택 매핑/L, 다음 보조 queue/시작 조정, 다음 coordinator/ACK 순서 | ACK 조건·SQLite transaction 실험의 불변식 참고; Python 실험/DDL 그대로 이식 금지 | 별도 앱/스키마 승인 후 ID·COUNT·원본 보존, 연타·A→B→A·kill·undo·조정 실패를 앱 합성 fixture로 검증. 1·4 의존 |
| 6 인증 연결·통합 합성 검증 | `app/core/`의 검증 context/권한 command 연결과 앱–서버 검증 | 승인 Core UUID/세션 결합 재사용; 실제 목적 scope·관리 권한은 별도 | 3·5와 인증 경계 승인 의존. 6절 시나리오·다중 worker fence·로그 비노출·격리 복원 증거. 운영 자격/실제 자료 사용 금지 |
| 7 실제 수집 승인 | 목적·동의·보유·삭제 inventory·지원/사고 책임과 검증 결과를 사람이 심사 | 합성 PoC 성공으로 대체 불가 | 개인 사용자 명시 동의·기록 선택과 별도로 운영 수집 승인 필요. 현재 BLOCKED |
| 8 배포·활성화 | 승인 환경·대상 Android·feature flag·중단/복구 절차 | 기본 disabled·로컬 전용 사용 보존 | 7 및 별도 배포/외부 연결 승인 후만. 이번 제안은 실행 허가 아님 |

## 6. 인수 시나리오

모든 행의 **실제 제품 통합 검증은 NOT_RUN**이다. 기존 실험 커버리지는 정적 코드/과거 기록이며 이번 재실행 PASS가 아니다. 합성 fixture로 전후 로컬 원본·COUNT·매핑·queue·서버 행/receipt/장벽을 비교해야 한다.

| 시나리오 | 인수 조건 | 기존 근거와 남은 공백 |
|---|---|---|
| 정상 전송·신규 자격 | 로컬 저장 성공 후 동일 흐름 선택 한 건만 전송; 최소 필드·한 행·ACK 뒤 반영 표시; 원본/COUNT 불변. 이탈/재시작에서 미선택 기록 자격 없음 | `tests/test_completions.py`의 create·allowlist·owner fixture는 기존 v1. 실제 신규 선택/날짜/동의 계약은 미검증 |
| 응답 유실·중복 재시도 | commit 후 timeout/ACK 저장 실패에도 동일 binding·operation·payload; 활성 동일 명령만 재생. 키 변조 409, 삭제 뒤 모두 410·GET 404 | 기존 CRUD retry와 모델 receipt bool은 부분 근거. 실제 영속 receipt/캐시 제거·원문 비교 순서 NOT_RUN |
| A→B→A·로그아웃 | B로 A queue/삭제 재개 금지; 돌아온 A도 첫 session ACK 무시. 현재 A 자격과 동의로 적격 queue만 조정 | ACK 실험의 epoch/operation·중복 거부, 사용자 보고 합성 A/B 관찰. 실제 queue·권한·동시 worker 연결 미검증 |
| 로컬 삭제·undo·진행 upload | L에 기존 삭제/COUNT 전이와 표식 함께 commit; undo는 기존 COUNT만 복원. create/삭제 양 순서에서 장벽·보상 유지, 늦은 ACK 무효 | SQLite `retire`, rollback·undo·split transaction 음성 대조군 및 모델 L. 실제 trash·COUNT·coordinator·서버 보상 미검증 |
| 재시작·강제 종료 | 선택 commit 전 종료는 새 선택 불가, 이후는 같은 명령 조정. L 전후 종료에서 부분 삭제/표식 없음, startup 조정 전 upload 금지 | SQLite 강제 종료 3지점·모델 restart의 제한된 근거. Android·실제 원본/보조 두 store·claim 회수·전원 장애 미검증 |
| 철회와 진행 commit | Admit 전 A는 거부, Admit→A→commit→F는 삭제 집합, F 뒤 commit 금지. A/F/D와 timeout·중복·역순 Open/ACK 구별. 동의 없이도 같은 본인 관리 권한으로 삭제/상태 조정 | 모델 A/F/관리 불변식; `tests/test_mobile_broker.py`의 합성 공유 transaction 경합. 실제 분리 commit/다중 instance·inventory D는 미입증 |
| 손상·복원·원본 접근 실패 | 매핑/원장/queue 손상은 격리·송신 중지, 새 ID 금지. 원본 삭제 commit 실패는 rollback·미완료 표시, 보조 실패만이면 L 보존. backup 복원은 최신 장벽 선적용 후 검증 전 서비스 금지 | 모델은 Durable 보존·reconcile 성공을 가정, 실험은 자체 임시 DB만 복구. 원장 유실·조정 실패·실제 backup·migration/rollback NOT_RUN |

## 7. 다음 한 단계

**추가 조사·문서 작업 한 건**: 이 저장소의 `MobileCoreStore.mobile_status`와 `MobileProjectionStore.create/erase` 호출 경계에 대해, P 13.3의 기존 command별 입력·출력·소유자·transaction·pending 상태 대응표를 작성하고 부재 삭제 base/장벽 버전·관리 상태 DTO의 공백을 표시한다. 새 프로토콜·독립 실험·코드/DDL은 만들지 않는다. 기존 동작을 근거로 한 계약 공백 정리는 목적/보유 결정 전에도 가능하고, 현재 공유 transaction의 안전성을 잃지 않으면서 분리할 후속 작업 크기를 정할 수 있다. 이는 별도 후속 문서 범위 제안이며 이번 파일 외 변경은 없다.

실제 구현 전 필수 선택은 (a) 세 필드 수집 또는 더 축소/보류: 유용성·노출 범위, (b) 신규 화면 한정 선택 또는 로컬 전용 유지: 사용자 선택 기회, (c) 로컬 삭제 연계+undo 비재전송 또는 삭제 기능 분리 재설계: 복구 기대, (d) queue/receipt/backup·단건 장벽 수명/압축: 잔존 정보와 부활 방지 비용이다. 실제 scope·관리 자격과 Core/제품 잠금·복구 설계도 담당자 결정이 필요하다. 기존 OIDC/Core UUID/일반 GET 404 승인은 다시 묻지 않는다. 실제 수집 BLOCKED·앱 적용 AUTHOR_REVIEW_REQUIRED는 유지한다.

## 문서 검사 기록

이번 검사는 문서 전용이다. 테스트·모델 탐색·pip check·제품 통합·실제 인증/기기/DB·backup 검증은 요청 범위에 따라 **NOT_RUN**이다.

| 검사 | 이번 결과 |
|---|---|
| PowerShell 정규식으로 Markdown 상대 링크 추출 후 `Test-Path -LiteralPath -PathType Leaf` | PASS: 30개 링크, 누락 0. 본문 API 소스·실험 심볼은 읽기/`rg -n`으로 대조. Flutter 후보 경로는 미확인으로 표시 |
| 상태·모순·중복 승인 요청 수동 검토 | PASS: 문서/실험/구현 구분, 과거 사용자 보고와 이번 실행 분리, 기존 구조/404 승인 유지, 실제-data 결정만 미결정. `??` 복원 없음 |
| 신규 파일 별도 trailing whitespace·탭·최종 newline/빈 줄 검사 | PASS: 문제 0. 미추적 파일은 일반 diff 검사에 포함되지 않아 별도 수행 |
| `git diff --check` | PASS: 종료 코드 0, tracked 변경 없음 |
| `git status --short --branch`, `git log -1 --oneline`, `git diff --name-only`, `git ls-files --others --exclude-standard` | PASS: 브랜치 `docs/nn-sync-implementation-contract`, HEAD `d129e2e` 유지. tracked 변경 없음, 이 문서 한 파일만 untracked 추가 |

실제 자료 수집 **BLOCKED**, 앱 적용 및 DB·인증·개인정보 경계 **AUTHOR_REVIEW_REQUIRED**. commit·push·PR 생성·병합·배포는 수행하지 않았다.

## 8. 2026-10-31 합성 DTO 한정 구현 기록

**승인 범위**: 사용자는 세 metadata 필드, 새 완료 직후 동일 흐름의 명시 선택,
확인한 본인 계정 귀속·타 계정 자동 이전 금지, 로컬 삭제 시 서버 삭제 요청·undo 후
자동 재전송 금지, 로그인과 별도 동의·철회 시 신규 전송 중단 및 서버 사본 삭제 요청이라는
권고안을 **합성 서버 DTO·검증 테스트에 한정하여** 구현하도록 승인했다. 운영 보유기간은
미정이다. 기존 PROPOSED 전체나 운영 정책을 APPROVED로 바꾸는 승인이 아니다.

**구현**: [후보 DTO](../../app/modules/neorang_narang/real_sync_schemas.py)와
[전용 합성 테스트](../../tests/test_nn_real_sync_dto.py)만 추가했다. 4.1절·P 3/5/6절을
근거로 생성 envelope 다섯 필드와 metadata 세 필드는 모두 필수·non-null이며,
base_revision은 생략 기본값 없이 명시적 strict 정수 0만 받는다. 두 계층 모두 extra를
거부한다. 과정은 strict 정수 1/2, 날짜는 실제 유효한 ASCII YYYY-MM-DD 문자열을
변환 없이 보존한다. UUID는 기존 schemas 관례처럼 문자열/UUID를 받아 canonical lowercase
hyphenated JSON으로 정규화하며 버전 제한은 없다. 서버 revision·received_at·owner는
생성 입력이 아니다.

consent_generation은 strict 정수지만 실제 계약의 숫자 하한이 명시되지 않아 양수 제약을
추가하지 않았다. 0/음수의 형태 통과도 유효 동의를 뜻하지 않는다. policy_version은
정책 식별 값이라는 최소 의미에 따라 비어 있지 않은 strict 문자열만 검사한다. 정규식·공백
정규화·지원 목록은 근거가 없어 추가하지 않았다. 공백 문자열/알 수 없는 버전의 형태 통과도
정책 지원·승인을 뜻하지 않는다. 실제 Core 세대·정책 일치 검증은 미구현이다.

**당시 보류(역사 기록; 현재 합성 후보는 [9절](#9-합성-ack-후보-구체화) 참조)**: 최소 ACK 필드 목록·최초 revision=1은 문서에 있으나 received_at의 정확한
형식/정규화, 재생 시 applied/current revision 관계가 미확정이므로 ACK DTO는 보류했다.
삭제 요청·관리 상태·부재 장벽 버전 DTO도 구현하지 않았다. DTO는 선택 자격·계정 확인·
동의·소유권·멱등성·로컬 삭제/undo·철회 fence의 실제 동작을 보장하지 않는다.

**오류 경계**: 기존 router의 SafeValidationRoute는 고정 422 패턴이나 이번 DTO와 연결하지
않았다. hide_input_in_errors는 문자열 오류의 입력값을 숨길 뿐 errors()의 입력이나
미지 필드 경로까지 안전하게 만들지 않는다. ValidationError 전체/구조화 오류를 응답·로그에
출력하면 안 된다. 공통 오류 helper/새 프로토콜은 추가하지 않았으며 실제 HTTP 고정 422
연결·관측 경로 비노출 검증은 미구현/NOT_RUN이다.

**검증**: `.venv\Scripts\python.exe -B -m unittest tests.test_nn_real_sync_dto -v`:
12개 PASS, FAIL 0, SKIP 0. 신규 테스트는 DTO·Pydantic·표준 라이브러리만 import한다.
`.venv\Scripts\python.exe -B -m scripts.test_offline`: 146개 중 124 PASS, 22 SKIP,
FAIL 0 (신규 12개 포함). 사전에 러너의 환경 allowlist 정리·.env 계열 open 차단·dotenv
mock·pymysql.connect 차단·외부 socket 차단을 읽고, 기존 opt-in MySQL/Core 테스트의 skip과
SQLiteMobile의 TemporaryDirectory 합성 DB 경로를 확인했다. 러너가 모든 임의 SQLite 경로를
차단하는 일반 sandbox라는 주장은 하지 않는다. 기존 fixture의 임시 합성 DB/mock 회귀이며
실제 DB나 migration 실행이 아니다. `.venv\Scripts\python.exe -B -m pip check`: PASS.
`git diff --check`, 신규 파일 별도 whitespace/최종 newline, 이 문서 상대 링크·변경 범위
검사: PASS. 소스 참조 검색에서 새 DTO는 전용 테스트만 참조하며 router/app 시작 경로는
변경하지 않았다. 실제 DB·기기·앱 통합·migration·배포는 NOT_RUN이다.

실제 수집 **BLOCKED**, 앱 적용 **AUTHOR_REVIEW_REQUIRED**를 유지한다. 패키지 설치·
네트워크 연결·모델 탐색·commit·push·PR 생성·병합은 수행하지 않았다.

## 9. 합성 ACK 후보 구체화

2026-10-31, `feature/nn-real-sync-ack-dto`, 시작 HEAD `f095fee`, clean 확인.
이번 허용은 기존 후보 DTO·전용 합성 테스트·이 문서 세 파일이다. **PROPOSED** 후보
검증이며 운영 정책 전체 승인이나 API 연결 승인이 아니다. 8절의 신규 12 PASS와
offline 124 PASS·22 SKIP은 이전 실행 기록이며 이번 결과와 구분한다.

### 근거와 후보 선택

P 5·6절과 이 문서 4.1절은 ACK 여섯 필드, 서버 최초 revision=1, 동일 operation의
정규화 명령 비교, 삭제·철회 후 성공 재생 금지를 명시한다. P 13.4는 erased receipt와
장벽을 원문 비교보다 먼저 판정한다. 이번 의미와 충돌은 발견하지 않았다.
v1 `CompletionResult`는 metadata·updated_at을 포함하고 서비스가 현재 row revision을
두 revision에 넣는 별도 계약이다. 이를 영속 operation receipt 근거로 쓰거나 변경하지 않는다.

기존 문서가 침묵한 정확한 관계·시각 선택은 이번 합성 구현의 **PROPOSED** 선택이다.

| 필드 | 후보 의미와 형태 |
|---|---|
| operation_id / sync_id | 명령/기록 UUID. 요청 DTO와 같은 문자열 또는 UUID 입력, 버전 제한 없이 canonical lowercase hyphenated JSON |
| applied_revision | 해당 명령이 최초 반영된 기록 revision. strict 양의 정수, 동일 명령 재생에서 최초 값 보존 |
| current_revision | 응답을 구성할 때 확인한 현재 기록 revision. strict 양의 정수, applied_revision 이상 |
| replayed | 같은 operation의 동일 명령 재생 여부, strict bool |
| received_at | 해당 명령의 최초 서버 접수 시각을 성공 receipt에 보존한 값. 재생 시 현재 시각으로 갱신하지 않음 |

최초 생성은 applied_revision=current_revision=1, replayed=false다. 재생은 replayed=true,
applied_revision 보존, current_revision>=applied_revision이다. DTO는 재생에 임의 양의
applied_revision을 허용하여 관계만 검사한다. 실제 생성 receipt의 최초 값이 1이었는지,
동일 명령인지, 과거 값을 보존했는지 대조하는 것은 서비스 의무다.

received_at wire 후보는 UTC RFC3339 `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` 문자열이다.
소수부는 없거나 1~6자리, 실제 달력·시각 유효성을 검사하고 원 문자열과 정밀도를 보존한다.
offset·시간대 없는 문자열·숫자·datetime 객체·공백·윤초를 거부한다. 기존 계약의 승인
사실이 아닌 후보 선택이다. 완료 날짜나 클라이언트 시각에서 생성하지 않으며 DTO에는
기본값이나 현재 시각 생성이 없다.

### 구현 경계와 미결정

[RealCompletionAck](../../app/modules/neorang_narang/real_sync_schemas.py)는 모든 필드
필수·non-null·extra 금지·frozen·문자열 오류 입력값 숨김을 적용한다. metadata·owner·
계정·토큰·원문은 응답 필드에 없다. 앱·설정 로더·DB import 없이 형태/관계만 검사하고
기존 생성 요청 의미는 유지한다. ValidationError.errors() 등은 입력을 포함할 수 있고
미지 필드 경로까지 안전하다고 주장하지 않는다. 전체 오류를 로그/응답에 직렬화하면 안 된다.
HTTP 201/200·고정 422 처리에는 연결하지 않았다.

실제 receipt 저장·최초 접수 시각 보존·current revision 조회·현재 generation/권한/장벽 검사,
삭제·철회·erased 상태의 성공 ACK 재생 차단은 **미구현**이다. DTO가 이 상태를 판정하는
것처럼 해석하지 않는다. 합성 시각 보존 테스트는 실제 receipt 재생 저장 증거가 아니다.

**응답 공백 유지**: 다른 operation의 같은 sync_id·동일 활성 내용은 4.1절상 기존 생성
결과 확인만 허용하지만 정확한 operation_id/applied_revision/received_at/replayed 응답
shape는 미확정이다. 동일 operation replay와 혼동하거나 처리 방식을 임의 확정하지 않는다.
삭제 요청·관리 상태·부재 장벽 버전·보유 정책도 이번에 확정하지 않는다.

### 이번 검증

- `.venv\Scripts\python.exe -B -m unittest tests.test_nn_real_sync_dto -v`: 최종 24 PASS,
  FAIL 0, SKIP 0 (기존 요청 12 + 신규 ACK 12). 첫 실행 23 PASS·1 FAIL에서 파서의
  24시 허용 경계를 확인하여 wire 정규식에 시·분·초 범위를 명시한 뒤 재실행했다.
- `.venv\Scripts\python.exe -B -m scripts.test_offline`: 158개 중 136 PASS·22 SKIP,
  FAIL 0. 기존 환경 정리·환경 파일 차단·dotenv mock·MySQL/외부 socket 차단 가드와
  opt-in skip·임시 합성 SQLite 경로를 확인했다. 러너/관련 기존 fixture는 변경하지 않았다.
  거부 경로 테스트의 고정 result=FAIL 로그는 테스트 실패 집계가 아니다.
- `.venv\Scripts\python.exe -B -m pip check`: PASS, 깨진 의존성 없음.

실제 수집 **BLOCKED**, 앱 적용 **AUTHOR_REVIEW_REQUIRED** 유지.
실제 DB·기기·앱 통합·CI·migration·배포는 **NOT_RUN**이다.
