import hashlib
import os
import re
from collections.abc import Iterator
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.core.security_crypto import decrypt_file_data, encrypt_file_data
from app.models.audit import Auditoria
from app.models.recording import Grabacion
from app.models.setting import AjustesOperativos
from app.models.user import Usuario
from app.schemas.recording import GrabacionResponse

router = APIRouter()
STORAGE_DIR = os.getenv("STORAGE_RECORDINGS_PATH", "storage/recordings")
os.makedirs(STORAGE_DIR, exist_ok=True)
CHUNK_SIZE = 64 * 1024
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _get_retention_days(db: Session) -> int:
    try:
        row = db.query(AjustesOperativos).order_by(AjustesOperativos.id.asc()).first()
        if row and row.retention_days and int(row.retention_days) > 0:
            return int(row.retention_days)
    except Exception:
        pass
    return 30


def _validate_upload_auth(request: Request, db: Session) -> None:
    expected_key = os.getenv("INGESTION_API_KEY", "").strip()
    sent_key = request.headers.get("X-Ingestion-Key", "").strip()
    auth_header = request.headers.get("Authorization", "").strip()

    if sent_key:
        if expected_key and sent_key != expected_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Ingestion-Key inválida")
        return

    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id = payload.get("sub")
            user = db.query(Usuario).filter(Usuario.id == int(user_id)).first() if user_id else None
        except (JWTError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido") from exc
        if not user or not user.activo or not user.rol or user.rol.nombre != "ADMIN":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo ADMIN puede subir grabaciones")
        return

    if expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere X-Ingestion-Key o Bearer token de ADMIN para subir grabaciones",
        )


def _authorize_stream_viewer(request: Request, token: str | None, db: Session) -> Usuario:
    auth_header = request.headers.get("Authorization", "")
    raw_token = (
        auth_header.split(" ", 1)[1].strip()
        if auth_header.lower().startswith("bearer ")
        else (token or "").strip()
    )
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticación requerida")
    try:
        user = deps.get_current_user_ws_or_query(db, raw_token)
    except HTTPException as exc:
        if exc.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.detail) from exc
        raise
    if not user.rol or user.rol.nombre not in ("ADMIN", "GUARDIA"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol no autorizado")
    return user


def _iter_bytes(data: bytes, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
    for offset in range(0, len(data), chunk_size):
        yield data[offset : offset + chunk_size]


@router.post(
    "/upload",
    response_model=GrabacionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir segmento de video grabado",
)
async def upload_recording(
    request: Request,
    file: UploadFile = File(...),
    vuelo_id: int | None = Form(None),
    duracion_segundos: int = Form(...),
    db: Session = Depends(deps.get_db),
):
    _validate_upload_auth(request, db)
    os.makedirs(STORAGE_DIR, exist_ok=True)

    content = await file.read()
    tamano_bytes = len(content)
    checksum = hashlib.sha256(content).hexdigest()
    ahora = datetime.utcnow()
    retention_days = _get_retention_days(db)

    nombre_archivo = f"{ahora.strftime('%Y%m%d_%H%M%S')}_{file.filename}.enc"
    ruta_destino = os.path.join(STORAGE_DIR, nombre_archivo)

    encrypted_data = encrypt_file_data(content)
    with open(ruta_destino, "wb") as f:
        f.write(encrypted_data)

    db_grabacion = Grabacion(
        vuelo_id=vuelo_id,
        ruta_archivo=ruta_destino,
        fecha_grabacion=ahora,
        duracion_segundos=duracion_segundos,
        tamano_bytes=tamano_bytes,
        checksum_sha256=checksum,
        fecha_purga=ahora + timedelta(days=retention_days),
        purgado=False,
    )
    db.add(db_grabacion)
    db.commit()
    db.refresh(db_grabacion)
    db_grabacion.dias_restantes_purga = retention_days
    return db_grabacion


@router.get("/", response_model=list[GrabacionResponse], summary="Listar grabaciones con filtros")
def list_recordings(
    vuelo_id: int | None = Query(None),
    fecha_inicio: datetime | None = Query(None),
    fecha_fin: datetime | None = Query(None),
    include_purged: bool = Query(True, description="Incluir metadatos criptográficos de videos ya purgados"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    query = db.query(Grabacion)
    if vuelo_id is not None:
        query = query.filter(Grabacion.vuelo_id == vuelo_id)
    if fecha_inicio:
        query = query.filter(Grabacion.fecha_grabacion >= fecha_inicio)
    if fecha_fin:
        query = query.filter(Grabacion.fecha_grabacion <= fecha_fin)
    if not include_purged:
        query = query.filter(Grabacion.purgado == False)  # noqa: E712

    records = query.order_by(Grabacion.fecha_grabacion.desc()).offset(skip).limit(limit).all()

    ahora = datetime.utcnow()
    for r in records:
        if r.purgado or not os.path.exists(r.ruta_archivo):
            r.dias_restantes_purga = 0
        else:
            delta = (r.fecha_purga - ahora).days
            r.dias_restantes_purga = max(0, delta)
    return records


@router.get("/{id}/stream", summary="Reproducir video descifrado con soporte HTTP Range")
def stream_recording(
    id: int,
    request: Request,
    token: str | None = Query(None),
    db: Session = Depends(deps.get_db),
):
    _authorize_stream_viewer(request, token, db)
    rec = db.query(Grabacion).filter(Grabacion.id == id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Grabación no encontrada")
    if rec.purgado or not os.path.exists(rec.ruta_archivo):
        raise HTTPException(
            status_code=410 if rec.purgado else 404,
            detail="El archivo de video fue purgado por retención normativa; se conserva su hash SHA-256.",
        )

    with open(rec.ruta_archivo, "rb") as f:
        encrypted_content = f.read()
    decrypted_content = decrypt_file_data(encrypted_content)
    total = len(decrypted_content)

    range_header = request.headers.get("range") or request.headers.get("Range")
    if range_header and total > 0:
        match = RANGE_RE.match(range_header.strip())
        if not match:
            raise HTTPException(status_code=416, detail="Cabecera Range inválida")
        start_s, end_s = match.groups()
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else total - 1
        end = min(end, total - 1)
        if start < 0 or start >= total or start > end:
            raise HTTPException(
                status_code=416,
                detail="Rango fuera de límites",
                headers={"Content-Range": f"bytes */{total}"},
            )
        chunk = decrypted_content[start : end + 1]
        return Response(
            content=chunk,
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(chunk)),
                "X-Recording-SHA256": rec.checksum_sha256,
            },
        )

    return StreamingResponse(
        _iter_bytes(decrypted_content),
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(total),
            "X-Recording-SHA256": rec.checksum_sha256,
        },
    )


@router.get("/{id}/download", summary="Descargar grabación (Solo Admin, auditado)")
def download_recording(
    id: int,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    rec = db.query(Grabacion).filter(Grabacion.id == id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Grabación no encontrada")
    if rec.purgado or not os.path.exists(rec.ruta_archivo):
        raise HTTPException(
            status_code=410 if rec.purgado else 404,
            detail="Grabación expirada y purgada del almacenamiento.",
        )

    with open(rec.ruta_archivo, "rb") as f:
        encrypted_content = f.read()
    decrypted_content = decrypt_file_data(encrypted_content)

    db.add(
        Auditoria(
            usuario_id=current_user.id,
            accion="DESCARGAR_GRABACION",
            recurso=f"/api/v1/recordings/{rec.id}/download",
            detalle=f"Descarga MP4 por {current_user.email} · SHA-256={rec.checksum_sha256[:12]}...",
            ip_origen=request.client.host if request.client else "unknown",
        )
    )
    db.commit()

    filename = os.path.basename(rec.ruta_archivo).replace(".enc", "")
    return StreamingResponse(
        _iter_bytes(decrypted_content),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Length": str(len(decrypted_content)),
            "X-Recording-SHA256": rec.checksum_sha256,
        },
    )
