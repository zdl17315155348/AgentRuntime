import pytest

from app.auth import create_token, decode_token, verify_password
from app.models import OrderCreate
from app.orders import create_order, get_order


def test_ownership_and_idempotency_and_expiration():
    alice = verify_password("alice", "alice-secret")
    bob = verify_password("bob", "bob-secret")
    assert get_order(1, bob) is None
    first = create_order(OrderCreate(item="chair", quantity=1), alice, idempotency_key="same-key")
    second = create_order(OrderCreate(item="chair", quantity=1), alice, idempotency_key="same-key")
    assert first.id == second.id
    expired = create_token(1, ttl_seconds=-1)
    with pytest.raises(ValueError):
        decode_token(expired)
