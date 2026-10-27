from unittest.mock import Mock

import pytest

from app.api.v1.endpoints import drone
from app.bootstrap_admin import create_initial_admin
from app.core.security import verify_password
from app.models.user import Rol, Usuario


@pytest.mark.parametrize("role, expected", [(None, 401), ("guardia", 403)])
def test_register_requires_admin(client, request, role, expected):
    headers = {} if role is None else {"Authorization": f"Bearer {request.getfixturevalue(role + '_token')}"}
    response = client.post(
        "/api/v1/auth/register",
        json={"nombre": "Intruso", "email": "new@test.com", "password": "Password123!", "rol_id": 1},
        headers=headers,
    )
    assert response.status_code == expected


@pytest.mark.parametrize("action, payload", [("connect", {}), ("takeoff", {"altitude": 10}), ("rtl", {})])
@pytest.mark.parametrize("role", [None, "guardia", "admin"])
def test_drone_permissions(client, request, monkeypatch, action, payload, role):
    service = Mock()
    monkeypatch.setattr(drone, "drone_service", service)
    headers = {} if role is None else {"Authorization": f"Bearer {request.getfixturevalue(role + '_token')}"}
    response = client.post(f"/api/v1/drone/{action}", json=payload, headers=headers)
    expected = 401 if role is None else 403 if role == "guardia" and action != "rtl" else 200
    assert response.status_code == expected
    if expected != 200:
        assert service.mock_calls == []
    else:
        assert len(service.mock_calls) == 1


@pytest.mark.parametrize("altitude", [-1, 0, 201, "NaN", "Infinity"])
def test_takeoff_invalid_altitude(client, admin_token, monkeypatch, altitude):
    service = Mock()
    monkeypatch.setattr(drone, "drone_service", service)
    response = client.post(
        "/api/v1/drone/takeoff",
        json={"altitude": altitude},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422
    assert service.mock_calls == []


def test_bootstrap_creates_roles_and_hashed_admin(db):
    db.query(Rol).delete()
    db.expunge_all()
    user = create_initial_admin(db, "Primer Admin", "first@test.com", "Password123!")
    assert user.rol.nombre == "ADMIN"
    assert verify_password("Password123!", user.password_hash)
    assert {rol.nombre for rol in db.query(Rol).all()} == {"ADMIN", "GUARDIA"}


def test_bootstrap_refuses_existing_admin(db, admin_user):
    with pytest.raises(ValueError, match="Ya existe"):
        create_initial_admin(db, "Otro Admin", "new@test.com", "Password123!")
    assert db.query(Usuario).count() == 1


def test_bootstrap_does_not_promote_existing_user(db, guardia_user):
    with pytest.raises(ValueError, match="correo ya existe"):
        create_initial_admin(db, "Otro Admin", guardia_user.email, "Password123!")
    assert guardia_user.rol.nombre == "GUARDIA"
