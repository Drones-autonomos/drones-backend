"""Pruebas de la base de carga simulada (acoplamiento en HOME y recarga)."""

from types import SimpleNamespace

from app.services.charging_base_service import ChargingBaseService
from app.services.drone_service import drone_service


def test_charging_base_dock_and_recharge_cycle(client, admin_token, guardia_token):
    original = drone_service.vehicle
    try:
        drone_service.vehicle = SimpleNamespace(
            last_heartbeat=0.1,
            armed=False,
            battery=SimpleNamespace(level=35, voltage=14.4),
            location=SimpleNamespace(global_relative_frame=SimpleNamespace(lat=20.70428, lon=-100.44358, alt=0.05)),
        )
        res = client.post(
            "/api/v1/drone/charging-base/dock-recharge",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["estado"] == "CHARGED"
        assert body["bateria_porcentaje"] == 100.0
        assert body["distancia_home_m"] < 3.0
        assert drone_service.vehicle.battery.level == 100

        status_res = client.get(
            "/api/v1/drone/charging-base",
            headers={"Authorization": f"Bearer {guardia_token}"},
        )
        assert status_res.status_code == 200
        assert status_res.json()["ciclos_completados"] >= 1
    finally:
        drone_service.vehicle = original


def test_charging_base_rejects_far_from_home(client, admin_token):
    original = drone_service.vehicle
    try:
        drone_service.vehicle = SimpleNamespace(
            last_heartbeat=0.1,
            armed=False,
            battery=SimpleNamespace(level=40, voltage=14.6),
            location=SimpleNamespace(global_relative_frame=SimpleNamespace(lat=20.70600, lon=-100.44358, alt=0.0)),
        )
        res = client.post(
            "/api/v1/drone/charging-base/dock-recharge",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 503
        assert "base de carga" in res.json()["detail"].lower()
    finally:
        drone_service.vehicle = original


def test_charging_base_service_rejects_airborne():
    base = ChargingBaseService()
    fake_drone = SimpleNamespace(is_grounded=lambda: False)
    try:
        base.dock_and_recharge(fake_drone)
        raise AssertionError("Debió rechazar dron en vuelo")
    except RuntimeError as exc:
        assert "tierra" in str(exc).lower()
