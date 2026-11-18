import base64
import difflib
import json
import os
import re
import tempfile
import uuid
from email.parser import BytesParser
from email.policy import default as default_email_policy
from pathlib import Path
from urllib.parse import quote, unquote

import boto3
from botocore.config import Config
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

REFINEMENT_INTENT_RE = (
    r'\b(?:empath\w*|harsh\w*|soft\w*|warm\w*|gentl\w*|kind\w*|compassion\w*|reassur\w*|'
    r'supportive|polite\w*|respectful|friendly|friendlier|conversational|simpl\w*|plain\s+english|'
    r'easy|easier|clearer|concise|short\w*|brief|formal|corporate|professional|tone|tune|rewrite|'
    r'redesign|rephrase|reword|make\s+it|want\s+it|change\s+the|less\s+harsh|not\s+harsh|too\s+harsh|'
    r'very\s+harsh|intimidating|threatening|strict|cold|senior\w*|audience|refine)\b'
)

FUZZY_INTENT_WORDS = (
    'empathy', 'empathetic', 'harsh', 'softer', 'gentle', 'warm', 'reassuring',
    'supportive', 'polite', 'friendly', 'conversational', 'simple', 'simplify',
    'concise', 'formal', 'professional', 'tone', 'rewrite', 'redesign',
    'rephrase', 'reword', 'refine', 'clearer', 'welcoming', 'approachable',
)


def _has_refinement_intent(text: str, has_active_doc: bool = False) -> bool:
    if not text or not text.strip():
        return False
    low = text.strip().lower()
    if re.search(REFINEMENT_INTENT_RE, low, re.IGNORECASE):
        return True
    tokens = re.findall(r'[a-z]+', low)
    for tok in tokens:
        if len(tok) >= 4:
            for kw in FUZZY_INTENT_WORDS:
                if difflib.SequenceMatcher(None, tok, kw).ratio() >= 0.72:
                    return True
    if has_active_doc and len(tokens) <= 25:
        pure_greetings = {'hi', 'hello', 'hey', 'ok', 'okay', 'thanks', 'thank', 'bye'}
        if tokens and not all(t in pure_greetings for t in tokens):
            if not re.match(r'^(?:what|when|where|who|how|why|is|are|can|do)\b.*\?$', low):
                return True
    return False

TMP_UPLOADS = Path(tempfile.gettempdir()) / 'uploads'
TMP_UPLOADS.mkdir(parents=True, exist_ok=True)
S3_BUCKET = os.environ.get('CLARIA_S3_BUCKET', 'claria-ui-984625844016')
REGION = os.environ.get('AWS_REGION', 'us-east-1')

s3_client = boto3.client(
    's3',
    region_name=REGION,
    endpoint_url=f'https://s3.{REGION}.amazonaws.com',
    config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
)

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': '*',
}


def _json_response(status_code: int, payload: dict) -> dict:
    return {
        'statusCode': status_code,
        'headers': {**CORS_HEADERS, 'Content-Type': 'application/json'},
        'body': json.dumps(payload),
    }


def _parse_multipart(body_bytes: bytes, content_type: str) -> dict:
    raw_msg = b'Content-Type: ' + content_type.encode('utf-8') + b'\r\nMIME-Version: 1.0\r\n\r\n' + body_bytes
    msg = BytesParser(policy=default_email_policy).parsebytes(raw_msg)
    fields = {}
    file_info = None
    if msg.is_multipart():
        for part in msg.iter_parts():
            cd = part.get('Content-Disposition', '')
            if not cd:
                continue
            name = part.get_param('name', header='content-disposition')
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b''
            if filename:
                file_info = {'filename': filename, 'bytes': payload}
            elif name:
                fields[name] = payload.decode('utf-8', errors='replace')
    return {'fields': fields, 'file': file_info}


def _display_name(stored: str) -> str:
    return stored.split('_', 1)[1] if len(stored) > 9 and stored[8] == '_' else stored


def _sanitize_filename(filename: str) -> str:
    name = Path(filename or 'document').name
    return re.sub(r'[^\w.\- ()+\[\]]', '_', name) or 'document'


def _get_s3_size(s3_key: str) -> int:
    try:
        head = s3_client.head_object(Bucket=S3_BUCKET, Key=s3_key)
        return int(head.get('ContentLength', 0))
    except Exception:
        return -1


def _resolve_upload(filename: str) -> Path:
    safe = Path(unquote(filename)).name
    local_path = TMP_UPLOADS / safe
    if not local_path.exists():
        try:
            obj = s3_client.get_object(Bucket=S3_BUCKET, Key=f'uploads/{safe}')
            local_path.write_bytes(obj['Body'].read())
        except Exception:
            return None
    return local_path


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
    """Runs full-document intelligence, redesign, fact verification, comparison, export & S3 sync on Lambda."""
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
        out_dir=TMP_UPLOADS,
        file_prefix=prefix,
        redesigned=redesigned,
        fact_verification=fact_ver,
        comparison=comparison,
        version_label=f"Version {ver_hint} — {version_reason}",
    )

    # Persist generated PDF/DOCX exports to S3 so /api/document/{filename} works across any Lambda instance
    for dl_info in (exports.get('downloads') or {}).values():
        stored_dl = dl_info.get('stored_name')
        if stored_dl:
            local_dl = TMP_UPLOADS / stored_dl
            if local_dl.exists():
                try:
                    s3_client.put_object(
                        Bucket=S3_BUCKET,
                        Key=f'uploads/{stored_dl}',
                        Body=local_dl.read_bytes(),
                    )
                except Exception:
                    pass

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


def lambda_handler(event, context):
    method = (
        event.get('requestContext', {}).get('http', {}).get('method')
        or event.get('httpMethod')
        or 'GET'
    ).upper()

    raw_path = (
        event.get('requestContext', {}).get('http', {}).get('path')
        or event.get('rawPath')
        or event.get('path')
        or '/'
    )

    if method == 'OPTIONS':
        return {'statusCode': 204, 'headers': CORS_HEADERS, 'body': ''}

    if raw_path in ('/api/health', '/health'):
        return _json_response(200, {
            'status': 'ok',
            'agent': 'CLARIA',
            'eyebrow': 'CUSTOMER COMMUNICATIONS REDESIGN',
            'aws_account': '984625844016',
        })

    if raw_path.startswith('/api/document/') and method == 'GET':
        tail = raw_path[len('/api/document/'):]
        is_view = tail.endswith('/view')
        fname = tail[:-len('/view')] if is_view else tail
        safe_stored = Path(unquote(fname)).name
        disp = _display_name(safe_stored)
        s3_size = _get_s3_size(f'uploads/{safe_stored}')

        if s3_size > 4_000_000 and (not is_view or safe_stored.lower().endswith('.pdf')):
            params = {
                'Bucket': S3_BUCKET,
                'Key': f'uploads/{safe_stored}',
                'ResponseContentDisposition': f'{"inline" if is_view else "attachment"}; filename="{disp}"',
            }
            if is_view and safe_stored.lower().endswith('.pdf'):
                params['ResponseContentType'] = 'application/pdf'
            presigned = s3_client.generate_presigned_url(
                ClientMethod='get_object',
                Params=params,
                ExpiresIn=3600,
            )
            return {'statusCode': 302, 'headers': {**CORS_HEADERS, 'Location': presigned}, 'body': ''}

        file_path = _resolve_upload(fname)
        if not file_path or not file_path.exists():
            return _json_response(404, {'detail': 'File not found. Please upload it again.'})

        if is_view:
            if file_path.suffix.lower() == '.pdf':
                return {
                    'statusCode': 200,
                    'headers': {
                        **CORS_HEADERS,
                        'Content-Type': 'application/pdf',
                        'Content-Disposition': f'inline; filename="{disp}"',
                    },
                    'isBase64Encoded': True,
                    'body': base64.b64encode(file_path.read_bytes()).decode('ascii'),
                }
            if file_path.name.startswith('highlighted_') and file_path.suffix.lower() in ('.html', '.htm'):
                return {
                    'statusCode': 200,
                    'headers': {**CORS_HEADERS, 'Content-Type': 'text/html; charset=utf-8'},
                    'body': file_path.read_text(encoding='utf-8', errors='ignore'),
                }
            html_out = viewer_service.render_html(file_path, disp)
            return {
                'statusCode': 200,
                'headers': {**CORS_HEADERS, 'Content-Type': 'text/html; charset=utf-8'},
                'body': html_out,
            }
        else:
            return {
                'statusCode': 200,
                'headers': {
                    **CORS_HEADERS,
                    'Content-Type': 'application/octet-stream',
                    'Content-Disposition': f'attachment; filename="{disp}"',
                },
                'isBase64Encoded': True,
                'body': base64.b64encode(file_path.read_bytes()).decode('ascii'),
            }

    if raw_path in ('/api/simplify', '/api/redesign', '/api/claria/redesign') and method == 'POST':
        headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
        ct = headers.get('content-type', '')
        body_raw = event.get('body') or ''
        body_bytes = base64.b64decode(body_raw) if event.get('isBase64Encoded') else body_raw.encode('utf-8')

        text = ''
        conversation_history = '[]'
        active_document_id = ''
        active_document_text = ''
        active_document_filename = ''
        file_obj = None

        if 'multipart/form-data' in ct:
            parsed_mp = _parse_multipart(body_bytes, ct)
            text = parsed_mp['fields'].get('text', '')
            conversation_history = parsed_mp['fields'].get('conversation_history', '[]')
            active_document_id = parsed_mp['fields'].get('active_document_id', '')
            active_document_text = parsed_mp['fields'].get('active_document_text', '')
            active_document_filename = parsed_mp['fields'].get('active_document_filename', '')
            file_obj = parsed_mp['file']
        else:
            try:
                j = json.loads(body_bytes.decode('utf-8'))
                text = j.get('text', '')
                ch = j.get('conversation_history', [])
                conversation_history = ch if isinstance(ch, str) else json.dumps(ch)
                active_document_id = j.get('active_document_id', '')
                active_document_text = j.get('active_document_text', '')
                active_document_filename = j.get('active_document_filename', '')
            except Exception:
                pass

        try:
            history = json.loads(conversation_history or '[]')
        except Exception:
            history = []

        doc_meta = None
        stored_name = None
        raw_doc_text = None
        doc_filename = None
        prior_redesigned = None
        user_instruction = (text or '').strip()
        combined_text = text or ''

        if file_obj:
            file_bytes = file_obj['bytes']
            orig_filename = file_obj['filename']
            doc_filename = orig_filename
            pre_rej = file_validation.validate_file_pre_extract(orig_filename, file_bytes)
            if pre_rej:
                return _json_response(200, {
                    'type': 'chat',
                    'message': pre_rej['message'],
                    'rejected': True,
                    'guardrail_status': 'BLOCKED',
                    'guardrail_details': {
                        'guardrails': {
                            'status': 'BLOCKED',
                            'triggered_rule': pre_rej.get('title') or 'Authentication Credentials / Access Keys Rejected',
                            'action': 'BLOCKED_SENSITIVE_CREDENTIALS',
                        }
                    },
                    'rejection_details': pre_rej,
                    'document_metadata': {'filename': orig_filename, 'size_bytes': len(file_bytes)},
                })
            stored_name = f"{uuid.uuid4().hex[:8]}_{_sanitize_filename(orig_filename)}"

            try:
                (TMP_UPLOADS / stored_name).write_bytes(file_bytes)
                s3_client.put_object(Bucket=S3_BUCKET, Key=f'uploads/{stored_name}', Body=file_bytes)
            except Exception:
                pass

            extracted = document_service.extract_text(file_bytes, orig_filename)
            doc_meta = extracted.get('metadata', {})
            q = quote(stored_name)
            doc_meta['stored_name'] = stored_name
            doc_meta['url'] = f'/api/document/{q}'
            doc_meta['view_url'] = f'/api/document/{q}/view'

            post_rej = file_validation.validate_file_post_extract(orig_filename, file_bytes, extracted.get('text', ''), meta=doc_meta)
            if post_rej or doc_meta.get('is_empty', False) or len(file_bytes) == 0:
                msg = post_rej['message'] if post_rej else f"File Not Accepted: '{orig_filename}' is empty."
                return _json_response(200, {
                    'type': 'chat',
                    'message': msg,
                    'rejected': True,
                    'rejection_details': post_rej,
                    'document_metadata': doc_meta,
                })

            file_content = extracted.get('text', '')
            raw_doc_text = file_content
            combined_text = (
                f"[COMMUNICATION DOCUMENT: {orig_filename}]\n"
                f"==================== ORIGINAL COMMUNICATION ====================\n"
                f"{file_content}\n"
                f"===============================================================\n"
            )
            if user_instruction:
                combined_text += f"\nRecipient's Question / Note: {user_instruction}\n"

        # If no new file was uploaded, check if user is refining an active document in the conversation (e.g. "make it empathy", "i want it in friednly tune")
        if not file_obj and user_instruction and len(user_instruction.split()) <= 60 and _has_refinement_intent(user_instruction, has_active_doc=bool(active_document_id or active_document_text.strip())):
            rec = (
                governance_store_service.get_document_record(active_document_id)
                if active_document_id
                else governance_store_service.get_latest_document_record()
            )
            if rec:
                structured_prev = rec.get('structured_doc') or {}
                raw_doc_text = '\n'.join(el.get('text', '') for el in (structured_prev.get('elements') or []))
                doc_filename = rec.get('filename') or active_document_filename or 'Customer_Communication.pdf'
                active_document_id = rec.get('document_id') or active_document_id
                latest_ver = (rec.get('versions') or [])[-1] if rec.get('versions') else {}
                prior_redesigned = latest_ver.get('redesigned_document')
                doc_meta = {
                    'filename': doc_filename,
                    'stored_name': rec.get('stored_name'),
                    'view_url': rec.get('original_view_url'),
                    'url': rec.get('original_download_url'),
                }
            elif active_document_text and active_document_text.strip():
                raw_doc_text = active_document_text.strip()
                doc_filename = active_document_filename or 'Customer_Communication.pdf'
                doc_meta = {'filename': doc_filename}
            else:
                # Recover latest uploaded source document from TMP_UPLOADS or S3 uploads/
                candidates = [
                    p for p in TMP_UPLOADS.glob('*')
                    if p.is_file()
                    and not p.name.startswith('highlighted_')
                    and not p.name.startswith('doc-')
                ]
                if candidates:
                    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    latest_p = candidates[0]
                    stored_name = latest_p.name
                    doc_filename = _display_name(stored_name)
                    ext_res = document_service.extract_text(latest_p.read_bytes(), doc_filename)
                    raw_doc_text = ext_res.get('text', '')
                    q = quote(stored_name)
                    doc_meta = {
                        'filename': doc_filename,
                        'stored_name': stored_name,
                        'url': f'/api/document/{q}',
                        'view_url': f'/api/document/{q}/view',
                    }
                else:
                    try:
                        s3_objs = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix='uploads/').get('Contents') or []
                        src_objs = [
                            o for o in s3_objs
                            if not Path(o['Key']).name.startswith('highlighted_')
                            and not Path(o['Key']).name.startswith('doc-')
                            and o.get('Size', 0) > 20
                        ]
                        if src_objs:
                            src_objs.sort(key=lambda o: o['LastModified'], reverse=True)
                            latest_key = src_objs[0]['Key']
                            stored_name = Path(latest_key).name
                            doc_filename = _display_name(stored_name)
                            f_bytes = s3_client.get_object(Bucket=S3_BUCKET, Key=latest_key)['Body'].read()
                            ext_res = document_service.extract_text(f_bytes, doc_filename)
                            raw_doc_text = ext_res.get('text', '')
                            q = quote(stored_name)
                            doc_meta = {
                                'filename': doc_filename,
                                'stored_name': stored_name,
                                'url': f'/api/document/{q}',
                                'view_url': f'/api/document/{q}/view',
                            }
                    except Exception:
                        pass

                # Last resort: reconstruct from conversation_history highlights if present
                if not (raw_doc_text and raw_doc_text.strip()) and history:
                    for h_msg in reversed(history):
                        c_raw = h_msg.get('content')
                        try:
                            c_obj = json.loads(c_raw) if isinstance(c_raw, str) and c_raw.startswith('{') else (c_raw if isinstance(c_raw, dict) else None)
                        except Exception:
                            c_obj = None
                        if isinstance(c_obj, dict) and c_obj.get('type') == 'redesign':
                            hl_list = c_obj.get('highlights') or []
                            hl_texts = [h.get('text') for h in hl_list if isinstance(h, dict) and h.get('text')]
                            if hl_texts or c_obj.get('what_this_is_about'):
                                raw_doc_text = '\n\n'.join([c_obj.get('what_this_is_about') or ''] + hl_texts).strip()
                                doc_filename = active_document_filename or 'Customer_Communication.pdf'
                                doc_meta = {'filename': doc_filename}
                                break

            if not (raw_doc_text and raw_doc_text.strip()):
                return _json_response(200, {
                    'type': 'chat',
                    'message': (
                        f"I'm ready to apply your instruction (\"{user_instruction}\")! "
                        "Please attach the customer communication file (PDF, DOCX, TXT) or paste the communication text you would like me to redesign."
                    ),
                })

        if not combined_text.strip() and not (raw_doc_text and raw_doc_text.strip()):
            return _json_response(400, {'detail': 'Please provide a communication text or upload a document.'})

        # Fast single-LLM path when we have a document to redesign
        if raw_doc_text and raw_doc_text.strip():
            guard = claria_service.guardrail_service.inspect_and_sanitize(raw_doc_text)
            if guard.get('blocked'):
                return _json_response(200, {
                    'type': 'chat',
                    'message': guard.get('message', 'The submitted communication cannot be processed.'),
                    'guardrail_status': 'BLOCKED',
                    'guardrail_details': guard,
                })
            clean_source = claria_service._extract_clean_document_text(raw_doc_text, guard.get('sanitized_text', raw_doc_text))
            effective_instruction = user_instruction or 'Redesign professionally for clarity while preserving all facts and disclosures.'

            ent_bundle = _run_enterprise_pipeline(
                raw_text=clean_source,
                filename=doc_filename or 'customer_communication.txt',
                instruction=effective_instruction,
                doc_meta=doc_meta,
                doc_id=active_document_id if prior_redesigned else None,
                prior_redesigned=prior_redesigned,
                version_reason=f"Tone/Redesign ({effective_instruction[:40]})" if user_instruction else 'Initial redesign',
            )
            rd = ent_bundle.get('redesigned_document') or {}
            tone_label = rd.get('tone_applied') or 'Professional & Clear'
            summary_line = f"Redesigned in {tone_label} tone"
            if user_instruction:
                summary_line += f" · Instruction applied: \"{user_instruction[:70]}\""

            parsed_stub = {
                'type': 'redesign',
                'what_this_is_about': rd.get('introduction') or rd.get('design_notes') or 'Customer communication redesigned for clarity.',
                'what_you_need_to_do': {
                    'action_required': bool(rd.get('checklist') or rd.get('deadline')),
                    'summary': summary_line,
                },
                'sentence_highlights': [],
            }
            hl_doc = claria_service.build_clarity_highlighted_document(
                raw_text=clean_source,
                parsed=parsed_stub,
                filename=doc_filename or 'Customer_Communication.txt',
            )
            parsed_stub['highlighted_document'] = hl_doc
            if doc_meta:
                parsed_stub['document_metadata'] = doc_meta

            hl_html = hl_doc.get('full_html') or ''
            orig_disp = _display_name(stored_name) if stored_name else (doc_filename or 'Customer_Communication.pdf')
            hl_name = f"highlighted_{stored_name or uuid.uuid4().hex[:8]}.html"
            try:
                (TMP_UPLOADS / hl_name).write_text(hl_html, encoding='utf-8')
                s3_client.put_object(
                    Bucket=S3_BUCKET,
                    Key=f'uploads/{hl_name}',
                    Body=hl_html.encode('utf-8'),
                    ContentType='text/html; charset=utf-8',
                    ContentDisposition=f'inline; filename="highlighted_{Path(orig_disp).stem}.html"',
                )
                q = quote(hl_name)
                parsed_stub['highlighted_document']['source_filename'] = orig_disp
                parsed_stub['highlighted_document']['filename'] = f"highlighted_{Path(orig_disp).stem}.html"
                parsed_stub['highlighted_document']['download_url'] = f"/api/document/{q}"
                parsed_stub['highlighted_document']['view_url'] = f"/api/document/{q}/view"
                if doc_meta and doc_meta.get('view_url'):
                    parsed_stub['highlighted_document']['original_view_url'] = doc_meta['view_url']
                    parsed_stub['highlighted_document']['original_download_url'] = doc_meta.get('url')
            except Exception:
                pass

            parsed_stub.update(ent_bundle)
            return _json_response(200, parsed_stub)

        try:
            result = claria_service.redesign_communication(
                combined_text,
                history,
                raw_document_text=raw_doc_text,
                filename=doc_filename
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            result = {
                'type': 'chat',
                'message': "I'm ready to assist. Please share the customer notice, letter, or communication you would like to discuss or simplify.",
            }

        if doc_meta:
            result['document_metadata'] = doc_meta

        if result.get('highlighted_document'):
            hl_html = result['highlighted_document'].get('full_html') or ''
            orig_disp = _display_name(stored_name) if stored_name else (doc_filename or 'Customer_Communication.pdf')
            hl_name = f"highlighted_{stored_name or uuid.uuid4().hex[:8]}.html"
            try:
                (TMP_UPLOADS / hl_name).write_text(hl_html, encoding='utf-8')
                s3_client.put_object(
                    Bucket=S3_BUCKET,
                    Key=f'uploads/{hl_name}',
                    Body=hl_html.encode('utf-8'),
                    ContentType='text/html; charset=utf-8',
                    ContentDisposition=f'inline; filename="highlighted_{Path(orig_disp).stem}.html"'
                )
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
            source_for_ent = raw_doc_text or (result.get('highlighted_document') or {}).get('raw_text') or combined_text
            if source_for_ent.strip():
                ent_bundle = _run_enterprise_pipeline(
                    raw_text=source_for_ent,
                    filename=doc_filename or 'customer_communication.txt',
                    instruction=user_instruction or 'Redesign professionally for clarity while preserving all facts and disclosures.',
                    doc_meta=doc_meta,
                )
                result.update(ent_bundle)

        return _json_response(200, result)

    return _json_response(404, {'detail': f'Not found: {raw_path}'})
