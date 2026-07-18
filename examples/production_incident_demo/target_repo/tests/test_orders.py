from app.auth import verify_password
from app.models import OrderCreate
from app.orders import create_order


def test_create_order_keeps_response_shape():
    user = verify_password("alice", "alice-secret")
    order = create_order(OrderCreate(item="desk", quantity=1), user)
    assert {"id", "user_id", "item", "quantity"} <= set(order.model_dump())
