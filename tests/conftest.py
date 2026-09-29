"""
conftest.py — Fixtures compartidos para toda la suite de tests.

Estrategia:
- Base de datos en memoria (SQLite) para no tocar PostgreSQL.
- Se crea el esquema completo antes de cada test y se destruye al terminar.
- El TestClient de FastAPI sobreescribe la dependencia get_db para usar
  la sesión de test en lugar de la sesión de producción.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.core.security import get_password_hash
from app.db.base_class import Base
from app.main import app
from app.models.user import Rol, Usuario

# ---------------------------------------------------------------------------
# Motor SQLite en memoria — aislado por sesión de test
# ---------------------------------------------------------------------------
SQLALCHEMY_TEST_URL = "sqlite:///:memory:"

engine_test = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # Una sola conexión compartida → permite FK entre sesiones
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def db():
    """
    Sesión de base de datos limpia para cada test.
    Crea todas las tablas antes del test y las elimina al terminar.
    """
    Base.metadata.create_all(bind=engine_test)
    session = TestingSessionLocal()

    # Seed: roles mínimos necesarios
    admin_rol = Rol(nombre="ADMIN", descripcion="Administrador del sistema")
    guardia_rol = Rol(nombre="GUARDIA", descripcion="Guardia de seguridad")
    session.add_all([admin_rol, guardia_rol])
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine_test)


@pytest.fixture(scope="function")
def client(db):
    """
    TestClient de FastAPI con la DB de test inyectada vía override de dependencias.
    """

    def override_get_db():
        try:
            yield db
        finally:
            pass  # El fixture `db` se encarga del cierre

    app.dependency_overrides[deps.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_user(db) -> Usuario:
    """Usuario ADMIN ya registrado en la DB de test."""
    rol = db.query(Rol).filter(Rol.nombre == "ADMIN").first()
    user = Usuario(
        nombre="Admin Test",
        email="admin@test.com",
        password_hash=get_password_hash("Admin1234!"),
        rol_id=rol.id,
        activo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def guardia_user(db) -> Usuario:
    """Usuario GUARDIA ya registrado en la DB de test."""
    rol = db.query(Rol).filter(Rol.nombre == "GUARDIA").first()
    user = Usuario(
        nombre="Guardia Test",
        email="guardia@test.com",
        password_hash=get_password_hash("Guardia1234!"),
        rol_id=rol.id,
        activo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def admin_token(client, admin_user) -> str:
    """JWT válido para el usuario ADMIN."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": admin_user.email, "password": "Admin1234!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture()
def guardia_token(client, guardia_user) -> str:
    """JWT válido para el usuario GUARDIA."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": guardia_user.email, "password": "Guardia1234!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]
