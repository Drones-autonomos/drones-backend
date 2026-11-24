"""Servicios de gestión de estado de alertas por usuario y serialización sin N+1."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.alert import Alerta, AlertaUsuario


def get_user_alert_states_map(
    db: Session,
    usuario_id: int,
    alerta_ids: list[int],
) -> dict[int, AlertaUsuario]:
    if not alerta_ids:
        return {}
    rows = (
        db.query(AlertaUsuario)
        .filter(
            AlertaUsuario.usuario_id == usuario_id,
            AlertaUsuario.alerta_id.in_(alerta_ids),
        )
        .all()
    )
    return {row.alerta_id: row for row in rows}


def upsert_user_alert_state(
    db: Session,
    *,
    usuario_id: int,
    alerta_id: int,
    mark_read: bool = False,
    mark_dismissed: bool = False,
) -> AlertaUsuario:
    now = datetime.utcnow()
    state = (
        db.query(AlertaUsuario)
        .filter(
            AlertaUsuario.usuario_id == usuario_id,
            AlertaUsuario.alerta_id == alerta_id,
        )
        .first()
    )
    if state is None:
        state = AlertaUsuario(
            usuario_id=usuario_id,
            alerta_id=alerta_id,
            leida_at=now if (mark_read or mark_dismissed) else None,
            descartada_at=now if mark_dismissed else None,
        )
        db.add(state)
    else:
        if (mark_read or mark_dismissed) and state.leida_at is None:
            state.leida_at = now
        if mark_dismissed and state.descartada_at is None:
            state.descartada_at = now
    return state


def serialize_alert_for_user(alerta: Alerta, state: AlertaUsuario | None) -> dict:
    leida_por_usuario = bool(state and state.leida_at is not None)
    descartada = bool(state and state.descartada_at is not None)
    return {
        "id": alerta.id,
        "evento_id": alerta.evento_id,
        "titulo": alerta.titulo,
        "mensaje": alerta.mensaje,
        "nivel_criticidad": alerta.nivel_criticidad,
        "leida": bool(alerta.leida or leida_por_usuario),
        "leida_por_usuario": leida_por_usuario,
        "descartada": descartada,
        "destinatario_rol": alerta.destinatario_rol,
        "timestamp_envio": alerta.timestamp_envio,
        "evento": alerta.evento,
    }
