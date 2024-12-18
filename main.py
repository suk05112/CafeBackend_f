from fastapi import FastAPI
from typing import Union
from pydantic import BaseModel

import pymysql
import dbinfo
import boto3
from botocore.client import Config

from routes import store
from routes import user
from routes import gifticon
from routes import menu
from routes import owner

#https://fastapi.tiangolo.com/ko/

app = FastAPI()

app.include_router(store.router, prefix="/store", tags=["Store"])
app.include_router(user.router, prefix="/user", tags=["User"])
app.include_router(gifticon.router, prefix="/gifticon", tags=["Gifticon"])
app.include_router(menu.router, prefix="/menu", tags=["Menu"])
app.include_router(owner.router, prefix="/owner", tags=["Owner"])

connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    )

bucket_name = "cafe-platform-bucket"
s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                aws_secret_access_key='***REMOVED_AWS_SECRET***',
                region_name='ap-northeast-2',
                config= Config(signature_version='s3v4'))
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

