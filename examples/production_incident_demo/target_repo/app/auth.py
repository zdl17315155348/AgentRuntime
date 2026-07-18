import base64
import json
import time

from app.database import users


def verify_password(username: str, password: str):
    user = users.get(username)
    if user is None:
        return None
    if user.password != password:
        return None
    return user


def create_token(user_id: int, ttl_seconds: int = 3600) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + ttl_seconds}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_token(token: str):
    payload = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("token expired")
    return int(payload["sub"])
