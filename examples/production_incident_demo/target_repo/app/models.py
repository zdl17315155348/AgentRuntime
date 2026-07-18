from pydantic import BaseModel


class User(BaseModel):
    id: int
    username: str
    password: str


class OrderCreate(BaseModel):
    item: str
    quantity: int = 1


class Order(BaseModel):
    id: int
    user_id: int
    item: str
    quantity: int
