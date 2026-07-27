#상위폴더 참조 (import 전에 실행해야 함)
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

from fastapi import FastAPI, Header, Request, APIRouter, Depends, HTTPException
from typing import Union
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from contextlib import asynccontextmanager
from starlette.concurrency import iterate_in_threadpool
from app import firebase_init  
from app.auth.auth_dependency import verify_firebase_token

import pymysql
# import app.database as database
import boto3
import watchtower
import logging
from datetime import datetime, timezone, timedelta
import json

from core.config import settings
from core.exceptions import InternalError, internal_error_handler
from core.s3_config import S3_CLIENT, BUCKET_NAME
from core.scheduler import create_scheduler
from app.system_logger import (
    log_process_event,
    log_app_startup_snapshot,
    log_rate_limit,
)

# 모든 엔드포인트는 api/endpoints로 통합됨
from api.endpoints import store, menu, settlement, common, admin, user, gifticon, owner, order, system

#https://fastapi.tiangolo.com/ko/

env = os.getenv("ENV", "dev")  # ENV=dev, development, local, prod, production
# 개발 환경: dev, development, local → /dev
# 운영 환경: prod, production → /prod
prefix = "/dev" if env in ["dev", "development", "local"] else "/prod"

print(env)
# router = APIRouter(prefix=prefix)
# router = APIRouter(prefix="/dev")
# ENV = os.getenv("ENV", "dev")  # 기본값 dev
# ROOT_PATH = f"/{ENV}"  # "/dev" 또는 "/prod"

# app = FastAPI(root_path=ROOT_PATH)
# app = FastAPI(root_path="/dev")

# S3 설정은 app.s3_config에서 가져옴
s3 = S3_CLIENT
bucket_name = BUCKET_NAME
print(f"S3 Bucket Name: {bucket_name} (ENV: {env})")

# CloudWatch 로깅 설정 (dev/prod 구분)
boto3_client = boto3.client(
    'logs',
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
    region_name='ap-northeast-2'
)

# 한국 시간대 (KST, UTC+9)
KST = timezone(timedelta(hours=9))

def get_kst_now():
    """한국 시간(KST)을 반환하는 헬퍼 함수"""
    return datetime.now(KST)

# CloudWatch 로그 그룹 및 스트림 설정 (환경별 구분)
# ENV 값에 따라: dev, development → development, prod, production → production
if env in ["dev", "development"]:
    log_group_name = "cafe-backend-development"
    log_stream_name = "api-requests-development"
else:
    log_group_name = "cafe-backend-production"
    log_stream_name = "api-requests-production"

cloudwatch_handler = watchtower.CloudWatchLogHandler(
    boto3_client=boto3_client,
    log_group_name=log_group_name,
    log_stream_name=log_stream_name,
    use_queues=True  # 비동기 큐 사용으로 성능 향상
)

# 로깅 포맷 설정 (한국 시간대 포함)
class KSTFormatter(logging.Formatter):
    """한국 시간대(KST)를 사용하는 커스텀 포맷터"""
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, KST)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

formatter = KSTFormatter(
    '%(asctime)s [KST] - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
cloudwatch_handler.setFormatter(formatter)
cloudwatch_handler.setLevel(logging.INFO)

# CloudWatch 핸들러를 logging logger에 추가 (환경별 구분)
if env in ["dev", "development"]:
    logger_name = "cafe-backend-development"
else:
    logger_name = "cafe-backend-production"
logger = logging.getLogger(logger_name)
logger.addHandler(cloudwatch_handler)
logger.setLevel(logging.INFO)
# 엔드포인트에서 사용하는 cafe_backend 로거에도 동일 핸들러 추가 (CloudWatch 수집)
cafe_backend_logger = logging.getLogger("cafe_backend")
cafe_backend_logger.addHandler(cloudwatch_handler)
cafe_backend_logger.setLevel(logging.INFO)

# lifespan 함수 정의 (app 생성 전에 정의 필요)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 필수 환경변수 유효성 검사
    if not settings.payletter_api_host:
        raise RuntimeError("PAYLETTER_API_HOST 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")

    # 앱 시작 환경 스냅샷 로깅 (민감정보 제외)
    log_app_startup_snapshot({
        "env": env,
        "db_host": settings.db_host,
        "db_name": settings.db_name,
        "s3_bucket": bucket_name,
    })

    # 스케줄러 시작 (15분마다 PENDING 만료, 매일 03:00 오래된 레코드 삭제)
    scheduler = create_scheduler()
    scheduler.start()
    print("스케줄러 시작 완료")
    log_process_event("STARTUP", f"env={env}, scheduler started")

    yield  # 서버가 실행 중일 때

    # 서버 종료 시 스케줄러 정리
    scheduler.shutdown(wait=False)
    print("스케줄러 종료 완료")
    log_process_event("SHUTDOWN", f"env={env}, scheduler stopped")

# Rate Limiter 설정 (전역 기본값: IP당 60req/min)
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# FastAPI 앱 생성
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    log_rate_limit(
        client_ip=request.client.host if request.client else "unknown",
        path=request.url.path,
    )
    return await _rate_limit_exceeded_handler(request, exc)

app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_exception_handler(InternalError, internal_error_handler)
app.add_middleware(SlowAPIMiddleware)
# app = FastAPI(redirect_slashes=False)
# app.include_router(router)

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용, 필요한 도메인만 허용할 수도 있음
    allow_credentials=True,
    allow_methods=["*"],  # 모든 HTTP 메서드 허용
    allow_headers=["*"],  # 모든 헤더 허용
)

# 모든 엔드포인트 (api/endpoints로 통합됨)
# prefix를 사용하여 환경별 경로 구분: /dev 또는 /prod
app.include_router(store.router, prefix=f'{prefix}/store', tags=["Store"])
app.include_router(menu.router, prefix=f'{prefix}/menu', tags=["Menu"])
app.include_router(settlement.router, prefix=f'{prefix}/settlement', tags=["Settlement"])
# common.router는 prefix 있음과 없음 둘 다 등록 (하위 호환성)
app.include_router(common.router, prefix=prefix, tags=["Common"])
app.include_router(common.router, prefix='', tags=["Common"])  # prefix 없이도 접근 가능
app.include_router(admin.router, prefix=f'{prefix}/admin', tags=["Admin"])
app.include_router(system.router, prefix=f'{prefix}/admin/system', tags=["System"])
app.include_router(user.router, prefix=f'{prefix}/user', tags=["User"])
app.include_router(gifticon.router, prefix=f'{prefix}/gifticon', tags=["Gifticon"])
app.include_router(owner.router, prefix=f'{prefix}/owner', tags=["Owner"])
app.include_router(order.router, prefix=f'{prefix}/order', tags=["Order"])

# 드림시큐리티 등록 URL이 https://.../dev/ 또는 https://.../prod/ 인 경우
# 표준창 returnUrl POST를 mok_return에 위임
from api.endpoints.owner import mok_return as _mok_return
app.add_api_route(f'{prefix}/', _mok_return, methods=["POST"], tags=["Owner"])
app.add_api_route(f'{prefix}', _mok_return, methods=["POST"], tags=["Owner"])
    

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = get_kst_now()
    is_get_request = request.method == "GET"
    
    # 헬스체크는 실패 시에만 로깅, login은 성공/실패 상관없이 항상 로깅
    is_health_check = (
        request.url.path in ["/health", "/dev/health", "/prod/health"] 
        or request.url.path.endswith("/health")
    )
    is_login_endpoint = (
        "/login" in request.url.path 
        or request.url.path.endswith("/login")
    )
    
    is_isRegistered_endpoint = (
        "/isRegistered" in request.url.path 
        or request.url.path.endswith("/isRegistered")
    )
    is_settlement_endpoint = "settlement" in request.url.path

    # 요청 본문 읽기 (POST/PUT/PATCH만, 최대 10KB로 제한)
    request_body = None
    if not is_get_request and request.method in ["POST", "PUT", "PATCH"]:
        try:
            body = await request.body()
            if body:
                request_body = body.decode('utf-8', errors='ignore')[:10000]
        except:
            request_body = None
    
    # 요청 처리
    response = await call_next(request)
    
    # 처리 시간 계산
    process_time = (get_kst_now() - start_time).total_seconds()
    
    # 로깅 판단
    # 헬스체크: 실패 시에만 로깅
    # login / settlement: 성공/실패 상관없이 항상 로깅 (AWS 수집)
    # 그 외 GET: 오류 시에만 로깅
    # 그 외: 모두 로깅
    if is_health_check:
        should_log = response.status_code >= 400
    elif is_login_endpoint or is_isRegistered_endpoint or is_settlement_endpoint:
        should_log = True
    elif is_get_request:
        should_log = response.status_code >= 400
    else:
        should_log = True
    
    # 응답 본문 읽기 (에러 응답 또는 로그인/정산 엔드포인트만, 최대 1000자로 제한)
    response_body_str = None
    if should_log and (response.status_code >= 400 or is_login_endpoint or is_isRegistered_endpoint or is_settlement_endpoint):
        try:
            response_body = [chunk async for chunk in response.body_iterator]
            response.body_iterator = iterate_in_threadpool(iter(response_body))
            if response_body:
                response_body_str = response_body[0].decode('utf-8', errors='ignore')[:1000]
        except:
            response_body_str = None
    
    if should_log:
        # User-Agent 헤더 가져오기
        user_agent = request.headers.get("user-agent", None)
        
        # 로깅할 데이터 구조화 (실패 여부와 상관없이 모든 필수 정보 포함)
        log_data = {
            "env": env,
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "process_time_seconds": round(process_time, 3),
            "timestamp": get_kst_now().isoformat(),
            "url": str(request.url),
            "query_params": str(request.query_params),
            "request_body": request_body,
            "response_body": response_body_str,  # 최대 1000자로 제한됨
            "client_host": request.client.host if request.client else None,
            "user_agent": user_agent,
        }
        
        # CloudWatch에 JSON 형태로 로깅
        current_time = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
        log_message = json.dumps(log_data, ensure_ascii=False)
        
        if response.status_code >= 400:
            logger.error(log_message)
        else:
            logger.info(log_message)
        
        # 느린 요청(1초 이상) 또는 에러만 콘솔 출력 (성능 최적화)
        if process_time > 1.0 or response.status_code >= 400:
            print(f"[{current_time} KST] [{env}] {request.method} {request.url.path} - {response.status_code} ({process_time:.3f}s)")

    return response

@app.get("/")
async def root():
    return {"msg" : "Hello World 이건 내 서버다 {env}"}

@app.get("/home")
async def root():
    return {"msg" : "home"}

#  http://127.0.0.1:8000/items/5?q=somequery
@app.get("/items/{item_id}")
def read_item(item_id: int, q: Union[str, None] = None):
    return {"item_id": item_id, "q": q}

