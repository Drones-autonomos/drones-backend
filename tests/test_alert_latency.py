import time
from urllib import response
from xmlrpc import client
from fastapi import status

from tests.conftest import admin_token


def test_critical_smoke_detection_latency(client, admin_token):
  """Mide el tiempo de respuesta total para una detección crítica de humo (RNF-01).

  Verifica que el ciclo completo de ingesta, creación de evento y emisión de
  alerta se ejecute por debajo del umbral de tiempo real (máx 500 ms).
  """
  payload = {
      "vuelo_id": None,
      "tipo": "HUMO",
      "nivel_confianza": 0.94,
      "frame_url": "/storage/frames/smoke_latency_test.jpg",
      "latitud": 20.5888,
      "longitud": -100.3899,
      "timestamp": "2026-10-27T10:00:00",
  }

  # 1. Medir tiempo de ejecución del endpoint de ingesta
  start_time = time.perf_counter()
  response = client.post("/api/v1/detections/ingest", json=payload)
  end_time = time.perf_counter()

  elapsed_time_seconds = end_time - start_time
  elapsed_time_ms = elapsed_time_seconds * 1000


  # 2. Validaciones funcionales



  response = client.post("/api/v1/detections/ingest", json=payload)
  print(response.json())
  assert response.status_code == status.HTTP_201_CREATED
  detection_data = response.json()
  assert detection_data["evento_id"] is not None

  # 3. Validar que la alerta fue creada en la base de datos
  headers = {"Authorization": f"Bearer {admin_token}"}
  alert_res = client.get(
      f"/api/v1/alerts/?nivel_criticidad=CRITICA", headers=headers
  )
  assert alert_res.status_code == status.HTTP_200_OK
  alertas = alert_res.json()
  assert len(alertas) > 0
  alerta_generada = next(
      (a for a in alertas if a["evento_id"] == detection_data["evento_id"]),
      None,
  )
  assert alerta_generada is not None
  assert alerta_generada["nivel_criticidad"] == "CRITICA"

  # 4. Validar umbral de tiempo real (RNF-01: < 500 ms en backend local)
  umbral_max_ms = 500.0
  print(f"\n[LATENCY BENCHMARK] Tiempo de procesamiento: {elapsed_time_ms:.2f} ms")
  assert (
      elapsed_time_ms < umbral_max_ms
  ), f"La latencia excedió el umbral ({elapsed_time_ms:.2f} ms > {umbral_max_ms} ms)"


def test_night_person_detection_latency(client, admin_token):
  """Mide el tiempo de respuesta para una detección nocturna de persona fuera de horario."""
  payload = {
      "vuelo_id": None,
      "tipo": "PERSONA",
      "nivel_confianza": 0.88,
      "frame_url": "/storage/frames/person_latency_test.jpg",
      "latitud": 20.5892,
      "longitud": -100.3901,
      "timestamp": "2026-10-27T23:30:00",
  }

  start_time = time.perf_counter()
  response = client.post("/api/v1/detections/ingest", json=payload)
  end_time = time.perf_counter()

  elapsed_time_ms = (end_time - start_time) * 1000

  assert response.status_code == status.HTTP_201_CREATED
  assert response.json()["evento_id"] is not None
  assert (
      elapsed_time_ms < 500.0
  ), f"Latencia excedida: {elapsed_time_ms:.2f} ms"