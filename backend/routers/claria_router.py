import os
import sys
from pathlib import Path
from typing import Optional
import json
import uuid
from urllib.parse import quote
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import claria_service, document_service, file_validation, viewer_service

router = APIRouter(prefix='/api')
UPLOADS_DIR = Path('/tmp/uploads') if os.path.exists('/tmp') else (Path(__file__).resolve().parent.parent / 'uploads')
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_upload(filename: str) -> Path:
    safe = Path(filename).name
    file_path = UPLOADS_DIR / safe
    if not file_path.exists():
        raise HTTPException(status_code=404, detail='File not found. Please upload it again.')
    return file_path


def _display_name(stored: str) -> str:
    return stored.split('_', 1)[1] if len(stored) > 9 and stored[8] == '_' else stored


@router.get('/health')
def health():
    return {"status": "ok", "agent": "CLARIA", "service": "Customer Communications Redesign"}


@router.get('/document/{filename}/view')
def view_document(filename: str):
    """Opens the uploaded file inside the browser (PDF inline, Excel/Word/CSV/TXT as HTML)."""
    file_path = _resolve_upload(filename)
    name = _display_name(file_path.name)
    if file_path.suffix.lower() == '.pdf':
        return FileResponse(path=file_path, media_type='application/pdf',
                            headers={'Content-Disposition': f'inline; filename="{name}"'})
    return HTMLResponse(viewer_service.render_html(file_path, name))


@router.get('/document/{filename}')
def get_document(filename: str):
    """Downloads the original uploaded file."""
    file_path = _resolve_upload(filename)
    return FileResponse(path=file_path, filename=_display_name(file_path.name))


@router.post('/redesign')
async def redesign(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    conversation_history: Optional[str] = Form('[]')
):
    try:
        history = json.loads(conversation_history or '[]')
    except json.JSONDecodeError:
        history = []

    doc_meta = None
    combined_text = text or ''

    if file:
        file_name = file.filename or 'document'
        file_bytes = await file.read()
        pre_rej = file_validation.validate_file_pre_extract(file_name, file_bytes)
        if pre_rej:
            return {
                'type': 'chat',
                'message': pre_rej['message'],
                'rejected': True,
                'rejection_details': pre_rej,
                'document_metadata': {'filename': file_name, 'size_bytes': len(file_bytes)},
            }
        stored_name = f"{uuid.uuid4().hex[:8]}_{Path(file_name).name}"
        try:
            (UPLOADS_DIR / stored_name).write_bytes(file_bytes)
        except Exception:
            stored_name = None

        extracted = document_service.extract_text(file_bytes, file_name)
        doc_meta = extracted.get('metadata', {})
        if stored_name:
            q = quote(stored_name)
            doc_meta['stored_name'] = stored_name
            doc_meta['url'] = f'/api/document/{q}'
            doc_meta['view_url'] = f'/api/document/{q}/view'

        user_text = (text or '').strip()

        post_rej = file_validation.validate_file_post_extract(file_name, file_bytes, extracted.get('text', ''), meta=doc_meta)
        if post_rej or doc_meta.get('is_empty', False) or len(file_bytes) == 0:
            return {
                'type': 'chat',
                'message': post_rej['message'] if post_rej else f"File Not Accepted: '{file_name}' is empty.",
                'rejected': True,
                'rejection_details': post_rej,
                'document_metadata': doc_meta,
            }

        file_content = extracted.get('text', '')
        combined_text = (
            f"[COMMUNICATION DOCUMENT: {file_name}]\n"
            f"==================== ORIGINAL COMMUNICATION ====================\n"
            f"{file_content}\n"
            f"===============================================================\n"
        )
        if user_text:
            combined_text += f"\nRecipient's Question / Note: {user_text}\n"

    if not combined_text.strip():
        raise HTTPException(status_code=400, detail='Please provide a communication text or upload a document.')

    result = claria_service.redesign_communication(combined_text, history)
    if doc_meta:
        result['document_metadata'] = doc_meta

    return result

