from app import database
from app.models import Order, OrderCreate, User


def create_order(payload: OrderCreate, user: User, idempotency_key: str | None = None) -> Order:
    if idempotency_key and idempotency_key in database.idempotency_keys:
        return database.orders[database.idempotency_keys[idempotency_key]]
    order_id = database.next_order_id
    database.next_order_id += 1
    order = Order(id=order_id, user_id=user.id, item=payload.item, quantity=payload.quantity)
    database.orders[order_id] = order
    if idempotency_key:
        database.idempotency_keys[idempotency_key] = order_id
    return order


def get_order(order_id: int, user: User) -> Order | None:
    order = database.orders.get(order_id)
    if order is None or order.user_id != user.id:
        return None
    return order
