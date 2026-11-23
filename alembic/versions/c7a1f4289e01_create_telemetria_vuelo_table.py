"""create telemetria_vuelo table

Revision ID: c7a1f4289e01
Revises: b5ba037744c6
Create Date: 2026-11-17 20:25:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a1f4289e01"
down_revision: str | Sequence[str] | None = "b5ba037744c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telemetria_vuelo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mision_id", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitud", sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column("longitud", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("altitud_metros", sa.Float(), nullable=True),
        sa.Column("bateria_porcentaje", sa.Float(), nullable=True),
        sa.Column("voltaje_bateria", sa.Float(), nullable=True),
        sa.Column("velocidad_tierra_ms", sa.Float(), nullable=True),
        sa.Column("rumbo_grados", sa.Float(), nullable=True),
        sa.Column("modo_vuelo", sa.String(length=30), nullable=True),
        sa.Column("armado", sa.Boolean(), nullable=False),
        sa.Column("estado_enlace", sa.String(length=30), nullable=False),
        sa.Column("heartbeat_age_s", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["mision_id"], ["misiones.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telemetria_vuelo_id"), "telemetria_vuelo", ["id"], unique=False)
    op.create_index(op.f("ix_telemetria_vuelo_mision_id"), "telemetria_vuelo", ["mision_id"], unique=False)
    op.create_index(op.f("ix_telemetria_vuelo_timestamp"), "telemetria_vuelo", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_telemetria_vuelo_timestamp"), table_name="telemetria_vuelo")
    op.drop_index(op.f("ix_telemetria_vuelo_mision_id"), table_name="telemetria_vuelo")
    op.drop_index(op.f("ix_telemetria_vuelo_id"), table_name="telemetria_vuelo")
    op.drop_table("telemetria_vuelo")
