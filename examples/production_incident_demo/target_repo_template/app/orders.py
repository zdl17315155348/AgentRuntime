from app import database
from app.models import Order, OrderCreate, User


def create_order(payload: OrderCreate, user: User, idempotency_key: str | None = None) -> Order:
    order_id = database.next_order_id
    database.next_order_id += 1
    order = Order(id=order_id, user_id=user.id, item=payload.item, quantity=payload.quantity)
    database.orders[order_id] = order
    return order


def get_order(order_id: int, user: User) -> Order | None:
    return database.orders.get(order_id)
