import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize("secret", ["", "short"])
def test_rejects_short_secret(secret):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, SECRET_KEY=secret)


def test_requires_secret(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
