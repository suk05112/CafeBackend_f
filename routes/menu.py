from fastapi import APIRouter, HTTPException
from fastapi import FastAPI

import pymysql
import dbinfo
import boto3
from botocore.client import Config

from models.menu import Menu

router = APIRouter()

@router.get("/list/{store_id}")
def getMenuList(store_id: int):
    connection = pymysql.connect(
    host = dbinfo.db_host,
    user = dbinfo.db_username,
    passwd = dbinfo.db_password,
    db = dbinfo.db_name,
    port = dbinfo.db_port
    )

    try:
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        cursor.execute("select menuId, name, price, description, status from Menu where storeId=%s;", store_id)
        rows = cursor.fetchall()
    
        bucket_name = "cafe-platform-bucket"
    
        s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                          aws_secret_access_key='***REMOVED_AWS_SECRET***',
                          region_name='ap-northeast-2',
                          config= Config(signature_version='s3v4'))
         
        menuList = []

        for row in rows:
            menu_id = row["menuId"]
            menu_image_url = s3.generate_presigned_url('get_object',
                                    Params={'Bucket': bucket_name,
                                            'Key': f'menu/menu_{store_id}_{menu_id}.png',
                                            },
                                    ExpiresIn=3600)
            menu = {
                "menu_id": row["menuId"],
                "store_id": store_id,
                "name":row["name"],
                "price": row["price"],
                "description": row["description"],
                "status": row["status"],
                "menu_image_url": menu_image_url
            }
            menuList.append(menu)
        
        return {
            'statusCode': 200,
            'menuList': menuList
        }
        
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed find menuList",
            'store_id': store_id
        }
        return result
    finally:
        connection.close()
        
@router.post("/add/{store_id}") 
def addMenu(menu: Menu):
    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config= Config(signature_version='s3v4'))
    
    try:
        connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
        )
        
        cursor = connection.cursor()
          
        query = """
        INSERT INTO Menu (
            storeId, name, price, description
        ) VALUES (
            {}, '{}', {}, '{}'
        );
        """.format(
                menu.store_id, 
                menu.name, 
                menu.price, 
                menu.description, 
            )
            
        cursor.execute(query)
        connection.commit()
        menu_id = cursor.lastrowid
        store_id = menu.store_id
        menu_put_url = s3.generate_presigned_url('put_object',
                                            Params={'Bucket': bucket_name,
                                                    'Key': f'menu/menu_{store_id}_{menu_id}.png',
                                                    },
                                          ExpiresIn=3600)
        menu_get_url = s3.generate_presigned_url('get_object',
                                    Params={'Bucket': bucket_name,
                                            'Key': f'menu/menu_{store_id}_{menu_id}.png',
                                            },
                                    ExpiresIn=3600)
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed add menu - " + str(e),
            'menu_put_url': "",
            'menu_get_url': ""        
            }
        return result
    
    finally:
        connection.close()

    return {
        'statusCode': 200,
        'menu_id': menu_id,
        'menu_put_url': menu_put_url,
        'menu_get_url': menu_get_url
    }

@router.post("/update/{menu_id}") 
def updateMenu(menu_id: int, menu: Menu):
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
    
    try:
        cursor = connection.cursor()
        query = "UPDATE Menu SET "
        values = []
        
        if menu.name:
            query += "name = %s, "
            values.append(menu.name)
        if menu.price:
            query += "price = %s, "
            values.append(menu.price)
        if menu.description:
            query += "description = %s, "
            values.append(menu.description)
            
        query = query[:-2]  # 마지막 쉼표와 공백 제거
        query += " WHERE menuId = %s"
        
        values.append(menu_id)
        cursor.execute(query, tuple(values))
        connection.commit()
        
        #새로 업데이트 된 이미지 저장 
        menu_put_url = s3.generate_presigned_url('put_object',
                                                Params={'Bucket': bucket_name,
                                                        'Key': f'menu/menu_{menu.store_id}_{menu_id}.png',
                                                        },
                                            ExpiresIn=3600)
        menu_get_url = s3.generate_presigned_url('get_object',
                                    Params={'Bucket': bucket_name,
                                            'Key': f'menu/menu_{menu.store_id}_{menu_id}.png',
                                            },
                                    ExpiresIn=3600)
        result = {
            'statusCode': 200,
            'msg': "success",
            'menu_put_url': menu_put_url,
            'menu_get_url': menu_get_url
        }
        
        return result
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed update menu - " + str(e),
            'menu_put_url': "",
            'menu_get_url': ""        
            }
        
        return result
    finally:
        connection.close()

@router.delete("/delete/{menu_id}") 
def deleteeMenu(menu_id: int):
    connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    )

    bucket_name = "cafe-platform-bucket"

    s3 = boto3.client('s3',
                      aws_access_key_id='***REMOVED_AWS_KEY***',
                      aws_secret_access_key='***REMOVED_AWS_SECRET***',
                      region_name='ap-northeast-2',
                      config=Config(signature_version='s3v4'))

    try:
        cursor = connection.cursor()

        # Check if the menu exists
        cursor.execute("SELECT storeId FROM Menu WHERE menuId = %s", (menu_id,))
        row = cursor.fetchone()
        
        if not row:
            return {
                'statusCode': 404,
                'msg': f"Menu with id {menu_id} not found",
            }
        store_id = row[0]  # Retrieve store_id for S3 key

        # Delete the menu from the database
        cursor.execute("DELETE FROM Menu WHERE menuId = %s", (menu_id,))
        connection.commit()

        # Delete the associated image from S3
        try:
            s3_key = f'menu/menu_{store_id}_{menu_id}.png'
            s3.delete_object(Bucket=bucket_name, Key=s3_key)
        except Exception as s3_error:
            print(f"S3 deletion failed: {s3_error}")

        return {
            'statusCode': 200,
            'msg': "Menu deleted successfully",
        }

    except Exception as e:
        print(e)
        return {
            'statusCode': 500,
            'msg': "Failed to delete menu - " + str(e),
        }

    finally:
        connection.close()