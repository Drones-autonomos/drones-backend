"""Persist mission execution and exclusive vehicle reservation.

Revision ID: 6bf21ac304de
Revises: 4cd1d3910acb
"""

import sqlalchemy as sa
from alembic import op

revision = "6bf21ac304de"
down_revision = "4cd1d3910acb"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("misiones") as batch:
        batch.add_column(sa.Column("iniciada_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("finalizada_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("waypoints_completados", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(sa.Column("error_ejecucion", sa.Text(), nullable=True))
        batch.add_column(sa.Column("vehiculo_activo", sa.Integer(), nullable=True))
        batch.create_unique_constraint("uq_misiones_vehiculo_activo", ["vehiculo_activo"])
        batch.create_check_constraint("ck_mision_vehiculo", "vehiculo_activo IS NULL OR vehiculo_activo = 1")


def downgrade():
    with op.batch_alter_table("misiones") as batch:
        batch.drop_constraint("ck_mision_vehiculo", type_="check")
        batch.drop_constraint("uq_misiones_vehiculo_activo", type_="unique")
        for column in ("vehiculo_activo", "error_ejecucion", "waypoints_completados", "finalizada_at", "iniciada_at"):
            batch.drop_column(column)
