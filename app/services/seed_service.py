"""Seed idempotente de roles y cuentas demo para AeroLuferan.

`ensure_roles_and_demo_users` garantiza la existencia de los roles ADMIN y
GUARDIA y, cuando `seed_demo_users=True`, crea (solo si faltan) las cuentas
demo que usa `Login.jsx` en modo desarrollo (`import.meta.env.DEV`):

  - academico@uaq.mx / academico  (ADMIN)
  - seguridad@uaq.mx / seguridad  (GUARDIA)

Es seguro invocarlo en cada arranque: nunca modifica ni sobrescribe cuentas
existentes (emails ya registrados se respetan tal cual).
"""

from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.user import Rol, Usuario

ROLE_DEFINITIONS = (
    ("ADMIN", "Administrador académico del sistema"),
    ("GUARDIA", "Guardia de seguridad operativo"),
)

# Credenciales demo compartidas con drones-frontend/src/pages/Login/Login.jsx
# (TEST_CREDENTIALS). Solo se usan cuando seed_demo_users=True (entorno dev).
DEMO_USERS = (
    {
        "nombre": "Académico Demo",
        "email": "academico@uaq.mx",
        "password": "academico",
        "rol": "ADMIN",
        "puesto": "Administrador Académico",
    },
    {
        "nombre": "Guardia Demo",
        "email": "seguridad@uaq.mx",
        "password": "seguridad",
        "rol": "GUARDIA",
        "puesto": "Guardia de Seguridad",
    },
)


def ensure_roles(db: Session) -> dict[str, Rol]:
    """Garantiza que existan los roles base; devuelve {nombre: Rol}."""
    roles: dict[str, Rol] = {}
    for nombre, descripcion in ROLE_DEFINITIONS:
        rol = db.query(Rol).filter(Rol.nombre == nombre).first()
        if rol is None:
            rol = Rol(nombre=nombre, descripcion=descripcion)
            db.add(rol)
            db.flush()
        roles[nombre] = rol
    return roles


def ensure_roles_and_demo_users(db: Session, seed_demo_users: bool = False) -> dict[str, Usuario]:
    """Crea roles base y, opcionalmente, las cuentas demo de desarrollo.

    Idempotente: si un correo demo ya existe no se toca (ni contraseña ni rol).
    Devuelve el mapa {email: Usuario} de las cuentas demo gestionadas.
    """
    roles = ensure_roles(db)
    created: dict[str, Usuario] = {}
    if not seed_demo_users:
        db.commit()
        return created

    for spec in DEMO_USERS:
        existing = db.query(Usuario).filter(Usuario.email == spec["email"]).first()
        if existing is not None:
            created[spec["email"]] = existing
            continue
        user = Usuario(
            nombre=spec["nombre"],
            email=spec["email"],
            password_hash=get_password_hash(spec["password"]),
            rol_id=roles[spec["rol"]].id,
            puesto=spec["puesto"],
            activo=True,
        )
        db.add(user)
        db.flush()
        created[spec["email"]] = user
    db.commit()
    return created
