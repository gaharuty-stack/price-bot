import hashlib
import hmac
import json

from config import SECRET_KEY


def sign_data(data: dict) -> str:
    payload = data.copy()
    payload.pop("integrity", None)
    message = json.dumps(payload, sort_keys=True, default=str)
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(data: dict, signature: str) -> bool:
    payload = data.copy()
    payload.pop("integrity", None)
    message = json.dumps(payload, sort_keys=True, default=str)
    expected = hmac.new(
        SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
