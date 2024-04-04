from fastapi import FastAPI
from typing import Union
from pydantic import BaseModel

import pymysql
import dbinfo
import boto3
from botocore.client import Config

#https://fastapi.tiangolo.com/ko/

app = FastAPI()
connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    )

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

class StoreCreate(BaseModel):
    owner_id: int
    store_name: str
    store_telephone: str
    store_description: str
    store_address: str
    store_lat: float
    store_lng: float
    store_photo_cnt: int

# @app.post("/store/update/{store_id}")
# def registerStore():
@app.post("/store/register")
async def registerStore(store: StoreCreate):
    connection = pymysql.connect(
    host = dbinfo.db_host,
    user = dbinfo.db_username,
    passwd = dbinfo.db_password,
    db = dbinfo.db_name,
    port = dbinfo.db_port
    ) # db 접근 하기 위한 정보 

    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config= Config(signature_version='s3v4'))
                          
    # keys = event.keys()
    cursor = connection.cursor()

    # print(keys) 
    print("description")

    try:
        print("sujin1")
        query = """
            INSERT INTO Store (
                owner_id, store_name, store_telephone, store_description, store_address, , store_lat, store_lng, store_photo_cnt
            ) VALUES (
              {},'{}','{}', '{}', '{}', '{}', {}, {}, {}
            );
        """.format(
            store.owner_id,
            store.store_name,
            store.store_telephone,
            store.store_description,
            store.store_address,
            store.store_lat,
            store.store_lng,
            store.store_photo_cnt,
            )
            
        cursor.execute(query)
        connection.commit()
        print("sujin2")

        store_id = cursor.lastrowid
        print(store_id)

        store_logo_url = s3.generate_presigned_url('put_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'logo/store_logo_{store_id}.png',
                                                            },
                                                  ExpiresIn=3600)
                                                  
                              
    
        store_photo_urls = []
        
        for i in range(1, event['store_photo_cnt']+1):
            s3_url = s3.generate_presigned_url('put_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'store_image/store_image_{store_id}_{i}.png',
                                                            },
                                                  ExpiresIn=3600)

            store_photo_urls.append(s3_url)
        
        rows = cursor.fetchall()
        
        print(s3_url)
        print("sujin test")
        
        return {
            'statusCode': 200,
            'store_id': store_id,
            'store_logo_url': store_logo_url,
            'store_photo_urls': store_photo_urls
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register store - " + str(e),
            'store_id': -1
        }
        return result
    finally:
        connection.close()

@app.get("owner/store/list/{owner_Id}")
def getStoreList(owner_id: int):
    connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    ) # db 접근 하기 위한 정보 

    cursor = connection.cursor() # DB에 접속 및 DB 객체를 가져옴
    
    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config= Config(signature_version='s3v4'))
                      
    try:
        owner_id = owner_id
            
        cursor.execute('''select
        owner_id, 
        store_id, 
        store_name, 
        status, 
        inspection_status, 
        open_yn,
        store_photo_cnt
        from Store where owner_id=%s ;''', owner_id)
        
        rows = cursor.fetchall()
        row = rows[0]
        print(row)
        print(row[0])
    
        storeList = []
        
        for row in rows:
            store_logo_url = s3.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': f'logo/store_logo_{row[1]}.png',
                                                            },
                                                  ExpiresIn=3600)
                                                  
            print("logo url success")
            store_photo_urls = []
        
            for i in range(1, row[6]+1):
                s3_url = s3.generate_presigned_url('get_object',
                                                            Params={'Bucket': bucket_name,
                                                                    'Key': f'store_image/store_image_{row[1]}_{i}.png',
                                                                    },
                                                          ExpiresIn=3600)

                store_photo_urls.append(s3_url) 
            
            store = {
                "owner_id": row[0],
                "store_id": row[1],
                "store_name": row[2],
                "store_logo": store_logo_url,
                "store_photo_urls": store_photo_urls,
                "status": row[3],
                "inspection_status": row[4],
                "open_yn": row[5],
            }
            storeList.append(store)
    
        print(storeList)
        
        result = {
            # 'statusCode': 200,
            'store': storeList
        }
    
        # return result
        return {
            'statusCode': 200,
            'body': result
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed get store list",
        }
    finally:        
        cursor.close()
        connection.close()
    # return {"item_id": item_id}

@app.post("/store/update/{store_id}")
def updateStore():
    connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    )
    try:
        cursor = connection.cursor()
        
        store_id = store_id
        query = "UPDATE Store SET "
        values = []

        if 'store_address' in event:
            query += "store_address = %s, "
            values.append(event['store_address'])
        if 'store_telephone' in event:
            query += "store_telephone = %s, "
            values.append(event['store_telephone'])
        if 'store_description' in event:
            query += "store_description = %s, "
            values.append(event['store_description'])
        if 'store_photo' in event:
            query += "store_photo = %s, "
            values.append(event['store_photo'])
        if 'store_logo' in event:
            query += "store_logo = %s, "
            values.append(event['store_logo'])

        query = query[:-2]  # 마지막 쉼표와 공백 제거
        query += " WHERE store_id = %s"
        values.append(store_id)

        cursor.execute(query, tuple(values))
        connection.commit()

        print(cursor.rowcount)
        print(cursor._rows)

        if cursor.rowcount > 0:
            result = {
                'statusCode': 200,
                'msg': "success",
                'owner_id': store_id
            }
        else:
            result = {
                'statusCode': 404,
                'msg': "no record found",
                'owner_id': store_id
            }

        return result
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed update owner",
            'owner_id': -1
        }
    finally:
        connection.close()

@app.post("/store/delete/{store_id}")
def deleteStore():
    connection = pymysql.connect(
    host = dbinfo.db_host,
    user = dbinfo.db_username,
    passwd = dbinfo.db_password,
    db = dbinfo.db_name,
    port = dbinfo.db_port
    ) 

    try:
        cursor = connection.cursor()
        store_id = store_id
        query = "DELETE FROM Store WHERE store_id = %s"

        cursor.execute(query, (store_id,))
        connection.commit()
        
        if cursor.rowcount > 0:
            result = {
                'statusCode': 200,
                'msg': "success",
                'store_id': store_id
            }
        else:
            result = {
                'statusCode': 404,
                'msg': "no record found",
                'store_id': store_id
            }
        return result
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed update owner",
            'owner_id': -1
        }
    finally:
        connection.close()