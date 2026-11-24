"""enriched telemetry columns and estaciones_carga table

Revision ID: e2a9c41f7d36
Revises: b1f3a82c9d05
Create Date: 2026-01-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a9c41f7d36"
down_revision: str | Sequence[str] | None = "b1f3a82c9d05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("telemetria_vuelo") as batch_op:
        batch_op.add_column(sa.Column("viento_velocidad_kmh", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("viento_direccion_deg", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("satelites_gps", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("gps_fix_type", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tilt_grados", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("senal_rf_porcentaje", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("latencia_ms", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("zona_actual", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("estado_zona", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("failsafe_gcs_activo", sa.Boolean(), nullable=True))

    op.create_table(
        "estaciones_carga",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=40), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("latitud", sa.Float(), nullable=False),
        sa.Column("longitud", sa.Float(), nullable=False),
        sa.Column("dock_radius_m", sa.Float(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("domo_estado", sa.String(length=20), nullable=False),
        sa.Column("voltaje_pad_v", sa.Float(), nullable=True),
        sa.Column("temperatura_c", sa.Float(), nullable=True),
        sa.Column("bateria_porcentaje", sa.Float(), nullable=True),
        sa.Column("ciclos_completados", sa.Integer(), nullable=False),
        sa.Column("ultimo_acoplamiento_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo"),
    )
    op.create_index(op.f("ix_estaciones_carga_id"), "estaciones_carga", ["id"], unique=False)
    op.create_index(op.f("ix_estaciones_carga_codigo"), "estaciones_carga", ["codigo"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_estaciones_carga_codigo"), table_name="estaciones_carga")
    op.drop_index(op.f("ix_estaciones_carga_id"), table_name="estaciones_carga")
    op.drop_table("estaciones_carga")

    with op.batch_alter_table("telemetria_vuelo") as batch_op:
        batch_op.drop_column("failsafe_gcs_activo")
        batch_op.drop_column("estado_zona")
        batch_op.drop_column("zona_actual")
        batch_op.drop_column("latencia_ms")
        batch_op.drop_column("senal_rf_porcentaje")
        batch_op.drop_column("tilt_grados")
        batch_op.drop_column("gps_fix_type")
        batch_op.drop_column("satelites_gps")
        batch_op.drop_column("viento_direccion_deg")
        batch_op.drop_column("viento_velocidad_kmh")
