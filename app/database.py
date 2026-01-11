# app/database.py는 db/session.py의 연결 풀을 사용하도록 리다이렉트
from db.session import get_db_connection, close_db_connection

# 하위 호환성을 위해 close_db_connection도 export
__all__ = ['get_db_connection', 'close_db_connection']