"""Pruebas integrales de los módulos de vuelo, geocerca, visión, telemetría y base de carga."""

from pathlib import Path

from scripts.run_integral_demo import run_integral_mission_flow

from tests.conftest import TestingSessionLocal


def test_full_integral_simulated_mission(client, admin_token, tmp_path: Path):
    headers = {"Authorization": f"Bearer {admin_token}"}
    report = run_integral_mission_flow(
        client=client,
        admin_headers=headers,
        session_factory=TestingSessionLocal,
        work_dir=tmp_path / "integral",
    )

    assert report["mission_estado"] == "FINALIZADA"
    assert report["waypoints_completados"] == 2
    assert report["stream_estado"] == "ONLINE"
    assert report["detecciones_emitidas"] >= 1
    assert report["alertas_criticas"] >= 1
    assert report["muestras_telemetria"] >= 3
    assert report["base_carga_estado"] == "CHARGED"
    assert report["bateria_final"] == 100.0
