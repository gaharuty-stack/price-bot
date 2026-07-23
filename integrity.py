import hashlib
import hmac
import time
import json

SECRET_KEY = "your_secret_key_here_2048bits"  # Замени на свой

def sign_data(data: dict) -> str:
    """Подписывает данные с помощью HMAC-SHA256"""
    data_copy = data.copy()
    data_copy["_timestamp"] = int(time.time())
    message = json.dumps(data_copy, sort_keys=True)
    signature = hmac.new(
        SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature

def verify_signature(data: dict, signature: str) -> bool:
    """Проверяет подпись"""
    data_copy = data.copy()
    data_copy.pop("_timestamp", None)
    message = json.dumps(data_copy, sort_keys=True)
    expected = hmac.new(
        SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
