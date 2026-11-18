"""Ejecutor integral simulado: geocerca, vuelo, visión, alerta, streaming, grabación, bitácora y carga."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from app.services.charging_base_service import ChargingBaseService
from app.services.drone_service import DroneService
from app.services.mission_service import MissionService
from app.services.video_stream_service import video_stream_service
from app.vision.detector import PersonDetector, SmokeDetector, VisionAnalyzer
from app.vision.pipeline import FramePipeline
from app.vision.runner import DetectionBackendClient, TelemetryPoint, VisionPipelineRunner


class SimulatedAerialVehicle:
    """Vehículo simulado en memoria compatible con DroneService y TelemetriaVuelo."""

    def __init__(self, home_lat: float = 20.70428, home_lon: float = -100.44358) -> None:
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.last_heartbeat = 0.1
        self.armed = False
        self.is_armable = True
        self.mode = SimpleNamespace(name="STABILIZE")
        self.parameters = {}
        self.battery = SimpleNamespace(level=60, voltage=15.1)
        self.groundspeed = 0.0
        self.heading = 0
        self.location = SimpleNamespace(global_relative_frame=SimpleNamespace(lat=home_lat, lon=home_lon, alt=0.0))

    def simple_takeoff(self, target_altitude: float) -> None:
        self.location.global_relative_frame.alt = float(target_altitude)
        self.groundspeed = 4.5

    def simple_goto(self, target) -> None:
        self.location.global_relative_frame.lat = float(target.lat)
        self.location.global_relative_frame.lon = float(target.lon)
        self.location.global_relative_frame.alt = float(target.alt)
        self.battery.level = max(20, self.battery.level - 10)

    def close(self) -> None:
        pass


def _build_smoke_demo_frame() -> np.ndarray:
    frame = np.zeros((320, 320, 3), dtype=np.uint8)
    frame[:, :] = (35, 115, 45)
    cv2.ellipse(frame, (160, 160), (85, 60), 0, 0, 360, (190, 190, 190), -1)
    return cv2.GaussianBlur(frame, (29, 29), 0)


def run_integral_mission_flow(
    *,
    client,
    admin_headers: dict[str, str],
    session_factory,
    work_dir: Path,
) -> dict:
    """Ejecuta el ciclo completo de misión integral simulada contra la API y servicios."""
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. Configurar geocerca operativa en UAQ Juriquilla
    fence_res = client.post(
        "/api/v1/geofences/",
        json={
            "nombre": "Perímetro Integral UAQ",
            "tipo": "CIRCULAR",
            "centro_lat": 20.70428,
            "centro_lon": -100.44358,
            "radio_metros": 300.0,
            "altitud_min_m": 2.0,
            "altitud_max_m": 120.0,
        },
        headers=admin_headers,
    )
    assert fence_res.status_code == 201, fence_res.text

    # 2. Crear misión válida dentro de geocerca y ventana operativa
    mission_res = client.post(
        "/api/v1/missions/",
        json={
            "nombre": "Misión Integral Simulada",
            "peso_dron_kg": 2.5,
            "waypoints": [
                {"orden_waypoint": 1, "latitud": 20.70440, "longitud": -100.44355, "altitud_metros": 15.0},
                {"orden_waypoint": 2, "latitud": 20.70460, "longitud": -100.44340, "altitud_metros": 15.0},
            ],
        },
        headers=admin_headers,
    )
    assert mission_res.status_code == 201, mission_res.text
    mission_id = mission_res.json()["id"]

    # 3. Preparar vehículo simulado, failsafe y ejecutor inmediato
    vehicle = SimulatedAerialVehicle()

    class _ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

        def join(self, timeout=None):
            pass

    class _SimDrone(DroneService):
        def return_to_launch(self) -> bool:
            super().return_to_launch()
            vehicle.armed = False
            vehicle.location.global_relative_frame.lat = vehicle.home_lat
            vehicle.location.global_relative_frame.lon = vehicle.home_lon
            vehicle.location.global_relative_frame.alt = 0.0
            return True

    drone = _SimDrone(poll_interval=0.0, sleep=lambda _: None)
    drone.vehicle = vehicle
    drone.configure_gcs_failsafe(enabled=True)

    service = MissionService(session_factory, drone=drone, thread_factory=_ImmediateThread)
    service.start(mission_id)

    mission_detail = client.get(f"/api/v1/missions/{mission_id}", headers=admin_headers).json()

    # 4. Publicar frame al stream en vivo y procesarlo con visión -> evento + alerta
    demo_frame = _build_smoke_demo_frame()
    ok_jpg, buf = cv2.imencode(".jpg", demo_frame)
    assert ok_jpg
    stream_push = client.post(
        "/api/v1/video/frame?width=320&height=320",
        files={"file": ("live.jpg", buf.tobytes(), "image/jpeg")},
        headers=admin_headers,
    )
    assert stream_push.status_code == 202

    pipeline = FramePipeline(source=0, target_size=(320, 320), evidence_dir=work_dir / "frames")
    analyzer = VisionAnalyzer(
        person_detector=PersonDetector(model_path="models/nonexistent.onnx"),
        smoke_detector=SmokeDetector(confidence_threshold=0.65),
    )

    class _ClientAdapter:
        def post(self, url: str, json: dict):
            return client.post(url.replace("http://testserver", ""), json=json)

    runner = VisionPipelineRunner(
        pipeline,
        analyzer,
        DetectionBackendClient("http://testserver", client=_ClientAdapter()),
        telemetry_provider=lambda: TelemetryPoint(
            latitud=20.70440,
            longitud=-100.44355,
            vuelo_id=mission_id,
        ),
    )
    packet = next(pipeline.iter_from_arrays([demo_frame]))
    detections = runner.process_packet(packet, timestamp_override=datetime(2026, 11, 17, 23, 30, 0))

    # 5. Consultar bitácora de telemetría y alertas
    telemetry_rows = client.get(f"/api/v1/telemetry/log?mision_id={mission_id}", headers=admin_headers).json()
    alerts = client.get("/api/v1/alerts/?nivel_criticidad=CRITICA", headers=admin_headers).json()

    # 6. Acoplar a base de carga HOME y recargar al 100%
    base = ChargingBaseService()
    charge_report = base.dock_and_recharge(drone, target_pct=100.0)

    return {
        "mission_id": mission_id,
        "mission_estado": mission_detail["estado"],
        "waypoints_completados": mission_detail["waypoints_completados"],
        "stream_estado": video_stream_service.get_status()["estado_camara"],
        "detecciones_emitidas": len(detections),
        "alertas_criticas": len(alerts),
        "muestras_telemetria": len(telemetry_rows),
        "base_carga_estado": charge_report["estado"],
        "bateria_final": charge_report["bateria_porcentaje"],
    }


if __name__ == "__main__":
    print(json.dumps({"info": "Usa pytest tests/test_integral_mission.py para la ejecución verificada"}, indent=2))
