import pytest

from app.auth import create_token, decode_token


def test_expired_token_is_rejected():
    expired = create_token(1, ttl_seconds=-1)
    with pytest.raises(ValueError):
        decode_token(expired)
