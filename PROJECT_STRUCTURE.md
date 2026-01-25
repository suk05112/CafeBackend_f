# CafeBackend 프로젝트 구조

## 📁 디렉토리 구조

```
CafeBackend/
├── api/                    # API 엔드포인트
│   └── endpoints/          # 각 도메인별 API 라우터
│       ├── admin.py        # 관리자 API
│       ├── common.py       # 공통 API
│       ├── gifticon.py    # 기프티콘 API
│       ├── menu.py         # 메뉴 API
│       ├── order.py        # 주문 API
│       ├── owner.py        # 사장님 API
│       ├── settlement.py   # 정산 API
│       ├── store.py        # 매장 API
│       └── user.py         # 사용자 API
│
├── app/                    # FastAPI 애플리케이션
│   ├── main.py            # FastAPI 앱 진입점
│   ├── auth/              # 인증 관련
│   │   └── auth_dependency.py
│   ├── database.py        # 데이터베이스 설정
│   ├── fcm_service.py     # FCM 푸시 알림
│   └── firebase_init.py   # Firebase 초기화
│
├── core/                   # 핵심 설정 및 유틸리티
│   ├── config.py          # 환경 설정 (Pydantic)
│   ├── s3_config.py       # S3 설정
│   └── region_code.py     # 지역 코드 유틸리티
│
├── crud/                   # 데이터베이스 CRUD 작업
│   ├── admin.py           # 관리자 CRUD
│   ├── menu.py            # 메뉴 CRUD
│   ├── promotion.py       # 프로모션 CRUD
│   ├── settlement.py      # 정산 CRUD
│   ├── settlement_cycle.py # 정산 주기 CRUD
│   ├── stats.py           # 통계 CRUD
│   └── store.py           # 매장 CRUD
│
├── db/                     # 데이터베이스 연결
│   └── session.py         # DB 연결 풀 관리
│
├── models/                 # 데이터 모델 (Pydantic)
│   ├── gifticon.py
│   ├── menu.py
│   ├── notice.py
│   ├── owner.py
│   ├── push_token.py
│   ├── settlement.py
│   ├── store.py
│   └── user.py
│
├── schemas/                # API 스키마 (Pydantic)
│   ├── gifticon.py
│   ├── menu.py
│   ├── owner.py
│   ├── push_token.py
│   ├── settlement.py
│   ├── store.py
│   └── user.py
│
├── migrations/             # 데이터베이스 마이그레이션 SQL
│   ├── create_*.sql
│   └── ...
│
├── scripts/                # 실행 스크립트
│   ├── generate_settlement_cycles.py  # 정산 주기 생성
│   ├── run_migrations.py              # 마이그레이션 실행
│   ├── run_local.py                   # 로컬 실행
│   └── test_db_connection.py          # DB 연결 테스트
│
├── tests/                  # 테스트 코드
│   └── test_settlement.py  # 정산 데이터 검증 테스트
│
├── docs/                   # 문서
│   ├── API_ENV_GUIDE.md
│   ├── DEPLOYMENT_GUIDE.md
│   └── README_LOCAL_TEST.md
│
├── .env.dev               # 개발 환경 변수
├── .env.local             # 로컬 환경 변수
├── .env.prod              # 운영 환경 변수
├── requirements.txt       # Python 의존성
├── Dockerfile             # Docker 이미지 빌드
├── docker-compose.yml     # Docker Compose 설정
└── README.md              # 프로젝트 메인 문서
```

## 📋 주요 디렉토리 설명

### `api/endpoints/`
- FastAPI 라우터 정의
- 각 도메인별 API 엔드포인트 관리
- HTTP 요청/응답 처리

### `crud/`
- 데이터베이스 CRUD 작업
- 비즈니스 로직 포함
- DB 연결 풀 사용

### `models/`
- Pydantic 모델 정의
- 데이터 검증 및 직렬화

### `schemas/`
- API 요청/응답 스키마
- Pydantic 모델

### `core/`
- 핵심 설정 및 유틸리티
- 환경 변수 관리
- 공통 설정 (S3, 지역 코드 등)

### `db/`
- 데이터베이스 연결 관리
- 연결 풀 구현

### `migrations/`
- SQL 마이그레이션 파일
- 테이블 생성/수정 스크립트

### `scripts/`
- 실행 가능한 Python 스크립트
- 마이그레이션, 데이터 생성 등

### `tests/`
- 단위 테스트 및 통합 테스트
- 검증 테스트 코드

## 🔄 데이터 흐름

```
API Request
    ↓
api/endpoints/ (라우터)
    ↓
crud/ (비즈니스 로직)
    ↓
db/session.py (DB 연결)
    ↓
Database
```

## 📝 파일 명명 규칙

- **API 엔드포인트**: `api/endpoints/{domain}.py`
- **CRUD 작업**: `crud/{domain}.py`
- **모델**: `models/{domain}.py`
- **스키마**: `schemas/{domain}.py`
- **마이그레이션**: `migrations/create_{table}_table.sql`

## 🚀 실행 방법

### 로컬 개발 서버 실행
```bash
python scripts/run_local.py
```

### 마이그레이션 실행
```bash
python scripts/run_migrations.py
```

### 정산 주기 생성
```bash
python scripts/generate_settlement_cycles.py
```

### 테스트 실행
```bash
python tests/test_settlement.py
```

## 🔧 환경 설정

환경 변수는 `.env.dev`, `.env.local`, `.env.prod` 파일에서 관리됩니다.
`ENV` 환경 변수로 사용할 파일을 선택합니다.

- `ENV=dev` → `.env.dev`
- `ENV=local` → `.env.local`
- `ENV=prod` → `.env.prod`
