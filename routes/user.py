import traceback
from fastapi import APIRouter, HTTPException
from fastapi import FastAPI

from fastapi import FastAPI
from typing import Union
from pydantic import BaseModel

import pymysql
import app.database as database
import boto3
from botocore.client import Config
from app.database import get_db_connection

from loguru import logger

from models.user import User
from models.user import Inquiry
from models.user import InquiryResponse

router = APIRouter()

@router.post("/register")
async def registerUser(user: User):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
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
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
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
    connection = get_db_connection()  # 환경에 맞는 DB 연결                     
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

@router.post("/inquiry/{user_id}")
async def subjectInquiry(user_id: int, inquiry: Inquiry):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO Inquiry (
                user_id, title, content
            ) VALUES (
              {}, '{}', '{}'
            );
        """.format(
            user_id,
            inquiry.title,
            inquiry.content,
            )
            
        cursor.execute(query)
        connection.commit()
                
        return {
            'statusCode': 200,
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register inquiry - " + str(e),
            }
        traceback.print_exc() 
        logger.error(f"Error: {str(e)} {result}")
        raise HTTPException(status_code=500, detail="failed register inquiry - " + str(e))

    finally:
        connection.close()

#유저용. 
@router.get("/inquiry/{user_id}")
async def getInquiry(user_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                 
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''SELECT id, title, content, status, created_at FROM Inquiry WHERE user_id=%s ;''', (user_id,))
        inquiries = cursor.fetchall()  
        
        inquiry_list = []
        
        for inquiry in inquiries:
            cursor.execute('''SELECT response, created_at FROM Inquiry_response WHERE id=%s ;''', (inquiry['id'],))
            response = cursor.fetchone() 
            
            result = {
                "title": inquiry['title'],
                "content": inquiry['content'],
                "status": inquiry['status'],
                "inquiry_created": inquiry['created_at'],
                "response": response['response'] if response else None,
                "response_created": response['created_at'] if response else None,
            }
            
            inquiry_list.append(result)
                
        return {
            'inquiry_list': list(reversed(inquiry_list))
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed get inquiry - " + str(e),
            }
        traceback.print_exc() 
        logger.error(f"Error: {str(e)} {result}")
        raise HTTPException(status_code=500, detail="failed get inquiry - " + str(e))

    finally:
        connection.close()

#모든 문의내역 불러오기
@router.get("/inquiry")
async def getInquiry():
    connection = get_db_connection()  # 환경에 맞는 DB 연결                
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''SELECT id, title, content, status, created_at FROM Inquiry;''')
        inquiries = cursor.fetchall()  
        
        inquiry_list = []
        
        for inquiry in inquiries:
            cursor.execute('''SELECT response, created_at FROM Inquiry_response WHERE id=%s;''', (inquiry['id'],))
            response = cursor.fetchone() 
            
            result = {
                "id": inquiry['id'],
                "title": inquiry['title'],
                "content": inquiry['content'],
                "status": inquiry['status'],
                "inquiry_created": inquiry['created_at'],
                "response": response['response'] if response else None,
                "response_created": response['created_at'] if response else None,
            }
            
            inquiry_list.append(result)
                
        return {
            'inquiry_list': list(reversed(inquiry_list))
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register inquiry - " + str(e),
            }
        traceback.print_exc() 
        logger.error(f"Error: {str(e)} {result}")
        raise HTTPException(status_code=500, detail="failed get all inquiry - " + str(e))

    finally:
        connection.close()
        
@router.post("/reply/{inquiry_id}")
async def subjectInquiry(inquiry_id: int, reply: InquiryResponse):
    connection = get_db_connection()  # 환경에 맞는 DB 연결               
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO Owner_Inquiry_response (
                inquiry_id, response
            ) VALUES (
              {}, '{}'
            );
        """.format(
            inquiry_id,
            reply.response,
            )
            
        cursor.execute(query)
        
        # Owner_Inquiry 테이블에서 해당 inquiry_id의 status를 'answered'로 변경하는 쿼리
        query_update_status = """
            UPDATE Owner_Inquiry
            SET status = 'answered'
            WHERE id = %s;
        """
        cursor.execute(query_update_status, (inquiry_id,))
        
        # 변경 사항을 커밋
        connection.commit()                
        return {
            'statusCode': 200,
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed subject inquiry - " + str(e),
            }
        return result
    finally:
        connection.close()