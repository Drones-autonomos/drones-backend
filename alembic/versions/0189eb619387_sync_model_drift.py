"""sync model drift

Sincroniza el esquema con los modelos extendidos por los agentes del Plan
Maestro (columnas y tablas creadas vía create_all sin migración propia).
Idempotente: cada operación verifica si el objeto ya existe, así que es
segura tanto en bases ya sincronizadas como en cadenas de migración nuevas
(PostgreSQL y SQLite).

Revision ID: 0189eb619387
Revises: e2a9c41f7d36
Create Date: 2026-11-24 02:59:04.596886

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0189eb619387'
down_revision: Union[str, Sequence[str], None] = 'e2a9c41f7d36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _has_fk(table: str, name: str) -> bool:
    return any(fk.get("name") == name for fk in _inspector().get_foreign_keys(table))


def _has_index(table: str, name: str) -> bool:
    return any(ix.get("name") == name for ix in _inspector().get_indexes(table))


def _add_column(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)


def _drop_column(table: str, name: str) -> None:
    if _has_column(table, name):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column(name)


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if not _has_index(table, name):
        op.create_index(op.f(name), table, columns, unique=unique)


def upgrade() -> None:
    if not _has_table('alertas_usuarios'):
        op.create_table(
            'alertas_usuarios',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('usuario_id', sa.Integer(), nullable=False),
            sa.Column('alerta_id', sa.Integer(), nullable=False),
            sa.Column('leida_at', sa.DateTime(), nullable=True),
            sa.Column('descartada_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['alerta_id'], ['alertas.id']),
            sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('usuario_id', 'alerta_id', name='uq_alerta_usuario'),
        )
    _create_index('ix_alertas_usuarios_alerta_id', 'alertas_usuarios', ['alerta_id'])
    _create_index('ix_alertas_usuarios_id', 'alertas_usuarios', ['id'])
    _create_index('ix_alertas_usuarios_usuario_id', 'alertas_usuarios', ['usuario_id'])

    _add_column('bitacora_vuelos', sa.Column('prev_hash', sa.String(length=64), nullable=True))
    _add_column('bitacora_vuelos', sa.Column('hash_sha256', sa.String(length=64), nullable=True))
    _add_column('detecciones', sa.Column('altitud_metros', sa.Float(), nullable=True))
    _add_column('detecciones', sa.Column('checksum_sha256', sa.String(length=64), nullable=True))
    _add_column('eventos', sa.Column('atendido_por_id', sa.Integer(), nullable=True))
    _add_column('eventos', sa.Column('resuelto_por_id', sa.Integer(), nullable=True))
    _add_column('eventos', sa.Column('despachado_at', sa.DateTime(), nullable=True))
    _add_column('eventos', sa.Column('resuelto_at', sa.DateTime(), nullable=True))
    _add_column('eventos', sa.Column('notas_resolucion', sa.Text(), nullable=True))
    with op.batch_alter_table('eventos') as batch_op:
        if not _has_fk('eventos', 'fk_eventos_resuelto_por_id'):
            batch_op.create_foreign_key('fk_eventos_resuelto_por_id', 'usuarios', ['resuelto_por_id'], ['id'])
        if not _has_fk('eventos', 'fk_eventos_atendido_por_id'):
            batch_op.create_foreign_key('fk_eventos_atendido_por_id', 'usuarios', ['atendido_por_id'], ['id'])

    _add_column('geocercas', sa.Column('descripcion', sa.Text(), nullable=True))
    _add_column('geocercas', sa.Column('motivo', sa.String(length=255), nullable=True))
    _add_column('geocercas', sa.Column('codigo_badge', sa.String(length=20), nullable=True))
    _add_column('grabaciones', sa.Column('purgado', sa.Boolean(), server_default=sa.false(), nullable=False))

    _add_column('misiones', sa.Column('ejecutado_por', sa.Integer(), nullable=True))
    _add_column('misiones', sa.Column('horario_fin_programado', sa.DateTime(), nullable=True))
    _add_column('misiones', sa.Column('duracion_estimada_min', sa.Integer(), nullable=True))
    _add_column('misiones', sa.Column('helipuerto_salida', sa.String(length=80), nullable=True))
    _add_column('misiones', sa.Column('helipuerto_llegada', sa.String(length=80), nullable=True))
    _add_column('misiones', sa.Column('es_recurrente', sa.Boolean(), server_default=sa.false(), nullable=False))
    _add_column('misiones', sa.Column('dias_semana_json', sa.String(length=100), nullable=True))
    _add_column('misiones', sa.Column('evitacion_exclusion', sa.Boolean(), server_default=sa.true(), nullable=False))
    _add_column('misiones', sa.Column('bateria_minima_pct', sa.Integer(), nullable=True))
    _add_column('misiones', sa.Column('sensor_optico', sa.String(length=60), nullable=True))
    with op.batch_alter_table('misiones') as batch_op:
        if not _has_fk('misiones', 'fk_misiones_ejecutado_por'):
            batch_op.create_foreign_key('fk_misiones_ejecutado_por', 'usuarios', ['ejecutado_por'], ['id'])

    _add_column('rutas', sa.Column('hover_segundos', sa.Float(), server_default='0', nullable=False))

    # tokens_revocados nació por create_all y no tiene migración propia:
    # donde existe se ajusta (jti único + revocado_at NOT NULL); en una
    # cadena fresca se crea según el modelo.
    if _has_table('tokens_revocados'):
        with op.batch_alter_table('tokens_revocados') as batch_op:
            batch_op.alter_column('revocado_at', existing_type=sa.DateTime(), nullable=False)
            if _has_index('tokens_revocados', 'ix_tokens_revocados_jti'):
                batch_op.drop_index('ix_tokens_revocados_jti')
            batch_op.create_index('ix_tokens_revocados_jti', ['jti'], unique=True)
    else:
        op.create_table(
            'tokens_revocados',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('jti', sa.String(length=64), nullable=False),
            sa.Column('expira_at', sa.DateTime(), nullable=False),
            sa.Column('revocado_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('jti'),
        )
        _create_index('ix_tokens_revocados_id', 'tokens_revocados', ['id'])
        _create_index('ix_tokens_revocados_jti', 'tokens_revocados', ['jti'], unique=True)

    _add_column('zonas_exclusion', sa.Column('clasificacion', sa.String(length=20), server_default='restringida', nullable=False))
    _add_column('zonas_exclusion', sa.Column('motivo', sa.String(length=255), nullable=True))
    _add_column('zonas_exclusion', sa.Column('descripcion', sa.Text(), nullable=True))
    _add_column('zonas_exclusion', sa.Column('codigo_badge', sa.String(length=20), nullable=True))
    _add_column('zonas_exclusion', sa.Column('altitud_max_m', sa.Float(), nullable=True))


def downgrade() -> None:
    _drop_column('zonas_exclusion', 'altitud_max_m')
    _drop_column('zonas_exclusion', 'codigo_badge')
    _drop_column('zonas_exclusion', 'descripcion')
    _drop_column('zonas_exclusion', 'motivo')
    _drop_column('zonas_exclusion', 'clasificacion')
    if _has_table('tokens_revocados'):
        op.drop_table('tokens_revocados')
    _drop_column('rutas', 'hover_segundos')
    if _has_fk('misiones', 'fk_misiones_ejecutado_por'):
        with op.batch_alter_table('misiones') as batch_op:
            batch_op.drop_constraint('fk_misiones_ejecutado_por', type_='foreignkey')
    _drop_column('misiones', 'sensor_optico')
    _drop_column('misiones', 'bateria_minima_pct')
    _drop_column('misiones', 'evitacion_exclusion')
    _drop_column('misiones', 'dias_semana_json')
    _drop_column('misiones', 'es_recurrente')
    _drop_column('misiones', 'helipuerto_llegada')
    _drop_column('misiones', 'helipuerto_salida')
    _drop_column('misiones', 'duracion_estimada_min')
    _drop_column('misiones', 'horario_fin_programado')
    _drop_column('misiones', 'ejecutado_por')
    _drop_column('grabaciones', 'purgado')
    _drop_column('geocercas', 'codigo_badge')
    _drop_column('geocercas', 'motivo')
    _drop_column('geocercas', 'descripcion')
    with op.batch_alter_table('eventos') as batch_op:
        if _has_fk('eventos', 'fk_eventos_resuelto_por_id'):
            batch_op.drop_constraint('fk_eventos_resuelto_por_id', type_='foreignkey')
        if _has_fk('eventos', 'fk_eventos_atendido_por_id'):
            batch_op.drop_constraint('fk_eventos_atendido_por_id', type_='foreignkey')
    _drop_column('eventos', 'notas_resolucion')
    _drop_column('eventos', 'resuelto_at')
    _drop_column('eventos', 'despachado_at')
    _drop_column('eventos', 'resuelto_por_id')
    _drop_column('eventos', 'atendido_por_id')
    _drop_column('detecciones', 'checksum_sha256')
    _drop_column('detecciones', 'altitud_metros')
    _drop_column('bitacora_vuelos', 'hash_sha256')
    _drop_column('bitacora_vuelos', 'prev_hash')
    if _has_table('alertas_usuarios'):
        op.drop_table('alertas_usuarios')
