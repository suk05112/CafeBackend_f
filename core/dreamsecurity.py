"""
드림시큐리티 mobileOK 표준창 암복호화 유틸
mok_keyInfo.dat 복호화 → ServiceId, ClientPrivateKey, ServerPublicKey 추출
"""
import base64
import hashlib
import json

from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import unpad


def _load_keyinfo(dat_path: str, password: str) -> dict:
    """
    mok_keyInfo.dat(AES-256-CBC 암호화) 복호화 → dict 반환
    키: SHA-256(password), IV: 앞 16바이트
    """
    with open(dat_path, "rb") as f:
        raw = f.read()

    key = hashlib.sha256(password.encode("utf-8")).digest()
    iv = raw[:16]
    ciphertext = raw[16:]

    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
    return json.loads(plaintext.decode("utf-8"))


_keyinfo_cache: dict = {}


def get_keyinfo(dat_path: str, password: str) -> dict:
    """캐시된 keyinfo 반환 (프로세스 생애주기 동안 1회 복호화)"""
    if dat_path not in _keyinfo_cache:
        _keyinfo_cache[dat_path] = _load_keyinfo(dat_path, password)
    return _keyinfo_cache[dat_path]


def encrypt_client_info(json_data: str, server_public_key_pem: str) -> str:
    """
    JSONData를 RSA-OAEP(SHA-256, MGF1-SHA-256)로 암호화 후 Base64 반환
    """
    pub_key = RSA.import_key(server_public_key_pem)
    cipher = PKCS1_OAEP.new(pub_key, hashAlgo=SHA256, mgfunc=lambda x, y: PKCS1_OAEP.MGF1(x, y, SHA256))
    encrypted = cipher.encrypt(json_data.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def decrypt_mok_result(encrypt_mok_result: str, client_private_key_pem: str) -> dict:
    """
    encryptMOKResult 복호화:
    1. '|' 구분 → encryptKeyIvHashData + encryptResultData
    2. RSA PKCS#8(ClientPrivateKey)로 encryptKeyIvHashData 복호화 → AES key(32) + IV(16) + hash(32)
    3. encryptResultData를 AES-256-CBC 복호화
    4. SHA-256 해시 무결성 검증
    5. 개인정보 JSON 반환
    """
    parts = encrypt_mok_result.split("|")
    if len(parts) != 2:
        raise ValueError("encryptMOKResult 형식 오류: '|' 구분자 없음")

    encrypt_key_iv_hash_b64, encrypt_result_b64 = parts

    # RSA 복호화
    priv_key = RSA.import_key(client_private_key_pem)
    rsa_cipher = PKCS1_OAEP.new(priv_key, hashAlgo=SHA256, mgfunc=lambda x, y: PKCS1_OAEP.MGF1(x, y, SHA256))
    key_iv_hash = rsa_cipher.decrypt(base64.b64decode(encrypt_key_iv_hash_b64))

    aes_key = key_iv_hash[:32]
    aes_iv = key_iv_hash[32:48]
    expected_hash = key_iv_hash[48:80]

    # AES-256-CBC 복호화
    aes_cipher = AES.new(aes_key, AES.MODE_CBC, aes_iv)
    result_bytes = unpad(aes_cipher.decrypt(base64.b64decode(encrypt_result_b64)), AES.block_size)

    # SHA-256 무결성 검증
    actual_hash = hashlib.sha256(result_bytes).digest()
    if actual_hash != expected_hash:
        raise ValueError("encryptMOKResult 무결성 검증 실패")

    return json.loads(result_bytes.decode("utf-8"))
