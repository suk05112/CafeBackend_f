from fastapi import FastAPI, Request
from typing import Union
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from starlette.concurrency import iterate_in_threadpool

import pymysql
import app.database as database
import boto3
from botocore.client import Config
from loguru import logger
import watchtower
import logging

from app.settings import settings
from app.database import get_db_connection

from routes import store
from routes import user
from routes import gifticon
from routes import menu
from routes import owner
from routes import settlement

#https://fastapi.tiangolo.com/ko/

app = FastAPI()

boto3_client = boto3.client("logs",
                            region_name="us-east-2",
                            aws_access_key_id="***REMOVED_AWS_KEY***",
                            aws_secret_access_key="***REMOVED_AWS_SECRET***")
handler = watchtower.CloudWatchLogHandler(
    boto3_client=boto3_client,
    log_group_name="owner_prod",
    log_stream_name="owner_prod_stream",
    use_queues=False
)

logger = logging.getLogger("uvicorn")
formatter = logging.Formatter("[%(levelname)s] %(message)s")
handler.setFormatter(formatter)
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)


# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용, 필요한 도메인만 허용할 수도 있음
    allow_credentials=True,
    allow_methods=["*"],  # 모든 HTTP 메서드 허용
    allow_headers=["*"],  # 모든 헤더 허용
)

app.include_router(store.router, prefix=f'/store', tags=["Store"])
app.include_router(user.router, prefix='/user', tags=["User"])
app.include_router(gifticon.router, prefix='/gifticon', tags=["Gifticon"])
app.include_router(menu.router, prefix=f'/menu', tags=["Menu"])
app.include_router(owner.router, prefix='/owner', tags=["Owner"])
app.include_router(settlement.router, prefix='/settlement', tags=["Settlement"])

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시 DB 연결
    connection = get_db_connection()  # 환경에 맞는 DB 연결

    app.state.db = connection
    print("DB 연결 완료")
    print("연결된 config", settings.Config)

    yield  # 서버가 실행 중일 때

    # 서버 종료 시 DB 연결 해제
    connection.close()
    print("DB 연결 종료")
    

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"Logging request: {request.method} {request.url}")  # 콘솔에 직접 출력

    # 요청 데이터 로깅
    logger.info(f"Received request: {request.method} {request.url}")
    if request.method == "POST":
        body = await request.body()
        print(f"POST Body: {body.decode()}")  # 콘솔 출력으로 확인
        logger.info(f"Request body: {body.decode()}")
    
    # 응답 데이터 로깅
    response = await call_next(request)
    
     # 응답 데이터를 로깅하기 전에, 응답을 복사하여 로깅
    response_body = [chunk async for chunk in response.body_iterator]  # 응답 본문을 읽고
    # response.body_iterator = iter(response_body) 
    response.body_iterator = iterate_in_threadpool(iter(response_body))
    
    # Stringified response body object
    if response_body:
        response_body = response_body[0].decode()
    else:
        response_body = "response_body not found"
    
    if response.status_code == 200:
        logger.info(f"Responding with status code {response.status_code} Response body: {response_body}")
    else:
        logger.error(f"Responding with status code {response.status_code} Response body: {response_body}")

    print(f"Response status: {response.status_code}")  # 확인용 출력

    return response

@app.get("/")
async def root():
    return {"msg" : "Hello World"}

@app.get("/home")
async def root():
    return {"msg" : "home"}

#  http://127.0.0.1:8000/items/5?q=somequery
@app.get("/items/{item_id}")
def read_item(item_id: int, q: Union[str, None] = None):
    return {"item_id": item_id, "q": q}

