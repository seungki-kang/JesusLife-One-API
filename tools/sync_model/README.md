# 독립 완료 동기화 실행 명세 검토 기록

2026-10-31. 설계 보조용이며 제품 구현이 아니다. 실제-data 활성화는 **BLOCKED**이고
권한·보유·스키마 결정은 **AUTHOR_REVIEW_REQUIRED**다. 모델 성공으로 해제하지 않는다.
기존 앱·API·테스트·CI·offline runner와 연결하지 않는다. 의존성은 Python 표준 라이브러리뿐이다.

## 모델과 제안서 대응

| 모델 상태·이벤트 | 제안서 절 | 의미 |
|---|---|---|
| `admit_old/new`, `commit_old/new`, `A` | 7, 13.3 | admission과 철회 접수 직렬화; 이미 발급한 ticket은 F 전 commit 가능 |
| `F`, `drain` | 7, 13.3 | 제품 fence와 미사용 ticket 폐기; drain 자체는 삭제 완료가 아님 |
| `clean_*`, `D` | 13.4.1 | 선언한 6개 live 사본 그룹 ACK를 모두 받은 뒤에만 완료 |
| `L`, `aux_fail`, `restart`, `reconcile`, `undo` | 13.2 | 원본 표식이 권위 있음; 보조 journal 실패·재시작·undo에도 폐기 증거 유지 |
| `delete`, `replay` | 5, 6, 13.4.2 | 활성 세대의 단건 장벽, erased receipt; 옛/새 operation ID 모두 재생성 차단 |
| `ack`, 계정 전환, `unverify` | 4, 7, 13.2–13.3 | 지연 업로드 ACK는 소유 계정·폐기·epoch 조건 충족 때만 적용 |
| 동의·권한 이벤트, `status` | 4, 5, 7, 13.5 | 업로드는 유효 동의+업로드 권한; 철회·삭제·상태 조정은 동의와 독립인 본인 관리 권한 |

`Durable`은 내구성이 있다고 **가정한** 상태이고 `Volatile`은 세션·권한·보조 저장소 가용성·시작 gate·
클라이언트 표시 상태다. restart는 Durable을 보존하고 Volatile을 초기화하며 재검증/조정을 요구한다.
합성 owner/other 계정, 단일 generation·sync ID, old/new operation ID만 사용한다.
metadata와 성공 receipt 본문은 존재 여부로 추상화한다. 실제 원문·기록은 없다.
각 `step`의 내구 변경은 원자 commit 가정이며 저장 장치의 증거가 아니다.
이미 admission된 서버 commit은 계정 전환 뒤에도 F 전 실행될 수 있다. 이것은 다른 계정의
작업 재개 권한이 아니다. 재개 admission·관리·조회는 같은 검증 계정만 허용한다.

`violations`는 transition guard를 호출하지 않고 별도 요구식으로 전이를 검사한다.
관리 명령은 허용 여부를 관측 가능한 effect로 반환하여, 동의 없이 허용해야 하는 동작도 검사한다.
`consent_on`은 유효 동의 입력의 추상값일 뿐 새 세대 활성화 이벤트가 아니다. 폐기 증거를 지우지 않는다.
`delete`는 서버 단건 삭제이고 `L`은 로컬 삭제다. 서버 삭제만으로 로컬 완료를 지우지 않는다.

## 실행과 실제 결과

저장소 루트 PowerShell에서 실행한다. 파일·네트워크 영속화나 환경 설정을 사용하지 않는다.

```powershell
.\.venv\Scripts\python.exe -I -B -m unittest discover -s tools/sync_model -v
.\.venv\Scripts\python.exe -I -B -c "import sys,runpy; sys.path.insert(0,'tools/sync_model'); runpy.run_path('tools/sync_model/explore.py',run_name='__main__')"
git diff --check
.\.venv\Scripts\python.exe -B -m pip check
.\.venv\Scripts\python.exe -B -c "from pathlib import Path; files = [Path('docs/design/nn-real-completion-sync-proposal.md'), *sorted(Path('tools/sync_model').glob('*'))]; bad = [(str(p), 'whitespace') for p in files if p.is_file() and ((t := p.read_text(encoding='utf-8')).endswith(chr(10)) is False or t.endswith(chr(10)*2) or any(line.rstrip() != line or chr(9) in line for line in t.splitlines()))]; print('files=', len(files), 'issues=', bad); raise SystemExit(bool(bad))"
```

- unittest: **11개 PASS**, skip 없음. 이 수는 탐색 상태 수와 별개다.
- 정상 모델 BFS: 깊이 **10**, 최대 고유 상태 **60,000**, 실제 고유 상태 **51,759**,
  검사 전이 **1,043,610**, state-limit 잘림 없음, 반례 없음.
- 깊이 경계의 상태도 방문 상태에 포함하지만 그 상태의 후속 전이는 검사하지 않는다.
  no-op/거부/중복 전이도 검사 전이 수에 포함한다. FIFO와 고정 이벤트 순서로 결정적이다.
  깊이 경계 때문에 탐색은 항상 유한하며 전체 증명이 아니다. D 도달은 별도 unittest에서도 확인한다.
- `git diff --check`와 미추적 파일 별도 whitespace 검사: PASS (최종 작업 보고와 함께 확인).
- 별도 whitespace 검사: 제안서 포함 5개 파일, trailing whitespace·탭·EOF 문제 0개.
  `pip check`: PASS (`No broken requirements found.`). 위 검증 명령은 모두 종료 코드 0이다.

음성 대조군은 `test_fault` 인자를 테스트에서만 전달한다. CLI는 정상 모델만 실행한다.
각 대조군은 깊이 5, 최대 상태 60,000으로 탐색하고 첫 위반에서 중단한다.
아래 trace는 잘림 없는 BFS가 찾은 **해당 추상 모델의 최단 반례**다. 불변식은 변경하지 않았다.

| 의도적 결함 | 고유 상태 | 검사 전이 | 최단 반례 | 탐지한 위반 |
|---|---:|---:|---|---|
| F 검사 제거 | 487 | 3,213 | `admit_old → A → F → commit_old` | F 뒤 폐기 세대 commit |
| sync ID 장벽 검사 제거 | 117 | 483 | `admit_old → delete → commit_old` | 삭제 ID 재생성 |
| 관리에도 업로드 동의 요구 | 36 | 95 | `A → A` | 철회로 동의가 사라진 뒤 멱등 철회 관리 재개 거부 |

## 가정·생략·NOT_RUN

실제 SQLite/MySQL transaction, commit 실패/rollback, 잠금과 격리, 여러 process/worker/instance,
실제 디스크 내구성, 원본/보조 저장소 조정, authentication·토큰·scope 검증은 **NOT_RUN**이다.
boolean 자격 값이 검증 결과를 정확히 전달하고 모든 제품 commit이 하나의 F를 공유한다고 가정한다.
실제 outbox/inbox 전달, command ID·revision CAS, backoff·timeout, 정책 버전, 여러 세대/기기/기록,
Flutter COUNT·복구 보관함·구버전 migration 및 실제 인증 세션 복원은 모델링하지 않는다.

live inventory는 제안서의 사본 그룹을 6개 ACK로 축약한다. ACK는 해당 그룹의 전체 제거·최종 sweep과
진행 메시지 처리가 확인되었다는 신뢰 입력이다. 실제 캐시·복제본·로그·메시지를 검사하지 않는다.
물리적 erasure, WAL·backup 만료, backup restoration과 최신 장벽 선적용은 **NOT_RUN**이다.
원장 유실·손상 복구나 실제 외부 서비스 안전성을 입증하지 않는다. 모든 계정·ID·metadata는 합성 추상값이다.
무기한 실패·partition 아래 완료 liveness, 공정 scheduling, 완료 시한은 보장하지 않는다.
이 모델과 선택 trace의 성공은 위 생략 사항, 제품 회귀 suite 또는 실제-data 활성화 승인을 대체하지 않는다.

## 2026-10-31 R1/R2 ?? ??

`missing_ack_epoch`? epoch guard? ????. `admit_old ? commit_old` ?
????? epoch=1, retired=False? ??? ???? `ack`? ???? ??????
`stale ACK requires verified owner and captured epoch` ??? ????.
? fixture? ?? ?? ??? ???. ?? ???? epoch=1? ?? retired=True?
???? ?? epoch-only mutant? ?? ?? ?? BFS ???? ???? ???.
wrong-owner?unverified?retired?barrier?receipt ??? effect ?? ??? ???? ??? ????.
startup ???? admission? startup ??? ???? ?? ?? ?? BFS?? ????.
?? commit ?? ?? `admit_old ? delete ? commit_old`? ??? ?? ????.

restart? ??? ???? Durable ?? ??, Volatile ??? ??? ????.
???aux_ok? ?? True? ???? verified/startup_ready? False?.
aux_fail? ?? L? journal ??? ???. reconcile? aux_ok? ???? ??
marker? journal? ???? gate? ??. journal ????? ????? commit?rollback?
?? ?? ????? ?? crash? ????? ???.
? clean ???? ?? ACK? ????? ?? row/receipt? ???. ??? payload,
????????? ??? ??. D ??? ?? ACK ?? ??? ???.
? ??? crash/cleanup ??? ???? ???. ??-data ???? ?? **BLOCKED**?.
