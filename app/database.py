import pymysql
from app.settings import settings

def get_db_connection():
    return pymysql.connect(
    # return await aiomysql.create_pool(
        host=settings.db_host,
        user=settings.db_user,
        passwd=settings.db_password,
        db=settings.db_name,
        port=settings.db_port,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=180,   # 기본 10초
        autocommit=True
        # minsize=1,
        # maxsize=10
    )