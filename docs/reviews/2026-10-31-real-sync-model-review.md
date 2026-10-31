# 실제 완료 동기화 독립 모델 리뷰

2026-10-31. 판정: 한정된 추상 모델로는 유용하나 검사기 보완 필요. 실제-data 활성화는 **BLOCKED**, 인증·DB·개인정보 경계는 **AUTHOR_REVIEW_REQUIRED**다. 제품 결함이나 운영 안전성을 입증한 리뷰가 아니다.

## 범위와 보존

- 검토 대상: `docs/design/nn-real-completion-sync-proposal.md` 전체와 `tools/sync_model/`에 실제 존재하는 `model.py`, `explore.py`, `test_model.py`, `README.md` 전체. 숨김 파일 포함 목록에서도 모델 디렉터리는 이 네 파일뿐이다.
- 프로젝트 `AGENTS.md`, 루트 README, 두 requirements 파일 및 JesusLife development 공통 보호·design·implementation의 관련 절차를 읽었다. 제품 원본은 너랑나랑, Core는 동의·자격 조정 소유라는 제안 경계를 기준으로 검토했다. 외부 문서·현재 제품 구현의 사실관계는 재검증하지 않았다.
- 시작 경로와 Git 루트는 `D:/CHGO-VibeCodeing/JesusLife-One-API`, 브랜치는 `main`. 시작 변경은 위 다섯 파일 모두 untracked였고 tracked diff는 없었다. 명시적으로 요청된 이 리뷰만 추가하며 기존 파일·브랜치는 변경하지 않았다.
- 앱 import, DB·사용자 기록·환경 파일·비밀·백업 접근, 설치, 네트워크, staging·commit·push·활성화는 수행하지 않았다.

## 발견 사항: 심각도와 위치

### 중간 R1 — ACK의 소유 계정 조건과 시작 조정 gate를 검사기가 독립적으로 보장하지 않는다

위치: `tools/sync_model/model.py:133–136, 174–186`, `tools/sync_model/test_model.py:81–84`, `tools/sync_model/README.md:16, 20, 27`.

현재 `step`은 ACK에 owner 조건을 적용하지만, `violations`의 owner 검사는 admitted/management/metadata effect에만 적용된다. ACK의 client_active 변경은 포함하지 않는다. stale ACK 검사는 retired/barrier 상태의 false→true만 검사하며 계정·검증·epoch를 직접 확인하지 않는다. 실제 reachable prefix `admit_old → commit_old → switch_other` 뒤 잘못된 ACK가 client_active를 true로 만든 결과를 주입하면 오류 목록은 `[]`였다. 이는 현재 정상 모델에서 그 잘못된 ACK가 실행된다는 뜻이 아니라 **검사기의 독립 탐지 공백**이다. 선택된 unittest는 현재 guard를 확인하지만 해당 mutant의 탐색 검출 증거는 없다.

또한 `upload_allowed`의 startup_ready 조건에 대응하는 독립 불변식이 없다. startup_ready=False 상태에 ticket 추가와 admitted=True 결과를 주입해도 `[]`였다. README의 재검증/조정 요구는 transition 구현에 있고, checker가 모두 별도로 입증하지는 않는다.

다음 보완 후보: ACK false→true에서 이전 계정·검증·폐기·epoch 조건을 검사하고, admission에서 startup_ready를 검사하는 요구식을 추가한 뒤 각각의 guard만 제거한 음성 대조군으로 검증한다. 본 리뷰에서는 모델·불변식·시험을 바꾸지 않았다.

### 중간 R2 — 일부 안전 불변식은 실제 상태 변경보다 transition이 자체 보고한 effect에 의존한다

위치: `tools/sync_model/model.py:87–99, 158–180`, `tools/sync_model/README.md:27–28`.

guard helper를 호출하지 않는다는 설명은 맞다. 그러나 A/F와 owner·업로드 권한 검사는 대부분 admitted/committed 등의 자체 보고를 신뢰한다. `A → F` 뒤 row를 True로 잘못 바꾸되 committed=False로 반환하는 가상 결과는 검사 오류 `[]`였다. barrier 검사는 row 변화도 보는 반면 F 검사는 보지 않는다. 따라서 “별도 요구식”은 “상태 변화와 무관한 완전한 독립 oracle”을 뜻하지 않는다.

현재 세 mutant는 effect를 정확히 보고하므로 탐지 자체는 유효하다. 다만 effect와 상태의 일관성 또는 관측 가능한 상태 delta 검사가 없으면 다른 transition 회귀를 놓칠 수 있다. effect를 명세의 신뢰 관측값으로 가정한다면 그 한계를 명시하고, 아니라면 최소 일관성 검사를 보강할 필요가 있다.

### 낮음 R3 — crash/조정·사본 정리 대응표는 실제 실패 검증보다 강하게 읽힐 여지가 있다

위치: `tools/sync_model/model.py:111–130`, `tools/sync_model/README.md:13–14, 19–23, 66–75`, 제안서 `13.2–13.5`.

restart는 Durable 전체 보존을 가정하고 Volatile을 기본값으로 교체한다. aux_fail은 이후 L의 journal 기록만 막는다. reconcile은 aux_ok를 검사하지 않고 항상 journal 복제·startup_ready=True로 성공한다. 기존 journal 유실, 조정 실패, 원본 저장 실패, 부분 commit/rollback은 없다. restart는 권한과 aux_ok도 기본 True로 되돌리며 verified=False만 별도로 둔다. 이는 실제 자격·저장소 복구 검증이 아니다.

각 clean_*는 해당 ACK flag를 추가하면서 **어떤 그룹이든** 동일한 row·receipt를 지운다. 사본 그룹별 payload·실패·재유입은 없다. README가 신뢰 ACK와 생략 사항을 명시하므로 실제 erasure를 입증한다는 직접적인 허위 주장은 없지만, 대응표는 “ACK 집합 조건과 가정된 보존만 검증”으로 읽어야 한다. 제안서 13.5의 실패 주입 계획은 여전히 전부 NOT_RUN이다.

## A,A 반례의 의미와 음성 대조군

`management_requires_consent`는 보호를 제거하는 mutant가 아니라 **잘못된 추가 제한**을 넣는 mutant다(`model.py:79–80`). 첫 A는 성공하여 consent=False가 되고, 둘째 A는 관리 effect=False다. checker는 동의와 무관하게 verified owner+management_permission이면 관리가 허용되어야 한다고 요구한다(`181–184`). 따라서 `A → A`는 실제로 그 결함의 증거이며 단순 상태 멱등성 불일치만은 아니다. 상태 자체는 두 번째 A에서 달라지지 않을 수 있지만 관측된 허용 여부가 다르다. 모델에는 HTTP 응답이나 withdrawal command ID가 없어 실제 API 멱등 응답까지 입증하지는 않는다.

더 분명한 확인을 위해 최초 명령 `consent_off → A`, `consent_off → delete`, `consent_off → status`를 직접 실행했다. 정상 모델은 각각 관리 허용, mutant는 각각 거부하고 같은 관리 불변식 위반을 냈다. 따라서 재철회에만 한정된 결함이 아니다. 동의 없는 상태에 switch_other/unverify/management_permission_off를 각각 적용한 9개 관리 조합은 정상 모델에서 모두 거부되었다. 업로드 동의 면제는 owner·관리 권한 면제가 아니다.

`missing_fence`는 commit의 F 조건만 우회한다(`93`). `admit_old → A → F → commit_old`를 직접 재생해 F 불변식 위반을 확인했다. `missing_barrier`는 admission과 commit의 barrier 조건을 우회한다(`84–86, 94`). `admit_old → delete → commit_old` 재생으로 삭제 ID 재생성 위반을 확인했다. 이 trace는 commit 보호의 필요성을 보여주며 admission 우회까지 별도로 필수임을 증명하지는 않는다. op 중복·erased 검사는 남아 있으므로 모든 보호를 제거한 mutant도 아니다.

## 주장과 실제 커버리지

| 주장 | 실제 모델·검사 | 판정과 한계 |
|---|---|---|
| 독립 불변식 | violations는 helper를 재호출하지 않고 이전/이후 상태와 effect를 검사 | 부분 충족. R1/R2의 미검사 조건·effect 신뢰가 남음 |
| 상태 중복 제거 | frozen State의 Durable 16개, Volatile 7개 필드 전체가 기본 equality/hash에 포함(`model.py:15–50`); frozenset 불변 | 현재 모델의 미래 동작에 쓰는 상태 필드 누락 없음. effect는 해당 edge에서 즉시 검사되며 미래 상태 입력이 아니어서 dedup key에서 빠져도 됨. 실제 생략된 generation/command 등은 dedup 결함과 구분 |
| 깊이·상태 상한 | FIFO, enqueue 시 seen 등록, depth 이상 확장 안 함(`explore.py:19–43`) | states는 초기/깊이 경계 상태 포함. depth는 설정 상한이고 실제 최대 도달 깊이 필드가 아님 |
| 전이 집계 | 각 확장 상태의 EVENTS 30개 실행마다 +1; 위반 검사 후 dedup | no-op·거부·중복 edge 포함. 고유 edge 수 아님. 첫 위반 edge의 after는 seen에 넣기 전 반환하므로 오류 결과 states는 그 after를 반드시 포함하지 않음 |
| truncation | 새 상태를 상한 때문에 버릴 때 True; 나머지 retained state 탐색은 계속 | False는 state-limit 미잘림만 뜻하며 깊이 제한 없음/전체 증명이 아님. CLI는 errors만 exit code에 반영(`49`); 향후 상한 변경 시 truncated=True여도 성공 종료 가능. 현재 test는 truncated도 별도 검사 |
| 최단 반례 | 단위 비용 이벤트·FIFO·상태 전체 dedup·각 edge 즉시 검사 | truncation 없는 BFS의 첫 오류는 해당 mutant/초기 상태/이벤트 집합에서 최소 이벤트 길이. 같은 길이 여러 반례 중 고정 이벤트 순서가 A,A를 먼저 선택. 실제 시스템 최단/모든 종류 위반별 최단이라는 뜻 아님 |
| A/F/drain/D | admission 접수 차단과 F 후 commit 차단을 분리; drain은 tickets 제거; D는 6개 clean ACK 전부 요구 | 단일 공유 gate의 원자 직렬화를 가정. D의 물리 사본 제거·메시지 drain은 신뢰 입력. 초기 상태에서 A/F/drain+6 clean+D가 10단계, admit/commit으로 채운 상태부터 D까지는 최소 12단계라 정상 깊이 10 탐색의 삭제 커버리지와 구분. 별도 unittest에 채워진 경로가 있음(`test_model.py:27–35`), 이번 실행 안 함 |
| 로컬 삭제·undo | L은 marker/retired/epoch와 local_deleted 설정, undo는 local_deleted만 복원 | marker 단조 보존과 재admission 차단. L만으로 server row 삭제는 하지 않으며 보상 삭제 전송·COUNT·원본/보조 두 DB transaction은 미모델링 |
| crash/restart | 이벤트 사이 restart; Durable 그대로, verified/startup gate 꺼짐 | 단계 내부 crash·디스크·원장 유실·복구 정리·rollback·실패한 reconcile은 없음(R3) |
| stale ACK·계정 전환 | 고정 owner/other, captured epoch=0 추상 ACK, retired/barrier로 활성화 방지 | generation/operation/revision/ACK envelope 없음. 계정 전환은 epoch를 증가시키지 않아 owner→other→owner 뒤 옛 ACK를 구별하지 못함. 제안서 7절의 계정 변경 epoch 전부를 검증하지 않음; R1도 해당 |
| 관리와 업로드 권한 | 업로드 consent+upload_permission, 관리 verified owner+management_permission | 동의 없는 최초 관리·재관리 차이를 직접 확인. status는 허용 effect뿐이며 응답 shape/정보 비노출은 검증하지 않음 |
| erased receipt | receipt/erased op 집합과 metadata bool, barrier가 재create 차단 | 동일/변조 payload 비교, 정확한 410/404, receipt 원문 제거·보유 수명 없음 |
| 격리·원자성 | import는 dataclasses/collections/unittest와 로컬 model/explore뿐; 파일 전체 정적 확인 | 앱 import·network·실저장·환경 읽기·비밀·외부 패키지 없음. Python import의 소스 읽기와 stdout은 있음. atomic step은 명시적 가정(`model.py:76`, README:23); DB transaction/locks 증거 아님 |
| 문서의 증명/준비도 | 제안서 12절, README:49, 64–77 | 유한 검증·NOT_RUN·활성화 BLOCKED를 명시. exhaustive proof/실제-data 준비 완료 주장 없음. 기존 실행 숫자는 이번 독립 실행 결과로 승격하지 않음 |

## 가정과 생략

한 계정 소유자와 다른 계정 한 개, 단일 generation·sync ID, 두 operation ID, row 존재 bool만 모델링한다. old/new는 generation이 아니라 operation 이름이다. metadata 날짜·필드 검증, 신규 선택 창·binding, 여러 기록/기기/세대, command ID 충돌, revision CAS, Core/제품별 inbox/outbox·재전송/역순 메시지, 늦은 Open/새 세대 ACK, 재동의 활성화는 없다. consent_on은 입력 bool만 바꾸고 retired를 해제하지 않는다.

boolean 자격의 진실성, 내구 상태 보존, 모든 commit과 F의 공유 직렬화, clean ACK의 정직성을 가정한다. 실제 인증·scope 만료·DB 잠금/격리·deadlock·백업/WAL·로그 sink·물리 erasure·Flutter COUNT·migration/rollback·원장 복원은 NOT_RUN 또는 미모델링이다. liveness·공정 scheduling·partition 완료 시한도 보장하지 않는다.

## 증거 분리와 실제 실행

### USER-REPORTED — 이번 리뷰에서 독립 재실행하지 않은 결과

- unittest discovery: 11 tests passed.
- 정상 탐색: states=51759, transitions=1043610, depth=10, state_limit=60000, truncated=False, no errors.
- missing_fence: admit_old, A, F, commit_old.
- missing_barrier: admit_old, delete, commit_old.
- management_requires_consent: A, A.

README:44–62에 수치·반례가 기재되어 있다. 이 리뷰는 해당 탐색 규모·최단성의 실행 재현을 주장하지 않는다. README의 과거 pip/whitespace PASS 역시 이번 실행과 별개다.

### 실제 실행 — 집중 검사만 수행

Python 3.14.8을 ` .\.venv\Scripts\python.exe -I -B --version`으로 확인했다. 전체 unittest discovery, 정상/음성 대조군 전체 BFS, 제품 회귀, pip check는 **NOT_RUN**이다. 아래 PowerShell stdin 명령을 실행했다(종료 코드 0). 모델 파일을 수정하지 않고 표준 라이브러리의 replace로 검사기 입력을 일시 구성했다. `trace`는 결과를 출력하며 assertion 기반 시험 suite가 아니다. 출력에서 세 직접 반례의 관련 위반, 관리 허용/거부, oracle의 빈 오류 목록을 확인했다.

```powershell
@'
import sys
from dataclasses import replace
sys.path.insert(0, 'tools/sync_model')
from model import State, Effect, step, violations
from explore import explore

def trace(events, fault=None):
    s = State()
    for event in events:
        a, e = step(s, event, test_fault=fault)
        errors = violations(s, event, a, e)
        print(f'{fault or "normal"} {event}: management={e.management}, errors={errors}')
        s = a
    return s

for fault, events in [('missing_fence', ('admit_old','A','F','commit_old')), ('missing_barrier', ('admit_old','delete','commit_old')), ('management_requires_consent', ('A','A'))]:
    trace(events, fault)
for event in ('A','delete','status'):
    trace(('consent_off',event), 'management_requires_consent')
    trace(('consent_off',event))
for restriction in ('switch_other','unverify','management_permission_off'):
    for event in ('A','delete','status'):
        trace(('consent_off',restriction,event))
# Deliberately fabricated transition outcomes test the checker only, not model changes.
s = trace(('admit_old','commit_old','switch_other'))
a = replace(s, volatile=replace(s.volatile, client_active=True))
print('ORACLE wrong-owner ACK:', violations(s,'ack',a,Effect()))
s = State(); s = replace(s, volatile=replace(s.volatile,startup_ready=False))
a = replace(s, durable=replace(s.durable,tickets=frozenset({'old'})))
print('ORACLE admission before reconciliation:', violations(s,'admit_old',a,Effect(admitted=True)))
s = trace(('A','F'))
a = replace(s,durable=replace(s.durable,row=True))
print('ORACLE fenced row write without committed effect:', violations(s,'commit_old',a,Effect()))
print('BOUNDS', explore(depth=0,state_limit=1), explore(depth=1,state_limit=1))
'@ | .\.venv\Scripts\python.exe -I -B -
```

경계 검사 결과는 각각 `(states=1, transitions=0, depth=0, state_limit=1, truncated=False)`와 `(states=1, transitions=30, depth=1, state_limit=1, truncated=True)`였다. 설정 상한과 잘림 flag 동작을 소규모로 확인했으며 정상 탐색 수치는 재검증하지 않았다.

`git diff --check`: **PASS**, 종료 코드 0. untracked 파일을 검사하지 않는 한계를 보완하여 아래 별도 검사를 실행: **PASS**, 6개 파일, issues=[], 종료 코드 0.

```powershell
@'
from pathlib import Path
paths = [Path('docs/design/nn-real-completion-sync-proposal.md'),
         *sorted(Path('tools/sync_model').glob('*')),
         Path('docs/reviews/2026-10-31-real-sync-model-review.md')]
bad = []
for p in paths:
    if not p.is_file():
        continue
    t = p.read_text(encoding='utf-8')
    if not t.endswith('\n') or t.endswith('\n\n'):
        bad.append((str(p), 'EOF'))
    for n, line in enumerate(t.splitlines(), 1):
        if line.rstrip() != line or '\t' in line:
            bad.append((str(p), n))
print('files=', len(paths), 'issues=', bad)
raise SystemExit(bool(bad))
'@ | .\.venv\Scripts\python.exe -I -B -
git diff --check
```

## 향후 design/model commit에 포함할 후보 파일

아래는 명시적인 후보 목록이며 stage/commit 승인이나 실행을 뜻하지 않는다. 기존 미추적 파일의 내용을 자동 승인하지 않는다.

- `docs/design/nn-real-completion-sync-proposal.md`
- `tools/sync_model/model.py`
- `tools/sync_model/explore.py`
- `tools/sync_model/test_model.py`
- `tools/sync_model/README.md`
- `docs/reviews/2026-10-31-real-sync-model-review.md`

## 다음 최소 단계

별도 승인된 모델 보정 작업에서 먼저 R1의 wrong-owner ACK와 startup gate에 대한 검사기 단위 fixture 및 단일 guard 제거 mutant를 추가한다. 현재 불변식을 약화하지 말고 해당 조건을 독립 검사하도록 보강한 다음, 해당 짧은 trace만 실행해 검출을 확인한다. A,A 설명에는 consent_off→delete/status의 최초 관리 반례를 병기하면 의도가 명확하다. 이후 R2 effect 일관성과 R3의 가정 표현을 보정한다. 생산 구현·DB·실제 수집 단계로 확대하지 않는다.

## 2026-10-31 R1/R2 ?? ?? (?? ?? ?? ??)

??? tools/sync_model/model.py, test_model.py, README.md? ? ??? ?? ????.
?? untracked ??? ????. app/Flutter/CI/???/DB/??/???/Git ???
???? ???. ?? ????? ??????????? ??? ??? staging/commit/
push/???? ???? ???.

R1: ACK ???? ?? owner/verified/epoch=0/receipt/retired/barrier? ?? ????
startup_ready=False?? ? ticket? ????. wrong-owner, unverified, retired,
barrier, epoch-only, receipt ?? fixture? Effect()? ????? ????.
R2: ticket/receipt/row/client ???? before/after delta? ????. false effect?
A/F/??/owner/??/startup ??? ?? ? ??. admission/commit effect?
?? ticket/receipt delta ???? ????. ?? ?? ??? owner/?? ??? ????.
status/metadata? ??? ?? ??? ?? effect? ?????? ??? ????.
?? fence?????????? ?? ?? ???? ???? ?? admission ??? ????.

### ?? ??: PASS

Python 3.14.8. ?? unittest 14? PASS, skip=0. ?? ?? ?? ?? ?? ?? 0.

~~~powershell
.\.venv\Scripts\python.exe -I -B --version
.\.venv\Scripts\python.exe -I -B -m unittest discover -s tools/sync_model -v
.\.venv\Scripts\python.exe -I -B -c "import sys,runpy; sys.path.insert(0,'tools/sync_model'); runpy.run_path('tools/sync_model/explore.py',run_name='__main__')"
.\.venv\Scripts\python.exe -I -B -m pip check
git diff --check
~~~

?? BFS: unique states=51,759, transitions=1,043,610, depth=10,
state_limit=60,000, truncated=False, errors=(). ?? ?? ?? ??, ? ?? ?? ???.
no-op/??/?? ?? ??. ?? ??? ???.
?? BFS? ?? depth=5, state_limit=60000, truncated=False, ? ???? ????.

| test_fault | unique states | transitions | trace | ?? |
|---|---:|---:|---|---|
| missing_startup_reconciliation | 346 | 2101 | restart ? switch_owner ? admit_old | startup reconciliation required before admission |
| missing_fence | 487 | 3213 | admit_old ? A ? F ? commit_old | F blocks retired-generation commit |
| missing_barrier | 46 | 121 | delete ? admit_old | deleted sync ID cannot be recreated |
| management_requires_consent | 36 | 95 | A ? A | management is consent-independent and permission-restricted |

??? ?? commit ???? ?? admission ??? ?? ????.
missing_ack_epoch? epoch ??? ????. ?? prefix admit_old ? commit_old ?
????? epoch=1, retired=False? ???? ack? ???? ??????
stale ACK requires verified owner and captured epoch ??? ????.
?? fixture edge? BFS unique states/transition/bounds/truncation ??? ?? ????.
?? ?? ??? epoch=1? retired=True? ???? ?? epoch-only mutant? reachable
BFS ???? ???? ???. ?? ?? epoch ??? ??? ??????.

?? suite? ?? ?? ?? ??? 3? ? ??? 2? ?? 14? ? 1? FAIL???.
??? ???? ?? ???? ??? ????. -I -B explore.py ?? ??? sibling
import ???? ????. ? ??? ?? sys.path+runpy ???? ?? ????
?????. ?? suite? ??? PASS?.

### ??? ??

README? restart? ??? ?? Durable ?? ??? Volatile ???? ???? ????.
aux_fail? L? journal ??? ?? reconcile? aux_ok? ???? ????.
?? ?? crash, ?? ?? ??, journal ??, ?? ??, ?? commit/rollback? ??.
clean_*? ?? ACK? ?? row/receipt ???? ??? payload/??/???/?? ??
??? ???. R3 ?? ??? ?? ???. ?? erasure?????? ??? NOT_RUN.
?? ??? production safety proof? ??? ??-data ???? ?? BLOCKED?.

git diff --check: PASS. untracked ??? ?? whitespace ??: files=4, issues=[], PASS.
pip check: No broken requirements found. ?? ??? ??? ??:

~~~powershell
@'
from pathlib import Path
paths = [Path('tools/sync_model/model.py'), Path('tools/sync_model/test_model.py'),
         Path('tools/sync_model/README.md'), Path('docs/reviews/2026-10-31-real-sync-model-review.md')]
bad = []
for p in paths:
    t = p.read_text(encoding='utf-8')
    if not t.endswith('\n') or t.endswith('\n\n'):
        bad.append((str(p), 'EOF'))
    for n, line in enumerate(t.splitlines(), 1):
        if line.rstrip() != line or '\t' in line:
            bad.append((str(p), n))
print('files=', len(paths), 'issues=', bad)
raise SystemExit(bool(bad))
'@ | .\.venv\Scripts\python.exe -I -B -
~~~
