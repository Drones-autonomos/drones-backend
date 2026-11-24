"""create ajustes_operativos table

Revision ID: 9c4e7a21f3b8
Revises: 91fce11fd247, d8b2a510c302
Create Date: 2026-11-24 00:00:00.000000

Esta revisión actúa además como punto de merge de los dos heads abiertos
(91fce11fd247 → bitacora_vuelos/auditoria y d8b2a510c302 → geocercas),
dejando un único head para migraciones futuras.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c4e7a21f3b8"
down_revision: str | Sequence[str] | None = ("91fce11fd247", "d8b2a510c302")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ajustes_operativos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("critical_push_enabled", sa.Boolean(), nullable=False),
        sa.Column("ai_sensitivity_id", sa.String(length=10), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("transmission_quality_id", sa.String(length=20), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ajustes_operativos_id"), "ajustes_operativos", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ajustes_operativos_id"), table_name="ajustes_operativos")
    op.drop_table("ajustes_operativos")
