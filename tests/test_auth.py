"""
test_auth.py — Tests de autenticación y gestión de usuarios.

Cubre:
- POST /api/v1/auth/register  → registro exitoso, email duplicado, rol inexistente
- POST /api/v1/auth/login     → login exitoso, contraseña incorrecta, usuario inexistente
- GET  /api/v1/auth/me        → perfil con token válido, sin token, token inválido
"""

import pytest


# =============================================================================
# REGISTER
# =============================================================================


class TestRegister:
    ENDPOINT = "/api/v1/auth/register"

    def test_register_admin_success(self, client):
        """Registrar un nuevo ADMIN devuelve 201 con datos del usuario."""
        payload = {
            "nombre": "Juan Admin",
            "email": "juan@test.com",
            "password": "Password123!",
            "rol_id": 1,  # ADMIN (seed en conftest)
        }
        r = client.post(self.ENDPOINT, json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["email"] == "juan@test.com"
        assert data["nombre"] == "Juan Admin"
        assert data["activo"] is True
        assert "password" not in data
        assert "password_hash" not in data

    def test_register_guardia_success(self, client):
        """Registrar un GUARDIA devuelve 201."""
        payload = {
            "nombre": "María Guardia",
            "email": "maria@test.com",
            "password": "Password123!",
            "rol_id": 2,  # GUARDIA
        }
        r = client.post(self.ENDPOINT, json=payload)
        assert r.status_code == 201
        assert r.json()["rol"]["nombre"] == "GUARDIA"

    def test_register_duplicate_email(self, client, admin_user):
        """Registrar con email ya existente devuelve 400."""
        payload = {
            "nombre": "Otro Admin",
            "email": admin_user.email,  # ya existe
            "password": "Password123!",
            "rol_id": 1,
        }
        r = client.post(self.ENDPOINT, json=payload)
        assert r.status_code == 400
        assert "correo" in r.json()["detail"].lower()

    def test_register_invalid_rol(self, client):
        """Registrar con rol_id inexistente devuelve 404."""
        payload = {
            "nombre": "Sin Rol",
            "email": "sinrol@test.com",
            "password": "Password123!",
            "rol_id": 999,
        }
        r = client.post(self.ENDPOINT, json=payload)
        assert r.status_code == 404

    def test_register_password_too_short(self, client):
        """Contraseña menor a 6 caracteres devuelve 422."""
        payload = {
            "nombre": "Test",
            "email": "short@test.com",
            "password": "abc",
            "rol_id": 1,
        }
        r = client.post(self.ENDPOINT, json=payload)
        assert r.status_code == 422

    def test_register_invalid_email(self, client):
        """Email inválido devuelve 422."""
        payload = {
            "nombre": "Test",
            "email": "no-es-email",
            "password": "Password123!",
            "rol_id": 1,
        }
        r = client.post(self.ENDPOINT, json=payload)
        assert r.status_code == 422


# =============================================================================
# LOGIN
# =============================================================================


class TestLogin:
    ENDPOINT = "/api/v1/auth/login"

    def test_login_admin_success(self, client, admin_user):
        """Login exitoso devuelve token Bearer."""
        r = client.post(
            self.ENDPOINT,
            json={"email": admin_user.email, "password": "Admin1234!"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 20

    def test_login_wrong_password(self, client, admin_user):
        """Contraseña incorrecta devuelve 401."""
        r = client.post(
            self.ENDPOINT,
            json={"email": admin_user.email, "password": "MalPassword"},
        )
        assert r.status_code == 401

    def test_login_nonexistent_user(self, client):
        """Email inexistente devuelve 401."""
        r = client.post(
            self.ENDPOINT,
            json={"email": "noexiste@test.com", "password": "Password123!"},
        )
        assert r.status_code == 401

    def test_login_inactive_user(self, client, db):
        """Usuario inactivo devuelve 400."""
        from app.core.security import get_password_hash
        from app.models.user import Rol, Usuario

        rol = db.query(Rol).filter(Rol.nombre == "GUARDIA").first()
        inactivo = Usuario(
            nombre="Inactivo",
            email="inactivo@test.com",
            password_hash=get_password_hash("Password123!"),
            rol_id=rol.id,
            activo=False,
        )
        db.add(inactivo)
        db.commit()

        r = client.post(
            self.ENDPOINT,
            json={"email": "inactivo@test.com", "password": "Password123!"},
        )
        assert r.status_code == 400

    def test_login_invalid_email_format(self, client):
        """Email con formato inválido devuelve 422."""
        r = client.post(
            self.ENDPOINT,
            json={"email": "noesunmail", "password": "Password123!"},
        )
        assert r.status_code == 422


# =============================================================================
# ME (perfil autenticado)
# =============================================================================


class TestMe:
    ENDPOINT = "/api/v1/auth/me"

    def test_me_with_valid_token(self, client, admin_token, admin_user):
        """GET /me con token válido devuelve el perfil del usuario."""
        r = client.get(self.ENDPOINT, headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == admin_user.email
        assert data["nombre"] == admin_user.nombre
        assert "password_hash" not in data

    def test_me_without_token(self, client):
        """GET /me sin token devuelve 401."""
        r = client.get(self.ENDPOINT)
        assert r.status_code == 401

    def test_me_with_invalid_token(self, client):
        """GET /me con token malformado devuelve 401."""
        r = client.get(self.ENDPOINT, headers={"Authorization": "Bearer token.invalido.xxx"})
        assert r.status_code == 401

    def test_me_guardia_role(self, client, guardia_token, guardia_user):
        """GET /me devuelve correctamente el rol GUARDIA."""
        r = client.get(self.ENDPOINT, headers={"Authorization": f"Bearer {guardia_token}"})
        assert r.status_code == 200
        assert r.json()["rol"]["nombre"] == "GUARDIA"
