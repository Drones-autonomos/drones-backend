import io
from datetime import datetime, timedelta
from fastapi import status
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
            {"orden_waypoint": 1, "latitud": 20.58, "longitud": -100.38, "altitud_metros": 250.0} # > 200m
        ]
    }
    res = client.post("/api/v1/missions/", json=payload, headers=headers)
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

def test_normative_rejection_out_of_hours(client, admin_token):
    """Verifica rechazo HTTP 422 si el vuelo está fuera de la ventana operativa (RNF-02)."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {
        "nombre": "Misión Ilegal Madrugada",
        "horario_inicio_programado": "2026-11-04T03:00:00", # 3 AM
        "peso_dron_kg": 2.0,
        "waypoints": [
            {"orden_waypoint": 1, "latitud": 20.58, "longitud": -100.38, "altitud_metros": 50.0}
        ]
    }
    res = client.post("/api/v1/missions/", json=payload, headers=headers)
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

def test_guard_cannot_download_recording(client, guardia_token):
    """Valida control de acceso (RBAC): Guardia no puede descargar archivo directamente."""
    headers = {"Authorization": f"Bearer {guardia_token}"}
    res = client.get("/api/v1/recordings/1/download", headers=headers)
    assert res.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]