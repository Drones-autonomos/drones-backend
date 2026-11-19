# Verification

- Use the existing virtual environment: `venv/bin/python -m pytest`.
- Patrol navigation regression checks: `venv/bin/python -m pytest tests/test_patrol_navigation.py tests/test_drone_navigation.py tests/test_normative_flight.py -q`.
- Lint patrol changes: `venv/bin/ruff check scripts/drone_backend.py tests/test_patrol_navigation.py`.
- `scripts.drone_backend.validar_ruta()` validates configured route segments against interference circles without connecting to a vehicle.
- Do not start another flight controller against an already running SITL patrol; running Python processes do not reload script edits automatically.
- Patrol selection: `venv/bin/python scripts/drone_backend.py --ruta clasica|interior|canchas` (choose one name, not the literal pipes). Cruise altitude defaults to 30 m relative to home; Base 2 holds at cruise altitude, with descent only for the final landing at Base 1.
- Validate any variant without flight commands: `venv/bin/python scripts/drone_backend.py --ruta interior --dry-run`. Validation covers all transit, patrol and return segments against configured interference circles; it does not model building heights or terrain.
