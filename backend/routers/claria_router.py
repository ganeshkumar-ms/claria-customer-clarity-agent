import os
import sys
from pathlib import Path
from typing import Optional
import json
import uuid
from urllib.parse import quote
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body, Query
from fastapi.responses import FileResponse, HTMLResponse

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import (
    claria_service,
    document_service,
    file_validation,
    viewer_service,
    document_intelligence_service,
    redesign_engine_service,
    document_export_service,
    governance_store_service,
)

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
    return {"status": "ok", "agent": "CLARIA", "service": "Customer Communication Intelligence & Redesign Engine"}


@router.get('/document/{filename}/view')
def view_document(filename: str):
    """Opens the uploaded file inside the browser (PDF inline, highlighted HTML direct, Excel/Word/CSV/TXT as HTML)."""
    file_path = _resolve_upload(filename)
    name = _display_name(file_path.name)
    if file_path.suffix.lower() == '.pdf':
        return FileResponse(path=file_path, media_type='application/pdf',
                            headers={'Content-Disposition': f'inline; filename="{name}"'})
    if file_path.name.startswith('highlighted_') and file_path.suffix.lower() in ('.html', '.htm'):
        return HTMLResponse(file_path.read_text(encoding='utf-8', errors='ignore'))
    return HTMLResponse(viewer_service.render_html(file_path, name))


@router.get('/document/{filename}')
def get_document(filename: str):
    """Downloads the original or generated file (.pdf, .docx, .html, etc.)."""
    file_path = _resolve_upload(filename)
    ext = file_path.suffix.lower()
    mtype = None
    if ext == '.pdf':
        mtype = 'application/pdf'
    elif ext == '.docx':
        mtype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    return FileResponse(path=file_path, media_type=mtype, filename=_display_name(file_path.name))


def _run_enterprise_pipeline(
    raw_text: str,
    filename: str,
    instruction: str,
    doc_meta: dict | None,
    doc_id: str | None = None,
    prior_redesigned: dict | None = None,
    version_reason: str = 'Initial redesign',
    creator: str = 'Document Creator',
) -> dict:
    """Runs full-document intelligence, redesign, fact verification, comparison, export & governance."""
    structured = document_intelligence_service.parse_structured_document(raw_text, filename, doc_id=doc_id or '')
    used_doc_id = structured['document_id']
    redesigned = redesign_engine_service.generate_redesigned_document(
        structured,
        instruction=instruction,
        prior_redesigned=prior_redesigned,
    )
    fact_ver = document_intelligence_service.verify_output_facts(
        structured.get('source_facts') or [],
        redesigned.get('plain_text') or '',
    )
    comparison = redesign_engine_service.compare_original_vs_redesigned(structured, redesigned, fact_ver)
    detected_issues = redesign_engine_service.detect_communication_issues(structured, redesigned, fact_ver, comparison)

    ver_hint = 1
    existing_rec = governance_store_service.get_document_record(used_doc_id)
    if existing_rec:
        ver_hint = len(existing_rec.get('versions') or []) + 1

    prefix = f"{used_doc_id}_v{ver_hint}_{uuid.uuid4().hex[:5]}"
    exports = document_export_service.generate_all_outputs(
        out_dir=UPLOADS_DIR,
        file_prefix=prefix,
        redesigned=redesigned,
        fact_verification=fact_ver,
        comparison=comparison,
        version_label=f"Version {ver_hint} — {version_reason}",
    )
    gov = governance_store_service.create_or_add_version(
        doc_id=used_doc_id,
        original_meta=doc_meta or {'filename': filename},
        structured_doc=structured,
        redesigned=redesigned,
        fact_verification=fact_ver,
        comparison=comparison,
        downloads=exports['downloads'],
        quality_validation=exports['quality_validation'],
        instruction=instruction,
        version_reason=version_reason,
        creator=creator,
    )

    return {
        'document_id': used_doc_id,
        'version_number': gov['version_number'],
        'version_label': gov['version_label'],
        'intelligence': {
            'document_title': structured['document_title'],
            'document_type': structured['document_type'],
            'total_pages': structured['total_pages'],
            'word_count': structured['word_count'],
            'customer_elements_count': len(structured['customer_elements']),
            'internal_elements_count': len(structured['internal_elements']),
            'internal_sections': [
                {'section': el.get('section'), 'text': el.get('text')}
                for el in structured['internal_elements'][:10]
            ],
            'headings': structured['headings'][:20],
            'audience_clarification_needed': structured['audience_clarification_needed'],
            'communication_intelligence': structured.get('communication_intelligence') or {},
        },
        'redesigned_document': redesigned,
        'fact_verification': fact_ver,
        'comparison': comparison,
        'issues': detected_issues,
        'downloads': exports['downloads'],
        'quality_validation': exports['quality_validation'],
        'governance': gov,
    }


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
    stored_name = None
    raw_doc_text = None
    doc_filename = None
    combined_text = text or ''

    if file:
        file_name = file.filename or 'document'
        doc_filename = file_name
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
        raw_doc_text = file_content
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

    result = claria_service.redesign_communication(
        combined_text,
        history,
        raw_document_text=raw_doc_text,
        filename=doc_filename
    )
    if doc_meta:
        result['document_metadata'] = doc_meta

    if result.get('highlighted_document'):
        hl_html = result['highlighted_document'].get('full_html') or ''
        orig_disp = _display_name(stored_name) if stored_name else 'notice.txt'
        hl_name = f"highlighted_{stored_name or uuid.uuid4().hex[:8]}.html"
        try:
            (UPLOADS_DIR / hl_name).write_text(hl_html, encoding='utf-8')
            q = quote(hl_name)
            result['highlighted_document']['source_filename'] = orig_disp
            result['highlighted_document']['filename'] = f"highlighted_{Path(orig_disp).stem}.html"
            result['highlighted_document']['download_url'] = f"/api/document/{q}"
            result['highlighted_document']['view_url'] = f"/api/document/{q}/view"
            if doc_meta and doc_meta.get('view_url'):
                result['highlighted_document']['original_view_url'] = doc_meta['view_url']
                result['highlighted_document']['original_download_url'] = doc_meta.get('url')
        except Exception:
            pass

    if result.get('type') == 'redesign':
        source_for_ent = raw_doc_text or (result.get('highlighted_document') or {}).get('raw_text') or ''
        if source_for_ent.strip():
            ent_bundle = _run_enterprise_pipeline(
                raw_text=source_for_ent,
                filename=doc_filename or 'customer_communication.txt',
                instruction=(text or '').strip() or 'Redesign professionally for clarity while preserving all facts and disclosures.',
                doc_meta=doc_meta,
            )
            result.update(ent_bundle)

    return result


@router.post('/documents/{doc_id}/refine')
def refine_document(doc_id: str, payload: dict = Body(...)):
    """Iterative conversational refinement on an active document without restarting."""
    rec = governance_store_service.get_document_record(doc_id)
    if not rec:
        raise HTTPException(status_code=404, detail='Document not found.')
    instruction = str(payload.get('instruction') or '').strip()
    if not instruction:
        raise HTTPException(status_code=400, detail='Refinement instruction is required.')

    latest = (rec.get('versions') or [])[-1] if rec.get('versions') else {}
    prior_red = latest.get('redesigned_document')
    structured = rec.get('structured_doc') or {}
    raw_text = '\n'.join(el.get('text', '') for el in (structured.get('elements') or []))

    ent = _run_enterprise_pipeline(
        raw_text=raw_text,
        filename=rec.get('filename', 'document.txt'),
        instruction=instruction,
        doc_meta={
            'filename': rec.get('filename'),
            'sha256': rec.get('sha256'),
            'stored_name': rec.get('stored_name'),
            'view_url': rec.get('original_view_url'),
            'url': rec.get('original_download_url'),
        },
        doc_id=doc_id,
        prior_redesigned=prior_red,
        version_reason=f"Refinement ({instruction[:36]})",
        creator=rec.get('creator', 'Document Creator'),
    )
    return {'type': 'redesign_update', **ent}


@router.post('/documents/{doc_id}/correct')
def correct_document(doc_id: str, payload: dict = Body(...)):
    """Applies ONLY user-approved/edited corrections (YES) or records NO decision preserving version."""
    rec = governance_store_service.get_document_record(doc_id)
    if not rec:
        raise HTTPException(status_code=404, detail='Document not found.')
    decision_mode = str(payload.get('confirm') or 'yes').strip().lower()
    corrections = payload.get('corrections') or []
    actor = str(payload.get('actor') or 'Editor').strip()

    latest = (rec.get('versions') or [])[-1] if rec.get('versions') else None
    if not latest:
        raise HTTPException(status_code=400, detail='No redesigned version found.')

    if decision_mode == 'no':
        gov_res = governance_store_service.record_approval_action(
            doc_id=doc_id,
            decision='preserve_no_correction',
            reviewer_name=actor,
            reviewer_role='Editor',
            comments='User chose NO — preserved current redesigned version and kept discrepancy findings available.',
            version_number=latest['version_number'],
        )
        return {'type': 'correction_preserved', 'preserved': True, 'governance': gov_res}

    updated_red, decision_log = redesign_engine_service.apply_selected_corrections(
        latest['redesigned_document'],
        corrections,
    )
    structured = rec.get('structured_doc') or {}
    fact_ver = document_intelligence_service.verify_output_facts(
        structured.get('source_facts') or [],
        updated_red.get('plain_text') or '',
    )
    comparison = redesign_engine_service.compare_original_vs_redesigned(structured, updated_red, fact_ver)
    ver_num = len(rec.get('versions') or []) + 1
    prefix = f"{doc_id}_v{ver_num}_{uuid.uuid4().hex[:5]}"
    exports = document_export_service.generate_all_outputs(
        out_dir=UPLOADS_DIR,
        file_prefix=prefix,
        redesigned=updated_red,
        fact_verification=fact_ver,
        comparison=comparison,
        version_label=f"Version {ver_num} — Approved corrections",
    )
    gov = governance_store_service.create_or_add_version(
        doc_id=doc_id,
        original_meta={'filename': rec.get('filename'), 'sha256': rec.get('sha256')},
        structured_doc=structured,
        redesigned=updated_red,
        fact_verification=fact_ver,
        comparison=comparison,
        downloads=exports['downloads'],
        quality_validation=exports['quality_validation'],
        instruction='Applied approved user corrections',
        version_reason='Approved corrections',
        creator=rec.get('creator', 'Document Creator'),
    )
    governance_store_service.append_audit_event(
        doc_id=doc_id,
        action='Applied Approved Corrections',
        actor=actor,
        role='Editor',
        details=f"Processed {len(decision_log)} issue decision(s); created Version {gov['version_number']}.",
        version_number=gov['version_number'],
    )
    return {
        'type': 'correction_applied',
        'document_id': doc_id,
        'version_number': gov['version_number'],
        'version_label': gov['version_label'],
        'decision_log': decision_log,
        'redesigned_document': updated_red,
        'fact_verification': fact_ver,
        'comparison': comparison,
        'downloads': exports['downloads'],
        'quality_validation': exports['quality_validation'],
        'governance': gov,
    }


@router.get('/documents/{doc_id}/compare')
def compare_versions(doc_id: str, v1: int = Query(0), v2: int = Query(0)):
    """Compares Original (0) vs any version, or any two versions."""
    rec = governance_store_service.get_document_record(doc_id)
    if not rec:
        raise HTTPException(status_code=404, detail='Document not found.')
    vers = rec.get('versions') or []
    if not vers:
        raise HTTPException(status_code=400, detail='No versions available.')

    target_v2 = next((v for v in vers if v['version_number'] == v2), vers[-1])
    if v1 == 0:
        return {
            'document_id': doc_id,
            'left_label': 'Original Document',
            'right_label': target_v2['version_label'],
            'left_text': '\n'.join(el.get('text', '') for el in (rec.get('structured_doc', {}).get('customer_elements') or [])),
            'right_text': target_v2['redesigned_document'].get('plain_text', ''),
            'comparison': target_v2['comparison'],
            'fact_verification': target_v2['fact_verification'],
        }

    target_v1 = next((v for v in vers if v['version_number'] == v1), vers[0])
    fake_struct = {
        'customer_elements': [
            {'element_type': 'paragraph', 'text': ln}
            for ln in (target_v1['redesigned_document'].get('plain_text') or '').splitlines() if ln.strip()
        ],
        'total_pages': rec.get('total_pages', 1),
    }
    cmp_res = redesign_engine_service.compare_original_vs_redesigned(
        fake_struct,
        target_v2['redesigned_document'],
        target_v2['fact_verification'],
    )
    return {
        'document_id': doc_id,
        'left_label': target_v1['version_label'],
        'right_label': target_v2['version_label'],
        'left_text': target_v1['redesigned_document'].get('plain_text', ''),
        'right_text': target_v2['redesigned_document'].get('plain_text', ''),
        'comparison': cmp_res,
        'fact_verification': target_v2['fact_verification'],
    }


@router.post('/documents/{doc_id}/approve')
def approve_document(doc_id: str, payload: dict = Body(...)):
    """Human approval workflow enforcing role-based separation of duties."""
    decision = str(payload.get('decision') or '').strip()
    reviewer_name = str(payload.get('reviewer_name') or '').strip() or 'Compliance Reviewer'
    reviewer_role = str(payload.get('reviewer_role') or 'Compliance Reviewer').strip()
    comments = str(payload.get('comments') or '').strip()
    ver_num = payload.get('version_number')

    res = governance_store_service.record_approval_action(
        doc_id=doc_id,
        decision=decision,
        reviewer_name=reviewer_name,
        reviewer_role=reviewer_role,
        comments=comments,
        version_number=ver_num,
    )
    if res.get('error'):
        raise HTTPException(status_code=403, detail=res['error'])
    return res


@router.get('/documents/{doc_id}')
def get_document_details(doc_id: str):
    rec = governance_store_service.get_document_record(doc_id)
    if not rec:
        raise HTTPException(status_code=404, detail='Document not found.')
    return rec


@router.post('/documents/{doc_id}/adapt-channel')
def adapt_document_channel(doc_id: str, payload: dict = Body(...)):
    """Adapts an active redesigned communication to a specific delivery channel (Email, SMS, Push, WhatsApp, CS Script)."""
    rec = governance_store_service.get_document_record(doc_id)
    if not rec:
        raise HTTPException(status_code=404, detail='Document not found.')
    latest = (rec.get('versions') or [])[-1] if rec.get('versions') else None
    if not latest:
        raise HTTPException(status_code=400, detail='No redesigned version found.')
    channel = str(payload.get('channel') or 'email').strip()
    adapted = redesign_engine_service.adapt_for_channel(
        latest['redesigned_document'],
        channel=channel,
        structured_doc=rec.get('structured_doc'),
    )
    governance_store_service.append_audit_event(
        doc_id=doc_id,
        action='Multi-Channel Adaptation',
        actor=str(payload.get('actor') or 'Editor'),
        role='Editor',
        details=f"Adapted Version {latest['version_number']} for channel: {adapted['channel']}.",
        version_number=latest['version_number'],
    )
    return adapted


@router.get('/dashboard')
def dashboard(
    status: str = Query(''),
    doc_type: str = Query(''),
    severity: str = Query(''),
    search: str = Query(''),
):
    return governance_store_service.get_dashboard_metrics(
        status_filter=status,
        doc_type_filter=doc_type,
        severity_filter=severity,
        search=search,
    )

