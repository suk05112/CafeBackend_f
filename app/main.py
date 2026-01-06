#상위폴더 참조 (import 전에 실행해야 함)
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

from fastapi import FastAPI, Header, Request, APIRouter, Depends, HTTPException
from typing import Union
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
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
from db.session import get_db_connection
from core.s3_config import S3_CLIENT, BUCKET_NAME

# 기존 routes (점진적으로 api/endpoints로 이동 예정)
# from routes import user  # api/endpoints로 이동됨
from routes import gifticon
from routes import owner
from routes import order
# admin은 새로운 구조로 이동됨
# from routes import admin

# 새로운 구조 (api/endpoints)
from api.endpoints import store, menu, settlement, common, admin, user

#https://fastapi.tiangolo.com/ko/

env = os.getenv("ENV", "dev")  # ENV=dev or ENV=prod
prefix = "/dev" if env == "dev" else "/prod"

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
    aws_access_key_id='***REMOVED_AWS_KEY***',
    aws_secret_access_key='***REMOVED_AWS_SECRET***',
    region_name='ap-northeast-2'
)

# 한국 시간대 (KST, UTC+9)
KST = timezone(timedelta(hours=9))

def get_kst_now():
    """한국 시간(KST)을 반환하는 헬퍼 함수"""
    return datetime.now(KST)

# log_group_name = f"cafe-backend-{env}"  # cafe-backend-dev 또는 cafe-backend-prod
log_group_name = "cafe-backend-production" if env == "prod" else "cafe-backend-development"
log_stream_name = f"api-requests-{env}-{get_kst_now().strftime('%Y%m%d')}"  # 날짜별 스트림 (환경별, 한국 시간 기준)
log_stream_name = "api-requests-production" if env == "prod" else "api-requests-development"

cloudwatch_handler = watchtower.CloudWatchLogHandler(
    boto3_client=boto3_client,
    log_group_name=log_group_name,
    log_stream_name=log_stream_name,
    use_queues=False
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

# CloudWatch 핸들러를 logging logger에 추가
logger_name = "cafe-backend-production" if env == "prod" else "cafe-backend-development"
logger = logging.getLogger(logger_name)
logger.addHandler(cloudwatch_handler)
logger.setLevel(logging.INFO)

# lifespan 함수 정의 (app 생성 전에 정의 필요)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시 DB 연결
    try:
        connection = get_db_connection()  # 환경에 맞는 DB 연결

        app.state.db = connection
        print("DB 연결 완료")
        print(f"연결된 config: db_host={settings.db_host}, db_user={settings.db_user}")
    except Exception as e:
        logger.error(f"❌ DB 연결 실패: {e}")
        app.state.db = None
        
    yield  # 서버가 실행 중일 때

    # 서버 종료 시 DB 연결 해제
    connection.close()
    print("DB 연결 종료")

# FastAPI 앱 생성
app = FastAPI(lifespan=lifespan)
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

# 새로운 구조 (리팩토링된 엔드포인트) - import는 위에서 이미 했음
app.include_router(store.router, prefix=f'/store', tags=["Store"])
app.include_router(menu.router, prefix=f'/menu', tags=["Menu"])
app.include_router(settlement.router, prefix='/settlement', tags=["Settlement"])
app.include_router(common.router, prefix='', tags=["Common"])
app.include_router(admin.router, prefix='/admin', tags=["Admin"])
app.include_router(user.router, prefix='/user', tags=["User"])

# 기존 routes (점진적으로 리팩토링 예정)
app.include_router(gifticon.router, prefix='/gifticon', tags=["Gifticon"])
app.include_router(owner.router, prefix='/owner', tags=["Owner"])
app.include_router(order.router, prefix='/order', tags=["Order"])
# 기존 admin 라우트는 새로운 구조로 대체됨
# app.include_router(admin.router, prefix='/admin', tags=["Admin"])
    

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = get_kst_now()
    is_get_request = request.method == "GET"
    
    # 요청 정보 수집 (GET 요청은 request_body 없음)
    request_body = None
    if not is_get_request and request.method in ["POST", "PUT", "PATCH"]:
        body = await request.body()
        request_body = body.decode('utf-8') if body else None
    
    # 요청 처리
    response = await call_next(request)
    
    # 응답 본문 읽기
    response_body = [chunk async for chunk in response.body_iterator]
    response.body_iterator = iterate_in_threadpool(iter(response_body))
    
    response_body_str = None
    if response_body:
        try:
            response_body_str = response_body[0].decode('utf-8')
        except:
            response_body_str = "Unable to decode response body"
    else:
        response_body_str = "Empty response body"
    
    # 처리 시간 계산
    process_time = (get_kst_now() - start_time).total_seconds()
    
    # GET 요청은 오류(status_code >= 400)인 경우에만 로깅
    # GET이 아닌 요청은 모두 로깅
    # should_log = not is_get_request or response.status_code >= 400
    should_log = True
    if should_log:
        # User-Agent 헤더 가져오기
        user_agent = request.headers.get("user-agent", None)
        
        # 로깅할 데이터 구조화
        log_data = {
            "environment": env,
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "query_params": str(request.query_params),
            "status_code": response.status_code,
            "process_time_seconds": round(process_time, 3),
            "timestamp": get_kst_now().isoformat(),
            "request_body": request_body,
            "response_body": response_body_str[:1000] if response_body_str else None,  # 응답 본문은 최대 1000자만
            "client_host": request.client.host if request.client else None,
            "user_agent": user_agent,
        }
        
        # CloudWatch에 JSON 형태로 로깅 (한국 시간 포함)
        current_time = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
        log_message = json.dumps(log_data, ensure_ascii=False, indent=2)
        
        if response.status_code >= 400:
            logger.error(log_message)
        else:
            logger.info(log_message)
        
        # 콘솔에도 출력 (개발 편의성, 한국 시간 포함)
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

