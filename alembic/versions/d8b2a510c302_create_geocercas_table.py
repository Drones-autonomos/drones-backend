"""create geocercas table

Revision ID: d8b2a510c302
Revises: c7a1f4289e01
Create Date: 2026-11-17 20:27:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8b2a510c302"
down_revision: str | Sequence[str] | None = "c7a1f4289e01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "geocercas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column("centro_lat", sa.Float(), nullable=True),
        sa.Column("centro_lon", sa.Float(), nullable=True),
        sa.Column("radio_metros", sa.Float(), nullable=True),
        sa.Column("poligono_json", sa.Text(), nullable=True),
        sa.Column("altitud_min_m", sa.Float(), nullable=False),
        sa.Column("altitud_max_m", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_geocercas_id"), "geocercas", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_geocercas_id"), table_name="geocercas")
    op.drop_table("geocercas")
