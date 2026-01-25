# 배포 가이드

이 문서는 운영 서버, 개발 서버, 웹페이지를 각각 독립적으로 배포하는 방법을 설명합니다.

## 📋 목차

1. [개요](#개요)
2. [운영 서버 배포](#운영-서버-배포)
3. [개발 서버 배포](#개발-서버-배포)
4. [웹페이지 배포](#웹페이지-배포)
5. [문제 해결](#문제-해결)

---

## 개요

### 서버 구성

- **운영 서버 (Production)**: Blue-Green 배포 방식으로 무중단 배포
  - 포트: 8000 (green), 8002 (blue)
  - URL: `https://www.502company.com/prod/`
  - 환경 변수: `.env.prod`

- **개발 서버 (Development)**: 단일 컨테이너 배포
  - 포트: 8001
  - URL: `https://www.502company.com/dev/`
  - 환경 변수: `.env.dev`

- **웹페이지 (Django)**: Gunicorn으로 실행
  - 포트: 8005
  - URL: `https://www.502company.com/`
  - 프로젝트: `/home/ubuntu/Manager`

### 배포 스크립트 위치

```
/home/ubuntu/CafeBackend/deploy-prod.sh    # 운영 서버 배포
/home/ubuntu/CafeBackend/deploy-dev.sh     # 개발 서버 배포
/home/ubuntu/Manager/deploy-web.sh         # 웹페이지 배포
```

---

## 운영 서버 배포

### 배포 방법

```bash
cd /home/ubuntu/CafeBackend
./deploy-prod.sh
```

### 배포 프로세스

1. **현재 활성 환경 감지** (green 또는 blue)
2. **새 환경 빌드 및 시작** (비활성 환경 사용)
3. **Health check 대기** (최대 120초)
4. **Nginx 설정 업데이트** (새 포트를 기본으로 변경)
5. **트래픽 전환 대기** (10초)
6. **기존 환경 중지**

### 특징

- ✅ **무중단 배포**: Blue-Green 방식으로 서비스 중단 없이 배포
- ✅ **자동 롤백**: Health check 실패 시 자동으로 롤백
- ✅ **상태 관리**: `.deployment_state` 파일로 현재 활성 환경 추적

### 주의사항

- `.env.prod` 파일이 반드시 있어야 합니다
- 배포 중에는 다른 배포 스크립트를 실행하지 마세요
- Health check가 실패하면 자동으로 롤백됩니다

---

## 개발 서버 배포

### 배포 방법

```bash
cd /home/ubuntu/CafeBackend
./deploy-dev.sh
```

### 배포 프로세스

1. **기존 컨테이너 제거**
2. **이미지 빌드** (--no-cache 옵션 사용)
3. **컨테이너 시작**
4. **Health check 대기** (최대 120초)

### 특징

- ✅ **독립 배포**: 운영 서버에 영향 없음
- ✅ **빠른 배포**: 단일 컨테이너로 간단하게 배포
- ✅ **자동 재시작**: 컨테이너가 중지되면 자동으로 재시작

### 주의사항

- `.env.dev` 파일이 반드시 있어야 합니다
- 개발 서버는 운영 서버와 완전히 독립적으로 동작합니다

---

## 웹페이지 배포

### 배포 방법

```bash
cd /home/ubuntu/Manager
./deploy-web.sh
```

### 배포 프로세스

1. **가상환경 활성화**
2. **의존성 업데이트** (requirements.txt)
3. **정적 파일 수집** (collectstatic)
4. **데이터베이스 마이그레이션** (migrate)
5. **기존 서비스 종료**
6. **Gunicorn 서비스 시작**
7. **Health check**

### 특징

- ✅ **독립 배포**: API 서버에 영향 없음
- ✅ **자동 마이그레이션**: 데이터베이스 변경사항 자동 적용
- ✅ **정적 파일 관리**: collectstatic 자동 실행

### 주의사항

- 가상환경(`venv`)이 반드시 있어야 합니다
- systemd 서비스로 실행 중인 경우 자동으로 재시작됩니다
- 직접 실행 중인 경우 프로세스를 종료하고 재시작합니다

---

## 문제 해결

### 502 Bad Gateway 에러

**원인**: Nginx가 백엔드 서버에 연결할 수 없음

**해결 방법**:

1. **서비스 상태 확인**
   ```bash
   # 운영 서버
   sudo docker ps | grep -E 'green|blue'
   
   # 개발 서버
   sudo docker ps | grep app-dev
   
   # 웹페이지
   sudo systemctl status gunicorn
   # 또는
   sudo lsof -i:8005
   ```

2. **포트 확인**
   ```bash
   sudo netstat -tlnp | grep -E ':(8000|8001|8002|8005)'
   ```

3. **Nginx 설정 확인**
   ```bash
   sudo nginx -t
   sudo cat /etc/nginx/sites-available/502company | grep upstream
   ```

4. **서비스 재시작**
   ```bash
   # 운영 서버 재배포
   cd /home/ubuntu/CafeBackend && ./deploy-prod.sh
   
   # 개발 서버 재배포
   cd /home/ubuntu/CafeBackend && ./deploy-dev.sh
   
   # 웹페이지 재배포
   cd /home/ubuntu/Manager && ./deploy-web.sh
   ```

### Health Check 실패

**원인**: 서비스가 정상적으로 시작되지 않음

**해결 방법**:

1. **컨테이너 로그 확인**
   ```bash
   # 운영 서버
   sudo docker logs green
   sudo docker logs blue
   
   # 개발 서버
   sudo docker logs app-dev
   ```

2. **환경 변수 확인**
   ```bash
   # .env.prod 또는 .env.dev 파일 확인
   cat /home/ubuntu/CafeBackend/.env.prod
   cat /home/ubuntu/CafeBackend/.env.dev
   ```

3. **수동 Health Check**
   ```bash
   # 운영 서버
   curl http://127.0.0.1:8000/prod/health
   curl http://127.0.0.1:8002/prod/health
   
   # 개발 서버
   curl http://127.0.0.1:8001/dev/health
   
   # 웹페이지
   curl http://127.0.0.1:8005/
   ```

### Nginx 설정 오류

**원인**: Nginx 설정 파일에 문법 오류

**해결 방법**:

1. **설정 파일 테스트**
   ```bash
   sudo nginx -t
   ```

2. **백업 파일로 복원** (필요한 경우)
   ```bash
   sudo ls -lt /tmp/nginx_config_backup_* | head -1
   # 가장 최근 백업 파일로 복원
   ```

3. **Nginx 재시작**
   ```bash
   sudo nginx -s reload
   # 또는
   sudo systemctl restart nginx
   ```

### 디스크 공간 부족

**원인**: Docker 이미지나 로그 파일이 너무 많음

**해결 방법**:

1. **디스크 정리 스크립트 실행**
   ```bash
   cd /home/ubuntu/CafeBackend
   ./cleanup-disk.sh
   ```

2. **Docker 정리**
   ```bash
   sudo docker system prune -a -f
   sudo docker builder prune -a -f
   ```

---

## 빠른 참조

### 서비스 상태 확인

```bash
# 모든 컨테이너 상태
sudo docker ps -a

# 운영 서버 상태
sudo docker ps | grep -E 'green|blue'

# 개발 서버 상태
sudo docker ps | grep app-dev

# 웹페이지 상태
sudo systemctl status gunicorn
```

### 로그 확인

```bash
# 운영 서버 로그
sudo docker logs -f green
sudo docker logs -f blue

# 개발 서버 로그
sudo docker logs -f app-dev

# 웹페이지 로그
sudo journalctl -u gunicorn.service -f
# 또는
tail -f /var/log/gunicorn/error.log
```

### Nginx 로그 확인

```bash
# 액세스 로그
sudo tail -f /var/log/nginx/502company_access.log

# 에러 로그
sudo tail -f /var/log/nginx/502company_error.log
```

---

## 추가 정보

- **프로젝트 디렉토리**: `/home/ubuntu/CafeBackend`
- **웹페이지 디렉토리**: `/home/ubuntu/Manager`
- **Nginx 설정**: `/etc/nginx/sites-available/502company`
- **상태 파일**: `/home/ubuntu/CafeBackend/.deployment_state`

각 서버는 독립적으로 배포할 수 있으며, 다른 서버에 영향을 주지 않습니다.


