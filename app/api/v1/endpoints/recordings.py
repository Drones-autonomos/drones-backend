import os
import hashlib
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api import deps
from app.models.recording import Grabacion
from app.models.user import Usuario
from app.schemas.recording import GrabacionResponse
from app.core.security_crypto import encrypt_file_data, decrypt_file_data # implementado en security_crypto.py

router = APIRouter()
STORAGE_DIR = os.getenv("STORAGE_RECORDINGS_PATH", "storage/recordings")
os.makedirs(STORAGE_DIR, exist_ok=True)

@router.post(
    "/upload", 
    response_model=GrabacionResponse, 
    status_code=status.HTTP_201_CREATED,
    summary="Subir segmento de video grabado"
)
async def upload_recording(
    file: UploadFile = File(...),
    vuelo_id: int | None = Form(None),
    duracion_segundos: int = Form(...),
    db: Session = Depends(deps.get_db)
):
    content = await file.read()
    tamano_bytes = len(content)
    checksum = hashlib.sha256(content).hexdigest()
    
    nombre_archivo = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{file.filename}.enc"
    ruta_destino = os.path.join(STORAGE_DIR, nombre_archivo)
    
    # Cifrado en reposo (AES-GCM)
    encrypted_data = encrypt_file_data(content)
    with open(ruta_destino, "wb") as f:
        f.write(encrypted_data)
        
    db_grabacion = Grabacion(
        vuelo_id=vuelo_id,
        ruta_archivo=ruta_destino,
        duracion_segundos=duracion_segundos,
        tamano_bytes=tamano_bytes,
        checksum_sha256=checksum
    )
    db.add(db_grabacion)
    db.commit()
    db.refresh(db_grabacion)
    return db_grabacion

@router.get("/", response_model=list[GrabacionResponse], summary="Listar grabaciones con filtros")
def list_recordings(
    vuelo_id: int | None = Query(None),
    fecha_inicio: datetime | None = Query(None),
    fecha_fin: datetime | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin)
):
    query = db.query(Grabacion)
    if vuelo_id:
        query = query.filter(Grabacion.vuelo_id == vuelo_id)
    if fecha_inicio:
        query = query.filter(Grabacion.fecha_grabacion >= fecha_inicio)
    if fecha_fin:
        query = query.filter(Grabacion.fecha_grabacion <= fecha_fin)
        
    records = query.order_by(Grabacion.fecha_grabacion.desc()).offset(skip).limit(limit).all()
    
    # Inyectar cálculo de días restantes para purga para la UI de Guadalupe
    ahora = datetime.utcnow()
    for r in records:
        delta = (r.fecha_purga - ahora).days
        r.dias_restantes_purga = max(0, delta)
    return records

@router.get("/{id}/stream", summary="Reproducir video descifrado")
def stream_recording(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin)
):
    rec = db.query(Grabacion).filter(Grabacion.id == id).first()
    if not rec or not os.path.exists(rec.ruta_archivo):
        raise HTTPException(status_code=404, detail="Grabación no encontrada")
        
    with open(rec.ruta_archivo, "rb") as f:
        encrypted_content = f.read()
    decrypted_content = decrypt_file_data(encrypted_content)
    
    return StreamingResponse(iter([decrypted_content]), media_type="video/mp4")

@router.get("/{id}/download", summary="Descargar grabación (Solo Admin)")
def download_recording(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin) # Restricción estricta RBAC
):
    rec = db.query(Grabacion).filter(Grabacion.id == id).first()
    if not rec or not os.path.exists(rec.ruta_archivo):
        raise HTTPException(status_code=404, detail="Grabación no encontrada")
        
    with open(rec.ruta_archivo, "rb") as f:
        encrypted_content = f.read()
    decrypted_content = decrypt_file_data(encrypted_content)
    
    filename = os.path.basename(rec.ruta_archivo).replace(".enc", "")
    return StreamingResponse(
        iter([decrypted_content]), 
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )