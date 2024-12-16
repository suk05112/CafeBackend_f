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


#https://fastapi.tiangolo.com/ko/

app = FastAPI()

app.include_router(store.router, prefix="/store", tags=["Store"])
app.include_router(user.router, prefix="/user", tags=["User"])
app.include_router(gifticon.router, prefix="/gifticon", tags=["Gifticon"])
app.include_router(menu.router, prefix="/menu", tags=["Menu"])

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





# @app.api_route('/', methods=['PATCH'])
@app.patch("/gifticon/use/{gifticon_id}")
def useGifticon(gifticon_id: int):
    connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    ) # db 접근 하기 위한 정보 

    cursor = connection.cursor(pymysql.cursors.DictCursor)
       
    print("1")
    try:
        gifticon_id = gifticon_id
        print("2")

        cursor.execute('''UPDATE Gifticon SET use_yn=1 WHERE id=%s ;''', gifticon_id)
        
        print("3")

        _ = cursor.fetchall()
        print("4")

        return {
            'statusCode': 200,
        }
        
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed get gifticon list",
        }
        return result
    
    finally:        
        cursor.close()
        connection.close()