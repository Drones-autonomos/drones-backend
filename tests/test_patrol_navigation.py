import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from scripts import drone_backend as patrol


@pytest.fixture()
def vehicle(monkeypatch):
    monkeypatch.setitem(sys.modules, "dronekit", SimpleNamespace(
        LocationGlobalRelative=lambda lat, lon, alt: SimpleNamespace(lat=lat, lon=lon, alt=alt),
    ))
    ticks = iter(range(1000))
    monkeypatch.setattr(patrol.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(patrol.time, "sleep", lambda _: None)
    monkeypatch.setattr(patrol, "TIMEOUT_TRAMO_S", 20)
    return SimpleNamespace(
        location=SimpleNamespace(global_relative_frame=SimpleNamespace(lat=20.70, lon=-100.44, alt=15)),
        mode=SimpleNamespace(name="GUIDED"),
        armed=True,
        last_heartbeat=0.1,
        simple_goto=Mock(),
    )


def test_lost_goto_is_retried_before_advancing(vehicle):
    def receive_second_command(target, **kwargs):
        if vehicle.simple_goto.call_count == 2:
            vehicle.location.global_relative_frame = target

    vehicle.simple_goto.side_effect = receive_second_command
    patrol.volar_a(vehicle, patrol.BASE_1_COORDS, 15, 6, "Base 1")
    assert vehicle.simple_goto.call_count == 2
    assert vehicle.simple_goto.call_args_list[0] == vehicle.simple_goto.call_args_list[1]


def test_unreachable_waypoint_raises_instead_of_skipping(vehicle):
    with pytest.raises(TimeoutError, match="Base 1"):
        patrol.volar_a(vehicle, patrol.BASE_1_COORDS, 15, 6, "Base 1")


@pytest.mark.parametrize("state", ["disarmed", "mode", "heartbeat"])
def test_invalid_flight_state_prevents_navigation(vehicle, state):
    if state == "disarmed":
        vehicle.armed = False
    elif state == "mode":
        vehicle.mode.name = "RTL"
    else:
        vehicle.last_heartbeat = 10
    with pytest.raises(RuntimeError):
        patrol.volar_a(vehicle, patrol.BASE_1_COORDS, 15, 6, "Base 1")
    vehicle.simple_goto.assert_not_called()


def test_complete_route_recovers_lost_commands(vehicle):
    route = [
        *patrol.RUTA_TRASLADO,
        patrol.BASE_1_COORDS,
        *[point[:2] for point in patrol.RUTA_BARRIDO],
        patrol.BASE_2_COORDS,
        *patrol.RUTA_REGRESO,
        patrol.BASE_1_COORDS,
    ]
    received = []

    def receive_retry(target, **kwargs):
        if vehicle.simple_goto.call_count % 2 == 0:
            received.append((target.lat, target.lon))
            vehicle.location.global_relative_frame = target

    vehicle.simple_goto.side_effect = receive_retry
    for point in route:
        patrol.volar_a(vehicle, point, 15, 6, str(point))
    assert received == route


def test_mode_change_during_navigation_stops_retries(vehicle, monkeypatch):
    monkeypatch.setattr(patrol.time, "sleep", lambda _: setattr(vehicle.mode, "name", "RTL"))
    with pytest.raises(RuntimeError, match="GUIDED"):
        patrol.volar_a(vehicle, patrol.BASE_1_COORDS, 15, 6, "Base 1")
    assert vehicle.simple_goto.call_count == 1


def test_horizontal_arrival_does_not_skip_altitude(vehicle):
    vehicle.location.global_relative_frame.lat, vehicle.location.global_relative_frame.lon = patrol.BASE_1_COORDS
    vehicle.location.global_relative_frame.alt = 6
    with pytest.raises(TimeoutError):
        patrol.volar_a(vehicle, patrol.BASE_1_COORDS, 15, 6, "ascenso")


def test_patrol_preserves_interference_clearance():
    clearance, length = patrol.validar_ruta()
    assert clearance >= 8
    assert length > 2000
