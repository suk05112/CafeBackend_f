"""
FCM 푸시 메시지 전송 서비스
"""
from firebase_admin import messaging
from app.database import get_db_connection
import pymysql
from loguru import logger

def send_fcm_notification_to_user(user_id: int, title: str, body: str):
    """
    User에게 FCM 푸시 메시지 전송
    user_id로 모든 활성화된 FCM token을 찾아서 메시지 전송
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # user_id로 활성화된 모든 FCM token 조회 (서비스 푸시 동의한 것만)
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
        
        # FCM 메시지 생성
        fcm_tokens = [token['fcm_token'] for token in tokens]
        
        notification = messaging.Notification(
            title=title,
            body=body
        )
        
        # send_multicast가 있으면 사용, 없으면 개별 메시지로 전송
        try:
            message = messaging.MulticastMessage(
                notification=notification,
                tokens=fcm_tokens
            )
            response = messaging.send_multicast(message)
            sent_count = response.success_count
            failed_count = response.failure_count
        except AttributeError:
            # send_multicast가 없으면 개별 메시지로 전송
            sent_count = 0
            failed_count = 0
            for token in fcm_tokens:
                try:
                    message = messaging.Message(
                        notification=notification,
                        token=token
                    )
                    messaging.send(message)
                    sent_count += 1
                except Exception:
                    failed_count += 1
        
        logger.info(f"FCM notification sent to user_id {user_id}: {sent_count} successful, {failed_count} failed")
        
        return {
            "sent": sent_count,
            "failed": failed_count,
            "total": len(fcm_tokens)
        }
        
    except Exception as e:
        logger.error(f"Error sending FCM notification to user {user_id}: {str(e)}")
        return {"sent": 0, "error": str(e)}
    finally:
        cursor.close()
        connection.close()

def send_fcm_notification_to_owner(owner_id: int, title: str, body: str):
    """
    Owner에게 FCM 푸시 메시지 전송
    owner_id로 모든 활성화된 FCM token을 찾아서 메시지 전송
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # owner_id로 활성화된 모든 FCM token 조회 (서비스 푸시 동의한 것만)
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
        
        # FCM 메시지 생성
        fcm_tokens = [token['fcm_token'] for token in tokens]
        
        notification = messaging.Notification(
            title=title,
            body=body
        )
        
        # send_multicast가 있으면 사용, 없으면 개별 메시지로 전송
        try:
            message = messaging.MulticastMessage(
                notification=notification,
                tokens=fcm_tokens
            )
            response = messaging.send_multicast(message)
            sent_count = response.success_count
            failed_count = response.failure_count
        except AttributeError:
            # send_multicast가 없으면 개별 메시지로 전송
            sent_count = 0
            failed_count = 0
            for token in fcm_tokens:
                try:
                    message = messaging.Message(
                        notification=notification,
                        token=token
                    )
                    messaging.send(message)
                    sent_count += 1
                except Exception:
                    failed_count += 1
        
        logger.info(f"FCM notification sent to owner_id {owner_id}: {sent_count} successful, {failed_count} failed")
        
        return {
            "sent": sent_count,
            "failed": failed_count,
            "total": len(fcm_tokens)
        }
        
    except Exception as e:
        logger.error(f"Error sending FCM notification to owner {owner_id}: {str(e)}")
        return {"sent": 0, "error": str(e)}
    finally:
        cursor.close()
        connection.close()

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
            # 마케팅 푸시 동의한 사용자만
            cursor.execute('''
                SELECT DISTINCT fcm_token 
                FROM user_push_tokens 
                WHERE allow_marketing_push = 1
            ''')
        else:
            # 서비스 푸시 동의한 사용자만
            cursor.execute('''
                SELECT DISTINCT fcm_token 
                FROM user_push_tokens 
                WHERE allow_service_push = 1
            ''')
        
        tokens = cursor.fetchall()
        
        if not tokens:
            logger.info("No FCM tokens found for users")
            return {"sent": 0, "message": "No active FCM tokens found"}
        
        # FCM 메시지 생성
        fcm_tokens = [token['fcm_token'] for token in tokens]
        
        # Firebase는 한 번에 최대 500개 토큰까지만 전송 가능
        # 여러 배치로 나눠서 전송
        batch_size = 500
        total_sent = 0
        total_failed = 0
        
        for i in range(0, len(fcm_tokens), batch_size):
            batch_tokens = fcm_tokens[i:i + batch_size]
            
            # send_multicast가 없으면 개별 메시지로 전송
            try:
                message = messaging.MulticastMessage(
                    notification=messaging.Notification(
                        title=title,
                        body=body
                    ),
                    tokens=batch_tokens
                )
                response = messaging.send_multicast(message)
                total_sent += response.success_count
                total_failed += response.failure_count
            except AttributeError:
                # send_multicast가 없으면 개별 메시지로 전송
                notification = messaging.Notification(
                    title=title,
                    body=body
                )
                for token in batch_tokens:
                    try:
                        message = messaging.Message(
                            notification=notification,
                            token=token
                        )
                        messaging.send(message)
                        total_sent += 1
                    except Exception:
                        total_failed += 1
        
        logger.info(f"FCM notification sent to all users: {total_sent} successful, {total_failed} failed")
        
        return {
            "sent": total_sent,
            "failed": total_failed,
            "total": len(fcm_tokens)
        }
        
    except Exception as e:
        logger.error(f"Error sending FCM notification to all users: {str(e)}")
        return {"sent": 0, "error": str(e)}
    finally:
        cursor.close()
        connection.close()

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
            # 마케팅 푸시 동의한 사용자만
            cursor.execute('''
                SELECT DISTINCT fcm_token 
                FROM owner_push_tokens 
                WHERE allow_marketing_push = 1
            ''')
        else:
            # 서비스 푸시 동의한 사용자만
            cursor.execute('''
                SELECT DISTINCT fcm_token 
                FROM owner_push_tokens 
                WHERE allow_service_push = 1
            ''')
        
        tokens = cursor.fetchall()
        
        if not tokens:
            logger.info("No FCM tokens found for owners")
            return {"sent": 0, "message": "No active FCM tokens found"}
        
        # FCM 메시지 생성
        fcm_tokens = [token['fcm_token'] for token in tokens]
        
        # Firebase는 한 번에 최대 500개 토큰까지만 전송 가능
        # 여러 배치로 나눠서 전송
        batch_size = 500
        total_sent = 0
        total_failed = 0
        
        for i in range(0, len(fcm_tokens), batch_size):
            batch_tokens = fcm_tokens[i:i + batch_size]
            
            # send_multicast가 없으면 send_each 사용
            try:
                message = messaging.MulticastMessage(
                    notification=messaging.Notification(
                        title=title,
                        body=body
                    ),
                    tokens=batch_tokens
                )
                response = messaging.send_multicast(message)
                total_sent += response.success_count
                total_failed += response.failure_count
            except AttributeError:
                # send_multicast가 없으면 개별 메시지로 전송
                notification = messaging.Notification(
                    title=title,
                    body=body
                )
                for token in batch_tokens:
                    try:
                        message = messaging.Message(
                            notification=notification,
                            token=token
                        )
                        messaging.send(message)
                        total_sent += 1
                    except Exception:
                        total_failed += 1
        
        logger.info(f"FCM notification sent to all owners: {total_sent} successful, {total_failed} failed")
        
        return {
            "sent": total_sent,
            "failed": total_failed,
            "total": len(fcm_tokens)
        }
        
    except Exception as e:
        logger.error(f"Error sending FCM notification to all owners: {str(e)}")
        return {"sent": 0, "error": str(e)}
    finally:
        cursor.close()
        connection.close()

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

