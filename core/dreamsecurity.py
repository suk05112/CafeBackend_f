import base64
import hashlib
import json
import os
import urllib.parse
from datetime import datetime, timezone

import httpx
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import unpad

from core.config import settings


def _load_mok_key_info() -> dict:
    """mok_keyInfo.dat을 복호화하여 ServiceId, ClientPrivateKey, ServerPublicKey 반환"""
    key_file_path = settings.mok_key_file_path
    password = settings.mok_key_password

    with open(key_file_path, "rb") as f:
        encrypted_data = f.read()

    # SHA-256으로 password 2회 해싱하여 AES-256 키와 IV 생성
    password_bytes = password.encode("utf-8")
    hash1 = hashlib.sha256(password_bytes).digest()  # 32바이트
    hash2 = hashlib.sha256(hash1).digest()           # 32바이트

    aes_key = hash1[:16] + hash2[16:]  # Hash1 앞 16 + Hash2 뒤 16 = 32바이트
    aes_iv = hash2[:16]                # Hash2 앞 16바이트

    cipher = AES.new(aes_key, AES.MODE_CBC, aes_iv)
    decrypted = unpad(cipher.decrypt(encrypted_data), AES.block_size)
    return json.loads(decrypted.decode("utf-8"))


_mok_key_info: dict | None = None


def get_mok_key_info() -> dict:
    global _mok_key_info
    if _mok_key_info is None:
        _mok_key_info = _load_mok_key_info()
    return _mok_key_info


def generate_encrypt_req_client_info(client_tx_id: str) -> str:
    """clientTxId를 RSA-OAEP로 암호화하여 encryptReqClientInfo 반환"""
    key_info = get_mok_key_info()
    server_public_key_b64 = key_info["ServerPublicKey"]

    request_time = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    json_data = json.dumps({
        "version": "V2",
        "clientTxId": client_tx_id,
        "requestTime": request_time,
    }, ensure_ascii=False)

    public_key_bytes = base64.b64decode(server_public_key_b64)
    rsa_key = RSA.import_key(public_key_bytes)
    cipher = PKCS1_OAEP.new(rsa_key, hashAlgo=SHA256, mgfunc=lambda x, y: PKCS1_OAEP.MGF1(x, y, SHA256))
    encrypted = cipher.encrypt(json_data.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def decrypt_mok_result(encrypt_mok_result: str) -> dict:
    """encryptMOKResult를 복호화하여 개인정보 dict 반환"""
    key_info = get_mok_key_info()
    client_private_key_b64 = key_info["ClientPrivateKey"]

    # | 구분자로 분리
    parts = encrypt_mok_result.split("|")
    if len(parts) != 2:
        raise ValueError("Invalid encryptMOKResult format")
    encrypt_key_iv_hash_data = parts[0]
    encrypt_result_data = parts[1]

    # RSA 복호화로 keyIvHashData 추출
    private_key_bytes = base64.b64decode(client_private_key_b64)
    rsa_key = RSA.import_key(private_key_bytes)
    cipher = PKCS1_OAEP.new(rsa_key, hashAlgo=SHA256, mgfunc=lambda x, y: PKCS1_OAEP.MGF1(x, y, SHA256))
    key_iv_hash_data = cipher.decrypt(base64.b64decode(encrypt_key_iv_hash_data)).decode("utf-8")

    # keyIv와 hashData 분리
    kv_parts = key_iv_hash_data.split("|")
    if len(kv_parts) != 2:
        raise ValueError("Invalid keyIvHashData format")
    key_iv_bytes = base64.b64decode(kv_parts[0])  # 48바이트
    expected_hash = kv_parts[1]

    aes_key = key_iv_bytes[:32]  # 앞 32바이트
    aes_iv = key_iv_bytes[32:]   # 다음 16바이트

    # AES-256-CBC 복호화
    cipher = AES.new(aes_key, AES.MODE_CBC, aes_iv)
    decrypted = unpad(cipher.decrypt(base64.b64decode(encrypt_result_data)), AES.block_size)

    # SHA-256 무결성 검증
    actual_hash = base64.b64encode(hashlib.sha256(decrypted).digest()).decode("utf-8")
    if actual_hash != expected_hash:
        raise ValueError("Hash verification failed")

    return json.loads(decrypted.decode("utf-8"))


async def request_mok_verification(encrypt_mok_key_token: str) -> dict:
    """드림시큐리티 검증 서버에 토큰 전달 후 encryptMOKResult 수신"""
    env = os.getenv("ENV", "dev")
    if env in ["prod", "production"]:
        url = "https://cert.mobile-ok.com/gui/service/v1/result/request"
    else:
        url = "https://scert.mobile-ok.com/gui/service/v1/result/request"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            url,
            headers={"Content-Type": "application/json; charset=UTF-8"},
            json={"encryptMOKKeyToken": encrypt_mok_key_token},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("resultCode") != "2000":
        raise ValueError(f"MOK verification failed: {data.get('resultMsg')}")

    return data
