from app.models import Order, User

users = {
    "alice": User(id=1, username="alice", password="alice-secret"),
    "bob": User(id=2, username="bob", password="bob-secret"),
}

orders = {
    1: Order(id=1, user_id=1, item="book", quantity=1),
    2: Order(id=2, user_id=2, item="pen", quantity=2),
}
idempotency_keys = {}
next_order_id = 3


def reset_state():
    global orders, idempotency_keys, next_order_id
    orders = {
        1: Order(id=1, user_id=1, item="book", quantity=1),
        2: Order(id=2, user_id=2, item="pen", quantity=2),
    }
    idempotency_keys = {}
    next_order_id = 3
