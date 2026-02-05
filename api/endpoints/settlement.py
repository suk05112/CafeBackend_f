"""
Settlement API 엔드포인트
"""
import traceback
from fastapi import APIRouter, HTTPException, status

from loguru import logger

from models.settlement import Account
from crud import settlement as settlement_crud

router = APIRouter()


@router.post("/register/{store_id}")
def register_account(store_id: int, account: Account):
    """계좌 정보 등록"""
    try:
        settlement_crud.create_account(store_id, account)
        return {}
    except Exception as e:
        logger.error(f"Error in register_account: {traceback.format_exc()}")
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
        logger.error(f"Error in get_settlement_list: {traceback.format_exc()}")
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
        logger.error(f"Error in get_detail_settlements: {traceback.format_exc()}")
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
        logger.error(f"Error in get_account: {traceback.format_exc()}")
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
        logger.error(f"Error in update_account: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed update Account: {str(e)}"
        )