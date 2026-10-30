# Android 모바일 인수 기록 — 2026-10-30

## 최신 Flutter 수정 후 검사 — USER-REPORTED (2026-10-31)

UI 동시 실행 제어, 세션 거부 처리, 로그인 취소 수정 이후 사용자가 전달한 최신 결과다. 에이전트가 독립 실행하거나 검증한 결과가 아니다.

| 상태 / 출처 | 검사 | 보고된 결과 |
|---|---|---|
| PASS / USER-REPORTED | Flutter analyze | `No issues found.` |
| PASS / USER-REPORTED | 모바일 테스트 | 22 passed |
| PASS / USER-REPORTED | 전체 Flutter 테스트 | 213 passed |

최신 수정 이후 사용자 보고 기기 관찰은 아래 범위에 한정한다. 아래의 이전 기기 관찰을 최신 수정의 기기 재검증으로 간주하지 않는다. 실제 Flutter 저장소가 정본이며 잔존 `.mobile-stage` 파일은 오래되어 적용하면 안 된다. 위 수치는 API 오프라인 테스트 결과와 별개다.

### 최신 로그아웃·동일 계정 재로그인 관찰 — USER-REPORTED

| 상태 / 출처 | 순서 | 보고된 결과 |
|---|---|---|
| PASS / USER-REPORTED | 기존 선택 항목 전송 | 이미 선택한 합성 항목의 서버 저장 확인 성공 |
| PASS / USER-REPORTED | 로그아웃 | 로그아웃 완료 및 대기 전송 일시정지 |
| PASS / USER-REPORTED | 동일 계정 재로그인 | 같은 테스트 계정 A로 다시 로그인함 |
| PASS / USER-REPORTED | 동의 상태 | 동의가 유효하게 유지됨 |
| PASS / USER-REPORTED | 수동 재시도 | 새 항목을 선택하거나 동의를 다시 저장하지 않고 수동 재시도하여 서버 저장 확인 성공 |

위 관찰은 에이전트가 독립 실행하거나 검증하지 않았다. 성공 메시지만으로 전후 UUID·payload 동일성 또는 서버 행 수 불변을 독립적으로 입증할 수 없다. 이 최신 시험의 서버 행 수 비교는 보고되지 않았다. 이전 시험의 SELECT 결과로 이를 대신하지 않는다.

최신 수정의 실제 기기 검증 중 **전송 진행 중 철회·로그아웃**, **서버가 거부한 401 처리**, **페이지 이탈 시 로그인 취소 및 늦은 복귀 거부**는 각각 **NOT_RUN**이다. 위 순차 로그아웃·재로그인 관찰이나 보고된 테스트 통과를 해당 기기 검증의 PASS로 간주하지 않는다.

## 출처와 범위

아래 실행 결과는 모두 **USER-REPORTED (사용자 보고)** 이다. 문서 작성 에이전트가 기기, Flutter, MySQL 또는 인증 흐름을 실행하거나 독립 검증한 결과가 아니다. PASS는 보고된 해당 관찰 범위에만 적용하며, 전체 프로젝트 테스트 통과 또는 운영 준비 완료를 뜻하지 않는다.

환경: Galaxy S22 SM S901N, Android 16, USB ADB reverse. 최초 시험은 동일한 테스트 계정 A로 진행했고, 후속 시험은 서로 다른 테스트 계정 A/B로 진행한 합성 자료 시험이다. 계정 UUID, 비밀정보, 토큰 및 기록 내용은 포함하지 않는다.

## 사용자 보고 실행 결과

| 상태 / 출처 | 항목 | 보고된 결과 |
|---|---|---|
| PASS / USER-REPORTED | Core broker 로그인 | 동일 테스트 계정으로 로그인 및 앱 복귀 성공 |
| PASS / USER-REPORTED | Flutter analyze | `No issues found.` |
| PASS / USER-REPORTED | 모바일 테스트 파일 | 12개 테스트 통과. 전체 프로젝트 테스트 결과는 아님 |
| PASS / USER-REPORTED | 합성 항목 재전송 | 재시도 수정 후 기존 합성 항목 재전송 성공 |
| PASS / USER-REPORTED | 전송 후 계정 범위 MySQL SELECT | generation 1에서 `total_rows=1`, `unerased_rows=1`, `metadata_not_null_rows=1` |
| PASS / USER-REPORTED | 화면 꺼짐/켜짐 | 성공 메시지가 유지됨 |
| FAIL / USER-REPORTED | 최초 철회 시도 | 인증 실패 발생. 삭제 대기(deletion pending)를 유지함 |
| PASS / USER-REPORTED | 삭제 재개 | 동일 계정 재로그인 후 삭제 재개 |
| PASS / USER-REPORTED | 후속 계정 범위 MySQL SELECT | `active=false`, `generation=1`, `deletion_through=1`, `deletion_status=complete`, `total_rows=1`, `erased_rows=1`, `metadata_not_null_rows=0` |
| PASS / USER-REPORTED | 기존 로컬 완료 기록 | 사용자가 기존 완료 기록이 계속 보이는 것을 확인함 |

## 후속 A/B 계정 전환 관찰 — USER-REPORTED

아래 기기 관찰과 SELECT 결과도 모두 사용자 보고이며 에이전트가 독립 실행하거나 검증하지 않았다. PASS는 각 관찰에만 적용하며, 완전한 보안 격리 검증을 뜻하지 않는다.

| 상태 / 출처 | 순서 | 보고된 결과 |
|---|---|---|
| PASS / USER-REPORTED | B 로그인·동의 후 선택 없이 전송 | A와 다른 계정 B로 로그인하고 동의한 뒤, 항목을 선택하기 전에 전송을 시도하자 선택된 합성 항목이 없다고 표시됨 |
| PASS / USER-REPORTED | B 선택·업로드 | 합성 항목 하나를 선택하고 업로드 성공 |
| PASS / USER-REPORTED | A로 복귀 | 동의 비활성 및 삭제 대기 없음으로 표시됨. 이 시점의 A/B SELECT는 아래 표와 같음 |
| PASS / USER-REPORTED | A 재동의 후 선택 없이 전송 | A가 다시 동의했으나 새 항목을 선택하지 않은 상태에서 전송하자 항목이 없다고 표시됨. 재동의 후 A의 generation은 조회 결과가 없어 추론하지 않음 |
| PASS / USER-REPORTED | B로 다시 복귀·재전송 | B로 돌아와 다시 선택하거나 동의하지 않고 재전송 성공 |

A로 처음 복귀한 시점의 계정별 SELECT:

| 출처 | 계정 | generation | active | deletion_through | deletion_status | total | erased | metadata_not_null |
|---|---|---|---|---|---|---|---|---|
| USER-REPORTED | A | 1 | false | 1 | complete | 1 | 1 | 0 |
| USER-REPORTED | B | 1 | true | 0 | none | 1 | 0 | 1 |

B 재전송 후 최종 SELECT:

| 출처 | 계정 | active | generation | total | erased | metadata_not_null |
|---|---|---|---|---|---|---|
| USER-REPORTED | B | true | 1 | 1 | 0 | 1 |

최종 B SELECT에 보고되지 않은 삭제 관련 필드는 추정하지 않는다. 위 A 재동의 직후에는 SELECT가 보고되지 않았으며, 이후 A의 상태는 아래 후속 시험의 SELECT로 별도 기록한다. 재전송 성공과 행 수만으로 실제 payload 또는 UUID의 동일성을 입증할 수 없다.

## 후속 API 경로 단절·앱 재실행 관찰 — USER-REPORTED

아래 실행 결과와 후속 SELECT는 모두 사용자 보고이며 에이전트가 독립 실행하거나 검증하지 않았다. PASS는 보고된 관찰 범위에만 적용한다.

| 상태 / 출처 | 순서 | 보고된 결과 |
|---|---|---|
| PASS / USER-REPORTED | A 합성 항목 선택 | 동의가 활성인 상태에서 A가 합성 항목 하나를 선택함 |
| PASS / USER-REPORTED | API 경로 단절 | USB 연결과 API 실행을 유지한 채 ADB reverse `tcp:8000`을 제거함 |
| PASS / USER-REPORTED | 단절 중 수동 전송 | 통신 실패가 표시되고 전송 대기 데이터가 유지됨 |
| PASS / USER-REPORTED | Recent Apps에서 앱 닫기·재실행 | 사용자가 Recent Apps에서 앱을 닫은 뒤 다시 열자 로그인 필요가 표시됨 |
| PASS / USER-REPORTED | 경로 복구·재로그인·수동 전송 | ADB reverse를 복구하고 A가 다시 로그인함. 새 항목을 선택하거나 다시 동의하지 않고 수동 전송 성공 |

전송 후 SELECT:

| 출처 | 계정 / 범위 | active | generation | total_rows | erased_rows | metadata_not_null_rows |
|---|---|---|---|---|---|---|
| USER-REPORTED | A 현재 동의 / 현재 generation | true | 2 | 1 | 0 | 1 |
| USER-REPORTED | A 이전 generation | 보고되지 않음 | 1 | 1 | 1 | 0 |

이 시험은 API 경로 단절을 시험했으며 전체 인터넷 연결 상실을 시험한 것은 아니다. Recent Apps에서 앱을 닫았다는 관찰만으로 OS 프로세스 종료를 독립적으로 입증할 수 없다. 전후 UUID 또는 payload 비교는 수행하지 않았으므로 해당 동일성 검사를 PASS로 간주하지 않는다.

## 실패 이력과 수정의 구분

재시도 수정과 그 이후의 재전송 성공 보고를 구분한다. 수정 자체를 모든 재시도 경로의 검증으로 간주하지 않는다. 이전 재전송 문제의 상세 오류와 실행 로그는 이번 보고에 제공되지 않았다.

철회 중 인증 실패는 이후 삭제 완료 보고로 덮어쓰지 않는다. 관찰된 순서는 인증 실패 → 삭제 대기 유지 → 동일 계정 로그인 → 삭제 재개 → 후속 SELECT의 complete 확인이다. 최초 철회가 즉시 성공했다는 의미가 아니다.

[모바일 첫 연결 안내](../mobile-first-link.md)의 기존 실패·수정·검사 기록은 당시 범위의 이력으로 유지한다. 이 문서는 위 사용자 보고 결과만 추가하며, 과거 미실행 항목 전체를 PASS로 바꾸지 않는다.

## 검증 한계

- 실제 MySQL에서 전후 UUID 또는 payload 비교를 수행하지 않았다. 행 수와 상태 보고만으로 동일 UUID·동일 payload 보존을 입증할 수 없다.
- 기존 로컬 기록의 byte 단위 검증은 하지 않았다. 화면에서 보인다는 확인만 있으며 원본의 완전한 불변성 증거는 아니다.
- 모바일 A/B 계정 전환의 위 관찰은 사용자 보고 범위에서만 확인되었다. 교차 계정 위조 API 요청 거부, 실제 payload/UUID 동일성 비교, 삭제 대기가 아닌 전송 대기 큐 항목이 있는 상태의 계정 전환은 미검증이다 (**NOT_RUN**). 완전한 보안 격리 검증으로 간주하지 않는다.
- 실제 기록 동기화, 오프라인 기기 재시작, 백업 만료 및 운영 준비 상태는 미검증이다 (**NOT_RUN**).
- 화면 꺼짐/켜짐 결과는 기기 재시작 또는 앱 프로세스 종료 후 복원 검증이 아니다.
- 후속 ADB reverse 제거 시험은 API 경로 단절 범위에 한정하며 전체 인터넷 연결 상실은 미검증이다 (**NOT_RUN**). Recent Apps에서 앱을 닫은 뒤 재실행한 결과도 OS 프로세스 종료를 독립적으로 입증하지 않으므로, 프로세스 종료 후 복원 검증을 PASS로 변경하지 않는다.
- 에이전트의 기기 실행, Flutter analyze/테스트, MySQL 조회, API 회귀 테스트 및 `pip check`는 이번 문서 작업에서 **NOT_RUN**이다. 전체 프로젝트 테스트 통과를 주장하지 않는다.

이번 작업은 문서 작성에 한정한다. DB, Auth0, 앱, stage, 서비스 및 설정을 변경하지 않으며 commit·push를 수행하지 않는다.
