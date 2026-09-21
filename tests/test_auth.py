from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.services.security import hash_secret
from app.services.settings import get_default_profile

client = TestClient(app)


def _set_password(password: str) -> None:
    with SessionLocal() as db:
        profile = get_default_profile(db)
        profile.password_hash = hash_secret(password)
        db.commit()


def test_login_success() -> None:
    _set_password("StrongPassword123!")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "pharmacist@example.com", "password": "StrongPassword123!"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["profile"]["email"] == "pharmacist@example.com"


def test_login_failure_invalid_password() -> None:
    _set_password("StrongPassword123!")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "pharmacist@example.com", "password": "WrongPassword123!"},
    )

    assert response.status_code == 401
    assert "Invalid" in response.json()["detail"]
