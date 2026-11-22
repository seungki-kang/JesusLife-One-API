# ChurchOS Supabase 개발 HTTP 검증

기존 `app.auth0_pc:app`, `.env.auth0-pc`, 로컬 Core DB와 제품 저장 경로를
변경하지 않는다. 별도 명령을 실행하고 별도 파일의 활성화 값이 정확히 `1`인
경우에만 개발 Supabase에 연결한다. 운영 적용·배포·커밋·푸시는 포함하지 않는다.

## Windows 입력 위치

프로젝트 루트에서 다음 명령으로 보호된 폴더와 설정을 한 번 준비한다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.churchos_supabase_dev prepare
```

`D:\CHGO-VibeCodeing\JesusLife-One-API\.env.churchos-supabase-dev\settings.env`를
Windows 편집기로 열어 `POOLER_HOST`와 `PROJECT_REF`를 개발 프로젝트
`jesuslife-api-dev`의 Connect → Session pooler 표시값으로 채운다.
프로젝트 이름만으로 원격 프로젝트의 신원이 증명되지는 않으므로 참조값을 반드시
개발 대시보드에서 확인한다. `PROJECT_NAME`은 유지한다.
DB 이름 `postgres`, 포트 `5432`, 로그인 역할 `jl_churchos_dev_login`은 코드에서
고정하며 pooler 사용자명에는 프로젝트 참조값을 붙인다.

Database Settings → SSL Configuration에서 받은 인증서를 같은 폴더의
`project-ca.crt`로 저장한다. 다른 절대 경로는 `SSLROOTCERT`에 지정할 수 있다.
`JESUSLIFE_SUPABASE_DEV_ENABLED=1`로 명시적으로 켠다. 비밀번호는 파일에 쓰지 않는다.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.churchos_supabase_dev probe
.\.venv\Scripts\python.exe -B -m scripts.churchos_supabase_dev serve
```

각 명령의 Windows 터미널 숨김 입력 프롬프트에서 전용 읽기 계정의 비밀번호를
입력한다. 인자·환경 변수·DSN에 비밀번호를 넣지 않는다. 명령은 `PG*` 환경 변수가
있으면 거부한다. 인증서 오류가 나면 중단하며 TLS 검증을 완화하지 않는다.
서버는 `127.0.0.1:8000`에만 바인딩하고 access log를 비활성화한다.
포트가 사용 중이면 기존 서버를 임의 종료하지 말고 소유 프로세스를 확인한다.

연결할 때 현재 역할, superuser/BYPASSRLS 부재, 테이블 쓰기 권한 부재,
SELECT 권한, ENABLE/FORCE RLS, 읽기 전용 트랜잭션을 검사한다.
제품 조회는 기존 트랜잭션 로컬 계정·교회 컨텍스트를 사용한다.
자동 재시도는 없으며 연결 제한은 5초다.

## 브라우저와 관리자 순서

브라우저는 `http://127.0.0.1:8000/dev/churchos/`를 사용한다. 각 로그인 후
기존 PC 화면으로 돌아오면 같은 탭에서 위 검증 주소를 다시 연다.
실제 계정 식별자·토큰·세션·소속 응답 본문은 검증 화면에 표시하지 않는다.

1. 미로그인 요청 버튼으로 실제 HTTP 401을 확인한다.
2. 기본 로그인 링크에서 기존에 검증한 테스트 계정으로 로그인한다.
3. 검증 화면으로 돌아와 테스트 계정 확인 버튼을 누른다. 서버의 검증된
   세션에서 계정을 가져와 새 교회 UUID 한 개와 다른 교회 UUID를 생성한다.
4. 같은 보호 폴더의 `insert.sql`을 Windows 편집기로 열어 개발 프로젝트의
   SQL Editor에서 관리자 역할로 실행한다. 내용을 채팅·로그에 붙이지 않는다.
   관리자 RLS 우회 권한이 없으면 중단한다. 임시 정책을 만들지 않는다.
5. 기본 로그인 소속 조회 버튼으로 HTTP 403을 확인한다.
6. 앱 로그아웃 버튼을 누르고 같은 테스트 계정으로 ChurchOS 로그인한다.
7. 검증 화면에서 자기 소속 조회 200, 다른 교회 조회 403을 확인한다.
   결과는 기본 로그인과 동일 계정·서로 다른 쿠키 세션일 때만 집계한다.
8. HTTP 결과 버튼으로 네 상태를 확인한다. 다른 계정의 요청은 성공 증거로
   집계하지 않는다. 화면의 결과에는 SQL 정리가 확인되지 않았음이 표시된다.
9. 성공·실패와 무관하게 SQL Editor에서 같은 폴더의 `cleanup.sql`을 관리자
   역할로 실행한다. `synthetic_rows_absent=true`,
   `temporary_verification_policies=0`을 확인한다. 이 실행은 정책을 생성하지
   않으므로 기존 RLS 정책을 삭제하지 않는다. SQL 결과 확인 전 정리를 PASS로
   보고하지 않는다.
10. 서버를 Ctrl+C로 종료하고 활성화 값을 `0`으로 돌린다. 기존 PC 앱은 기존
    명령으로 실행한다. SQL 파일에는 계정 UUID가 있으므로 보호를 유지한다.
    새 실행은 기존 SQL 파일이 있으면 거부한다. 정리 확인 후에만 별도로 보관한다.

SQL 삽입은 한 트랜잭션에서 활성·관리 권한 없는 한 행만 수행한다. 삭제는
이번 계정·교회의 합성 행으로 한정하며 예상 밖 자료가 있으면 롤백한다.
관리자 자격증명은 FastAPI에 제공하지 않는다. 프로세스가 중단되어도
`cleanup.sql`이 남아 관리자 복구가 가능하다. 실제 HTTP 검증과 관리자 SQL 실행은
사용자 브라우저/SQL Editor 단계가 필요하며 오프라인 테스트 결과로 대체하지 않는다.

공식 참고: [Supabase 연결과 인증서](https://supabase.com/docs/guides/database/psql),
[Session pooler와 사용자명](https://supabase.com/docs/guides/database/connecting-to-postgres).
