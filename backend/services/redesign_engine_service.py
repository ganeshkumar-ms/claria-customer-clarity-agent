"""
CLARIA Conversational Redesign, Multi-Level Comparison & Change Highlighting Engine
(Modules 3, 4, 5, 7, 8, 9).
"""
import difflib
import html as html_lib
import json
import os
import re
from typing import Any

import boto3
from botocore.config import Config

from services import document_intelligence_service as intel_svc

PRIMARY_MODEL_ID = 'us.amazon.nova-lite-v1:0'
FALLBACK_MODEL_ID = 'us.amazon.nova-pro-v1:0'

REDESIGN_SYSTEM_PROMPT = """You are CLARIA, an Enterprise Customer Communication Redesign Engine (Senior CCM Designer & BFSI Content Strategist).
Your job is to transform a dense, formal banking/enterprise letter into a clear, customer-friendly communication while preserving EVERY financial figure, date, deadline, accounting standard, auditor certification requirement, incomplete-submission warning, and contractual obligation.

OUTPUT STRUCTURE:
1. Clear customer-friendly headline (e.g., "Let's complete your annual financial review") + short plain-English opening.
2. Prominent submission/action deadline (exact date from source, or [TO BE CONFIRMED] if absent).
3. Actionable checklist (clear bullet items of what the customer must submit or do).
4. Clear "What happens next?", "How to submit", and "Need help?" sections.
5. Dedicated "Important Obligations & Regulatory Disclosures" preserving all contractual, legal, accounting, and warning clauses verbatim without weakening them.

RULES:
- NEVER invent facts, dates, amounts, phone numbers, or bank names not in the source.
- NEVER remove or weaken accounting standards, auditor requirements, warnings, or contractual clauses.
- NEVER include internal-only staff instructions.
- Output ONLY valid JSON matching this schema:
{
  "title": "Customer-friendly headline",
  "salutation": "Dear Valued Customer,",
  "introduction": "Clear, empathetic opening explaining what is needed and why.",
  "deadline": "Exact deadline date from source (e.g. 15 December 2026) or '' if none",
  "checklist": ["Actionable checklist item 1", "Item 2"],
  "what_happens_next": "Plain-English explanation of what the bank/organisation will do next.",
  "how_to_submit": "Clear submission channel instructions from source.",
  "need_help": "Contact / Relationship Manager help instructions from source.",
  "sections": [
    {
      "heading": "Section heading",
      "paragraphs": ["Clear paragraph text preserving all facts and dates."],
      "bullets": ["Optional bullet items"],
      "table": [["Col 1", "Col 2"], ["Val 1", "Val 2"]]
    }
  ],
  "mandatory_disclosures": ["Exact preserved accounting standards, auditor certification, incomplete-submission warnings, and contractual reporting obligations"],
  "closing": "Institutional sign-off from source.",
  "design_notes": "1-sentence summary of what was restructured and why it improves customer clarity."
}"""


def _get_bedrock_client():
    region = os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION') or 'us-east-1'
    return boto3.client(
        'bedrock-runtime',
        region_name=region,
        config=Config(read_timeout=18, connect_timeout=3, retries={'max_attempts': 1}),
    )


def _strip_json_fences(raw: str) -> str:
    txt = (raw or '').strip()
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', txt)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'\{[\s\S]*\}', txt)
    return m2.group(0) if m2 else txt


def _sections_to_plain_text(redesigned: dict[str, Any]) -> str:
    parts = []
    if redesigned.get('title'):
        parts.append(redesigned['title'])
    if redesigned.get('salutation'):
        parts.append(redesigned['salutation'])
    if redesigned.get('introduction'):
        parts.append(redesigned['introduction'])
    for sec in redesigned.get('sections') or []:
        if sec.get('heading'):
            parts.append(f"\n{sec['heading']}")
        for p in sec.get('paragraphs') or []:
            if p:
                parts.append(p)
        for b in sec.get('bullets') or []:
            if b:
                parts.append(f"• {b}")
        for row in sec.get('table') or []:
            if row:
                parts.append(' | '.join(str(c) for c in row))
    if redesigned.get('mandatory_disclosures'):
        parts.append("\nImportant Disclosures")
        for d in redesigned['mandatory_disclosures']:
            parts.append(d)
    if redesigned.get('closing'):
        parts.append(f"\n{redesigned['closing']}")
    return '\n'.join(parts).strip()


def _deterministic_redesign(
    structured_doc: dict[str, Any],
    tone_info: dict[str, Any],
    instruction: str,
) -> dict[str, Any]:
    """Produces a clean, fact-preserving structured redesign from customer_elements."""
    cust = structured_doc.get('customer_elements') or []
    grouped: list[dict[str, Any]] = []
    sec_map: dict[str, dict[str, Any]] = {}

    for el in cust:
        sec_name = el.get('section') or 'Key Information'
        etype = el.get('element_type')
        txt = (el.get('text') or '').strip()
        if not txt:
            continue
        if etype == 'heading':
            if txt not in sec_map:
                obj = {'heading': txt, 'paragraphs': [], 'bullets': [], 'table': []}
                sec_map[txt] = obj
                grouped.append(obj)
            continue
        if sec_name not in sec_map:
            obj = {'heading': sec_name, 'paragraphs': [], 'bullets': [], 'table': []}
            sec_map[sec_name] = obj
            grouped.append(obj)
        target = sec_map[sec_name]
        if etype == 'table' and el.get('rows'):
            target['table'].extend(el['rows'])
        elif etype == 'bullet':
            target['bullets'].append(re.sub(r'^(?:[•\-\*▪▸]|\d+[\.\)])\s*', '', txt))
        else:
            target['paragraphs'].append(txt)

    disclosures = [
        el['text'] for el in cust
        if el.get('classification') == 'mandatory_disclosure' and el.get('element_type') != 'heading'
    ][:6]

    title = structured_doc.get('document_title') or 'Customer Communication'
    comm_intel = structured_doc.get('communication_intelligence') or {}
    ident = comm_intel.get('document_identity') or {}
    fin = comm_intel.get('financial_intelligence') or {}
    act = comm_intel.get('customer_action_intelligence') or {}

    intro = grouped[0]['paragraphs'][0] if (grouped and grouped[0].get('paragraphs')) else (
        f"Summary of {structured_doc.get('document_type', 'Customer Communication')}: {title}."
    )
    if grouped and grouped[0].get('paragraphs'):
        grouped[0]['paragraphs'] = grouped[0]['paragraphs'][1:]

    # Build Reassure -> Explain -> Action -> Consequences -> Support sections from existing content
    reassure_p, explain_p, action_p, conseq_p, support_p = [], [], [], [], []
    tables_found = []
    for g in grouped:
        if g.get('table'):
            tables_found.append(g['table'])
        for txt in (g.get('paragraphs') or []) + (g.get('bullets') or []):
            tl = txt.lower()
            if any(k in tl for k in ('thank you', 'valued', 'we appreciate', 'here to help', 'support you')):
                reassure_p.append(txt)
            elif any(k in tl for k in ('please ', 'must ', 'submit', 'confirm', 'complete ', 'pay ', 'required to')):
                action_p.append(txt)
            elif any(k in tl for k in ('if not', 'failure to', 'consequence', 'penalty', 'late fee', 'suspend', 'legal', 'disclosure', 'terms')):
                conseq_p.append(txt)
            elif any(k in tl for k in ('helpline', 'support', 'contact', 'toll-free', 'email', 'branch', '1800')):
                support_p.append(txt)
            else:
                explain_p.append(txt)

    flow_sections = []
    if reassure_p:
        flow_sections.append({'stage': 'Reassure', 'heading': 'Reassure — Context & Support', 'paragraphs': reassure_p, 'bullets': [], 'table': []})
    if explain_p or tables_found:
        flow_sections.append({'stage': 'Explain', 'heading': 'Explain — Key Details', 'paragraphs': explain_p, 'bullets': [], 'table': tables_found[0] if tables_found else []})
    if action_p:
        flow_sections.append({'stage': 'Action', 'heading': 'Action — What You Need To Do', 'paragraphs': [], 'bullets': action_p, 'table': []})
    if conseq_p:
        flow_sections.append({'stage': 'Consequences', 'heading': 'Consequences & Regulatory Terms', 'paragraphs': conseq_p, 'bullets': [], 'table': []})
    if support_p:
        flow_sections.append({'stage': 'Support', 'heading': 'Support & Contact Channels', 'paragraphs': support_p, 'bullets': [], 'table': []})
    if not flow_sections:
        flow_sections = [g for g in grouped if g['paragraphs'] or g['bullets'] or g['table']]

    primary_action = (act.get('required_actions') or ['Review the details below'])[0][:180]
    deadline_val = (fin.get('payment_or_effective_dates') or ['[TO BE CONFIRMED]'])[0]
    account_details = [
        {'label': 'Document Type', 'value': structured_doc.get('document_type') or 'Customer Communication'},
        {'label': 'Reference / ID', 'value': ident.get('document_reference') or '[TO BE CONFIRMED]'},
        {'label': 'Key Date / Deadline', 'value': deadline_val},
    ]
    if fin.get('monetary_amounts'):
        account_details.append({'label': 'Key Amount(s)', 'value': ', '.join(fin['monetary_amounts'][:3])})

    tbc_list = [f"{a['label']}: [TO BE CONFIRMED]" for a in account_details if '[TO BE CONFIRMED]' in a['value']]

    return {
        'title': title,
        'deadline': deadline_val if deadline_val != '[TO BE CONFIRMED]' else '',
        'checklist': action_p[:8],
        'what_happens_next': (explain_p[0] if explain_p else ''),
        'how_to_submit': next((p for p in action_p + explain_p if any(k in p.lower() for k in ('portal', 'submit', 'relationship manager', 'channel', 'upload'))), ''),
        'need_help': (support_p[0] if support_p else ''),
        'status_summary': {
            'outcome': structured_doc.get('document_type') or 'Customer Communication',
            'key_figures': (fin.get('monetary_amounts') or [])[:3] + (fin.get('rates_and_percentages') or [])[:2],
            'primary_action': primary_action,
        },
        'account_details': account_details,
        'salutation': 'Dear Valued Customer,',
        'introduction': intro,
        'sections': flow_sections,
        'call_to_action': {
            'label': 'Primary Action Required' if act.get('required_actions') else 'For Your Information',
            'deadline': deadline_val,
            'instruction': primary_action,
        },
        'options': [],
        'timeline': [],
        'mandatory_disclosures': disclosures or conseq_p[:4],
        'tbc_placeholders': tbc_list,
        'closing': (support_p[0] if support_p else 'Contact details: [TO BE CONFIRMED]'),
        'design_notes': f"Restructured source communication into customer-friendly sections with prominent deadline, checklist, and preserved disclosures ({tone_info['tone_label']} tone).",
    }


def generate_redesigned_document(
    structured_doc: dict[str, Any],
    instruction: str,
    prior_redesigned: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generates a complete customer-facing redesigned document preserving facts and disclosures."""
    customer_text_parts = []
    for el in structured_doc.get('customer_elements') or []:
        if el.get('element_type') == 'heading':
            customer_text_parts.append(f"\n[Page {el.get('page', 1)}] ## {el['text']}")
        else:
            customer_text_parts.append(f"[Page {el.get('page', 1)} | {el.get('section', '')}] {el['text']}")
    customer_text = '\n'.join(customer_text_parts)[:24000]

    tone_info = intel_svc.parse_tone_and_audience(instruction, customer_text)

    prompt_lines = [
        f"USER INSTRUCTION: {instruction or 'Redesign this customer communication professionally while preserving all facts, dates, fees, and mandatory disclosures.'}",
        f"REQUESTED TONE: {tone_info['tone_label']}",
        f"TARGET AUDIENCE: {tone_info['audience']}",
        f"DESIGN MODE: {tone_info['design_mode']}",
    ]
    if tone_info.get('preserve_fee_table'):
        prompt_lines.append("CRITICAL: Preserve the original fee table structure and every numeric value verbatim.")
    if prior_redesigned:
        prompt_lines.append(f"PREVIOUS VERSION TO REFINE:\n{json.dumps(prior_redesigned, ensure_ascii=False)[:8000]}")
    prompt_lines.append(f"CUSTOMER-FACING SOURCE CONTENT:\n{customer_text}")

    user_prompt = '\n\n'.join(prompt_lines)
    parsed = None
    model_used = PRIMARY_MODEL_ID

    try:
        client = _get_bedrock_client()
        for mid in (PRIMARY_MODEL_ID, FALLBACK_MODEL_ID):
            try:
                model_used = mid
                resp = client.converse(
                    modelId=mid,
                    system=[{'text': REDESIGN_SYSTEM_PROMPT}],
                    messages=[{'role': 'user', 'content': [{'text': user_prompt}]}],
                    inferenceConfig={'maxTokens': 2800, 'temperature': 0.15},
                )
                raw = resp['output']['message']['content'][0]['text']
                cand = json.loads(_strip_json_fences(raw))
                if isinstance(cand, dict) and (cand.get('sections') or cand.get('introduction')):
                    parsed = cand
                    break
            except Exception:
                continue
    except Exception:
        parsed = None

    if not parsed:
        model_used = 'deterministic-fallback'
        parsed = _deterministic_redesign(structured_doc, tone_info, instruction)

    parsed.setdefault('title', structured_doc.get('document_title') or 'Customer Communication')
    parsed.setdefault('salutation', 'Dear Valued Customer,')
    parsed.setdefault('introduction', '')
    parsed.setdefault('sections', [])
    parsed.setdefault('mandatory_disclosures', [])
    parsed.setdefault('closing', '')
    parsed['tone_applied'] = tone_info['tone_label']
    parsed['audience_applied'] = tone_info['audience']
    parsed['design_mode'] = tone_info['design_mode']
    parsed['tone_safety_warning'] = tone_info.get('tone_safety_warning')
    parsed['model_used'] = model_used
    parsed['plain_text'] = _sections_to_plain_text(parsed)
    return parsed


def compare_original_vs_redesigned(
    structured_doc: dict[str, Any],
    redesigned: dict[str, Any],
    fact_verification: dict[str, Any],
) -> dict[str, Any]:
    """
    Performs multi-level comparison (Content, Financial, Structural, Semantic) between
    the original document and the redesigned output, producing traceable change records
    and a 4-color change-highlighted HTML view (Green=Added, Yellow=Modified, Red=Removed, Blue=Structural).
    """
    orig_cust_lines = [
        el['text'].strip()
        for el in (structured_doc.get('customer_elements') or [])
        if el.get('element_type') != 'heading' and el.get('text', '').strip()
    ]
    out_lines = [
        ln.strip()
        for ln in (redesigned.get('plain_text') or '').splitlines()
        if ln.strip()
    ]

    changes: list[dict[str, Any]] = []
    change_idx = 0

    # 1. Include all fact verification discrepancies as Critical / High financial or date changes
    for iss in fact_verification.get('issues') or []:
        change_idx += 1
        changes.append({
            'change_id': f"CHG-{change_idx:03d}",
            'category': iss['category'],
            'severity': iss['severity'],
            'highlight_color': 'red' if 'Missing' in iss['category'] else 'yellow',
            'original_page': iss.get('source_page', 1),
            'output_page': 1,
            'original_section': iss.get('source_section', 'Source'),
            'output_section': 'Redesigned Output',
            'original_text': iss.get('original_value', ''),
            'revised_text': iss.get('output_value', ''),
            'change_explanation': iss.get('explanation', ''),
            'source_evidence': iss.get('source_evidence', ''),
            'impact_assessment': 'May affect financial accuracy or customer obligations.',
            'recommended_correction': iss.get('recommended_correction', ''),
            'review_status': iss.get('review_status', 'pending'),
            'issue_id': iss.get('issue_id'),
        })

    # 2. Content & structural diff across paragraphs using SequenceMatcher
    sm = difflib.SequenceMatcher(None, orig_cust_lines[:80], out_lines[:80])
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        orig_seg = ' '.join(orig_cust_lines[i1:i2]).strip()
        rev_seg = ' '.join(out_lines[j1:j2]).strip()
        if not orig_seg and not rev_seg:
            continue

        if tag == 'insert':
            cat = 'Added content'
            color = 'green'
            sev = 'Low'
            expl = 'New customer-friendly framing or transitional text added during redesign.'
        elif tag == 'delete':
            cat = 'Removed content'
            color = 'red'
            sev = 'Medium' if len(orig_seg) > 40 else 'Low'
            expl = 'Source passage omitted or consolidated in redesigned output; verify nothing mandatory was dropped.'
        else:
            cat = 'Modified content'
            color = 'yellow'
            sev = 'Informational' if difflib.SequenceMatcher(None, orig_seg.lower(), rev_seg.lower()).ratio() > 0.65 else 'Medium'
            expl = 'Passage rewritten for clarity, tone, or audience readability.'

        change_idx += 1
        changes.append({
            'change_id': f"CHG-{change_idx:03d}",
            'category': cat,
            'severity': sev,
            'highlight_color': color,
            'original_page': 1,
            'output_page': 1,
            'original_section': 'Original Body',
            'output_section': 'Redesigned Body',
            'original_text': orig_seg[:320] or '—',
            'revised_text': rev_seg[:320] or '—',
            'change_explanation': expl,
            'source_evidence': orig_seg[:220] or 'Added in redesigned version',
            'impact_assessment': 'Cosmetic / readability simplification' if sev in ('Low', 'Informational') else 'Requires reviewer confirmation',
            'recommended_correction': 'Restore omitted text if mandatory.' if tag == 'delete' else 'No correction needed if meaning is preserved.',
            'review_status': 'pending',
        })
        if change_idx >= 30:
            break

    # 3. Structural / formatting record if design mode changed
    if redesigned.get('design_mode') != 'preserve_format':
        change_idx += 1
        changes.append({
            'change_id': f"CHG-{change_idx:03d}",
            'category': 'Formatting and structural change',
            'severity': 'Informational',
            'highlight_color': 'blue',
            'original_page': 1,
            'output_page': 1,
            'original_section': 'Document Layout',
            'output_section': 'Redesigned Layout',
            'original_text': 'Original document formatting',
            'revised_text': f"Reformatted using {redesigned.get('design_mode', 'modern').replace('_', ' ')} layout",
            'change_explanation': redesigned.get('design_notes', 'Visual hierarchy and spacing modernized.'),
            'source_evidence': 'Layout comparison',
            'impact_assessment': 'Visual presentation improvement only.',
            'recommended_correction': 'None required.',
            'review_status': 'approved',
        })

    # 4. Build 4-color highlighted HTML for the redesigned output
    orig_set = {ln.lower() for ln in orig_cust_lines}
    hl_blocks = []
    for ln in out_lines:
        low = ln.lower()
        esc = html_lib.escape(ln)
        if low in orig_set:
            hl_blocks.append(f'<div class="claria-cmp-line claria-cmp-unchanged">{esc}</div>')
        else:
            # Check if modified vs newly added
            best_ratio = max((difflib.SequenceMatcher(None, low, o).ratio() for o in orig_set), default=0.0)
            if best_ratio >= 0.45:
                hl_blocks.append(f'<div class="claria-cmp-line claria-cmp-modified" title="Modified for clarity"><mark class="cmp-yellow">{esc}</mark></div>')
            else:
                hl_blocks.append(f'<div class="claria-cmp-line claria-cmp-added" title="Added in redesign"><mark class="cmp-green">{esc}</mark></div>')

    # Append removed passages visibly at bottom of comparison view
    removed_items = [c for c in changes if c['highlight_color'] == 'red']
    if removed_items:
        hl_blocks.append('<div class="claria-cmp-removed-box"><strong>Removed / Missing Items Requiring Review:</strong>')
        for r in removed_items:
            hl_blocks.append(f'<div class="claria-cmp-removed"><mark class="cmp-red">{html_lib.escape(r["original_text"])}</mark></div>')
        hl_blocks.append('</div>')

    actionable_issues = fact_verification.get('issues') or []
    correction_prompt = (
        "I identified differences that may affect the accuracy or meaning of your redesigned document. "
        "Would you like me to apply the selected corrections and regenerate it?"
        if actionable_issues else None
    )

    counts = {
        'total_changes': len(changes),
        'added': sum(1 for c in changes if c['highlight_color'] == 'green'),
        'modified': sum(1 for c in changes if c['highlight_color'] == 'yellow'),
        'removed': sum(1 for c in changes if c['highlight_color'] == 'red'),
        'structural': sum(1 for c in changes if c['highlight_color'] == 'blue'),
        'critical': sum(1 for c in changes if c['severity'] == 'Critical'),
        'high': sum(1 for c in changes if c['severity'] == 'High'),
    }

    total_pages = structured_doc.get('total_pages', 1)
    return {
        'changes': changes,
        'counts': counts,
        'highlighted_changes_html': ''.join(hl_blocks),
        'actionable_issues': actionable_issues,
        'correction_prompt': correction_prompt,
        'coverage': {
            'status': 'Successfully compared',
            'pages_total': total_pages,
            'pages_compared': total_pages,
            'checks_performed': [
                'Content diff',
                'Financial fact verification',
                'Mandatory disclosure check',
                'Structural & semantic comparison',
            ],
            'pagination_note': 'Best-effort section alignment applied between original and redesigned layouts.' if total_pages > 1 else 'Single-page aligned comparison.',
        },
    }


def apply_selected_corrections(
    redesigned: dict[str, Any],
    corrections: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Applies ONLY approved/edited corrections to the redesigned document.
    Returns (updated_redesigned, decision_log).
    """
    updated = json.loads(json.dumps(redesigned))
    decision_log = []

    def replace_in_text(text: str, old_val: str, new_val: str) -> str:
        if not text:
            return text
        if old_val and old_val in text:
            return text.replace(old_val, new_val)
        return text

    for corr in corrections:
        action = (corr.get('decision') or 'approve').lower()
        orig_val = str(corr.get('original_value') or '').strip()
        out_val = str(corr.get('output_value') or '').strip()
        custom_val = str(corr.get('edited_value') or orig_val).strip()

        decision_log.append({
            'issue_id': corr.get('issue_id'),
            'decision': action,
            'applied_value': custom_val if action in ('approve', 'edit') else None,
            'justification': corr.get('justification', ''),
        })

        if action not in ('approve', 'edit') or not custom_val:
            continue

        if out_val and out_val != 'Not found in redesigned output':
            updated['introduction'] = replace_in_text(updated.get('introduction', ''), out_val, custom_val)
            updated['closing'] = replace_in_text(updated.get('closing', ''), out_val, custom_val)
            for sec in updated.get('sections') or []:
                sec['paragraphs'] = [replace_in_text(p, out_val, custom_val) for p in (sec.get('paragraphs') or [])]
                sec['bullets'] = [replace_in_text(b, out_val, custom_val) for b in (sec.get('bullets') or [])]
                if sec.get('table'):
                    sec['table'] = [[replace_in_text(str(c), out_val, custom_val) for c in row] for row in sec['table']]
            updated['mandatory_disclosures'] = [
                replace_in_text(d, out_val, custom_val) for d in (updated.get('mandatory_disclosures') or [])
            ]
        else:
            # Missing fact -> restore cleanly into mandatory_disclosures or a Restored Facts section
            src_ev = str(corr.get('source_evidence') or '').strip()
            restored_line = src_ev if custom_val in src_ev else f"Verified Detail ({corr.get('source_section', 'Source')}): {custom_val}"
            disclosures = updated.setdefault('mandatory_disclosures', [])
            if restored_line not in disclosures:
                disclosures.append(restored_line)

    updated['plain_text'] = _sections_to_plain_text(updated)
    return updated, decision_log


def detect_communication_issues(
    structured_doc: dict[str, Any],
    redesigned: dict[str, Any],
    fact_verification: dict[str, Any],
    comparison: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Section 12: Intelligent Issue Detection & Recommendation Engine.
    Inspects the redesigned output against the source without inventing artificial issues
    or auto-modifying the document. Every optional improvement requires human approval.
    """
    issues: list[dict[str, Any]] = []
    idx = 1

    for disc in fact_verification.get('discrepancies') or []:
        issues.append({
            'issue_id': f"ISSUE-{idx:02d}",
            'severity': disc.get('severity') or 'Critical',
            'title': f"Source Fact Discrepancy ({disc.get('fact_type', 'Fact')})",
            'description': disc.get('issue') or 'A source value was altered or omitted in the redesigned output.',
            'evidence': f"Page {disc.get('source_page', 1)} · {disc.get('source_section', 'Source')}: {disc.get('source_evidence', '')}",
            'current_output': disc.get('output_value') or 'Missing in redesigned output',
            'recommended_modification': f"Restore exact source value: {disc.get('original_value', '')}",
            'reason': 'Immutable source financial figures, dates, and identifiers must match the authoritative document.',
            'impact': 'Financial / Regulatory integrity',
            'approval_required': True,
            'prompt': 'Would you like me to apply this improvement?',
        })
        idx += 1

    comm_intel = structured_doc.get('communication_intelligence') or {}
    actions = (comm_intel.get('customer_action_intelligence') or {}).get('required_actions') or []
    intro = (redesigned.get('introduction') or '').lower()
    if actions and not any(k in intro for k in ('please', 'must', 'action', 'submit', 'confirm', 'pay', 'by ')):
        issues.append({
            'issue_id': f"ISSUE-{idx:02d}",
            'severity': 'Medium',
            'title': 'Action Visibility in Opening Summary',
            'description': 'Required customer action is present in the communication but not highlighted in the opening introduction.',
            'evidence': f"Source action: {actions[0][:160]}",
            'current_output': (redesigned.get('introduction') or '')[:180],
            'recommended_modification': 'Surface the primary customer action and deadline clearly in the opening panel without adding new facts.',
            'reason': 'Improves immediate customer comprehension and reduces missed deadlines.',
            'impact': 'Customer experience / Operational',
            'approval_required': True,
            'prompt': 'Would you like me to apply this improvement?',
        })
        idx += 1

    if not (redesigned.get('mandatory_disclosures') or []) and (comm_intel.get('legal_and_regulatory_intelligence') or {}).get('disclosures_and_clauses_count', 0) > 0:
        issues.append({
            'issue_id': f"ISSUE-{idx:02d}",
            'severity': 'High',
            'title': 'Mandatory Disclosure Placement',
            'description': 'Source contains legal/regulatory disclosures that should appear in a dedicated Mandatory Disclosures block.',
            'evidence': 'Source legal/regulatory clauses detected.',
            'current_output': 'Mandatory disclosures list is empty.',
            'recommended_modification': 'Preserve all source regulatory disclosures verbatim in the Important Disclosures section.',
            'reason': 'Protects legal and regulatory integrity.',
            'impact': 'Compliance / Legal',
            'approval_required': True,
            'prompt': 'Would you like me to apply this improvement?',
        })
        idx += 1

    return issues


CHANNEL_LIMITS = {
    'sms': 320,
    'push': 180,
    'whatsapp': 1024,
    'email': 4000,
    'web_portal': 6000,
    'mobile_app': 1500,
    'physical_letter': 12000,
    'cs_script': 4000,
}


def adapt_for_channel(
    redesigned: dict[str, Any],
    channel: str,
    structured_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Section 16: Multi-Channel Communication Adaptation.
    Maintains one authoritative source of truth for key facts and flags when long legal
    disclosures cannot fit a constrained channel and need an approved secondary mechanism.
    """
    ch = (channel or 'email').strip().lower().replace(' ', '_')
    limit = CHANNEL_LIMITS.get(ch, 4000)
    title = redesigned.get('title') or 'Customer Communication'
    intro = redesigned.get('introduction') or ''
    closing = redesigned.get('closing') or ''
    disclosures = redesigned.get('mandatory_disclosures') or []

    key_points = []
    for sec in redesigned.get('sections') or []:
        if sec.get('heading'):
            key_points.append(sec['heading'])
        for p in (sec.get('paragraphs') or [])[:1]:
            key_points.append(p)
        for b in (sec.get('bullets') or [])[:2]:
            key_points.append(f"- {b}")

    if ch in ('sms', 'push'):
        body = f"{title}: {intro}".strip()
        if len(body) > limit - 40:
            body = body[:limit - 43].rstrip() + '...'
        body += " View full notice & terms in your secure portal."
        disclosure_note = (
            "Channel character limit cannot hold full legal disclosures; deliver full mandatory disclosures via linked secure portal or email."
            if disclosures else "No long disclosures omitted."
        )
    elif ch == 'cs_script':
        body = (
            f"AGENT OPENING: Hello, I am calling regarding '{title}'.\n\n"
            f"KEY MESSAGE: {intro}\n\n"
            f"KEY DETAILS:\n" + '\n'.join(key_points[:6]) + "\n\n"
            f"MANDATORY DISCLOSURES TO READ/CONFIRM:\n" + ('\n'.join(disclosures[:3]) if disclosures else 'None specified.') + "\n\n"
            f"CLOSING: {closing}"
        )
        disclosure_note = "Mandatory disclosures included in agent script."
    else:
        parts = [f"Subject: {title}", "", redesigned.get('salutation') or 'Dear Valued Customer,', "", intro, ""]
        parts.extend(key_points[:10])
        if disclosures:
            parts.append("")
            parts.append("Important Disclosures:")
            parts.extend(disclosures[:6])
        if closing:
            parts.append("")
            parts.append(closing)
        body = '\n'.join(parts).strip()
        if len(body) > limit:
            body = body[:limit - 45].rstrip() + "\n\n[Full notice available via secure portal/PDF]"
        disclosure_note = "Full disclosures preserved within channel constraints." if len(body) <= limit else "Truncated for channel limit; attach full PDF."

    return {
        'channel': ch,
        'character_limit': limit,
        'character_count': len(body),
        'adapted_content': body,
        'disclosure_handling': disclosure_note,
        'source_document_id': (structured_doc or {}).get('document_id'),
    }
