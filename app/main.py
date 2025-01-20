from fastapi import FastAPI
from typing import Union
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

import pymysql
import app.database as database
import boto3
from botocore.client import Config

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

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용, 필요한 도메인만 허용할 수도 있음
    allow_credentials=True,
    allow_methods=["*"],  # 모든 HTTP 메서드 허용
    allow_headers=["*"],  # 모든 헤더 허용
)

prefix = "/dev" if settings.debug == True else ""

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

