"""Crear el primer administrador: python -m app.bootstrap_admin."""

from getpass import getpass

from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.user import Rol, Usuario
from app.schemas.user import UserCreate


def create_initial_admin(db: Session, nombre: str, email: str, password: str) -> Usuario:
    """Inicialización local; no modifica usuarios existentes ni permite repetir el bootstrap."""
    data = UserCreate(nombre=nombre, email=email, password=password, rol_id=1)
    if db.query(Usuario).join(Rol).filter(Rol.nombre == "ADMIN").first():
        raise ValueError("Ya existe un administrador. Usa el registro autenticado de la API.")
    if db.query(Usuario).filter(Usuario.email == data.email).first():
        raise ValueError("El correo ya existe; no se modificó su rol ni su contraseña.")
    for name in ("ADMIN", "GUARDIA"):
        if not db.query(Rol).filter(Rol.nombre == name).first():
            db.add(Rol(nombre=name))
    db.flush()
    rol = db.query(Rol).filter(Rol.nombre == "ADMIN").one()
    user = Usuario(
        nombre=data.nombre,
        email=data.email,
        password_hash=get_password_hash(data.password),
        rol_id=rol.id,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def main() -> None:
    nombre = input("Nombre del administrador: ")
    email = input("Correo: ")
    password = getpass("Contraseña (mínimo 6 caracteres): ")
    if password != getpass("Confirma la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden.")
    try:
        with SessionLocal.begin() as db:
            create_initial_admin(db, nombre, email, password)
    except ValueError:
        # No imprimir ValidationError: puede incluir la contraseña recibida.
        raise SystemExit(
            "No se pudo crear: revisa los datos y que no exista ya el correo o un administrador."
        ) from None
    print("Administrador creado. Inicia sesión en /api/v1/auth/login.")


if __name__ == "__main__":
    main()
