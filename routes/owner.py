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

from models.owner import Owner
from models.owner import OwnerFind
from models.owner import OwnerFindPw
from models.owner import OwnerInquiry
from models.owner import OwnerInquiryResponse

from models.user import User

router = APIRouter()

@router.post("/register")
async def registerOwner(owner: Owner):
    connection = get_db_connection()  # 환경에 맞는 DB 연결           
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO Owner (
                name, email, uid, phone_number
            ) VALUES (
              '{}', '{}', '{}', '{}'
            );
        """.format(
            owner.name,
            owner.email,
            owner.uid,
            owner.phone_number,
            )
            
        cursor.execute(query)
        connection.commit()
        
        owner_id = cursor.lastrowid
        
        print("owner_id", owner_id)
        return {
            'statusCode': 200,
            'owner_id': owner_id,
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register owner - " + str(e),
            }
        return result
    finally:
        connection.close()

@router.get("/login/{uid}")
async def login(uid: str):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''SELECT * FROM Owner WHERE uid=%s ;''', (uid,))
        user = cursor.fetchone()  # 한 행만 가져옴
        
        # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
        if user:  # 사용자가 존재하는 경우
            print("user:", user)
            return {
                'statusCode': 200,
                'owner_id': user['id'],
                'name': user['name'],
                'phone_number': user['phone_number'],
            }
        else:
            return {
                'statusCode': 200,
                'msg': "unregistered user",
                'owner_id': None,
                'name': None,
                'phone_number': None,
            }

    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "An unexpected error occurred.",
            'owner_id': None,
            'name': None,
            'phone_number': None,
        }
        return result
    finally:
        connection.close()
        
@router.post("/find_ownerId")
async def findOwnerId(owner: OwnerFind):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''SELECT * FROM Owner WHERE name=%s AND phone_number=%s;''', (owner.name, owner.phone_number))
        user = cursor.fetchone()  # 한 행만 가져옴
        
        # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
        if user:  # 사용자가 존재하는 경우
            print("user:", user)
            return {
                'statusCode': 200,
                'owner_id': user['id'],
                'created_time': user['created_time'],
                'email': user['email'],

            }
        else:
            return {
                'statusCode': 200,
                'msg': "unregistered user", 
            }

    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "An unexpected error occurred." + str(e),
            'owner_id': None,
            'name': None,
            'phone_number': None,
        }
        return result
    finally:
        connection.close()
        
@router.post("/find_ownerPw")
async def findOwnerPW(owner: OwnerFindPw):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                     
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''SELECT * FROM Owner WHERE email=%s AND phone_number=%s;''', (owner.email, owner.phone_number))
        user = cursor.fetchone()  # 한 행만 가져옴
        
        # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
        if user:  # 사용자가 존재하는 경우
            print("user:", user)
            return {
                'msg': 'success'
            }
        else:
            return {
                'msg': "fail", 
            }

    except Exception as e:
        print(e)
        result = {
            'msg': "An unexpected error occurred." + str(e),
        }
        return result
    finally:
        connection.close()
        
@router.post("/inquiry/{owner_id}")
async def subjectInquiry(owner_id: int, inquiry: OwnerInquiry):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO Owner_Inquiry (
                owner_id, title, content
            ) VALUES (
              {}, '{}', '{}'
            );
        """.format(
            owner_id,
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
        return result
    finally:
        connection.close()

#사장님용. 
@router.get("/inquiry/{owner_id}")
async def getInquiry(owner_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                 
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''SELECT id, title, content, status, created_at FROM Owner_Inquiry WHERE owner_id=%s ;''', (owner_id,))
        inquiries = cursor.fetchall()  
        
        inquiry_list = []
        
        for inquiry in inquiries:
            cursor.execute('''SELECT response, created_at FROM Owner_Inquiry_response WHERE id=%s ;''', (inquiry['id'],))
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
            'inquiry_list': inquiry_list
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register inquiry - " + str(e),
            }
        return result
    finally:
        connection.close()

#관리자용. 모든 문의내역 불러오기
@router.get("/inquiry")
async def getInquiry():
    connection = get_db_connection()  # 환경에 맞는 DB 연결                
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''SELECT id, title, content, status, created_at FROM Owner_Inquiry;''')
        inquiries = cursor.fetchall()  
        
        inquiry_list = []
        
        for inquiry in inquiries:
            cursor.execute('''SELECT response, created_at FROM Owner_Inquiry_response WHERE id=%s ;''', (inquiry['id'],))
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
            'inquiry_list': inquiry_list
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register inquiry - " + str(e),
            }
        return result
    finally:
        connection.close()
        
@router.post("/reply/{inquiry_id}")
async def subjectInquiry(inquiry_id: int, reply: OwnerInquiryResponse):
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
            'msg': "failed register inquiry - " + str(e),
            }
        return result
    finally:
        connection.close()