from fastapi import APIRouter, HTTPException, status
from fastapi import FastAPI
from loguru import logger
import os

import pymysql
import app.database as database
from app.database import get_db_connection
from app.s3_config import S3_CLIENT, BUCKET_NAME

from models.menu import Menu

router = APIRouter()

# S3 설정은 app.s3_config에서 가져옴
s3 = S3_CLIENT
bucket_name = BUCKET_NAME

@router.get("/list/{store_id}")
def getMenuList(store_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    try:
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT id, menu_name, price, description, status FROM menu WHERE store_id=%s AND is_deleted=0", (store_id,))
        rows = cursor.fetchall()
         
        menuList = []

        for row in rows:
            menu_id = row["id"]
            menu_image_url = s3.generate_presigned_url('get_object',
                                    Params={'Bucket': bucket_name,
                                            'Key': f'menu/menu_{store_id}_{menu_id}.png',
                                            },
                                    ExpiresIn=3600)
            menu = {
                "menu_id": row["id"],
                "store_id": store_id,
                "name":row["menu_name"],
                "price": row["price"],
                "description": row["description"],
                "status": row["status"],
                "menu_image_url": menu_image_url
            }
            menuList.append(menu)
            print(f"menuList: {menuList}")
        
        return {'menuList': menuList}
        
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed find menuList"
        )
    finally:
        connection.close()
        
@router.post("/add/{store_id}") 
def addMenu(menu: Menu):    
    try:
        connection = get_db_connection()  # 환경에 맞는 DB 연결
        cursor = connection.cursor()
          
        query = """
        INSERT INTO menu (
            store_id, menu_name, price, description
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
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed add menu: {str(e)}"
        )
    finally:
        connection.close()

    return {
        'menu_id': menu_id,
        'menu_put_url': menu_put_url,
        'menu_get_url': menu_get_url
    }

@router.post("/update/{menu_id}") 
def updateMenu(menu_id: int, menu: Menu):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
        
    try:
        cursor = connection.cursor()
        query = "UPDATE menu SET "
        values = []
        
        if menu.name:
            query += "menu_name = %s, "
            values.append(menu.name)
        if menu.price:
            query += "price = %s, "
            values.append(menu.price)
        if menu.description:
            query += "description = %s, "
            values.append(menu.description)
            
        query = query[:-2]  # 마지막 쉼표와 공백 제거
        query += " WHERE id = %s"
        
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
        return {
            'msg': "success",
            'menu_put_url': menu_put_url,
            'menu_get_url': menu_get_url
        }
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed update menu: {str(e)}"
        )
    finally:
        connection.close()

@router.delete("/delete/{menu_id}") 
def deleteeMenu(menu_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결

    try:
        cursor = connection.cursor()

        # Check if the menu exists
        cursor.execute("SELECT store_id FROM menu WHERE id = %s", (menu_id,))
        row = cursor.fetchone()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Menu with id {menu_id} not found"
            )

        # Delete the menu from the database
        cursor.execute("UPDATE menu SET is_deleted=1 WHERE id = %s", (menu_id,))
        connection.commit()

        return {'msg': "Menu deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete menu: {str(e)}"
        )

    finally:
        connection.close()