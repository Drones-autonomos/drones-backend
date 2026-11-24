import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from scripts import drone_backend as patrol


@pytest.fixture()
def vehicle(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "dronekit",
        SimpleNamespace(
            LocationGlobalRelative=lambda lat, lon, alt: SimpleNamespace(lat=lat, lon=lon, alt=alt),
        ),
    )
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


@pytest.mark.parametrize("name", ["clasica", "interior", "canchas"])
def test_complete_route_recovers_lost_commands(vehicle, name):
    route = [
        *patrol.RUTA_TRASLADO,
        patrol.BASE_1_COORDS,
        *[point[:2] for point in patrol.RUTAS_BARRIDO[name]],
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


@pytest.mark.parametrize("name", ["clasica", "interior", "canchas"])
def test_patrol_preserves_interference_clearance(name):
    clearance, length = patrol.validar_ruta(nombre_ruta=name)
    assert clearance >= 8
    assert length > 1000


def test_classic_patrol_preserves_original_points():
    assert patrol.RUTAS_BARRIDO["clasica"] == patrol.RUTA_BARRIDO


def test_variants_visit_different_points():
    classic = {point[:2] for point in patrol.RUTA_BARRIDO}
    for name in ("interior", "canchas"):
        assert {point[:2] for point in patrol.RUTAS_BARRIDO[name]} - classic


def test_unknown_route_rejected():
    with pytest.raises(ValueError, match="desconocida"):
        patrol.validar_ruta(nombre_ruta="inexistente")


def test_validation_checks_segments_not_only_waypoints(monkeypatch):
    monkeypatch.setitem(patrol.RUTAS_BARRIDO, "cruce", [(20.702645, -100.443974), (20.702645, -100.442340)])
    with pytest.raises(ValueError, match="interferencia"):
        patrol.validar_ruta(nombre_ruta="cruce")


@pytest.mark.parametrize("name", ["clasica", "interior", "canchas"])
def test_cli_selects_route_at_30_metres(monkeypatch, name):
    run = Mock()
    monkeypatch.setattr(patrol, "run_flight", run)
    monkeypatch.setattr(sys, "argv", ["drone_backend.py", "--ruta", name])
    patrol.main()
    run.assert_called_once_with(
        connection_string="127.0.0.1:14550",
        target_altitude=30.0,
        weight_kg=2.5,
        nombre_ruta=name,
    )


@pytest.mark.parametrize("name", ["clasica", "interior", "canchas"])
def test_dry_run_never_connects(monkeypatch, name, capsys):
    run = Mock()
    monkeypatch.setattr(patrol, "run_flight", run)
    monkeypatch.setattr(patrol, "validate_flight_plan", Mock())
    monkeypatch.setattr(sys, "argv", ["drone_backend.py", "--ruta", name, "--dry-run"])
    patrol.main()
    run.assert_not_called()
    assert name in capsys.readouterr().out


@pytest.mark.parametrize("name", ["clasica", "interior", "canchas"])
def test_flight_executes_selected_route_at_30_metres(vehicle, monkeypatch, name):
    vehicle.parameters = {}
    vehicle._master = SimpleNamespace(target_system=1, target_component=1, mav=Mock())
    vehicle.close = Mock()
    sys.modules["dronekit"].connect = Mock(return_value=vehicle)
    monkeypatch.setattr(patrol, "validate_flight_plan", Mock())
    monkeypatch.setattr(patrol, "arm_and_takeoff", Mock())
    navigate = Mock()
    monkeypatch.setattr(patrol, "volar_a", navigate)

    def land(*args):
        vehicle.location.global_relative_frame.alt = 0
        vehicle.armed = False

    vehicle._master.mav.set_mode_send.side_effect = land
    patrol.run_flight(nombre_ruta=name)
    patrol.arm_and_takeoff.assert_called_once_with(vehicle, 30.0)
    calls = navigate.call_args_list
    expected = [
        *patrol.RUTA_TRASLADO,
        patrol.BASE_1_COORDS,
        *[point[:2] for point in patrol.RUTAS_BARRIDO[name]],
        patrol.BASE_2_COORDS,
        *patrol.RUTA_REGRESO,
        patrol.BASE_1_COORDS,
    ]
    assert [call.args[1] for call in calls[:-1]] == expected
    assert all(call.args[2] == 30 for call in calls[:-1])
    assert calls[-1].args[1:3] == (patrol.BASE_1_COORDS, patrol.ALT_BASE_M)
    vehicle.close.assert_called_once()
