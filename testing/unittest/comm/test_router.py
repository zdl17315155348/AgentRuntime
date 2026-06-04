from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter


def test_message_router_send_and_receive_consumes():
    r = MessageRouter()
    m1 = Message(from_agent="a", to_agent="b", payload={"k": 1})
    m2 = Message(from_agent="a", to_agent="b", payload={"k": 2})
    r.send(m1)
    r.send(m2)

    got = r.receive("b", limit=10)
    assert [m.payload for m in got] == [{"k": 1}, {"k": 2}]

    got2 = r.receive("b", limit=10)
    assert got2 == []


def test_message_router_limit():
    r = MessageRouter()
    r.send(Message(from_agent="a", to_agent="b", payload={"i": 1}))
    r.send(Message(from_agent="a", to_agent="b", payload={"i": 2}))
    got = r.receive("b", limit=1)
    assert len(got) == 1
    got2 = r.receive("b", limit=10)
    assert len(got2) == 1

