from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Hash import SHA256
import base64

_rsa_key = RSA.generate(2048)


def get_public_key_pem() -> str:
    return _rsa_key.publickey().export_key("PEM").decode("utf-8")


def decrypt_password(encrypted_b64: str) -> str:
    try:
        ciphertext = base64.b64decode(encrypted_b64)
        cipher = PKCS1_OAEP.new(_rsa_key, hashAlgo=SHA256)
        return cipher.decrypt(ciphertext).decode("utf-8")
    except Exception:
        raise ValueError("복호화 실패")
