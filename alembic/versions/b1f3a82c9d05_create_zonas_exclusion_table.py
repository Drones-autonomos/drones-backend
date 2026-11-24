"""create zonas_exclusion table

Revision ID: b1f3a82c9d05
Revises: 9c4e7a21f3b8
Create Date: 2026-11-24 08:10:00.000000

El modelo ZonaExclusion existía desde hace tiempo pero nunca tuvo migración;
los POST a /exclusion-zones fallaban con UndefinedTable.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1f3a82c9d05"
down_revision: str | Sequence[str] | None = "9c4e7a21f3b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "zonas_exclusion" not in inspector.get_table_names():
        op.create_table(
            "zonas_exclusion",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nombre", sa.String(length=100), nullable=False),
            sa.Column("lat_min", sa.Float(), nullable=False),
            sa.Column("lat_max", sa.Float(), nullable=False),
            sa.Column("lon_min", sa.Float(), nullable=False),
            sa.Column("lon_max", sa.Float(), nullable=False),
            sa.Column("activa", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_ix = {ix.get("name") for ix in inspector.get_indexes("zonas_exclusion")} if "zonas_exclusion" in inspector.get_table_names() else set()
    if op.f("ix_zonas_exclusion_id") not in existing_ix:
        op.create_index(op.f("ix_zonas_exclusion_id"), "zonas_exclusion", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_zonas_exclusion_id"), table_name="zonas_exclusion")
    op.drop_table("zonas_exclusion")
