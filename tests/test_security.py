"""
test_security.py — Tests unitarios de la capa de seguridad (sin HTTP).

Cubre:
- Hashing y verificación de contraseñas (bcrypt)
- Creación y validación de tokens JWT
"""

from datetime import timedelta

import pytest
from jose import jwt

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        """El hash de la contraseña no debe ser igual al texto plano."""
        password = "MiContraseña123!"
        hashed = get_password_hash(password)
        assert hashed != password

    def test_verify_correct_password(self):
        """verify_password devuelve True con la contraseña correcta."""
        password = "MiContraseña123!"
        hashed = get_password_hash(password)
        assert verify_password(password, hashed) is True

    def test_verify_wrong_password(self):
        """verify_password devuelve False con contraseña incorrecta."""
        hashed = get_password_hash("ContraseñaCorrecta")
        assert verify_password("ContraseñaIncorrecta", hashed) is False

    def test_same_password_different_hashes(self):
        """Dos hashes de la misma contraseña deben ser diferentes (bcrypt usa salt)."""
        password = "MismaContraseña"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)
        assert hash1 != hash2
        # Pero ambos deben verificar correctamente
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True


class TestJWTToken:
    def test_token_contains_subject(self):
        """El token generado debe contener el subject (user_id)."""
        token = create_access_token(subject=42)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert payload["sub"] == "42"

    def test_token_contains_expiration(self):
        """El token debe tener campo 'exp'."""
        token = create_access_token(subject=1)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert "exp" in payload

    def test_token_with_custom_expiration(self):
        """Token con expiración personalizada de 1 minuto es válido."""
        token = create_access_token(subject=1, expires_delta=timedelta(minutes=1))
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert payload["sub"] == "1"

    def test_token_string_subject(self):
        """Subject tipo string se almacena correctamente."""
        token = create_access_token(subject="admin@test.com")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert payload["sub"] == "admin@test.com"

    def test_invalid_token_raises(self):
        """Un token firmado con clave incorrecta lanza excepción al decodificar."""
        from jose import JWTError

        token = create_access_token(subject=1)
        with pytest.raises(JWTError):
            jwt.decode(token, "clave-incorrecta", algorithms=[settings.ALGORITHM])
