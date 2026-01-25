# 로컬 테스트 가이드

배포 전에 로컬 환경에서 테스트하는 방법입니다.

## 빠른 시작

### 1. 환경 설정 파일 확인
`.env.local` 파일이 `.env.dev`와 동일하게 설정되어 있는지 확인합니다.

```bash
cd /home/ubuntu/CafeBackend
ls -la .env.local
```

### 2. 데이터베이스 연결 테스트
```bash
python3 test_db_connection.py
```

### 3. 서버 실행

#### 방법 1: 테스트 스크립트 사용 (권장)
```bash
./test_local.sh
```

#### 방법 2: Python 스크립트 직접 실행
```bash
python3 run_local.py
```

#### 방법 3: uvicorn 직접 실행
```bash
ENV=local uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 테스트 엔드포인트

서버가 실행되면 다음 엔드포인트로 테스트할 수 있습니다:

```bash
# 헬스 체크
curl http://localhost:8000/dev/health

# 루트 엔드포인트
curl http://localhost:8000/

# 대시보드 통계
curl http://localhost:8000/dev/admin/dashboard/statistics

# 매장 리스트
curl http://localhost:8000/dev/admin/stores
```

## 주요 파일

- `.env.local`: 로컬 테스트용 환경 변수 파일 (`.env.dev`와 동일)
- `run_local.py`: 로컬 서버 실행 스크립트
- `test_local.sh`: 통합 테스트 스크립트 (의존성 확인, DB 연결 테스트, 서버 실행)
- `test_db_connection.py`: 데이터베이스 연결만 테스트하는 스크립트

## 주의사항

1. **포트 충돌**: 8000 포트가 이미 사용 중이면 다른 포트를 사용하세요.
2. **데이터베이스**: 실제 개발 DB에 연결되므로 주의하세요.
3. **환경 변수**: `.env.local` 파일이 없으면 자동으로 `.env.dev`를 사용합니다.

## 문제 해결

### 데이터베이스 연결 실패
```bash
# 연결 테스트
python3 test_db_connection.py

# 설정 확인
python3 -c "from core.config import settings; print(f'DB: {settings.db_host}:{settings.db_port}/{settings.db_name}')"
```

### 포트가 이미 사용 중
```bash
# 포트 사용 확인
lsof -i :8000

# 다른 포트로 실행
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### 의존성 문제
```bash
pip3 install -r requirements.txt
```


