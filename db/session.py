import pymysql
from pymysql.cursors import DictCursor
from queue import Queue
import threading
from core.config import settings

class ConnectionPool:
    def __init__(self, max_connections=20):
        self.max_connections = max_connections
        self._pool = Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._created = 0
        
    def _create_connection(self):
        return pymysql.connect(
        host=settings.db_host,
        user=settings.db_user,
        passwd=settings.db_password,
        db=settings.db_name,
        port=settings.db_port,
            cursorclass=DictCursor,
            connect_timeout=10,
            autocommit=False,
            charset='utf8mb4',
            read_timeout=30,
            write_timeout=30
        )
    
    def get_connection(self):
        try:
            conn = self._pool.get_nowait()
        except Exception:
            conn = None

        if conn is not None:
            try:
                conn.ping(reconnect=True)
                return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                with self._lock:
                    if self._created > 0:
                        self._created -= 1

        with self._lock:
            if self._created < self.max_connections:
                self._created += 1
                create_new = True
            else:
                create_new = False
        if create_new:
            try:
                return self._create_connection()
            except Exception:
                with self._lock:
                    if self._created > 0:
                        self._created -= 1
                raise
        try:
            return self._pool.get(timeout=5)
        except Exception:
            raise Exception("DB 연결 풀 초과: 잠시 후 다시 시도해주세요")

    def return_connection(self, conn):
        rollback_ok = True
        try:
            if not conn.get_autocommit():
                conn.rollback()
        except Exception:
            rollback_ok = False

        if not rollback_ok:
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                if self._created > 0:
                    self._created -= 1
            return

        try:
            self._pool.put_nowait(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                if self._created > 0:
                    self._created -= 1

# 전역 연결 풀 (최대 20개 연결)
_pool = ConnectionPool(max_connections=20)

def get_db_connection():
    """연결 풀에서 연결 가져오기"""
    return _pool.get_connection()

def close_db_connection(conn):
    """연결을 풀에 반환"""
    _pool.return_connection(conn)
