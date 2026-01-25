# CafeBackend

카페 플랫폼 백엔드 API 서버

## 📋 프로젝트 개요

개인 카페 기프티콘 플랫폼의 백엔드 API 서버입니다. FastAPI를 사용하여 구현되었습니다.

## 🏗️ 프로젝트 구조

자세한 구조는 [PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md)를 참고하세요.

```
CafeBackend/
├── api/          # API 엔드포인트
├── app/          # FastAPI 애플리케이션
├── core/         # 핵심 설정
├── crud/         # 데이터베이스 CRUD
├── db/           # 데이터베이스 연결
├── models/       # 데이터 모델
├── schemas/      # API 스키마
├── migrations/   # DB 마이그레이션
├── scripts/      # 실행 스크립트
├── tests/        # 테스트 코드
└── docs/         # 문서
```

## 🚀 빠른 시작

### 1. 환경 설정

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정
cp .env.dev .env.local
# .env.local 파일을 편집하여 설정값 수정
```

### 2. 데이터베이스 마이그레이션

```bash
# 마이그레이션 실행
python scripts/run_migrations.py

# 정산 주기 데이터 생성 (1년치)
python scripts/generate_settlement_cycles.py
```

### 3. 서버 실행

```bash
# 로컬 개발 서버
python scripts/run_local.py

# 또는 직접 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 📚 주요 기능

### API 엔드포인트

- **사용자 API** (`/api/endpoints/user.py`)
- **사장님 API** (`/api/endpoints/owner.py`)
- **매장 API** (`/api/endpoints/store.py`)
- **메뉴 API** (`/api/endpoints/menu.py`)
- **기프티콘 API** (`/api/endpoints/gifticon.py`)
- **주문 API** (`/api/endpoints/order.py`)
- **정산 API** (`/api/endpoints/settlement.py`)
- **관리자 API** (`/api/endpoints/admin.py`)

### 주요 기능

- ✅ 사용자/사장님 인증 (Firebase)
- ✅ 매장 및 메뉴 관리
- ✅ 기프티콘 발행 및 사용
- ✅ 주문 및 결제 처리
- ✅ 정산 시스템 (주기별 정산)
- ✅ 수수료 프로모션 관리
- ✅ 통계 데이터 조회
- ✅ FCM 푸시 알림

## 🔧 환경 변수

환경 변수는 `.env.dev`, `.env.local`, `.env.prod` 파일에서 관리됩니다.

주요 설정:
- `ENV`: 환경 설정 (dev/local/prod)
- `DB_HOST`: 데이터베이스 호스트
- `DB_USER`: 데이터베이스 사용자
- `DB_PASSWORD`: 데이터베이스 비밀번호
- `DB_NAME`: 데이터베이스 이름

자세한 내용은 [docs/API_ENV_GUIDE.md](./docs/API_ENV_GUIDE.md)를 참고하세요.

## 🧪 테스트

```bash
# 정산 데이터 검증 테스트
python tests/test_settlement.py

# DB 연결 테스트
python scripts/test_db_connection.py
```

## 📦 배포

배포 가이드는 [docs/DEPLOYMENT_GUIDE.md](./docs/DEPLOYMENT_GUIDE.md)를 참고하세요.

```bash
# 개발 환경 배포
./deploy-dev.sh

# 운영 환경 배포
./deploy-prod.sh
```

## 📝 API 문서

서버 실행 후 다음 URL에서 API 문서를 확인할 수 있습니다:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 🛠️ 개발 가이드

### 코드 구조

- **API 엔드포인트**: HTTP 요청/응답 처리
- **CRUD**: 비즈니스 로직 및 데이터베이스 작업
- **Models**: 데이터 모델 정의
- **Schemas**: API 요청/응답 스키마

### 새로운 기능 추가

1. `models/`에 데이터 모델 정의
2. `schemas/`에 API 스키마 정의
3. `crud/`에 비즈니스 로직 구현
4. `api/endpoints/`에 API 엔드포인트 추가
5. `migrations/`에 필요한 경우 마이그레이션 파일 추가

## 📄 라이선스

이 프로젝트는 비공개 프로젝트입니다.
