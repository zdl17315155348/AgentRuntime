from app.auth import verify_password
from app.models import OrderCreate
from app.orders import create_order


def test_same_idempotency_key_returns_same_order():
    user = verify_password("alice", "alice-secret")
    first = create_order(OrderCreate(item="lamp", quantity=1), user, idempotency_key="idem-1")
    second = create_order(OrderCreate(item="lamp", quantity=1), user, idempotency_key="idem-1")
    assert first.id == second.id
