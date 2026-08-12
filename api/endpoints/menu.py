"""
Menu API 엔드포인트
"""
import traceback
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status

from loguru import logger

from models.menu import Menu
from crud import menu as menu_crud
from core.exceptions import InternalError

router = APIRouter()


@router.get("/recommend")
def get_recommended_menus(
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    radius: float = Query(5.0),
    district_code: Optional[str] = Query(None),
    limit: int = Query(20),
    cursor: Optional[str] = Query(None),
):
    """주변 매장 메뉴 추천. lat+lng → GPS 5km 반경, district_code → 지역구 기준."""
    if limit < 1:
        limit = 20
    if limit > 100:
        limit = 100

    gps_mode = lat is not None and lng is not None
    district_mode = district_code is not None

    if not gps_mode and not district_mode:
        raise HTTPException(status_code=400, detail="lat/lng 또는 district_code 중 하나는 필수입니다.")

    try:
        if gps_mode:
            result = menu_crud.get_recommended_menus_by_location(lat, lng, radius, limit, cursor)
        else:
            result = menu_crud.get_recommended_menus_by_district(district_code, limit, cursor)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_recommended_menus: {traceback.format_exc()}")
        raise InternalError(e, "menu")


@router.get("/vouchers")
def get_voucher_menus():
    """금액권(교환권) 상품 리스트 조회. 액면가 오름차순."""
    try:
        vouchers = menu_crud.get_voucher_menus()
        return {"voucherList": vouchers}
    except Exception as e:
        logger.error(f"Error in get_voucher_menus: {traceback.format_exc()}")
        raise InternalError(e, "vouchers")


@router.get("/list/{store_id}")
def get_menu_list(store_id: int):
    """매장별 메뉴 리스트 조회"""
    try:
        menus = menu_crud.get_menus_by_store(store_id)
        return {"menuList": menus}
    except Exception as e:
        logger.error(f"Error in get_menu_list: {traceback.format_exc()}")
        raise InternalError(e, "menu")


@router.post("/add/{store_id}")
def add_menu(store_id: int, menu: Menu):
    """메뉴 추가"""
    try:
        if menu.store_id != store_id:
            raise HTTPException(status_code=400, detail="store_id mismatch")
        
        menu_id = menu_crud.create_menu(store_id, menu)
        s3_urls = menu_crud.generate_menu_s3_urls(store_id, menu_id)
        menu_crud.save_menu_image_key(menu_id, s3_urls['image_key'])

        return {
            'menu_id': menu_id,
            'menu_put_url': s3_urls['menu_put_url'],
            'menu_get_url': s3_urls['menu_get_url']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in add_menu: {traceback.format_exc()}")
        raise InternalError(e, "add_menu")


@router.delete("/delete/{menu_id}")
def delete_menu(menu_id: int):
    """메뉴 삭제 (soft delete)"""
    try:
        success = menu_crud.delete_menu(menu_id)
        if not success:
            raise HTTPException(status_code=404, detail="Menu not found")
        return {"message": "메뉴가 삭제되었습니다.", "menu_id": menu_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_menu: {traceback.format_exc()}")
        raise InternalError(e, "delete_menu")


@router.post("/update/{menu_id}")
def update_menu(menu_id: int, menu: Menu):
    """메뉴 정보 업데이트"""
    try:
        success = menu_crud.update_menu(menu_id, menu.store_id, menu)
        if not success:
            raise HTTPException(status_code=404, detail="Menu not found")

        if not menu.change_image:
            return {'menu_id': menu_id}

        s3_urls = menu_crud.generate_menu_s3_urls(menu.store_id, menu_id)
        menu_crud.save_menu_image_key(menu_id, s3_urls['image_key'])

        return {
            'menu_id': menu_id,
            'menu_put_url': s3_urls['menu_put_url'],
            'menu_get_url': s3_urls['menu_get_url']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_menu: {traceback.format_exc()}")
        raise InternalError(e, "update_menu")

