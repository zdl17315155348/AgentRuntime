from app.auth import verify_password
from app.orders import get_order


def test_user_cannot_read_other_users_order():
    bob = verify_password("bob", "bob-secret")
    assert get_order(1, bob) is None
