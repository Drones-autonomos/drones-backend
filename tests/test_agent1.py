"""tests/test_agent1.py — Agente 1: Auth, Usuarios, Perfil, Ajustes y Auditoría.

Cubre los cambios introducidos por el Agente 1 del Plan Maestro:
- Login con expected_role + rate limiting + auditoría de accesos.
- Registro con bloqueo de dominios de correo personal.
- Perfil propio (PATCH /auth/me), preferencias (PATCH /auth/me/preferences).
- Cambio de contraseña, logout y refresh con revocación de jti.
- Administración de usuarios (listado, PATCH, reset-password, baja lógica,
  protección del último administrador activo).
- Persistencia de la ventana operativa en ajustes_operativos.
- Exportación del registro de auditoría con verificación de cadena SHA-256.
"""

import pytest
from sqlalchemy import update

from app.core.normative import get_normative_config, update_normative_config
from app.models.audit import Auditoria
from app.models.setting import AjustesOperativos
from app.models.user import Rol, Usuario


@pytest.fixture(autouse=True)
def restore_normative_config():
    """Los tests de ajustes mutan la config normativa global; restaurarla
    para no contaminar test_normative_flight y otros módulos."""
    original = get_normative_config()
    yield
    update_normative_config(original)


def _login(client, email: str, password: str, expected_role: str | None = None):
    payload = {"email": email, "password": password}
    if expected_role:
        payload["expected_role"] = expected_role
    return client.post("/api/v1/auth/login", json=payload)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Login: expected_role, rate limit y auditoría
# ---------------------------------------------------------------------------


def test_login_expected_role_correcto(client, admin_user):
    resp = _login(client, admin_user.email, "Admin1234!", expected_role="ADMIN")
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()


def test_login_expected_role_incorrecto_devuelve_403(client, admin_user):
    resp = _login(client, admin_user.email, "Admin1234!", expected_role="GUARDIA")
    assert resp.status_code == 403, resp.text
    assert "ADMIN" in resp.json()["detail"]


def test_login_rol_incorrecto_queda_auditado(client, db, admin_user):
    _login(client, admin_user.email, "Admin1234!", expected_role="GUARDIA")
    reg = (
        db.query(Auditoria)
        .filter(Auditoria.accion == "LOGIN_ROL_INCORRECTO")
        .order_by(Auditoria.id.desc())
        .first()
    )
    assert reg is not None
    assert reg.usuario_id == admin_user.id
    assert reg.hash_sha256 is not None  # registro sellado por la cadena


def test_login_fallido_queda_auditado(client, db, admin_user):
    resp = _login(client, admin_user.email, "password-inventado")
    assert resp.status_code == 401
    reg = (
        db.query(Auditoria)
        .filter(Auditoria.accion == "LOGIN_FALLIDO")
        .order_by(Auditoria.id.desc())
        .first()
    )
    assert reg is not None
    assert admin_user.email in reg.detalle


def test_login_rate_limit_tras_10_fallos(client, admin_user):
    email = "ratelimit@test.com"
    for i in range(10):
        resp = _login(client, email, "bad-password")
        assert resp.status_code == 401, f"intento {i}: {resp.status_code}"
    resp = _login(client, email, "bad-password")
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Registro: dominios personales
# ---------------------------------------------------------------------------


def test_register_dominio_personal_rechazado(client, admin_token):
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "nombre": "Usuario Gmail",
            "email": "nuevo@gmail.com",
            "password": "Secret123!",
            "rol_id": 2,
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400
    assert "institucional" in resp.json()["detail"].lower()


def test_register_correo_institucional_ok(client, admin_token):
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "nombre": "Usuario UAQ",
            "email": "nuevo@uaq.mx",
            "password": "Secret123!",
            "rol_id": 2,
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "nuevo@uaq.mx"


# ---------------------------------------------------------------------------
# Perfil propio y preferencias
# ---------------------------------------------------------------------------


def test_patch_me_persiste_nombre_y_puesto(client, guardia_token):
    resp = client.patch(
        "/api/v1/auth/me",
        json={"nombre": "Guardia Actualizado", "puesto": "Vigilante Nocturno"},
        headers=_auth(guardia_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["nombre"] == "Guardia Actualizado"
    assert data["puesto"] == "Vigilante Nocturno"

    me = client.get("/api/v1/auth/me", headers=_auth(guardia_token))
    assert me.json()["puesto"] == "Vigilante Nocturno"


def test_patch_me_foto_url_invalida_422(client, guardia_token):
    resp = client.patch(
        "/api/v1/auth/me",
        json={"foto_url": "ftp://malformato/foto.png"},
        headers=_auth(guardia_token),
    )
    assert resp.status_code == 422


def test_patch_me_preferences_guardia(client, guardia_token):
    resp = client.patch(
        "/api/v1/auth/me/preferences",
        json={"critical_push_enabled": False, "transmission_quality_id": "hd-30"},
        headers=_auth(guardia_token),
    )
    assert resp.status_code == 200, resp.text
    me = client.get("/api/v1/auth/me", headers=_auth(guardia_token)).json()
    assert me["preferencias"]["critical_push_enabled"] is False
    assert me["preferencias"]["transmission_quality_id"] == "hd-30"


def test_patch_me_preferences_conserva_otras_claves(client, guardia_token):
    client.patch(
        "/api/v1/auth/me/preferences",
        json={"transmission_quality_id": "4k-30"},
        headers=_auth(guardia_token),
    )
    client.patch(
        "/api/v1/auth/me/preferences",
        json={"critical_push_enabled": False},
        headers=_auth(guardia_token),
    )
    me = client.get("/api/v1/auth/me", headers=_auth(guardia_token)).json()
    assert me["preferencias"]["transmission_quality_id"] == "4k-30"
    assert me["preferencias"]["critical_push_enabled"] is False


# ---------------------------------------------------------------------------
# Revocación de tokens: change-password, logout, refresh
# ---------------------------------------------------------------------------


def test_change_password_revoca_token(client, guardia_user, guardia_token):
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Guardia1234!", "new_password": "NuevaClave99!"},
        headers=_auth(guardia_token),
    )
    assert resp.status_code == 200, resp.text

    # El token previo queda revocado.
    me = client.get("/api/v1/auth/me", headers=_auth(guardia_token))
    assert me.status_code == 401

    # La nueva contraseña permite iniciar sesión.
    resp = _login(client, guardia_user.email, "NuevaClave99!")
    assert resp.status_code == 200


def test_change_password_actual_incorrecta_400(client, guardia_token):
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "no-es", "new_password": "NuevaClave99!"},
        headers=_auth(guardia_token),
    )
    assert resp.status_code == 400


def test_logout_revoca_token(client, admin_token):
    resp = client.post("/api/v1/auth/logout", headers=_auth(admin_token))
    assert resp.status_code == 200
    me = client.get("/api/v1/auth/me", headers=_auth(admin_token))
    assert me.status_code == 401


def test_refresh_emite_nuevo_token_y_revoca_el_anterior(client, guardia_token):
    resp = client.post("/api/v1/auth/refresh", headers=_auth(guardia_token))
    assert resp.status_code == 200, resp.text
    new_token = resp.json()["access_token"]
    assert new_token != guardia_token

    assert client.get("/api/v1/auth/me", headers=_auth(guardia_token)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_auth(new_token)).status_code == 200


# ---------------------------------------------------------------------------
# Administración de usuarios (/users)
# ---------------------------------------------------------------------------


def test_list_users_solo_admin(client, admin_token, guardia_token):
    resp = client.get("/api/v1/users/", headers=_auth(admin_token))
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert "admin@test.com" in emails

    resp = client.get("/api/v1/users/", headers=_auth(guardia_token))
    assert resp.status_code == 403


def test_list_users_filtro_q(client, admin_token, guardia_user):
    resp = client.get("/api/v1/users/", params={"q": "guardia"}, headers=_auth(admin_token))
    assert resp.status_code == 200
    assert all("guardia" in u["email"] or "Guardia" in u["nombre"] for u in resp.json())


def test_patch_user_cambio_rol(client, admin_token, guardia_user, db):
    rol_admin = db.query(Rol).filter(Rol.nombre == "ADMIN").first()
    resp = client.patch(
        f"/api/v1/users/{guardia_user.id}",
        json={"rol_id": rol_admin.id},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rol"]["nombre"] == "ADMIN"


def test_patch_user_ultimo_admin_protegido(client, admin_token, admin_user, db):
    rol_guardia = db.query(Rol).filter(Rol.nombre == "GUARDIA").first()
    resp = client.patch(
        f"/api/v1/users/{admin_user.id}",
        json={"rol_id": rol_guardia.id},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 409

    resp = client.patch(
        f"/api/v1/users/{admin_user.id}",
        json={"activo": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 409


def test_reset_password_permite_nuevo_login(client, admin_token, guardia_user):
    resp = client.post(
        f"/api/v1/users/{guardia_user.id}/reset-password",
        json={"new_password": "ResetClave77!"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert _login(client, guardia_user.email, "ResetClave77!").status_code == 200


def test_delete_user_baja_logica(client, admin_token, guardia_user):
    resp = client.delete(f"/api/v1/users/{guardia_user.id}", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["activo"] is False
    # Login de cuenta inactiva -> 400
    assert _login(client, guardia_user.email, "Guardia1234!").status_code == 400


def test_delete_user_no_autoeliminacion(client, admin_token, admin_user):
    resp = client.delete(f"/api/v1/users/{admin_user.id}", headers=_auth(admin_token))
    assert resp.status_code == 400


def test_get_roles(client, admin_token):
    resp = client.get("/api/v1/users/roles", headers=_auth(admin_token))
    assert resp.status_code == 200
    nombres = {r["nombre"] for r in resp.json()}
    assert {"ADMIN", "GUARDIA"} <= nombres


# ---------------------------------------------------------------------------
# Ajustes: ventana operativa persistida en BD
# ---------------------------------------------------------------------------


def test_operating_window_persiste_en_bd(client, admin_token, db):
    resp = client.put(
        "/api/v1/settings/operating-window",
        json={
            "altitud_minima_m": 5.0,
            "altitud_maxima_m": 120.0,
            "peso_maximo_kg": 10.0,
            "hora_apertura": "07:30",
            "hora_cierre": "21:00",
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text

    row = db.query(AjustesOperativos).order_by(AjustesOperativos.id).first()
    assert row is not None
    assert row.hora_apertura == "07:30"
    assert row.hora_cierre == "21:00"
    assert row.altitud_minima_m == 5.0
    assert row.altitud_maxima_m == 120.0

    # GET devuelve lo persistido en la fila.
    get_resp = client.get("/api/v1/settings/operating-window", headers=_auth(admin_token))
    assert get_resp.json()["hora_apertura"] == "07:30"


def test_operating_window_validaciones_422(client, admin_token):
    # Formato de hora inválido
    resp = client.put(
        "/api/v1/settings/operating-window",
        json={
            "altitud_minima_m": 5.0,
            "altitud_maxima_m": 120.0,
            "peso_maximo_kg": 10.0,
            "hora_apertura": "7am",
            "hora_cierre": "21:00",
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 422

    # altitud_minima >= altitud_maxima
    resp = client.put(
        "/api/v1/settings/operating-window",
        json={
            "altitud_minima_m": 50.0,
            "altitud_maxima_m": 50.0,
            "peso_maximo_kg": 10.0,
            "hora_apertura": "07:00",
            "hora_cierre": "21:00",
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 422


def test_operator_settings_guardia_no_puede_escribir(client, guardia_token):
    resp = client.put(
        "/api/v1/settings/operator",
        json={
            "critical_push_enabled": True,
            "ai_sensitivity_id": "95",
            "retention_days": 30,
            "transmission_quality_id": "fhd-60",
        },
        headers=_auth(guardia_token),
    )
    assert resp.status_code == 403


def test_operator_settings_admin_persiste(client, admin_token):
    resp = client.put(
        "/api/v1/settings/operator",
        json={
            "critical_push_enabled": False,
            "ai_sensitivity_id": "98",
            "retention_days": 90,
            "transmission_quality_id": "4k-30",
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ai_sensitivity_id"] == "98"
    assert data["retention_days"] == 90


# ---------------------------------------------------------------------------
# Auditoría: cadena de hashes y exportación
# ---------------------------------------------------------------------------


def test_audit_export_estructura_e_integridad(client, admin_token):
    resp = client.get("/api/v1/audit/export", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["integridad"]["chain_valid"] is True
    assert data["integridad"]["total_records"] >= 1  # al menos el LOGIN del fixture
    assert data["integridad"]["sealed_records"] >= 1
    assert "ventana_operativa" in data
    assert any(r["accion"] == "LOGIN" for r in data["registros"])
    assert any(r["hash_sha256"] for r in data["registros"])


def test_audit_orm_bloquea_modificacion_y_borrado(db):
    """El modelo impide UPDATE/DELETE vía ORM: solo inserciones."""
    reg = Auditoria(usuario_id=None, accion="PRUEBA", recurso="/x")
    db.add(reg)
    db.commit()
    reg.detalle = "alterado"
    with pytest.raises(ValueError, match="inmutable"):
        db.commit()
    db.rollback()
    db.delete(reg)
    with pytest.raises(ValueError, match="inmutable"):
        db.commit()
    db.rollback()


def test_audit_chain_detecta_manipulacion(client, admin_token, db):
    # Generar algunos registros sellados.
    client.patch("/api/v1/auth/me", json={"puesto": "X"}, headers=_auth(admin_token))

    # Manipular un registro sellado evadiendo el listener ORM (UPDATE Core),
    # como lo haría alguien con acceso directo a la base de datos.
    reg = db.query(Auditoria).filter(Auditoria.hash_sha256.isnot(None)).order_by(Auditoria.id).first()
    assert reg is not None
    db.execute(
        update(Auditoria)
        .where(Auditoria.id == reg.id)
        .values(detalle="detalle alterado por un atacante")
    )
    db.commit()

    resp = client.get("/api/v1/audit/export", headers=_auth(admin_token))
    assert resp.json()["integridad"]["chain_valid"] is False


def test_audit_export_solo_admin(client, guardia_token):
    resp = client.get("/api/v1/audit/export", headers=_auth(guardia_token))
    assert resp.status_code == 403
