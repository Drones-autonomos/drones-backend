# Verification

- Use the existing virtual environment: `venv/bin/python -m pytest`.
- Patrol navigation regression checks: `venv/bin/python -m pytest tests/test_patrol_navigation.py tests/test_drone_navigation.py tests/test_normative_flight.py -q`.
- Lint patrol changes: `venv/bin/ruff check scripts/drone_backend.py tests/test_patrol_navigation.py`.
- `scripts.drone_backend.validar_ruta()` validates configured route segments against interference circles without connecting to a vehicle.
- Do not start another flight controller against an already running SITL patrol; running Python processes do not reload script edits automatically.
