---
name: cafe-server
description: CafeBackend EC2/RDS 서버 접속 및 배포 워크플로우. "서버 접속", "EC2 접속", "RDS 조회/쿼리", "배포", "deploy", "dev/prod 서버 확인", "마이그레이션", "migration" 등을 요청할 때 사용.
---

# Cafe Server (EC2 / RDS 접속 & 배포)

CafeBackend는 EC2 위에서 Docker Compose로 운영되고, RDS는 EC2를 경유해야만 접근 가능하다(로컬에서 직접 접근 불가).

## 접속 정보

- EC2 Host: `admin` (SSH config alias)
  - HostName: `16.184.58.200`
  - User: `ubuntu`
  - Port: `22`
  - IdentityFile: `/Users/sujinhan/CafeManager/default_keypair.pem`
- 서버 프로젝트 경로: `/home/ubuntu/CafeBackend`
- RDS: `cafeplatform.ctu6ysesocm2.ap-northeast-2.rds.amazonaws.com:3306` — **EC2 안에서만 접근 가능**, 로컬에서 직접 접속 불가

## EC2 접속

```bash
ssh admin
```

SSH config에 `admin` 호스트가 없다면 아래로 직접 접속:

```bash
ssh -i /Users/sujinhan/CafeManager/default_keypair.pem ubuntu@16.184.58.200
```

## RDS 접근 (EC2 경유)

로컬에서 RDS로 직접 연결할 수 없으므로, EC2를 통해서만 조회/작업한다. 두 가지 방법:

### 방법 A — EC2에 SSH로 들어가서 그 안에서 직접 쿼리
```bash
ssh admin
# EC2 안에서
mysql -h cafeplatform.ctu6ysesocm2.ap-northeast-2.rds.amazonaws.com -P 3306 -u <user> -p
```

### 방법 B — SSH 터널링으로 로컬 포트를 RDS에 연결
```bash
ssh -i /Users/sujinhan/CafeManager/default_keypair.pem -L 13306:cafeplatform.ctu6ysesocm2.ap-northeast-2.rds.amazonaws.com:3306 -N -f ubuntu@16.184.58.200
# 이후 로컬에서 127.0.0.1:13306 으로 접속
mysql -h 127.0.0.1 -P 13306 -u <user> -p
```
터널 종료 시 해당 ssh 프로세스를 kill한다.

## 배포 워크플로우

- 배포는 GitHub Actions(`.github/workflows/deploy.yml`)가 자동 수행한다.
  - `development` 브랜치에 push → dev 서버 자동 배포
  - `main` 브랜치에 push → prod 서버 자동 배포
  - **PR 없이 브랜치에 직접 push하는 것만으로 배포된다.** PR 생성/머지 절차는 필요 없음.
- 수동 배포가 필요하면 EC2 안에서 직접 스크립트 실행:
  ```bash
  ssh admin
  cd /home/ubuntu/CafeBackend
  ./deploy-dev.sh   # 또는 ./deploy-prod.sh
  ```
- 배포 상태/헬스체크 확인:
  ```bash
  curl -f http://127.0.0.1:8001/dev/health   # EC2 내부에서 dev 확인
  ```

## DB 마이그레이션 (migration_history 기반)

`migrations/` 디렉토리에 `V{번호}__{설명}.up.sql` / `.down.sql` 형식으로 작성한다 (`scripts/run_migrations.py` 참고). 실행 시 `migration_history` 테이블에 자동으로 기록되며, 이미 적용된 version은 재실행되지 않는다.

**개발 흐름: 마이그레이션 실행이 코드 배포보다 먼저다.**
1. `migrations/V{n}__{설명}.up.sql`, `.down.sql` 작성
2. `run_migrations.py` 실행 → DB 스키마 변경 + `migration_history`에 기록 (실행 위치는 로컬이든 EC2 컨테이너든 무관, RDS에 붙을 수 있으면 됨)
   ```bash
   # EC2 컨테이너에서 실행하는 경우
   ssh admin && cd /home/ubuntu/CafeBackend
   docker compose exec -T app-dev python scripts/run_migrations.py   # prod는 해당 컨테이너에서
   ```
3. 마이그레이션 파일을 포함해 코드 커밋 → 브랜치 push → GitHub Actions 자동 배포

배포 파이프라인은 마이그레이션을 실행하지 않는다 — 스키마 변경은 이 시점 이전에 이미 끝나 있어야 한다.

DB 스키마 변경은 전역 CLAUDE.md의 "Database" 제약에 따라 실행 전 반드시 사용자 확인을 받는다.

## 주의사항

- `/Users/sujinhan/CafeManager/default_keypair.pem` 키 파일 권한은 `chmod 400`이어야 한다.
- RDS 자격 증명(비밀번호 등)은 절대 로그나 커밋에 노출하지 않는다.
- 이 프로젝트는 브랜치 push = 배포이므로, push 전 반드시 로컬 검증을 마치고 사용자 승인을 받은 뒤에만 push한다(전역 CLAUDE.md의 Approval-First 원칙 적용).
