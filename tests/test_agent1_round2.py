"""tests/test_agent1_round2.py — Agente 1 (Ronda 2): Auth, Usuarios, Ajustes y Auditoría.

Cubre los cambios de la Ronda 2 del Plan Maestro:
- `deps.validate_ws_token` para autenticación JWT en WebSockets.
- `puesto` en UserCreate persistido por POST /auth/register.
- Filtros `?q=` y `?activo=` en GET /users/.
- `hydrate_runtime_settings_from_db` (hidratación de ajustes al arranque).
- `ensure_roles_and_demo_users` (seed idempotente de roles y cuentas demo).
- Invalidación global de sesiones vía `tokens_invalidados_antes_de`.
"""

import pytest

from app.api import deps
from app.api.v1.endpoints.settings import hydrate_runtime_settings_from_db
from app.core.normative import get_normative_config, update_normative_config
from app.models.setting import AjustesOperativos
from app.models.user import Usuario
from app.services.seed_service import ensure_roles_and_demo_users


@pytest.fixture(autouse=True)
def restore_normative_config():
    """Los tests de hidratación mutan la config normativa global; restaurarla
    para no contaminar otros módulos de la suite."""
    original = get_normative_config()
    yield
    update_normative_config(original)


def _login(client, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# validate_ws_token
# ---------------------------------------------------------------------------


def test_validate_ws_token_valido_devuelve_usuario(db, client, admin_token, admin_user):
    user = deps.validate_ws_token(db, admin_token)
    assert user is not None
    assert user.id == admin_user.id


def test_validate_ws_token_revocado_devuelve_none(db, client, admin_token):
    # logout revoca el jti del token en uso
    resp = client.post("/api/v1/auth/logout", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert deps.validate_ws_token(db, admin_token) is None


def test_validate_ws_token_usuario_inactivo_devuelve_none(db, client, admin_token, admin_user):
    admin_user.activo = False
    db.commit()
    assert deps.validate_ws_token(db, admin_token) is None


def test_validate_ws_token_rol_no_permitido_devuelve_none(db, client, guardia_token):
    assert deps.validate_ws_token(db, guardia_token, allowed_roles=("ADMIN",)) is None
    user = deps.validate_ws_token(db, guardia_token, allowed_roles=("GUARDIA",))
    assert user is not None


def test_validate_ws_token_basura_devuelve_none(db):
    assert deps.validate_ws_token(db, "token-inventado") is None
    assert deps.validate_ws_token(db, "") is None
    assert deps.validate_ws_token(db, None) is None


# ---------------------------------------------------------------------------
# Registro con puesto
# ---------------------------------------------------------------------------


def test_register_persiste_puesto(client, db, admin_token):
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "nombre": "Guardia Puesto",
            "email": "guardia.puesto@uaq.mx",
            "password": "Guardia123!",
            "rol_id": 2,
            "puesto": "Guardia de Seguridad Nocturno",
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["puesto"] == "Guardia de Seguridad Nocturno"
    row = db.query(Usuario).filter(Usuario.email == "guardia.puesto@uaq.mx").first()
    assert row is not None and row.puesto == "Guardia de Seguridad Nocturno"


# ---------------------------------------------------------------------------
# Filtros ?q= y ?activo= en GET /users/
# ---------------------------------------------------------------------------


def test_users_filtro_q_por_nombre(client, admin_token, guardia_user):
    resp = client.get("/api/v1/users/?q=Guardia Test", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    emails = {u["email"] for u in resp.json()}
    assert guardia_user.email in emails


def test_users_filtro_q_sin_resultados(client, admin_token):
    resp = client.get("/api/v1/users/?q=no-existe-xyz", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_users_filtro_activo(client, db, admin_token, guardia_user):
    guardia_user.activo = False
    db.commit()

    resp = client.get("/api/v1/users/?activo=true", headers=_auth(admin_token))
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert guardia_user.email not in emails

    resp = client.get("/api/v1/users/?activo=false", headers=_auth(admin_token))
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert guardia_user.email in emails


# ---------------------------------------------------------------------------
# hydrate_runtime_settings_from_db
# ---------------------------------------------------------------------------


def test_hydrate_runtime_settings_crea_fila_y_sincroniza(db):
    # Semilla: fila singleton con valores distintos a los defaults de fábrica
    row = AjustesOperativos(
        altitud_minima_m=15.0,
        altitud_maxima_m=123.0,
        peso_maximo_kg=9.5,
        hora_apertura="07:30",
        hora_cierre="19:45",
    )
    db.add(row)
    db.commit()

    hydrate_runtime_settings_from_db(db)

    cfg = get_normative_config()
    assert cfg.altitud_minima_m == 15.0
    assert cfg.altitud_maxima_m == 123.0
    assert cfg.peso_maximo_kg == 9.5
    assert cfg.hora_apertura == "07:30"
    assert cfg.hora_cierre == "19:45"
    assert db.query(AjustesOperativos).count() == 1


def test_hydrate_runtime_settings_sin_fila_crea_defaults(db):
    assert db.query(AjustesOperativos).count() == 0
    hydrate_runtime_settings_from_db(db)
    row = db.query(AjustesOperativos).first()
    assert row is not None
    assert getattr(row, "scheduler_enabled", False) is False


# ---------------------------------------------------------------------------
# ensure_roles_and_demo_users
# ---------------------------------------------------------------------------


def test_seed_roles_idempotente(db):
    from app.models.user import Rol

    ensure_roles_and_demo_users(db)  # roles ya existen por conftest
    ensure_roles_and_demo_users(db)  # segunda llamada no duplica
    nombres = {r.nombre for r in db.query(Rol).all()}
    assert {"ADMIN", "GUARDIA"} <= nombres


def test_seed_demo_users_crea_cuentas_e_idempotente(db):
    users = ensure_roles_and_demo_users(db, seed_demo_users=True)
    assert "academico@uaq.mx" in users
    assert "seguridad@uaq.mx" in users
    assert users["academico@uaq.mx"].rol.nombre == "ADMIN"
    assert users["seguridad@uaq.mx"].rol.nombre == "GUARDIA"

    # Idempotente: no duplica ni altera cuentas existentes
    total_antes = db.query(Usuario).count()
    again = ensure_roles_and_demo_users(db, seed_demo_users=True)
    assert db.query(Usuario).count() == total_antes
    assert again["academico@uaq.mx"].id == users["academico@uaq.mx"].id


def test_seed_demo_users_login_funciona(db, client):
    ensure_roles_and_demo_users(db, seed_demo_users=True)
    resp = _login(client, "academico@uaq.mx", "academico")
    assert resp.status_code == 200, resp.text
    resp = _login(client, "seguridad@uaq.mx", "seguridad")
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Invalidación global de sesiones (tokens_invalidados_antes_de)
# ---------------------------------------------------------------------------


def test_reset_password_invalida_sesion_del_usuario(client, db, admin_token, guardia_user):
    # Token emitido antes del reset
    resp = _login(client, guardia_user.email, "Guardia1234!")
    assert resp.status_code == 200
    guardia_tok = resp.json()["access_token"]

    # Admin restablece la contraseña del guardia
    resp = client.post(
        f"/api/v1/users/{guardia_user.id}/reset-password",
        json={"new_password": "NuevaClave99!"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text

    # El token anterior queda invalidado aunque el jti no esté revocado
    assert deps.validate_ws_token(db, guardia_tok) is None
    resp = client.get("/api/v1/auth/me", headers=_auth(guardia_tok))
    assert resp.status_code == 401


def test_change_password_invalida_sesiones_anteriores(client, db, guardia_user):
    resp = _login(client, guardia_user.email, "Guardia1234!")
    old_token = resp.json()["access_token"]

    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Guardia1234!", "new_password": "ClaveNueva99!"},
        headers=_auth(old_token),
    )
    assert resp.status_code == 200, resp.text
    assert deps.validate_ws_token(db, old_token) is None

    # Login con la nueva contraseña sí funciona
    resp = _login(client, guardia_user.email, "ClaveNueva99!")
    assert resp.status_code == 200, resp.text
