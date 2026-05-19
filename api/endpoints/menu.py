"""
Menu API 엔드포인트
"""
import traceback
from fastapi import APIRouter, HTTPException, status

from loguru import logger

# schemas는 models를 직접 참조
from models.menu import Menu
from crud import menu as menu_crud

router = APIRouter()


@router.get("/list/{store_id}")
def get_menu_list(store_id: int):
    """매장별 메뉴 리스트 조회"""
    try:
        menus = menu_crud.get_menus_by_store(store_id)
        return {"menuList": menus}
    except Exception as e:
        logger.error(f"Error in get_menu_list: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류 발생: {str(e)}"
        )


@router.post("/add/{store_id}")
def add_menu(store_id: int, menu: Menu):
    """메뉴 추가"""
    try:
        if menu.store_id != store_id:
            raise HTTPException(status_code=400, detail="store_id mismatch")
        
        menu_id = menu_crud.create_menu(store_id, menu)
        s3_urls = menu_crud.generate_menu_s3_urls(store_id, menu_id)
        
        return {
            'menu_id': menu_id,
            'menu_put_url': s3_urls['menu_put_url'],
            'menu_get_url': s3_urls['menu_get_url']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in add_menu: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed add menu: {str(e)}"
        )


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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed delete menu: {str(e)}"
        )


@router.post("/update/{menu_id}")
def update_menu(menu_id: int, menu: Menu):
    """메뉴 정보 업데이트"""
    try:
        success = menu_crud.update_menu(menu_id, menu)
        if not success:
            raise HTTPException(status_code=404, detail="Menu not found")
        
        s3_urls = menu_crud.generate_menu_s3_urls(menu.store_id, menu_id)
        
        return {
            'menu_id': menu_id,
            'menu_put_url': s3_urls['menu_put_url'],
            'menu_get_url': s3_urls['menu_get_url']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_menu: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed update menu: {str(e)}"
        )

