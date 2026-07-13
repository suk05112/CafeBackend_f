"""
FCM 푸시 메시지 전송 서비스
"""
from firebase_admin import messaging
from app.firebase_init import user_app, owner_app
from db.session import get_db_connection, close_db_connection
import pymysql
from loguru import logger
from app.system_logger import log_external_api_error

def send_fcm_notification_to_user(user_id: int, title: str, body: str):
    """
    User에게 FCM 푸시 메시지 전송
    user_id로 모든 활성화된 FCM token을 찾아서 메시지 전송
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''
            SELECT fcm_token
            FROM user_push_tokens
            WHERE user_id = %s
            AND allow_service_push = 1
        ''', (user_id,))

        tokens = cursor.fetchall()

        if not tokens:
            logger.info(f"No FCM tokens found for user_id: {user_id}")
            return {"sent": 0, "message": "No active FCM tokens found"}

        fcm_tokens = [token['fcm_token'] for token in tokens]

        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            tokens=fcm_tokens
        )
        response = messaging.send_each_for_multicast(message, app=user_app)

        logger.info(f"FCM notification sent to user_id {user_id}: {response.success_count} successful, {response.failure_count} failed")

        return {
            "sent": response.success_count,
            "failed": response.failure_count,
            "total": len(fcm_tokens)
        }

    except Exception as e:
        logger.error(f"Error sending FCM notification to user {user_id}: {str(e)}")
        log_external_api_error("FCM", f"user_id={user_id} 푸시 전송 실패", e)
        return {"sent": 0, "error": str(e)}
    finally:
        cursor.close()
        close_db_connection(connection)

def send_fcm_notification_to_owner(owner_id: int, title: str, body: str):
    """
    Owner에게 FCM 푸시 메시지 전송
    owner_id로 모든 활성화된 FCM token을 찾아서 메시지 전송
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''
            SELECT fcm_token
            FROM owner_push_tokens
            WHERE owner_id = %s
            AND allow_service_push = 1
        ''', (owner_id,))

        tokens = cursor.fetchall()

        if not tokens:
            logger.info(f"No FCM tokens found for owner_id: {owner_id}")
            return {"sent": 0, "message": "No active FCM tokens found"}

        fcm_tokens = [token['fcm_token'] for token in tokens]

        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            tokens=fcm_tokens
        )
        response = messaging.send_each_for_multicast(message, app=owner_app)

        logger.info(f"FCM notification sent to owner_id {owner_id}: {response.success_count} successful, {response.failure_count} failed")

        return {
            "sent": response.success_count,
            "failed": response.failure_count,
            "total": len(fcm_tokens)
        }

    except Exception as e:
        logger.error(f"Error sending FCM notification to owner {owner_id}: {str(e)}")
        log_external_api_error("FCM", f"owner_id={owner_id} 푸시 전송 실패", e)
        return {"sent": 0, "error": str(e)}
    finally:
        cursor.close()
        close_db_connection(connection)

def send_fcm_notification_to_all_users(title: str, body: str, use_marketing: bool = False):
    """
    모든 User에게 FCM 푸시 메시지 전송
    use_marketing=True: allow_marketing_push=1인 사용자만
    use_marketing=False: allow_service_push=1인 사용자만
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        if use_marketing:
            cursor.execute('SELECT DISTINCT fcm_token FROM user_push_tokens WHERE allow_marketing_push = 1')
        else:
            cursor.execute('SELECT DISTINCT fcm_token FROM user_push_tokens WHERE allow_service_push = 1')

        tokens = cursor.fetchall()

        if not tokens:
            logger.info("No FCM tokens found for users")
            return {"sent": 0, "message": "No active FCM tokens found"}

        fcm_tokens = [token['fcm_token'] for token in tokens]

        batch_size = 500
        total_sent = 0
        total_failed = 0

        for i in range(0, len(fcm_tokens), batch_size):
            batch_tokens = fcm_tokens[i:i + batch_size]
            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                tokens=batch_tokens
            )
            response = messaging.send_each_for_multicast(message, app=user_app)
            total_sent += response.success_count
            total_failed += response.failure_count

        logger.info(f"FCM notification sent to all users: {total_sent} successful, {total_failed} failed")

        return {
            "sent": total_sent,
            "failed": total_failed,
            "total": len(fcm_tokens)
        }

    except Exception as e:
        logger.error(f"Error sending FCM notification to all users: {str(e)}")
        log_external_api_error("FCM", "전체 유저 푸시 전송 실패", e)
        return {"sent": 0, "error": str(e)}
    finally:
        cursor.close()
        close_db_connection(connection)

def send_fcm_notification_to_all_owners(title: str, body: str, use_marketing: bool = False):
    """
    모든 Owner에게 FCM 푸시 메시지 전송
    use_marketing=True: allow_marketing_push=1인 사용자만
    use_marketing=False: allow_service_push=1인 사용자만
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        if use_marketing:
            cursor.execute('SELECT DISTINCT fcm_token FROM owner_push_tokens WHERE allow_marketing_push = 1')
        else:
            cursor.execute('SELECT DISTINCT fcm_token FROM owner_push_tokens WHERE allow_service_push = 1')

        tokens = cursor.fetchall()

        if not tokens:
            logger.info("No FCM tokens found for owners")
            return {"sent": 0, "message": "No active FCM tokens found"}

        fcm_tokens = [token['fcm_token'] for token in tokens]

        batch_size = 500
        total_sent = 0
        total_failed = 0

        for i in range(0, len(fcm_tokens), batch_size):
            batch_tokens = fcm_tokens[i:i + batch_size]
            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                tokens=batch_tokens
            )
            response = messaging.send_each_for_multicast(message, app=owner_app)
            total_sent += response.success_count
            total_failed += response.failure_count

        logger.info(f"FCM notification sent to all owners: {total_sent} successful, {total_failed} failed")

        return {
            "sent": total_sent,
            "failed": total_failed,
            "total": len(fcm_tokens)
        }

    except Exception as e:
        logger.error(f"Error sending FCM notification to all owners: {str(e)}")
        log_external_api_error("FCM", "전체 오너 푸시 전송 실패", e)
        return {"sent": 0, "error": str(e)}
    finally:
        cursor.close()
        close_db_connection(connection)

def send_fcm_notification_to_all(title: str, body: str, use_marketing: bool = False):
    """
    모든 User와 Owner에게 FCM 푸시 메시지 전송
    use_marketing=True: allow_marketing_push=1인 사용자만
    use_marketing=False: allow_service_push=1인 사용자만
    """
    user_result = send_fcm_notification_to_all_users(title, body, use_marketing)
    owner_result = send_fcm_notification_to_all_owners(title, body, use_marketing)

    return {
        "users": user_result,
        "owners": owner_result,
        "total_sent": user_result.get("sent", 0) + owner_result.get("sent", 0),
        "total_failed": user_result.get("failed", 0) + owner_result.get("failed", 0)
    }
