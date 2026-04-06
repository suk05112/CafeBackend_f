"""페이레터 PPAY(통합 간편결제) 콜백용 해시·키 매핑."""

import hashlib
from typing import Any, Optional

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
