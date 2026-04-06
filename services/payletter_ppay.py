"""페이레터 PPAY(통합 간편결제) 콜백용 해시·키 매핑·클라이언트 IP."""

import hashlib
import ipaddress
from typing import Any, Optional, Tuple

from loguru import logger
from starlette.requests import Request

from core.config import settings


def normalize_amount_for_hash(amount: Any) -> int:
    if amount is None:
        raise ValueError("amount is required")
    if isinstance(amount, bool):
        raise ValueError("invalid amount")
    if isinstance(amount, int):
        return amount
    if isinstance(amount, float):
        return int(amount)
    return int(float(str(amount).strip()))


def callback_payhash_hex(user_id: str, amount: Any, tid: str, payment_api_key: str) -> str:
    """PPAY 콜백 payhash: SHA256(user_id + amount + tid + 결제용 API Key)."""
    a = normalize_amount_for_hash(amount)
    raw = f"{user_id}{a}{tid}{payment_api_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_callback_payhash(
    user_id: str, amount: Any, tid: str, payhash: Any, payment_api_key: str
) -> bool:
    if payhash is None or payment_api_key is None:
        return False
    ph = str(payhash).strip()
    if not ph:
        return False
    expected = callback_payhash_hex(user_id, amount, tid, payment_api_key)
    return expected.lower() == ph.lower()


def resolve_payment_api_key_for_client_id(client_id: Optional[str]) -> Optional[str]:
    if not client_id:
        return None
    cid = str(client_id).strip()
    naver_cid = (settings.payletter_naver_client_id or "").strip()
    main_cid = (settings.payletter_client_id or "").strip()
    if naver_cid and cid == naver_cid:
        key = (settings.payletter_naver_payment_api_key or "").strip()
        return key or None
    if main_cid and cid == main_cid:
        key = (settings.payletter_payment_api_key or "").strip()
        return key or None
    return None


def _peer_is_trusted_reverse_proxy(peer: str) -> bool:
    """nginx 등 사설망/루프백에서 온 요청만 X-Forwarded 헤더 신뢰."""
    if not peer:
        return False
    try:
        ip = ipaddress.ip_address(peer)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False


def get_effective_client_ip(request: Request) -> str:
    """
    직접 연결이면 peer IP.
    루프백/사설망 peer(nginx 프록시)면 X-Real-IP, 없으면 X-Forwarded-For 첫 홉.
    """
    peer = ""
    if request.client:
        peer = (request.client.host or "").strip()
    if _peer_is_trusted_reverse_proxy(peer):
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip().split(",")[0].strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return peer


def payletter_callback_ip_allowlist() -> frozenset[str]:
    raw = (settings.payletter_callback_allowed_ips or "").strip()
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def check_payletter_callback_ip(request: Request) -> Tuple[bool, str, str]:
    """
    (허용 여부, effective_ip, 거절 사유).
    enforcement 꺼짐이면 항상 허용.
    """
    ip_eff = get_effective_client_ip(request)
    if not settings.payletter_callback_enforce_ip:
        return True, ip_eff, ""
    allow = payletter_callback_ip_allowlist()
    if not allow:
        logger.warning("payletter_callback_enforce_ip on but allowlist empty")
        return False, ip_eff, "allowlist_empty"
    if ip_eff in allow:
        return True, ip_eff, ""
    return False, ip_eff, "ip_not_allowed"
