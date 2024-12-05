from fastapi import APIRouter, HTTPException
from fastapi import FastAPI

from fastapi import FastAPI
from typing import Union
from pydantic import BaseModel

import pymysql
import dbinfo
import boto3
from botocore.client import Config

from models.user import User

router = APIRouter()

@router.post("/register")
async def registerUser(user: User):
    connection = pymysql.connect(
    host = dbinfo.db_host,
    user = dbinfo.db_username,
    passwd = dbinfo.db_password,
    db = dbinfo.db_name,
    port = dbinfo.db_port
    ) # db 접근 하기 위한 정보 
                          
    cursor = connection.cursor()

    try:
        query = """
            INSERT INTO User (
                name, email, phone_number
            ) VALUES (%s, %s, %s);
        """

        cursor.execute(query, (user.name, user.email, user.phone_number))
        connection.commit()

        user_id = cursor.lastrowid
        print(user_id)
                                                  
        return {
            'statusCode': 200,
            'user_id': user_id
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

@router.get("/login/{email}")
async def idRegisteredUser(email: str):
    connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
        ) # db 접근 하기 위한 정보 
                          
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''SELECT * FROM User WHERE email=%s ;''', (email,))
        user = cursor.fetchone()  # 한 행만 가져옴

        # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
        if user:  # 사용자가 존재하는 경우
            print("user:", user)
            return {
                'statusCode': 200,
                'user_id': user['user_id'],
                'name': user['name'],
                'email': user['email'],
                'phone_number': user['phone_number'],
            }
        else:
            return {
                'statusCode': 200,
                'isRegistered': 0  # 이메일이 존재하지 않으면 0
            }

    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed login " + str(e),
            'store_id': -1
        }
        return result
    finally:
        connection.close()

@router.get("/isRegistered/{email}")
async def idRegisteredUser(email: str):
    connection = pymysql.connect(
    host = dbinfo.db_host,
    user = dbinfo.db_username,
    passwd = dbinfo.db_password,
    db = dbinfo.db_name,
    port = dbinfo.db_port
    ) # db 접근 하기 위한 정보 
                          
    cursor = connection.cursor()

    try:
        cursor.execute('''SELECT * FROM User WHERE email=%s ;''', (email,))

        # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
        if cursor.fetchone():
            return {
                'statusCode': 200,
                'isRegistered': 1  # 이메일이 존재하면 1
            }
        else:
            return {
                'statusCode': 200,
                'isRegistered': 0  # 이메일이 존재하지 않으면 0
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
