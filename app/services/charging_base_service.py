"""Gestión de estaciones de carga/helipuertos automatizados del campus.

El estado operativo vive en memoria (`_StationState`) y se sincroniza con la
tabla `estaciones_carga` cuando los endpoints entregan una sesión `db`
(write-through). Sin `db`, el servicio funciona en memoria para las pruebas.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.charging_base import EstacionCarga
from app.services.geofence_service import haversine_distance_m

# Estaciones fijas del campus: HOME (principal) y Base 2 (pad secundario sur).
DEFAULT_STATIONS = (
    {
        "station_id": "helipuerto_norte",
        "codigo": "HELIPUERTO_NORTE",
        "nombre": "Helipuerto Base Norte #01 (HOME)",
        "lat": 20.70428,
        "lon": -100.44358,
        "domo_estado": "Abierto",
        "voltaje_pad_v": 16.4,
        "temperatura_c": 31.5,
    },
    {
        "station_id": "helipuerto_sur",
        "codigo": "HELIPUERTO_SUR",
        "nombre": "Helipuerto Base Sur #02 (Base 2)",
        "lat": 20.705145,
        "lon": -100.444093,
        "domo_estado": "Cerrado",
        "voltaje_pad_v": 16.1,
        "temperatura_c": 33.2,
    },
)


@dataclass(slots=True)
class _StationState:
    station_id: str
    codigo: str
    nombre: str
    lat: float
    lon: float
    dock_radius_m: float
    estado: str = "IDLE"  # IDLE | DOCKED | CHARGING | CHARGED
    domo_estado: str = "Abierto"
    voltaje_pad_v: float | None = None
    temperatura_c: float | None = None
    bateria_porcentaje: float = 100.0
    ciclos_completados: int = 0
    distancia_m: float | None = None
    ultimo_acoplamiento_at: datetime | None = field(default=None)


def _row_from_station(st: _StationState) -> EstacionCarga:
    return EstacionCarga(
        codigo=st.codigo,
        nombre=st.nombre,
        latitud=st.lat,
        longitud=st.lon,
        dock_radius_m=st.dock_radius_m,
        estado=st.estado,
        domo_estado=st.domo_estado,
        voltaje_pad_v=st.voltaje_pad_v,
        temperatura_c=st.temperatura_c,
        bateria_porcentaje=st.bateria_porcentaje,
        ciclos_completados=st.ciclos_completados,
        ultimo_acoplamiento_at=st.ultimo_acoplamiento_at,
    )


def _sync_to_row(row: EstacionCarga, st: _StationState) -> None:
    row.nombre = st.nombre
    row.latitud = st.lat
    row.longitud = st.lon
    row.dock_radius_m = st.dock_radius_m
    row.estado = st.estado
    row.domo_estado = st.domo_estado
    row.voltaje_pad_v = st.voltaje_pad_v
    row.temperatura_c = st.temperatura_c
    row.bateria_porcentaje = st.bateria_porcentaje
    row.ciclos_completados = st.ciclos_completados
    row.ultimo_acoplamiento_at = st.ultimo_acoplamiento_at


def _sync_from_row(st: _StationState, row: EstacionCarga) -> None:
    st.nombre = row.nombre
    st.estado = row.estado
    st.domo_estado = row.domo_estado
    st.voltaje_pad_v = row.voltaje_pad_v
    st.temperatura_c = row.temperatura_c
    if row.bateria_porcentaje is not None:
        st.bateria_porcentaje = row.bateria_porcentaje
    st.ciclos_completados = row.ciclos_completados
    st.ultimo_acoplamiento_at = row.ultimo_acoplamiento_at


class ChargingBaseService:
    """Gestiona el acoplamiento y el ciclo simulado de recarga en cada estación."""

    def __init__(
        self,
        *,
        home_lat: float = 20.70428,
        home_lon: float = -100.44358,
        dock_radius_m: float = 3.0,
        stations: tuple[dict, ...] = DEFAULT_STATIONS,
    ) -> None:
        self._lock = RLock()
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.dock_radius_m = dock_radius_m
        self.default_station_id = stations[0]["station_id"]
        self._stations: dict[str, _StationState] = {}
        for cfg in stations:
            self._stations[cfg["station_id"]] = _StationState(
                station_id=cfg["station_id"],
                codigo=cfg["codigo"],
                nombre=cfg["nombre"],
                lat=cfg["lat"],
                lon=cfg["lon"],
                dock_radius_m=dock_radius_m,
                domo_estado=cfg["domo_estado"],
                voltaje_pad_v=cfg["voltaje_pad_v"],
                temperatura_c=cfg["temperatura_c"],
            )

    # ------------------------------------------------------------------
    # Persistencia en estaciones_carga
    # ------------------------------------------------------------------

    def ensure_default_stations(self, db: Session) -> None:
        """Inserta las estaciones del campus en `estaciones_carga` si no existen."""
        with self._lock:
            try:
                changed = False
                for st in self._stations.values():
                    row = (
                        db.query(EstacionCarga)
                        .filter(EstacionCarga.codigo == st.codigo)
                        .first()
                    )
                    if row is None:
                        db.add(_row_from_station(st))
                        changed = True
                    else:
                        # La fila persistida es la verdad; hidrata el runtime.
                        _sync_from_row(st, row)
                if changed:
                    db.commit()
            except SQLAlchemyError:
                db.rollback()
                raise

    def _hydrate(self, db: Session | None) -> None:
        if db is not None:
            self.ensure_default_stations(db)

    def _persist(self, db: Session | None, st: _StationState) -> None:
        if db is None:
            return
        try:
            row = (
                db.query(EstacionCarga)
                .filter(EstacionCarga.codigo == st.codigo)
                .first()
            )
            if row is None:
                row = _row_from_station(st)
                db.add(row)
            else:
                _sync_to_row(row, st)
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def _station(self, station_id: str | None) -> _StationState:
        sid = station_id or self.default_station_id
        st = self._stations.get(sid)
        if st is None:
            # Permite también referenciar por `codigo` (HELIPUERTO_NORTE, etc.)
            for candidate in self._stations.values():
                if candidate.codigo == sid or candidate.codigo == str(sid).upper():
                    return candidate
            raise RuntimeError(f"Estación de carga desconocida: {sid}")
        return st

    @staticmethod
    def _public_state(st: _StationState) -> dict:
        return {
            "station_id": st.station_id,
            "codigo": st.codigo,
            "nombre": st.nombre,
            "home_lat": st.lat,
            "home_lon": st.lon,
            "dock_radius_m": st.dock_radius_m,
            "estado": st.estado,
            "domo_estado": st.domo_estado,
            "sistema_aterrizaje": "GPS+IR-LOCK",
            "voltaje_v": st.voltaje_pad_v,
            "temperatura_c": st.temperatura_c,
            "bateria_porcentaje": st.bateria_porcentaje,
            "ciclos_completados": st.ciclos_completados,
            "distancia_home_m": st.distancia_m,
            "ultimo_acoplamiento_at": (
                st.ultimo_acoplamiento_at.isoformat() if st.ultimo_acoplamiento_at else None
            ),
        }

    def station_coords(self, station_id: str | None, db: Session | None = None) -> dict:
        """Coordenadas del pad de una estación y si coincide con el HOME del dron."""
        with self._lock:
            self._hydrate(db)
            st = self._station(station_id)
            same_as_home = (
                haversine_distance_m(st.lat, st.lon, self.home_lat, self.home_lon)
                <= st.dock_radius_m
            )
            return {
                "station_id": st.station_id,
                "codigo": st.codigo,
                "nombre": st.nombre,
                "lat": st.lat,
                "lon": st.lon,
                "same_as_home": same_as_home,
            }

    def list_stations(self, db: Session | None = None) -> list[dict]:
        with self._lock:
            self._hydrate(db)
            return [self._public_state(st) for st in self._stations.values()]

    def get_status(self, station_id: str | None = None, db: Session | None = None) -> dict:
        with self._lock:
            self._hydrate(db)
            return self._public_state(self._station(station_id))

    # ------------------------------------------------------------------
    # Acoplamiento y recarga
    # ------------------------------------------------------------------

    def dock_and_recharge(
        self,
        drone,
        *,
        station_id: str | None = None,
        target_pct: float = 100.0,
        step_pct: float = 25.0,
        db: Session | None = None,
    ) -> dict:
        """Verifica aterrizaje junto a la estación y recarga hasta `target_pct`."""
        with self._lock:
            self._hydrate(db)
            st = self._station(station_id)
            if not drone.is_grounded():
                raise RuntimeError("El dron debe estar en tierra y desarmado para acoplarse a la base")

            loc = drone.vehicle.location.global_relative_frame
            if loc.lat is None or loc.lon is None:
                raise RuntimeError("Coordenadas del vehículo no disponibles para verificar la estación")

            dist_m = round(haversine_distance_m(float(loc.lat), float(loc.lon), st.lat, st.lon), 3)
            st.distancia_m = dist_m
            if dist_m > st.dock_radius_m:
                raise RuntimeError(
                    f"Fuera de la base de carga {st.codigo} ({dist_m:.2f} m > {st.dock_radius_m:.2f} m)"
                )

            battery = getattr(drone.vehicle, "battery", None)
            current = getattr(battery, "level", None)
            st.bateria_porcentaje = float(current) if current is not None else st.bateria_porcentaje
            st.estado = "DOCKED"
            st.ultimo_acoplamiento_at = datetime.now(UTC)

            if st.bateria_porcentaje < target_pct:
                st.estado = "CHARGING"
                while st.bateria_porcentaje < target_pct:
                    st.bateria_porcentaje = min(target_pct, st.bateria_porcentaje + step_pct)
                if battery is not None:
                    try:
                        battery.level = int(round(st.bateria_porcentaje))
                    except Exception:
                        pass

            st.estado = "CHARGED"
            st.ciclos_completados += 1
            self._persist(db, st)
            return self._public_state(st)


charging_base_service = ChargingBaseService()
