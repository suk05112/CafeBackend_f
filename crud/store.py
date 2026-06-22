"""
Store CRUD operations
"""
import pymysql
from typing import Optional
from db.session import get_db_connection, close_db_connection

def update_inspection_status(store_id: int, status_value: str, inspection_msg: Optional[str] = None) -> bool:
    """매장 승인 상태 업데이트
    
    Args:
        store_id: 매장 ID
        status_value: 승인 상태 ('APPROVED', 'REJECTED', 'PENDING')
        inspection_msg: 승인/거부 메시지 (선택사항)
    
    Returns:
        업데이트 성공 여부 (True/False)
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        # store 존재 확인
        cursor.execute('SELECT id FROM store WHERE id = %s', (store_id,))
        store = cursor.fetchone()
        
        if not store:
            return False
        
        # inspection_msg가 None이면 빈 문자열로 처리
        msg = inspection_msg if inspection_msg is not None else ''
        
        query = """
            UPDATE store
            SET inspection_status = %s, inspection_msg = %s, updated_at = NOW()
            WHERE id = %s
        """
        cursor.execute(query, (status_value, msg, store_id))
        connection.commit()
        return cursor.rowcount > 0
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        close_db_connection(connection)

