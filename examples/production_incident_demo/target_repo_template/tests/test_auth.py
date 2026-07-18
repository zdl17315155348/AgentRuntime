from app.auth import verify_password


def test_wrong_password_returns_401():
    assert verify_password("alice", "wrong") is None
