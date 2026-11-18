"""
CLARIA Enterprise Version Control, Governance, Audit Trail & Live Dashboard Store
(Modules 10, 11, 12, 13, 14, 15).
"""
import datetime
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_STORE_PATH = (
    Path('/tmp/claria_enterprise_store.json')
    if os.path.exists('/tmp') and os.getenv('AWS_LAMBDA_FUNCTION_NAME')
    else (Path(__file__).resolve().parent.parent / 'data' / 'claria_enterprise_store.json')
)

WORKFLOW_STATUSES = (
    'Uploaded',
    'Processing',
    'Analysis completed',
    'Redesign generated',
    'Comparison completed',
    'Issues detected',
    'Awaiting correction',
    'Awaiting human review',
    'Approved',
    'Rejected',
    'Ready for release',
    'Failed',
)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def _load_store() -> dict[str, Any]:
    if not _STORE_PATH.exists():
        return {'documents': {}, 'audit_log': []}
    try:
        data = json.loads(_STORE_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            data.setdefault('documents', {})
            data.setdefault('audit_log', [])
            return data
    except Exception:
        pass
    return {'documents': {}, 'audit_log': []}


def _save_store(data: dict[str, Any]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def append_audit_event(
    doc_id: str,
    action: str,
    actor: str = 'System',
    role: str = 'Automated Engine',
    details: str = '',
    version_number: int | None = None,
) -> dict[str, Any]:
    evt = {
        'event_id': f"AUD-{uuid.uuid4().hex[:8].upper()}",
        'timestamp': _now_iso(),
        'document_id': doc_id,
        'version_number': version_number,
        'action': action,
        'actor': actor,
        'role': role,
        'details': details,
    }
    with _LOCK:
        store = _load_store()
        store['audit_log'].insert(0, evt)
        store['audit_log'] = store['audit_log'][:500]
        if doc_id in store['documents']:
            store['documents'][doc_id].setdefault('audit_trail', []).insert(0, evt)
        _save_store(store)
    return evt


def create_or_add_version(
    doc_id: str,
    original_meta: dict[str, Any],
    structured_doc: dict[str, Any],
    redesigned: dict[str, Any],
    fact_verification: dict[str, Any],
    comparison: dict[str, Any],
    downloads: dict[str, Any],
    quality_validation: dict[str, Any],
    instruction: str,
    version_reason: str = 'Initial redesign',
    creator: str = 'Document Creator',
    department: str = 'Customer Communications',
) -> dict[str, Any]:
    with _LOCK:
        store = _load_store()
        doc_rec = store['documents'].get(doc_id)

        if not doc_rec:
            doc_rec = {
                'document_id': doc_id,
                'filename': original_meta.get('filename') or structured_doc.get('filename', 'document.txt'),
                'document_title': structured_doc.get('document_title', 'Customer Communication'),
                'document_type': structured_doc.get('document_type', 'Enterprise Customer Communication'),
                'department': department,
                'creator': creator,
                'created_at': _now_iso(),
                'updated_at': _now_iso(),
                'sha256': original_meta.get('sha256', ''),
                'stored_name': original_meta.get('stored_name', ''),
                'original_view_url': original_meta.get('view_url', ''),
                'original_download_url': original_meta.get('url', ''),
                'total_pages': structured_doc.get('total_pages', 1),
                'word_count': structured_doc.get('word_count', 0),
                'structured_doc': structured_doc,
                'versions': [],
                'audit_trail': [],
                'status': 'Comparison completed',
                'approval_records': [],
            }
            store['documents'][doc_id] = doc_rec

        ver_num = len(doc_rec['versions']) + 1
        parent_ver = ver_num - 1 if ver_num > 1 else 0
        has_issues = len(comparison.get('actionable_issues') or []) > 0
        status = 'Issues detected' if has_issues else 'Awaiting human review'
        doc_rec['status'] = status
        doc_rec['updated_at'] = _now_iso()

        ver_label = f"Version {ver_num} — {version_reason}"
        ver_entry = {
            'version_number': ver_num,
            'version_label': ver_label,
            'parent_version': parent_ver,
            'created_at': _now_iso(),
            'instruction': instruction,
            'model_governance': {
                'model_id': redesigned.get('model_used', 'us.amazon.nova-lite-v1:0'),
                'prompt_version': 'claria-enterprise-v2.0',
                'processed_at': _now_iso(),
                'document_id': doc_id,
                'version_number': ver_num,
                'validation_status': fact_verification.get('overall_status', 'Verified'),
            },
            'redesigned_document': redesigned,
            'fact_verification': fact_verification,
            'comparison': comparison,
            'downloads': downloads,
            'quality_validation': quality_validation,
            'status': status,
        }
        doc_rec['versions'].append(ver_entry)

        evt = {
            'event_id': f"AUD-{uuid.uuid4().hex[:8].upper()}",
            'timestamp': _now_iso(),
            'document_id': doc_id,
            'version_number': ver_num,
            'action': f"Generated {ver_label}",
            'actor': creator,
            'role': 'Document Creator',
            'details': f"Fact check: {fact_verification.get('overall_status')}; Changes: {comparison.get('counts', {}).get('total_changes', 0)}",
        }
        doc_rec['audit_trail'].insert(0, evt)
        store['audit_log'].insert(0, evt)
        store['audit_log'] = store['audit_log'][:500]
        _save_store(store)

    return {
        'document_id': doc_id,
        'version_number': ver_num,
        'version_label': ver_label,
        'status': status,
        'versions_summary': [
            {
                'version_number': v['version_number'],
                'version_label': v['version_label'],
                'parent_version': v['parent_version'],
                'created_at': v['created_at'],
                'status': v['status'],
                'fact_status': v['fact_verification'].get('overall_status'),
                'changes_count': v['comparison'].get('counts', {}).get('total_changes', 0),
            }
            for v in doc_rec['versions']
        ],
        'approval_records': doc_rec['approval_records'],
        'audit_trail': doc_rec['audit_trail'][:20],
        'model_governance': ver_entry['model_governance'],
    }


def get_document_record(doc_id: str) -> dict[str, Any] | None:
    with _LOCK:
        store = _load_store()
        return store['documents'].get(doc_id)


def get_latest_document_record() -> dict[str, Any] | None:
    with _LOCK:
        store = _load_store()
        docs = list((store.get('documents') or {}).values())
        if not docs:
            return None
        docs.sort(key=lambda d: d.get('updated_at') or d.get('created_at') or '', reverse=True)
        return docs[0]


def record_approval_action(
    doc_id: str,
    decision: str,
    reviewer_name: str,
    reviewer_role: str,
    comments: str = '',
    version_number: int | None = None,
) -> dict[str, Any]:
    """Enforces separation of duties and updates document approval lifecycle."""
    dec_low = (decision or '').strip().lower()
    with _LOCK:
        store = _load_store()
        doc_rec = store['documents'].get(doc_id)
        if not doc_rec:
            return {'error': 'Document not found'}

        latest_ver = doc_rec['versions'][-1] if doc_rec['versions'] else None
        ver_num = version_number or (latest_ver['version_number'] if latest_ver else 1)

        # Separation of duties check: creator cannot self-approve/release
        creator = (doc_rec.get('creator') or '').strip().lower()
        if dec_low in ('approve', 'release') and reviewer_name.strip().lower() == creator:
            return {
                'error': 'Separation of duties violation: the document creator cannot independently approve or release this communication. Assign a Compliance Reviewer or Business Approver.'
            }

        status_map = {
            'submit_for_review': 'Awaiting human review',
            'approve': 'Approved',
            'reject': 'Rejected',
            'release': 'Ready for release',
            'preserve_no_correction': 'Awaiting human review',
        }
        new_status = status_map.get(dec_low, 'Awaiting human review')
        doc_rec['status'] = new_status
        doc_rec['updated_at'] = _now_iso()
        if latest_ver:
            latest_ver['status'] = new_status

        rec = {
            'approval_id': f"APR-{uuid.uuid4().hex[:6].upper()}",
            'reviewer': reviewer_name,
            'role': reviewer_role,
            'decision': new_status,
            'comments': comments,
            'version_number': ver_num,
            'timestamp': _now_iso(),
        }
        doc_rec.setdefault('approval_records', []).insert(0, rec)

        evt = {
            'event_id': f"AUD-{uuid.uuid4().hex[:8].upper()}",
            'timestamp': _now_iso(),
            'document_id': doc_id,
            'version_number': ver_num,
            'action': f"Governance: {new_status}",
            'actor': reviewer_name,
            'role': reviewer_role,
            'details': comments or f"Decision '{new_status}' recorded for Version {ver_num}.",
        }
        doc_rec['audit_trail'].insert(0, evt)
        store['audit_log'].insert(0, evt)
        store['audit_log'] = store['audit_log'][:500]
        _save_store(store)

        return {
            'document_id': doc_id,
            'status': new_status,
            'approval_records': doc_rec['approval_records'],
            'audit_trail': doc_rec['audit_trail'][:20],
        }


def get_dashboard_metrics(
    status_filter: str = '',
    doc_type_filter: str = '',
    severity_filter: str = '',
    search: str = '',
) -> dict[str, Any]:
    """Computes live, data-backed enterprise dashboard metrics from actual backend records."""
    with _LOCK:
        store = _load_store()
        docs = list(store['documents'].values())
        audit_log = list(store['audit_log'])

    total = len(docs)
    issues_cnt = 0
    critical_findings = 0
    high_findings = 0
    approved_cnt = 0
    rejected_cnt = 0
    awaiting_review_cnt = 0
    comparisons_done = 0

    rows = []
    for d in docs:
        vers = d.get('versions') or []
        latest = vers[-1] if vers else {}
        cmp_counts = latest.get('comparison', {}).get('counts', {})
        crit = cmp_counts.get('critical', 0)
        high = cmp_counts.get('high', 0)
        critical_findings += crit
        high_findings += high
        st = d.get('status', 'Uploaded')
        if vers:
            comparisons_done += 1
        if st in ('Issues detected', 'Awaiting correction'):
            issues_cnt += 1
        elif st in ('Approved', 'Ready for release'):
            approved_cnt += 1
        elif st == 'Rejected':
            rejected_cnt += 1
        elif st == 'Awaiting human review':
            awaiting_review_cnt += 1

        if status_filter and st.lower() != status_filter.lower():
            continue
        if doc_type_filter and d.get('document_type', '').lower() != doc_type_filter.lower():
            continue
        if severity_filter:
            sf = severity_filter.lower()
            if sf == 'critical' and crit == 0:
                continue
            if sf == 'high' and high == 0:
                continue
        if search and search.lower() not in (d.get('filename', '') + ' ' + d.get('document_title', '')).lower():
            continue

        rows.append({
            'document_id': d['document_id'],
            'filename': d.get('filename'),
            'document_title': d.get('document_title'),
            'document_type': d.get('document_type'),
            'department': d.get('department', 'Customer Communications'),
            'creator': d.get('creator', 'Document Creator'),
            'status': st,
            'versions_count': len(vers),
            'critical_findings': crit,
            'high_findings': high,
            'updated_at': d.get('updated_at'),
        })

    rows.sort(key=lambda r: r.get('updated_at') or '', reverse=True)

    return {
        'metrics': {
            'total_uploaded': total,
            'successfully_redesigned': comparisons_done,
            'comparisons_completed': comparisons_done,
            'requiring_review': issues_cnt + awaiting_review_cnt,
            'critical_findings': critical_findings,
            'high_findings': high_findings,
            'approved_documents': approved_cnt,
            'rejected_documents': rejected_cnt,
        },
        'documents': rows,
        'recent_activity': audit_log[:25],
    }
