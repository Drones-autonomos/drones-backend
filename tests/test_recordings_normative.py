import io
from datetime import datetime, timedelta
from fastapi import status
from app.api.v1.endpoints.settings import CONFIG_ACTUAL
from app.core.security_crypto import encrypt_file_data, decrypt_file_data

def test_encryption_decryption_cycle():
    """Valida que los datos cifrados con AES-GCM se recuperen intactos."""
    raw_video_data = b"DATOS_SIMULADOS_DE_VIDEO_MP4_12345"
    encrypted = encrypt_file_data(raw_video_data)
    assert encrypted != raw_video_data
    
    decrypted = decrypt_file_data(encrypted)
    assert decrypted == raw_video_data

def test_normative_rejection_altitude_exceeded(client, admin_token):
    """Verifica rechazo HTTP 422 si la altitud supera 200 m (RNF-07)."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {
        "nombre": "Misión Ilegal Altura",
        "horario_inicio_programado": "2026-11-04T10:00:00",
        "peso_dron_kg": 2.0,
        "waypoints": [
            {"orden_waypoint": 1, "latitud": 20.58, "longitud": -100.38, "altitud_metros": 50.0},
            {"orden_waypoint": 2, "latitud": 20.59, "longitud": -100.39, "altitud_metros": 250.0}
        ]
    }
    res = client.post("/api/v1/missions/", json=payload, headers=headers)
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

def test_normative_rejection_out_of_hours(client, admin_token):
    """Verifica rechazo HTTP 422 si el vuelo está fuera de la ventana operativa (RNF-02)."""
    from app.api.v1.endpoints.settings import CONFIG_ACTUAL
    CONFIG_ACTUAL.hora_apertura = "06:00"
    CONFIG_ACTUAL.hora_cierre = "23:00"
    try:
        headers = {"Authorization": f"Bearer {admin_token}"}
        payload = {
            "nombre": "Vuelo Fuera de Horario",
            "horario_inicio_programado": "2026-11-16T03:00:00",
            "peso_dron_kg": 2.0,
            "waypoints": [
                {"orden_waypoint": 1, "latitud": 20.58, "longitud": -100.38, "altitud_metros": 50.0},
                {"orden_waypoint": 2, "latitud": 20.59, "longitud": -100.39, "altitud_metros": 50.0},
            ],
        }
        response = client.post("/api/v1/missions/", json=payload, headers=headers)
        assert response.status_code == 422
    finally:
        CONFIG_ACTUAL.hora_apertura = "00:00"
        CONFIG_ACTUAL.hora_cierre = "23:59"

def test_guard_cannot_download_recording(client, guardia_token):
    """Valida control de acceso (RBAC): Guardia no puede descargar archivo directamente."""
    headers = {"Authorization": f"Bearer {guardia_token}"}
    res = client.get("/api/v1/recordings/1/download", headers=headers)
    assert res.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]