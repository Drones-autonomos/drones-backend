"""Tests para los endpoints /api/v1/settings/operator (ajustes operativos persistidos)."""

import pytest

from app.models.setting import AjustesOperativos

VALID_PAYLOAD = {
    "critical_push_enabled": False,
    "ai_sensitivity_id": "98",
    "retention_days": 60,
    "transmission_quality_id": "4k-30",
}

DEFAULTS = {
    "critical_push_enabled": True,
    "ai_sensitivity_id": "95",
    "retention_days": 30,
    "transmission_quality_id": "fhd-60",
}


def test_get_operator_requires_auth(client):
    response = client.get("/api/v1/settings/operator")
    assert response.status_code == 401


@pytest.mark.parametrize("token_fixture", ["admin_token", "guardia_token"])
def test_get_operator_defaults_for_admin_and_guard(client, request, token_fixture):
    token = request.getfixturevalue(token_fixture)
    response = client.get(
        "/api/v1/settings/operator",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == DEFAULTS


def test_put_operator_as_admin_persists(client, admin_token, db):
    response = client.put(
        "/api/v1/settings/operator",
        json=VALID_PAYLOAD,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json() == VALID_PAYLOAD

    # La fila única quedó persistida en BD.
    rows = db.query(AjustesOperativos).all()
    assert len(rows) == 1
    assert rows[0].ai_sensitivity_id == "98"
    assert rows[0].retention_days == 60

    # Un GET posterior (incluso de GUARDIA) lee el valor persistido.
    get_response = client.get(
        "/api/v1/settings/operator",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_response.status_code == 200
    assert get_response.json() == VALID_PAYLOAD


def test_put_operator_updates_existing_row(client, admin_token, db):
    headers = {"Authorization": f"Bearer {admin_token}"}
    client.put("/api/v1/settings/operator", json=VALID_PAYLOAD, headers=headers)
    updated = {**VALID_PAYLOAD, "retention_days": 90}
    response = client.put("/api/v1/settings/operator", json=updated, headers=headers)
    assert response.status_code == 200
    assert response.json()["retention_days"] == 90
    assert db.query(AjustesOperativos).count() == 1


def test_put_operator_forbidden_for_guard(client, guardia_token):
    response = client.put(
        "/api/v1/settings/operator",
        json=VALID_PAYLOAD,
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "field, value",
    [
        ("ai_sensitivity_id", "99"),
        ("retention_days", 45),
        ("transmission_quality_id", "8k-60"),
        ("critical_push_enabled", "quizá"),
    ],
)
def test_put_operator_rejects_invalid_values(client, admin_token, field, value):
    payload = {**VALID_PAYLOAD, field: value}
    response = client.put(
        "/api/v1/settings/operator",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422
