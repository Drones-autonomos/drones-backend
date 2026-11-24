"""complete round2 schema sync

Agrega de forma idempotente todas las columnas faltantes del ORM en:
- usuarios: puesto, foto_url, preferencias_json, tokens_invalidados_antes_de
- ajustes_operativos: altitud_minima_m, altitud_maxima_m, peso_maximo_kg,
  hora_apertura, hora_cierre, scheduler_enabled
- auditoria: prev_hash, hash_sha256 (+ triggers de inmutabilidad en SQLite)

Revision ID: c4d9e812ab77
Revises: 0189eb619387
Create Date: 2026-11-24 03:32:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d9e812ab77"
down_revision: str | Sequence[str] | None = "0189eb619387"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)


def _drop_column_if_present(table: str, name: str) -> None:
    if _has_column(table, name):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column(name)


def upgrade() -> None:
    # 1. Columnas extendidas de perfil y revocación por usuario
    _add_column_if_missing("usuarios", sa.Column("puesto", sa.String(length=100), nullable=True))
    _add_column_if_missing("usuarios", sa.Column("foto_url", sa.Text(), nullable=True))
    _add_column_if_missing("usuarios", sa.Column("preferencias_json", sa.Text(), nullable=True))
    _add_column_if_missing("usuarios", sa.Column("tokens_invalidados_antes_de", sa.DateTime(), nullable=True))

    # 2. Ventana operativa normativa y estado persistido del scheduler autónomo
    _add_column_if_missing(
        "ajustes_operativos",
        sa.Column("altitud_minima_m", sa.Float(), server_default="2.0", nullable=False),
    )
    _add_column_if_missing(
        "ajustes_operativos",
        sa.Column("altitud_maxima_m", sa.Float(), server_default="200.0", nullable=False),
    )
    _add_column_if_missing(
        "ajustes_operativos",
        sa.Column("peso_maximo_kg", sa.Float(), server_default="5.0", nullable=False),
    )
    _add_column_if_missing(
        "ajustes_operativos",
        sa.Column("hora_apertura", sa.String(length=5), server_default="06:00", nullable=False),
    )
    _add_column_if_missing(
        "ajustes_operativos",
        sa.Column("hora_cierre", sa.String(length=5), server_default="23:00", nullable=False),
    )
    _add_column_if_missing(
        "ajustes_operativos",
        sa.Column("scheduler_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    # 3. Cadena criptográfica SHA-256 en auditoria
    _add_column_if_missing("auditoria", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    _add_column_if_missing("auditoria", sa.Column("hash_sha256", sa.String(length=64), nullable=True))

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_auditoria_no_update
            BEFORE UPDATE ON auditoria
            BEGIN
                SELECT RAISE(ABORT, 'Operación prohibida: registro inmutable.');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_auditoria_no_delete
            BEFORE DELETE ON auditoria
            BEGIN
                SELECT RAISE(ABORT, 'Operación prohibida: registro inmutable.');
            END;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_auditoria_no_update;")
        op.execute("DROP TRIGGER IF EXISTS trg_auditoria_no_delete;")

    _drop_column_if_present("auditoria", "hash_sha256")
    _drop_column_if_present("auditoria", "prev_hash")

    _drop_column_if_present("ajustes_operativos", "scheduler_enabled")
    _drop_column_if_present("ajustes_operativos", "hora_cierre")
    _drop_column_if_present("ajustes_operativos", "hora_apertura")
    _drop_column_if_present("ajustes_operativos", "peso_maximo_kg")
    _drop_column_if_present("ajustes_operativos", "altitud_maxima_m")
    _drop_column_if_present("ajustes_operativos", "altitud_minima_m")

    _drop_column_if_present("usuarios", "tokens_invalidados_antes_de")
    _drop_column_if_present("usuarios", "preferencias_json")
    _drop_column_if_present("usuarios", "foto_url")
    _drop_column_if_present("usuarios", "puesto")
