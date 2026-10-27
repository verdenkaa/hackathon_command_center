"""Документы: дерево, содержимое, блокировки, изображения."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import Document, DocumentLock, User
from app.deps import get_current_user, get_db
from app.schemas import DocumentContent, DocumentCreate, DocumentOut, DocumentSave
from app.services import documents as doc_svc
from app.timeutil import utcnow

router = APIRouter(tags=["documents"])

ALLOWED_EXT = (".md", ".markdown")


def _get_document(db: Session, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise api_error(404, "NOT_FOUND", "Документ не найден")
    return doc


def _serialize(db: Session, doc: Document) -> DocumentOut:
    lock = doc_svc.active_lock(db, doc.id)
    return DocumentOut(
        id=doc.id,
        path=doc.path,
        author_id=doc.author_id,
        checksum=doc.checksum,
        trashed=doc.trashed,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        locked_by=lock.user_id if lock else None,
        editors=[lock.user_id] if lock else [],
    )


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
def list_documents(project_id: int, db: Session = Depends(get_db), _u=Depends(get_current_user)) -> list[DocumentOut]:
    rows = db.query(Document).filter(Document.project_id == project_id, Document.trashed.is_(False)).order_by(Document.path).all()
    return [_serialize(db, d) for d in rows]


@router.get("/projects/{project_id}/documents/trash", response_model=list[DocumentOut])
def list_trash(project_id: int, db: Session = Depends(get_db), _u=Depends(get_current_user)) -> list[DocumentOut]:
    rows = db.query(Document).filter(Document.project_id == project_id, Document.trashed.is_(True)).order_by(Document.path).all()
    return [_serialize(db, d) for d in rows]


@router.post("/projects/{project_id}/documents", response_model=DocumentOut)
def create_document(
    project_id: int,
    body: DocumentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentOut:
    path = body.path.strip().strip("/")
    if not path.endswith(ALLOWED_EXT):
        raise api_error(422, "VALIDATION_ERROR", "Поддерживаются только Markdown-файлы (.md)")
    if db.query(Document).filter(Document.project_id == project_id, Document.path == path).first():
        raise api_error(409, "DOCUMENT_EXISTS", "Документ с таким путём уже существует")
    doc_svc.write_file(project_id, path, body.content)
    doc = Document(
        project_id=project_id,
        path=path,
        author_id=user.id,
        checksum=doc_svc.checksum(body.content),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _serialize(db, doc)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db), _u=Depends(get_current_user)) -> DocumentOut:
    return _serialize(db, _get_document(db, document_id))


@router.get("/documents/{document_id}/content", response_model=DocumentContent)
def get_content(document_id: int, db: Session = Depends(get_db), _u=Depends(get_current_user)) -> DocumentContent:
    doc = _get_document(db, document_id)
    return DocumentContent(content=doc_svc.read_file(doc.project_id, doc.path))


@router.put("/documents/{document_id}/content", response_model=DocumentOut)
def save_content(
    document_id: int,
    body: DocumentSave,
    db: Session = Depends(get_db),
    _u=Depends(get_current_user),
) -> DocumentOut:
    doc = _get_document(db, document_id)
    if body.base_checksum != doc.checksum:
        raise api_error(409, "VERSION_CONFLICT", "Документ изменён другим пользователем")
    doc_svc.write_file(doc.project_id, doc.path, body.content)
    doc.checksum = doc_svc.checksum(body.content)
    doc.updated_at = utcnow()
    db.commit()
    db.refresh(doc)
    return _serialize(db, doc)


@router.post("/documents/{document_id}/lock", response_model=DocumentOut)
def lock_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DocumentOut:
    doc = _get_document(db, document_id)
    doc_svc.acquire_lock(db, doc.id, user.id)
    db.commit()
    return _serialize(db, doc)


@router.delete("/documents/{document_id}/lock", response_model=DocumentOut)
def unlock_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DocumentOut:
    doc = _get_document(db, document_id)
    doc_svc.release_lock(db, doc.id, user.id)
    db.commit()
    return _serialize(db, doc)


@router.post("/documents/{document_id}/heartbeat", response_model=DocumentOut)
def heartbeat(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DocumentOut:
    doc = _get_document(db, document_id)
    doc_svc.heartbeat_lock(db, doc.id, user.id)
    db.commit()
    return _serialize(db, doc)


@router.delete("/documents/{document_id}")
def trash_document(document_id: int, db: Session = Depends(get_db), _u=Depends(get_current_user)) -> dict:
    doc = _get_document(db, document_id)
    doc.trashed = True
    db.commit()
    return {"status": "ok"}


@router.post("/documents/{document_id}/restore")
def restore_document(document_id: int, db: Session = Depends(get_db), _u=Depends(get_current_user)) -> dict:
    doc = _get_document(db, document_id)
    doc.trashed = False
    db.commit()
    return {"status": "ok"}


@router.post("/projects/{project_id}/documents/images")
async def upload_image(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), _u=Depends(get_current_user)) -> dict:
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "png"
    if ext not in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
        raise api_error(422, "VALIDATION_ERROR", "Неподдерживаемый формат изображения")
    name = f"{uuid.uuid4().hex}.{ext}"
    rel = f"assets/{name}"
    doc_svc.write_bytes(project_id, rel, await file.read())
    return {"path": rel}


@router.get("/projects/{project_id}/documents/images/{filename}")
def get_image(project_id: int, filename: str, _db: Session = Depends(get_db), _u=Depends(get_current_user)) -> FileResponse:
    p = doc_svc.resolve_path(project_id, f"assets/{filename}")
    if not p.exists():
        raise api_error(404, "NOT_FOUND", "Изображение не найдено")
    return FileResponse(str(p))
