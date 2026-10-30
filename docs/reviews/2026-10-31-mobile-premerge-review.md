# API PR #1 모바일 pre-merge review — 2026-10-31

## 판단과 범위

검토 범위는 `6b28f01..10c7dda`(검토 시 HEAD), 브랜치는 `feature/nn-completion-contract`이다. 변경 22개 파일과 관련 기존 인증·저장소 코드, 테스트, 인수 문서를 정적으로 검토했다. 시작 시 `git status --short`는 비어 있었다. 이 작업은 이 리뷰 문서만 추가한다.

**개발 PoC: 사람의 경계 검토를 전제로 병합 가능한 상태로 판단한다.** 제한된 로컬 Android·합성 자료 PoC 범위에서 새로 확인한 P0/P1 코드 병합 차단 결함은 없다. 이는 승인이나 실제 merge 실행을 뜻하지 않는다. **운영 배포 준비 완료는 아니다.** 아래 AUTHOR_REVIEW_REQUIRED 결정, 실제 MySQL/복구 검증 및 운영 보안·보존 정책이 남아 있다.

DB, 환경 파일 내용, 비밀정보, 백업 산출물, Auth0, 기기 자료에는 접근하지 않았다. Python 앱이나 DB 도구도 실행하지 않았다. Flutter 전체 리뷰는 반복하지 않았다. 이전 PASS 테스트를 재실행할 구체적 사유가 없어 API·Flutter 테스트 및 pip check는 이번 작업에서 NOT_RUN이다.

## 근거의 출처

| 근거 | 상태와 한계 |
|---|---|
| API push run, commit `10c7dda` | PASS / USER-SUPPLIED CI EVIDENCE. 사용자가 제공한 성공 결과와 offline 로그 `Ran 134 tests`, `OK (skipped=22)`를 사용한다. 실행 성공은 112개, 의도적 skip은 22개다. 이번 에이전트가 실행하거나 GitHub 로그를 직접 조회한 결과가 아니다. |
| API pull_request run | 상세 실행 로그와 테스트 수는 이번 검토에서 확인하지 않았다. push 로그 수치를 PR run에 귀속하지 않는다. |
| Flutter PR #3 | USER-SUPPLIED CI EVIDENCE: analysis/tests 및 Android debug build를 포함한 4개 CI check 성공. API 테스트 수치와 합치지 않으며 전체 Flutter 리뷰를 대신하지 않는다. |
| Android 관찰·계정 범위 SELECT | USER-REPORTED. `docs/verification/2026-10-30-android-mobile-acceptance.md`의 순차 로그인·전송·철회 재개·계정 전환·경로 단절 복구 관찰만 인정한다. 화면/스크린샷/사용자 보고는 독립 실행 증거가 아니다. |
| 기존 PC A/B·재시작 문서 | 과거 증거다. `docs/verification/2026-10-30-auth0-ab-acceptance.md`는 당시 자동 검사와 실제 로그인 사용자 보고를 구분한다. `2026-10-30-restart-verification.md`의 API 재시작·체크포인트 결과는 USER-REPORTED이며 MySQL 실제 중지·재시작 로그는 미확인이다. 모바일 변경 검증으로 확대하지 않는다. |
| 소스와 테스트 검토 | 이 에이전트의 정적 확인이다. 테스트 함수의 존재·assertion을 확인했으며 이번 실행 PASS라는 뜻이 아니다. |

## 심각도별 발견 사항

### 병합 차단 및 사람 결정

- **AUTHOR_REVIEW_REQUIRED — AGENTS.md:41, 42 및 공통 보호 규칙:** 저장소 지침의 정확한 요구는 “DB 구조·인증 경계·개인정보 공유 변경은 AUTHOR_REVIEW_REQUIRED로 분류한다.” 및 “migration은 이전 버전 업그레이드·롤백·백업·복구 계획과 함께 검증한다.”이다. 이 문서는 저자 승인 기록을 새로 만들지 않는다. 아래 구체적 결정의 사람 검토가 확인되기 전에는 무조건 승인된 병합으로 표현할 수 없다.
- **P0/P1 코드 병합 차단 결함: 이번 제한된 정적 검토에서 확인되지 않음.** 미실행 검증을 PASS로 바꾸거나 운영 승인을 의미하지 않는다.

### P2 — 후속 구현·운영 적용 전 해결

1. **인증 확인과 쓰기 commit 사이 로그아웃 경합:** `app/core/mobile_routes.py:60`, `:174`, `:181`에서 세션 조회, 동의/업로드, 로그아웃이 서로 다른 transaction이다. `app/core/mobile_store.py:60`은 동의 행을 잠그지만 세션을 다시 확인하지 않는다. 이미 identity를 통과한 업로드는 로그아웃 commit 뒤에도 저장될 수 있다. 후속 요청 거부와 진행 중 요청 취소는 다른 보장이다. 강한 로그아웃 장벽이 필요하면 저장 transaction 안에서 세션 version/revocation을 검사하는 순서·잠금 계약을 정하고 MySQL 경합 검증을 추가해야 한다. `tests/test_mobile_broker.py:243`은 순차 로그아웃 이후 401만 확인한다. 개발 PoC 범위의 알려진 제한으로 남기며 운영의 즉시 취소 보장으로 홍보하면 안 된다.
2. **Core의 제품 DB 직접 쓰기와 권한 결합:** `scripts/mobile_mysql.py:134`, `app/modules/neorang_narang/mobile_store.py:12`, `app/core/mobile_store.py:77`은 Core 연결로 제품 테이블에 SELECT/INSERT/UPDATE하고 동의·삭제를 함께 commit한다. 원자성에는 도움이 되지만 제품 DB 쓰기 권한이 Core에 필요하다. `docs/mobile-backup-rehearsal.md`의 후속 분리안처럼 제품 소유 서비스/API 또는 outbox 계약으로 이전할지, PoC 동안 이 결합을 허용할지 사람이 결정해야 한다. 권한 축소 전에 generation·멱등성·삭제 장벽을 보존해야 한다.
3. **expiry는 보유 자료 정리를 의미하지 않음:** `app/core/mobile_store.py:19`, `:41`, `:49`, `:54`는 로그인 300초·handoff 60초 이후 사용을 거부하고 성공 소비 시 credential 암호문을 비운다. 만료된 미소비 browser/credential 암호문과 기존 세션 자료의 정리 작업은 이 변경에 없다. 삭제 장벽도 UUID/owner/generation을 의도적으로 보유한다(`app/modules/neorang_narang/mobile_store.py:32`). 보유 기간·정리·감사·백업 만료 정책과 복구 시 삭제 재적용을 운영 전에 승인·구현해야 한다. 실제 백업 만료 검증은 NOT_RUN이다.

### P3 — 유지보수 후속

- `.github/workflows/offline-tests.yml:17`, `:20`: 관찰된 Node action runtime 경고를 후속 과제로 기록한다. action SHA/runtime 호환성과 변경 검증을 별도 작업으로 처리한다. 이번 검토에서 경고 원문·제거 일정을 직접 확인하지 않았으며 버전/기한을 추정하지 않는다.
- `requirements-dev.txt:1`, `.github/workflows/offline-tests.yml:24`: 관찰된 dependency deprecation 경고를 후속 과제로 기록한다. 원문과 발생 패키지를 확보해 영향과 교체 시점을 판단한다. 경고를 테스트 실패나 취약점으로 단정하지 않는다. 이번 작업은 dependency·action을 변경하지 않는다.

## 인증 경계: 코드·테스트와 증거 한계

| 경계 | 지원 코드와 테스트 | 한계 |
|---|---|---|
| 검증된 계정 소유권 | `app/core/auth0_provider.py:80`, `:95`, `:112`: access JWT 검증과 ID JWT signature/issuer/audience/subject/nonce 결합. `app/core/auth0_poc.py:109`은 RS256, 고정 issuer/audience/client, access profile·수명·scope를 검사한다. `app/core/core_store.py:118`은 검증된 issuer+subject를 Core UUID에 매핑하며 계정 active/security version을 검사한다(`:162`). `tests/test_auth0_poc.py:106`, `:114`, `:182`에 등록·claim·identity 거부 검사가 있다. | provider subject를 본문 UUID로 대체하지 않는다. 실제 Auth0 설정·키·계정 상태는 조회하지 않았다. 과거 PC A/B 결과는 모바일 교차 계정 요청 실증이 아니다. |
| 모바일 bearer 및 scope | `app/core/mobile_routes.py:60`은 opaque credential을 저장 세션과 JWT로 검증하고 `session.account_id`만 소유자로 사용한다. GET read / 그 외 write scope를 요구한다. 본문은 extra forbid(`:19`)이며 인증값을 받아 소유자를 선택하는 필드가 없다. `tests/test_mobile_broker.py:186`은 A/B UUID 분리·외부 계정 동일 UUID 거부(409)·무인증 401·PC 경로에서 opaque bearer 거부를 확인한다. | 실제 기기/실제 MySQL에 대한 교차 계정 위조 요청 거부는 NOT_RUN. 오프라인 assertion과 기기 계정 전환 관찰을 구분한다. |
| 이중 PKCE와 callback | `app/core/mobile_routes.py:77`, `:88`, `:109`: 앱 challenge와 고정 return URI, 별도 upstream verifier/nonce/state, browser cookie 결합. `app/core/core_store.py:91`은 pending→exchanging을 조건부 갱신하여 callback proof를 먼저 소비한다. provider 교환은 고정 callback allowlist(`app/core/auth0_provider.py:83`)만 허용한다. `tests/test_mobile_broker.py:168`, `:179`, 기존 `tests/test_core_persistence.py:162`가 잘못된 binding/nonce/callback 입력을 다룬다. | 모바일의 bad-nonce 테스트 함수 이름만으로 모든 정상 callback replay 사례가 실행됐다고 주장하지 않는다. 기존 실제 Core 테스트는 CI에서 skip된다. 네트워크 교환 실패 후 같은 callback의 자동 재사용을 제공하지 않으며 새 로그인 필요. |
| handoff 일회성·expiry·replay | `app/core/mobile_store.py:14`, `:30`, `:44`: state/code hash, 암호화 credential, transaction UUID, return URI, PKCE, expiry를 결합한다. `FOR UPDATE` 안에서 consumed_at을 기록하고 credential 암호문을 제거한다. deep link에는 transaction+일회용 code만 실린다(`app/core/mobile_routes.py:127`). `tests/test_mobile_broker.py:168`은 잘못된 verifier/transaction/URI/code, replay 및 61초 경과 거부, `:246`은 단일 승자를 검사한다. | SQLite 단일 승자가 MySQL lock 동작을 입증하지 않는다. 소비 commit 후 응답 유실 시 같은 handoff로 credential을 재발급하지 않는다. 새 로그인으로 복구해야 한다. |
| logout·만료 | `app/core/mobile_routes.py:177`은 현재 app_session revoked_at/version을 갱신한다. 다음 요청은 `cookie_token`·`lookup`·binding 검사에서 거부된다(`app/core/core_store.py:180`, `app/core/auth0_poc.py:179`). `tests/test_mobile_broker.py:243`의 순차 204→401과 `tests/test_auth0_poc.py:160` 이후 primitive 검사가 지원한다. | Auth0 SSO 종료나 모든 세션 종료가 아니다. refresh/offline_access는 요청하지 않고 provider도 refresh_token 응답을 거부한다. primitive refresh/CAS 테스트가 실제 모바일 refresh 구현을 의미하지 않는다. 진행 중 요청은 P2 경합 제한이 있다. |
| 로컬 전송·오류 노출 | `app/core/mobile_routes.py:14`, `:15`의 HTTP loopback/custom scheme은 ADB reverse PoC 전용이다. `app/auth0_pc.py:74`, `:82`는 trusted host·고정 오류·no-store/no-referrer를 적용한다. `tests/test_mobile_broker.py:205`는 extra 입력이 오류에 노출되지 않음을 확인한다. | 운영 HTTPS, verified app links, secure cookie, rate limiting 및 만료/악용 모니터링은 별도 설계·검증 대상이다. TrustedHost만으로 실제 listener가 loopback에 bind됐음을 입증하지 않는다. |

## 동의·업로드·삭제 경계

| 경계 | 지원 코드와 테스트 | 한계 |
|---|---|---|
| 동의 세대·계정 범위 | `app/core/mobile_store.py:58`은 account PK 행을 생성/잠그고 inactive→grant 때만 generation을 증가시킨다. 업로드는 active, generation 일치, generation > deletion_through 모두 필요하다(`:80`). `tests/test_mobile_broker.py:186`, `:212`가 계정 분리·세대 재동의·이전 세대 410을 검사한다. | 모바일 동의는 기존 PC product_consents와 별도다. 모바일 identity는 PC consent를 gate로 쓰지 않고 각 모바일 작업에서 generation을 검사한다. 이 목적·범위 분리를 사람이 승인해야 한다. |
| 불변 재시도 | `app/modules/neorang_narang/mobile_store.py:11`은 전역 sync_id PK로 원본을 찾고 owner/generation/erased/전체 정규화 metadata가 같을 때만 replay 성공한다. 변경 payload·다른 계정·다른 세대는 409. account+generation unique로 합성 항목 1개만 허용한다. `tests/test_mobile_broker.py:193`부터 동일 재시도·payload 변경·다른 계정·새 UUID 충돌을 검사한다. | UUID는 계정별 재사용 가능 ID가 아니라 이 PoC 테이블에서 전역 장벽이다. 기기 전후 UUID/payload 동일성은 NOT_RUN. 성공 메시지나 행 수 1만으로 불변 재시도 실증을 주장하지 않는다. |
| 철회·삭제 장벽 | `app/core/mobile_store.py:70`은 미래 revoke를 409로 거부하고 through=max를 유지한다. 이전 revoke는 새 grant를 끄지 않는다. `app/modules/neorang_narang/mobile_store.py:32`는 해당 계정·through 이하 metadata를 NULL, erased=true로 만든다. `tests/test_mobile_broker.py:212`는 재시작 adapter·철회 재시도·재동의·옛 철회 재시도와 원본 NULL을 확인한다. | complete는 해당 live 합성 projection의 through 이하 삭제다. 계정/세션/백업/원본 로컬 기록의 완전 삭제가 아니다. 과거 complete와 현재 동의 구분은 current_generation_deletion_complete로 확인한다. |
| 전송/철회 원자성 | 같은 account consent 행 잠금 아래 product adapter erase/create와 Core UPDATE가 같은 연결로 commit된다. `tests/test_mobile_broker.py:257`, `:272`는 동시 send/revoke 후 서버 copy 없음과 erase 이후 예외 시 원본 보존을 확인한다. | 실제 MySQL transaction·lock·deadlock 결과는 NOT_RUN. 기기의 전송 중 철회 및 로그아웃 경합도 NOT_RUN. 세션 취소는 consent 행 잠금과 별도다. |
| 자료 허용 범위 | `app/core/mobile_routes.py:39`, `:163`은 synthetic=true와 UUID/course/mode/completed_at/generation만 허용하고 제품 metadata validator로 재검증한다. 자유 텍스트·서명·이름 필드는 받지 않는다. | synthetic 플래그는 클라이언트 자료의 출처를 증명하지 않는다. 실제 기록 수집·역사 자료 투영·다른 제품 동기화 승인이 아니다. |

## DB·migration·복구 경계

| 경계 | 지원 코드와 테스트 | 한계 및 판단 |
|---|---|---|
| 런타임 transaction | `app/core/core_store.py:57`: READ COMMITTED, begin/commit, finally rollback/close, MySQL 예외는 고정 503. `app/core/mobile_store.py:9`는 별도 mobile marker가 정확히 `[1]`인지 확인한다. InnoDB DDL은 두 `002` SQL에 정의돼 있다. | HTTP 인증 조회와 쓰기는 단일 transaction이 아니다. commit 응답 유실은 결과 불명일 수 있으며 UUID/세대 재조회·재시도 계약으로 복구해야 한다. 임의 DB 오류를 성공으로 바꾸지 않는다. |
| 잠금·uniqueness | mobile exchange의 transaction_id `FOR UPDATE`, consent account 행 잠금, projection PK 및 `(owner_sub,generation)` unique가 핵심이다. `tests/test_mobile_broker.py:39`는 FOR UPDATE를 제거하며 `:76`의 BEGIN IMMEDIATE로 대체한다. | SQLite 직렬화는 실제 MySQL의 행 잠금/다른 계정 동일 UUID 경합/timeout/deadlock을 인증하지 않는다. 다른 계정은 서로 다른 consent 행을 잠그므로 최종 전역 UUID 경합은 DB uniqueness에 의존한다. 충돌/DB 실패는 409/503이며 필요 시 동일 불변 요청으로 재시도한다. |
| 기존 DB 업그레이드 | `scripts/mobile_mysql.py:74`는 정지·복원 리허설 확인 플래그, 보호 snapshot, advisory lock, 양 DB v1/mobile shape 검사를 target DDL 전에 수행한다. layout DB는 별도로 생성한다. missing table만 추가하고 marker는 전체 shape 확인 뒤 기록한다(`:118`). `tests/test_mobile_migration.py:90` 이후는 partial retry·알 수 없는 shape/version·필수 v1 누락을 mock 검증한다. | 기존 v1 DB용이며 빈 DB 최초 설치 전체 절차가 아니다. 플래그는 실제 writer 정지를 증명하지 않으며 advisory lock도 앱 writer를 막지 않는다. 실제 DDL·권한·MySQL 재시도 검사는 NOT_RUN이다. |
| rollback·GRANT | `scripts/mobile_mysql.py:130`은 marker commit 후 GRANT하고 최종 원본 비교한다. `tests/test_mobile_migration.py:114`는 GRANT 실패 후 marker가 남아도 성공 처리하지 않고 새 시도로 재검사하는 것을 확인한다. | DDL/GRANT 자동 commit으로 전체 rollback 불가. marker만으로 성공 판정 금지. 코드 rollback도 DB/권한 rollback이 아니다. 부분 테이블·layout·백업을 보존하고 정지 상태에서 별도 복구 결정을 받아야 한다. 자동 DROP/초기화·원본 restore는 제공하지 않는다. |
| 백업·격리 복원 | `scripts/mobile_backup.py:84`, `:125`, `:174`: 양 InnoDB schema 일관 snapshot, DDL/rows/FK, 별도 권한 inventory, 새 무작위 DB만 복원, readback·원본/복원 비교, 실패 시 보존. `tests/test_mobile_backup.py:132`, `:149`, `:159`, `:195`, `:240`은 FK 순서·응답 유실·부분 실패·재시도·권한 실패를 mock 검증한다. | 보호 파일은 암호화 백업 자체가 아니다. writer 정지 증거는 파일 존재만 검사한다. 실제 MySQL 복원·ACL·키 가용성·복호화·세션 사용 가능성은 NOT_RUN. result에도 decrypt NOT_RUN을 명시한다(`:235`). 기존 Core 고정 목록 백업은 모바일 전체 복구에 충분하지 않다. |

## 오프라인 CI와 의도적 skip

`scripts/test_offline.py:16`은 import 전에 상속 환경을 정리하고 memory mode로 고정한다. 환경 파일 open, 외부 socket connect/DNS를 audit hook으로 거부하며 dotenv를 빈 설정으로, pymysql.connect를 거부 mock으로 대체한다. Windows asyncio socketpair 자체 wakeup loopback 예외만 허용한다. 이는 테스트의 실제 DB/네트워크 접근 방지 장치이며 임의 악성 subprocess까지 격리하는 OS sandbox라는 뜻은 아니다.

`.github/workflows/offline-tests.yml:3`은 main 대상 pull_request와 main/해당 feature push를 대상으로 Ubuntu 24.04·Python 3.14.8, 10분 제한, contents:read, SHA 고정 action과 persist-credentials:false를 사용한다. 설치·pip check 이후 격리 runner를 실행한다. 패키지 설치 자체는 네트워크 단계이며 테스트 실행의 offline 의미와 구분한다. `requirements-dev.txt`는 고정 목록이지만 해시 기반 배포 lock은 아니다.

의도적 22 skip은 `tests/test_mysql_persistence.py:25`의 RUN_MYSQL_TESTS opt-in 9개와 `tests/test_core_persistence.py:72`의 RUN_CORE_TESTS opt-in 13개다. runner가 이 opt-in 환경을 지우므로 CI에서 실제 DB 검사를 수행하지 않는다. 성공은 134개 전체 실행 통과가 아니라 **112 pass + 22 skip**이다. 모바일 migration/backup mock 성공을 실제 MySQL 실행 PASS로 바꾸지 않는다. 과거 문서의 128/106/22 등은 당시 수치이며 현재 push 증거와 덮어 합산하지 않는다.

폐기된 stage 도구는 `scripts/stage_mobile_client.py:14`에서 항상 exit 2로 거부하며 `tests/test_stage_mobile_client.py:16`이 합성 target 무접근을 검사한다. 잔존 `.mobile-stage`를 적용하지 않는다. Flutter 정본과 이번 리뷰 범위는 별개다.

## 사람 검토, 후속 검증 및 배포 조건

AGENTS.md의 위 문구에 더해 적용한 공통 규칙 `C:/Users/user/.agents/skills/jesuslife-platform-development/references/common-rules.md`는 “신학 문구·정본, Canonical ID 발급·병합·폐기, 개인정보 공유, DB 구조, 인증 경계 변경은 `AUTHOR_REVIEW_REQUIRED`로 분류한다. 초안·영향·대안·복구 계획을 제시하고 필요한 사람의 승인 전 적용하지 않는다.”라고 요구한다. 이 리뷰는 변경 적용이나 승인이 아니다.

저자는 병합 판단에서 다음 결정을 명시적으로 검토해야 한다.

1. 기존 검증된 issuer+subject→Core UUID 매핑을 쓰는 모바일 opaque bearer, 고정 local callback/custom scheme, 현재 세션만 logout하는 개발 인증 경계를 허용할지.
2. PC와 별도인 모바일 동의 generation, 계정별 합성 1개, 전역 sync UUID, 불변 replay, metadata 삭제 후 식별 장벽 보유 및 complete의 제한된 의미를 허용할지.
3. 추가 InnoDB 테이블·Core의 제품 테이블 직접 권한·같은 transaction 결합, marker 후 GRANT의 부분 실패, 자동 rollback 부재를 PoC에서 수용할지.
4. 실제 migration 적용 전에 writer 중단, 전체 보호 백업·격리 복원·키 복구, 원본 불변 비교, 실패 시 보존/복구 담당 계획을 어떻게 승인할지. PoC 소스 병합과 migration 실행 승인은 분리한다.

후속 기기 검증은 전송 중 철회·로그아웃, 서버 401 처리, 페이지 이탈 로그인 취소·늦은 복귀 거부, 전송 대기 상태 계정 전환, 교차 계정 위조 요청 거부, UUID/payload 전후 동일성이다. 모두 기존 NOT_RUN을 유지한다. 전체 인터넷 상실, OS 프로세스 종료 후 복원, 기기 재부팅, 백업 만료도 기존 관찰로 입증되지 않았다.

운영 배포 전에는 실제 MySQL 잠금/실패/복원 검증, 검증된 HTTPS·앱 복귀 경로와 비밀/키 관리, 로그·권한·rate limit 정책, 세션 취소 의미, 동의·보존·백업 삭제 정책 및 실제 자료 수집 승인이 필요하다. 이번 CI·기기 보고를 운영 승인으로 사용하지 않는다.

## 이번 작업에서 실제 실행한 검사

| 상태 | 검사 | 범위 |
|---|---|---|
| PASS | 현재 경로, `git rev-parse --show-toplevel`, `git branch --show-current`, `git status --short`, log/diff 및 허용된 소스·문서 읽기 | 독립 저장소·HEAD·시작 시 깨끗한 작업 트리 확인, 정적 검토 |
| PASS | `git diff --check` | 추적 파일의 공백 오류 없음. 새 untracked 문서는 아래 별도 검사로 확인 |
| PASS | `git -c core.autocrlf=false diff --no-index --check -- /dev/null docs/reviews/2026-10-31-mobile-premerge-review.md` | 새 문서 전체 공백 검사 |
| PASS | PowerShell 새 문서 whitespace 검사 | 후행 공백·탭·CR 문자·마지막 newline 누락 없음 |
| NOT_RUN | API/Flutter 테스트, pip check, DB/인증/기기·복구 실행 | 사용자 요청에 따라 기존 PASS를 반복하지 않고 금지 자원에 접근하지 않음 |
| AUTHOR_REVIEW_REQUIRED | 인증·DB·동의/공유 경계 결정 | 저자의 구체적 결정 필요. 승인 사실을 추정하지 않음 |

다음 단계는 저자가 위 네 경계 결정을 PR #1에 기록하고 개발 PoC 병합 여부를 판단하는 것이다. 이 작업에서는 stage·commit·push·merge·설정 변경을 수행하지 않는다.
