from datetime import datetime
from fastapi import status


# 1. Simular detección de persona nocturna a las 23:00 hrs -> Genera Evento (Status 201)
def test_ingest_person_nocturnal_triggers_event(client, admin_token):
  payload = {
      "tipo": "PERSONA",
      "nivel_confianza": 0.89,
      "frame_url": "/storage/frames/person_night_01.jpg",
      "latitud": 20.5888,
      "longitud": -100.3899,
      "timestamp": "2026-10-19T23:00:00",
  }
  # Ingesta de la detección
  response = client.post("/api/v1/detections/ingest", json=payload)
  assert response.status_code == status.HTTP_201_CREATED
  data = response.json()
  assert data["tipo"] == "PERSONA"
  assert (
      data["evento_id"] is not None
  )  # Verificamos que se haya enlazado a un evento

  # Comprobar el evento generado consultando por ID con rol autorizado
  headers = {"Authorization": f"Bearer {admin_token}"}
  event_res = client.get(f"/api/v1/events/{data['evento_id']}", headers=headers)
  assert event_res.status_code == status.HTTP_200_OK
  event_data = event_res.json()
  assert event_data["tipo"] == "PERSONA_NOCTURNA"
  assert event_data["nivel_criticidad"] == "ALTA"
  assert len(event_data["detecciones"]) >= 1


# 2. Simular detección con confianza baja (< 0.50) -> Se guarda, NO genera evento
def test_ingest_low_confidence_no_event(client):
  payload = {
      "tipo": "HUMO",
      "nivel_confianza": 0.45,  # Menor al umbral de 0.70
      "frame_url": "/storage/frames/smoke_doubtful.jpg",
      "latitud": 20.5895,
      "longitud": -100.3905,
      "timestamp": "2026-10-19T14:30:00",
  }
  response = client.post("/api/v1/detections/ingest", json=payload)
  assert response.status_code == status.HTTP_201_CREATED
  data = response.json()
  assert data["tipo"] == "HUMO"
  assert (
      data["evento_id"] is None
  )  # No debe vincularse ni crear ningún evento


# 3. Probar filtros por fecha y tipo en GET /api/v1/events/
def test_filter_events_by_type_and_date(client, guardia_token):
  headers = {"Authorization": f"Bearer {guardia_token}"}

  # Ingestar una detección de humo con confianza alta para garantizar un evento de HUMO
  client.post(
      "/api/v1/detections/ingest",
      json={
          "tipo": "HUMO",
          "nivel_confianza": 0.95,
          "frame_url": "/storage/frames/smoke_critical.jpg",
          "latitud": 20.5885,
          "longitud": -100.3892,
          "timestamp": "2026-10-19T10:00:00",
      },
  )

  # Filtrar por tipo HUMO_DETECTADO
  res_humo = client.get(
      "/api/v1/events/?tipo=HUMO_DETECTADO", headers=headers
  )
  assert res_humo.status_code == status.HTTP_200_OK
  lista_humo = res_humo.json()
  assert len(lista_humo) > 0
  for evento in lista_humo:
    assert evento["tipo"] == "HUMO_DETECTADO"

  # Filtrar por rango de fechas
  res_fechas = client.get(
      "/api/v1/events/?fecha_inicio=2026-10-19T00:00:00&fecha_fin=2026-10-19T23:59:59",
      headers=headers,
  )
  assert res_fechas.status_code == status.HTTP_200_OK
  assert isinstance(res_fechas.json(), list)


# 4. Probar actualización de estado (PATCH /api/v1/events/{id}/status)
def test_update_event_status_by_guard(client, guardia_token, admin_token):
  headers = {"Authorization": f"Bearer {guardia_token}"}

  # Obtener el último evento generado
  events_res = client.get("/api/v1/events/", headers=headers)
  eventos = events_res.json()
  assert len(eventos) > 0
  evento_id = eventos[0]["id"]

  # Cambiar estado a EN_REVISION
  patch_res = client.patch(
      f"/api/v1/events/{evento_id}/status",
      json={"estado": "EN_REVISION"},
      headers=headers,
  )
  assert patch_res.status_code == status.HTTP_200_OK
  assert patch_res.json()["estado"] == "EN_REVISION"