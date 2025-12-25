"""
Store API 엔드포인트
"""
import traceback
from fastapi import APIRouter, HTTPException, status
from typing import Optional

from loguru import logger

# schemas는 models를 직접 참조
from models.store import StoreCreate, InspectionStatusUpdate
from crud import store as store_crud
from core.s3_config import S3_CLIENT, BUCKET_NAME

router = APIRouter()

s3 = S3_CLIENT
bucket_name = BUCKET_NAME


@router.get("/list")
def get_store_list():
    """매장 리스트 조회"""
    try:
        stores = store_crud.get_all_stores()
        return {"store": stores}
    except Exception as e:
        logger.error(f"Error in get_store_list: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류 발생: {str(e)}"
        )


@router.get("/owner/list/{owner_id}")
def get_owner_store_list(owner_id: int):
    """오너별 매장 리스트 조회"""
    try:
        stores = store_crud.get_stores_by_owner(owner_id)
        return {"ownerStoreList": stores}
    except Exception as e:
        logger.error(f"Error in get_owner_store_list: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류 발생: {str(e)}"
        )


@router.get("/info/{store_id}")
def get_store_info(store_id: int):
    """매장 상세 정보 조회"""
    try:
        store = store_crud.get_store_by_id(store_id)
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        return store
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_store_info: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류 발생: {str(e)}"
        )


@router.post("/register")
async def register_store(store: StoreCreate):
    """매장 등록"""
    try:
        store_id = store_crud.create_store(store)
        s3_urls = store_crud.generate_store_s3_urls(store_id, store.store_photo_cnt)
        
        return {
            'store_id': store_id,
            'store_logo_url': s3_urls['store_logo_url'],
            'store_photo_urls': s3_urls['store_photo_urls'],
            'bankBook_put_url': s3_urls['bankBook_put_url'],
            'business_put_url': s3_urls['business_put_url']
        }
    except Exception as e:
        logger.error(f"Error in register_store: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed register store: {str(e)}"
        )


@router.post("/update/{store_id}")
def update_store(store_id: int, store: StoreCreate):
    """매장 정보 업데이트"""
    try:
        success = store_crud.update_store(store_id, store)
        if not success:
            raise HTTPException(status_code=404, detail="Store not found")
        
        # S3 URLs 생성 (업데이트 후에도 필요할 수 있음)
        s3_urls = store_crud.generate_store_s3_urls(store_id, store.store_photo_cnt)
        
        return {
            'store_id': store_id,
            'store_logo_url': s3_urls['store_logo_url'],
            'store_photo_urls': s3_urls['store_photo_urls'],
            'bankBook_put_url': s3_urls['bankBook_put_url'],
            'business_put_url': s3_urls['business_put_url']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_store: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed update store: {str(e)}"
        )


@router.post("/delete/{store_id}")
def delete_store(store_id: int):
    """매장 삭제"""
    try:
        success = store_crud.delete_store(store_id)
        if not success:
            raise HTTPException(status_code=404, detail="Store not found")
        return {"success": True, "message": "Store deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_store: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed delete store: {str(e)}"
        )


@router.patch("/{store_id}/inspection")
def update_inspection_status(store_id: int, status_update: InspectionStatusUpdate):
    """매장 승인 상태 업데이트"""
    # inspection_status를 문자열로 변환 (정수인 경우)
    status_value = status_update.inspection_status
    
    if isinstance(status_value, int):
        # 정수를 문자열로 매핑
        status_mapping = {
            0: "PENDING",
            1: "APPROVED",
            2: "REJECTED",
        }
        if status_value in status_mapping:
            status_value = status_mapping[status_value]
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid inspection status: {status_value}. Must be 0 (PENDING), 1 (APPROVED), or 2 (REJECTED)"
            )
    elif isinstance(status_value, str):
        # 문자열을 대문자로 정규화
        status_value = status_value.upper()
        # 유효한 문자열 값 검증
        valid_statuses = ["PENDING", "APPROVED", "REJECTED"]
        if status_value not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid inspection status: {status_value}. Must be one of: PENDING, APPROVED, REJECTED"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid inspection status type: {type(status_value)}. Must be int or str"
        )
    
    try:
        # inspection_msg는 Optional이므로 None이면 빈 문자열로 처리
        inspection_msg = status_update.inspection_msg if status_update.inspection_msg else ""
        
        success = store_crud.update_inspection_status(store_id, status_value, inspection_msg)
        if not success:
            raise HTTPException(status_code=404, detail=f"Store with id {store_id} not found or status not updated")
        return {"message": f"Store {store_id} inspection status updated to {status_value}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_inspection_status: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to update inspection status: {str(e)}")

