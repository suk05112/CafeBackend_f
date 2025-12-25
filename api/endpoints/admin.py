"""Admin API endpoints"""
import traceback
from fastapi import APIRouter, HTTPException, status, Query
from typing import Optional
from db.session import get_db_connection
from crud import admin as admin_crud
from crud import store as store_crud
from crud import menu as menu_crud
from models.store import StoreCreate
from models.menu import Menu

router = APIRouter()


@router.get("/dashboard/statistics")
def get_dashboard_statistics():
    """대시보드 통계 데이터"""
    connection = get_db_connection()
    try:
        result = admin_crud.get_dashboard_statistics(connection)
        return result
    except Exception as e:
        print(f"Error in get_dashboard_statistics: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/stores")
def get_stores(
    search: Optional[str] = Query(None, description="매장 이름, 사장님 이름으로 검색"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 항목 수")
):
    """매장 리스트 (관리자용, 페이지네이션)"""
    connection = get_db_connection()
    try:
        result = admin_crud.get_stores(connection, search, page, limit)
        return {
            'stores': result['items'],
            'pagination': {
                'total': result['total'],
                'page': result['page'],
                'limit': result['limit'],
                'total_pages': result['total_pages']
            }
        }
    except Exception as e:
        print(f"Error in get_stores: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/stores/{store_id}")
def get_store_detail(store_id: int):
    """매장 상세 정보"""
    connection = get_db_connection()
    try:
        store = admin_crud.get_store_detail(connection, store_id)
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        return store
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_store_detail: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/stores/{store_id}/menu")
def get_store_menus(store_id: int):
    """매장 메뉴 리스트"""
    connection = get_db_connection()
    try:
        menus = admin_crud.get_store_menus(connection, store_id)
        return {'menus': menus}
    except Exception as e:
        print(f"Error in get_store_menus: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/stores/{store_id}/giftcards")
def get_store_giftcards(
    store_id: int,
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(10, ge=1, le=100, description="페이지당 항목 수")
):
    """매장의 깊티(기프티콘) 리스트 (페이지네이션)"""
    connection = get_db_connection()
    try:
        result = admin_crud.get_store_giftcards(connection, store_id, page, limit)
        return {
            'giftcards': result['items'],
            'pagination': {
                'total': result['total'],
                'page': result['page'],
                'limit': result['limit'],
                'total_pages': result['total_pages']
            }
        }
    except Exception as e:
        print(f"Error in get_store_giftcards: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/users")
def get_users(
    search: Optional[str] = Query(None, description="이름, 아이디, 전화번호, ID로 검색"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 항목 수")
):
    """유저 리스트 (관리자용, 페이지네이션)"""
    connection = get_db_connection()
    try:
        result = admin_crud.get_users(connection, search, page, limit)
        return {
            'users': result['items'],
            'pagination': {
                'total': result['total'],
                'page': result['page'],
                'limit': result['limit'],
                'total_pages': result['total_pages']
            }
        }
    except Exception as e:
        print(f"Error in get_users: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/users/{user_id}")
def get_user_detail(user_id: int):
    """유저 상세 정보"""
    connection = get_db_connection()
    try:
        user = admin_crud.get_user_detail(connection, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_user_detail: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/users/{user_id}/orders")
def get_user_orders(user_id: int):
    """유저 주문 내역"""
    connection = get_db_connection()
    try:
        orders = admin_crud.get_user_orders(connection, user_id)
        return {'orders': orders}
    except Exception as e:
        print(f"Error in get_user_orders: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/users/{user_id}/giftcards")
def get_user_giftcards(user_id: int):
    """유저 기프티콘 리스트"""
    connection = get_db_connection()
    try:
        giftcards = admin_crud.get_user_giftcards(connection, user_id)
        return {'giftcards': giftcards}
    except Exception as e:
        print(f"Error in get_user_giftcards: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/orders")
def get_orders(
    search: Optional[str] = Query(None, description="주문번호, user id로 검색"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 항목 수")
):
    """주문 리스트 (관리자용, 페이지네이션)"""
    connection = get_db_connection()
    try:
        result = admin_crud.get_orders(connection, search, page, limit)
        return {
            'orders': result['items'],
            'pagination': {
                'total': result['total'],
                'page': result['page'],
                'limit': result['limit'],
                'total_pages': result['total_pages']
            }
        }
    except Exception as e:
        print(f"Error in get_orders: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/orders/{order_id}")
def get_order_detail(order_id: int):
    """주문 상세 정보"""
    connection = get_db_connection()
    try:
        order = admin_crud.get_order_detail(connection, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_order_detail: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/orders/{order_id}/giftcards")
def get_order_giftcards(order_id: int):
    """주문의 기프티콘 리스트"""
    connection = get_db_connection()
    try:
        giftcards = admin_crud.get_order_giftcards(connection, order_id)
        return {'giftcards': giftcards}
    except Exception as e:
        print(f"Error in get_order_giftcards: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/menus")
def get_all_menus(
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 항목 수")
):
    """전체 메뉴 리스트 (페이지네이션)"""
    connection = get_db_connection()
    try:
        result = admin_crud.get_all_menus(connection, page, limit)
        return {
            'menus': result['items'],
            'pagination': {
                'total': result['total'],
                'page': result['page'],
                'limit': result['limit'],
                'total_pages': result['total_pages']
            }
        }
    except Exception as e:
        print(f"Error in get_all_menus: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/notices")
def get_notices(
    target: Optional[str] = Query(None, description="'user' 또는 'owner', None이면 둘 다"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 항목 수")
):
    """공지사항 리스트 (페이지네이션)"""
    connection = get_db_connection()
    try:
        result = admin_crud.get_notices(connection, target, page, limit)
        return {
            'notices': result['items'],
            'pagination': {
                'total': result['total'],
                'page': result['page'],
                'limit': result['limit'],
                'total_pages': result['total_pages']
            }
        }
    except Exception as e:
        print(f"Error in get_notices: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.post("/notices")
def create_notice(notice: dict):
    """공지사항 등록
    
    Body:
        - target: 'user' 또는 'owner'
        - title: 공지사항 제목
        - content: 공지사항 내용
    """
    connection = get_db_connection()
    try:
        target = notice.get('target')
        title = notice.get('title')
        content = notice.get('content')
        
        if not target or target not in ['user', 'owner']:
            raise HTTPException(status_code=400, detail="target must be 'user' or 'owner'")
        
        if not title or not content:
            raise HTTPException(status_code=400, detail="title and content are required")
        
        notice_id = admin_crud.create_notice(connection, target, title, content)
        return {'message': 'Notice created successfully', 'id': notice_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in create_notice: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/notices/{target}/{notice_id}")
def get_notice_detail(target: str, notice_id: int):
    """공지사항 상세 조회"""
    connection = get_db_connection()
    try:
        if target not in ['user', 'owner']:
            raise HTTPException(status_code=400, detail="target must be 'user' or 'owner'")
        
        notice = admin_crud.get_notice_detail(connection, target, notice_id)
        if not notice:
            raise HTTPException(status_code=404, detail="Notice not found")
        return notice
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_notice_detail: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.put("/notices/{target}/{notice_id}")
def update_notice(target: str, notice_id: int, notice: dict):
    """공지사항 수정"""
    connection = get_db_connection()
    try:
        if target not in ['user', 'owner']:
            raise HTTPException(status_code=400, detail="target must be 'user' or 'owner'")
        
        title = notice.get('title')
        content = notice.get('content')
        
        success = admin_crud.update_notice(connection, target, notice_id, title, content)
        if not success:
            raise HTTPException(status_code=404, detail="Notice not found")
        return {'message': 'Notice updated successfully'}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in update_notice: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.delete("/notices/{target}/{notice_id}")
def delete_notice(target: str, notice_id: int):
    """공지사항 삭제"""
    connection = get_db_connection()
    try:
        if target not in ['user', 'owner']:
            raise HTTPException(status_code=400, detail="target must be 'user' or 'owner'")
        
        success = admin_crud.delete_notice(connection, target, notice_id)
        if not success:
            raise HTTPException(status_code=404, detail="Notice not found")
        return {'message': 'Notice deleted successfully'}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in delete_notice: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.post("/test/store")
def create_test_store(store: StoreCreate):
    """테스트 매장 추가"""
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
        print(f"Error in create_test_store: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed register store: {str(e)}"
        )


@router.post("/test/menu/{store_id}")
def create_test_menu(store_id: int, menu: Menu):
    """테스트 메뉴 추가"""
    try:
        if menu.store_id != store_id:
            raise HTTPException(status_code=400, detail="store_id in path and body must match")
        
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
        print(f"Error in create_test_menu: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed add menu: {str(e)}"
        )

