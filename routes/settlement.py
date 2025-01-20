from fastapi import APIRouter, HTTPException
import pymysql
import app.database as database
from app.database import get_db_connection

from models.settlement import Account

router = APIRouter()

@router.post("/register/{store_id}")
def registerAccount(store_id: int, account: Account):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴
      
    try:   
        query = """
            INSERT INTO Account ( 
                store_id, name, code, bank, account
                ) VALUES (
              {}, '{}', '{}', '{}', '{}'
            ); 
        """.format(
            store_id,
            account.name,
            account.code,
            account.bank,
            account.account
        )
        cursor.execute(query)
        connection.commit()

        return {}
        
    except Exception as e:
        msg = "failed register Account"
        print(f"Error during register Account: {e}")
        
        raise HTTPException(status_code=500, detail=f"Error: {str(e)} {msg}")
        # return {"statusCode": 500, "msg": f"Error: {str(e)}"}
    finally:        
        cursor.close()
        connection.close()
        
# 정산날짜별로 묶어서 정산 금액 리턴
@router.get("/list/{store_id}")
def getSettlementListByStore(store_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결
    cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴
      
    try:   
        query = """
            SELECT * 
            FROM `Settlement`
            WHERE store_id = %s order by settlement_date desc;
        """
        cursor.execute(
            query,
            (store_id,)
        )
        
        results = cursor.fetchall()
        settlements =  []
        
        # 결과 처리
        for result in results:
            total_price = result['total_price'] if result['total_price'] is not None else 0

            settlements.append({
                'settlement_id': result['settlement_id'],
                'total_price': total_price,
                'settlement_msg' : result['settlement_msg'],
                'settlement_date' : result['settlement_date'],
                'settlement_period' : result['settlement_period'],
                'status' : result['status'],
            })

        print(settlements)
        return {
            'settlements': settlements,
        }
        
    except Exception as e:
        msg = "failed getSettlementAmountsByDate"
        print(f"Error during getSettlementAmountsByDate: {e}")
        
        raise HTTPException(status_code=500, detail=f"Error: {str(e)} {msg}")
        # return {"statusCode": 500, "msg": f"Error: {str(e)}"}
    finally:        
        cursor.close()
        connection.close()
        
# 정산주기별 상세 구매내역 리턴
@router.get("/detail/{settlement_id}")
def getDetailSettlements(settlement_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결\
    cursor = connection.cursor(pymysql.cursors.DictCursor) # DB에 접속 및 DB 객체를 가져옴
      
    try:   
        query = """
            SELECT 
                m.name,
                o.price,
                g.used_time,
                o.commission
            FROM 
                Settlement s
            JOIN 
                `Order` o ON s.store_id = o.store_id 
            JOIN 
                Order_Gifticon og ON o.id = og.order_id  
            JOIN 
                Gifticon g ON og.gifticon_id = g.id  
            JOIN 
                Menu m ON g.menu_id = m.menuId
            WHERE s.settlement_id = %s  
            AND g.use_yn = 1
            ORDER BY settlement_date desc;
        """
        cursor.execute(
            query,
            (settlement_id,)
        )
        
        results = cursor.fetchall()
        settlements =  []
        
        # 결과 처리
        for result in results:
            commission = result['commission'] if result['commission'] is not None else 0

            settlements.append({
                'menu_name': result['name'],
                'commission': commission,
                'price' : result['price'],
                'deposit' : result['price'] - commission,
                'used_time' : result['used_time'],
            })

        print(settlements)
        return {
            'detail_settlements': settlements,
        }
        
    except Exception as e:
        msg = "failed getDetailSettlements"
        print(f"Error during getDetailSettlements: {e}")
        
        raise HTTPException(status_code=500, detail=f"Error: {str(e)} {msg}")
    finally:        
        cursor.close()
        connection.close()
        