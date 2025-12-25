import pymysql
from core.config import settings

def get_db_connection():
    return pymysql.connect(
        host=settings.db_host,
        user=settings.db_user,
        passwd=settings.db_password,
        db=settings.db_name,
        port=settings.db_port,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=180,
        autocommit=True
    )
