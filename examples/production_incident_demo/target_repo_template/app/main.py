from fastapi import FastAPI, Header, HTTPException

from app.auth import create_token, decode_token, verify_password
from app.database import reset_state, users
from app.models import OrderCreate
from app.orders import create_order, get_order

app = FastAPI(title="Order Incident Demo")


def current_user(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing token")
    user_id = decode_token(authorization.removeprefix("Bearer "))
    for user in users.values():
        if user.id == user_id:
            return user
    raise HTTPException(status_code=401, detail="invalid token")


@app.post("/login")
def login(payload: dict):
    user = verify_password(str(payload.get("username", "")), str(payload.get("password", "")))
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"access_token": create_token(user.id), "token_type": "bearer"}


@app.post("/orders")
def post_order(payload: OrderCreate, authorization: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)):
    return create_order(payload, current_user(authorization), idempotency_key)


@app.get("/orders/{order_id}")
def read_order(order_id: int, authorization: str | None = Header(default=None)):
    order = get_order(order_id, current_user(authorization))
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.post("/__reset")
def reset():
    reset_state()
    return {"ok": True}
