"""App version CRUD operations"""
import pymysql
from typing import List, Dict, Optional


def get_latest_by_platform(connection, platform: str) -> Optional[Dict]:
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            "SELECT * FROM app_versions WHERE platform = %s ORDER BY created_at DESC LIMIT 1",
            (platform,)
        )
        return cursor.fetchone()
    finally:
        cursor.close()


def get_all(connection) -> List[Dict]:
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("SELECT * FROM app_versions ORDER BY created_at DESC")
        return cursor.fetchall()
    finally:
        cursor.close()


def create(connection, platform: str, version: str, is_force_update: bool, memo: Optional[str]) -> Dict:
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            "INSERT INTO app_versions (platform, version, is_force_update, memo) VALUES (%s, %s, %s, %s)",
            (platform, version, int(is_force_update), memo)
        )
        connection.commit()
        new_id = cursor.lastrowid
        cursor.execute("SELECT * FROM app_versions WHERE id = %s", (new_id,))
        return cursor.fetchone()
    finally:
        cursor.close()


def update_force(connection, version_id: int, is_force_update: bool) -> Optional[Dict]:
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            "UPDATE app_versions SET is_force_update = %s WHERE id = %s",
            (int(is_force_update), version_id)
        )
        connection.commit()
        if cursor.rowcount == 0:
            return None
        cursor.execute("SELECT * FROM app_versions WHERE id = %s", (version_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
