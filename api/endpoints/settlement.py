"""
Settlement API 엔드포인트
"""
import logging
import traceback
from fastapi import APIRouter, HTTPException, status, Depends

from loguru import logger

import pymysql
from db.session import get_db_connection, close_db_connection
from models.settlement import Account
from crud import settlement as settlement_crud
from app.auth.auth_dependency import verify_firebase_token

router = APIRouter()
cloudwatch_logger = logging.getLogger("cafe_backend")


@router.post("/register/{store_id}")
def register_account(store_id: int, account: Account, user=Depends(verify_firebase_token)):
    """계좌 정보 등록"""
    if user is not None:
        uid = user.get("uid")
        connection = get_db_connection()
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        try:
            cursor.execute("SELECT id FROM owner WHERE uid = %s LIMIT 1", (uid,))
            db_owner = cursor.fetchone()
            if not db_owner:
                raise HTTPException(status_code=403, detail="Forbidden")
            cursor.execute("SELECT owner_id FROM store WHERE id = %s LIMIT 1", (store_id,))
            store = cursor.fetchone()
            if not store or store["owner_id"] != db_owner["id"]:
                raise HTTPException(status_code=403, detail="Forbidden")
        finally:
            cursor.close()
            close_db_connection(connection)

    try:
        settlement_crud.create_account(store_id, account)
        return {}
    except HTTPException:
        raise
    except Exception as e:
        err_msg = f"settlement register_account error: {traceback.format_exc()}"
        logger.error(err_msg)
        cloudwatch_logger.error(err_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed register Account: {str(e)}"
        )


@router.get("/list/{store_id}")
def get_settlement_list(store_id: int):
    """매장별 정산 리스트 조회"""
    try:
        settlements = settlement_crud.get_settlements_by_store(store_id)
        return {'settlements': settlements}
    except Exception as e:
        err_msg = f"settlement get_settlement_list error: {traceback.format_exc()}"
        logger.error(err_msg)
        cloudwatch_logger.error(err_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed getSettlementAmountsByDate: {str(e)}"
        )


@router.get("/detail/{settlement_id}")
def get_detail_settlements(settlement_id: int):
    """정산 상세 내역 조회"""
    try:
        details = settlement_crud.get_settlement_detail(settlement_id)
        return {'detail_settlements': details}
    except Exception as e:
        err_msg = f"settlement get_detail_settlements error: {traceback.format_exc()}"
        logger.error(err_msg)
        cloudwatch_logger.error(err_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed getDetailSettlements: {str(e)}"
        )


@router.get("/info/{store_id}")
def get_account(store_id: int):
    """계좌 정보 조회"""
    try:
        account = settlement_crud.get_account_by_store(store_id)
        if not account:
            return {'account': {}}
        return {'account': account}
    except Exception as e:
        err_msg = f"settlement get_account error: {traceback.format_exc()}"
        logger.error(err_msg)
        cloudwatch_logger.error(err_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed get Account: {str(e)}"
        )


@router.put("/account/{store_id}")
def update_account(store_id: int, account: Account):
    """계좌 정보 변경"""
    try:
        settlement_crud.update_account(store_id, account)
        return {'message': 'Account updated successfully'}
    except Exception as e:
        err_msg = f"settlement update_account error: {traceback.format_exc()}"
        logger.error(err_msg)
        cloudwatch_logger.error(err_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed update Account: {str(e)}"
        )