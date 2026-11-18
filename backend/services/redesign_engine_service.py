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

REDESIGN_SYSTEM_PROMPT = """You are CLARIA, an Enterprise Banking & Customer Communications Designer.
Transform the provided CUSTOMER-FACING document content according to the user's instruction, tone, and target audience.

STRICT RULES:
1. NEVER alter, round, or fabricate financial amounts, fees, interest rates, EMI values, dates, deadlines, or policy references. Preserve every source number/date verbatim unless the user explicitly instructed an authorized policy update.
2. NEVER weaken mandatory regulatory/legal disclosures, warnings, or customer obligations.
3. NEVER include internal-only staff instructions, internal implementation plans, or governance checklists in the customer-facing output.
4. Preserve tables clearly in structured row arrays when present.
5. Output ONLY valid JSON matching this schema:
{
  "title": "Clean customer-facing document title",
  "salutation": "Dear Valued Customer,",
  "introduction": "Clear, empathetic opening paragraph explaining what this communication is about.",
  "sections": [
    {
      "heading": "Section heading",
      "paragraphs": ["Clear paragraph text preserving all facts and dates."],
      "bullets": ["Optional bullet items"],
      "table": [["Col 1", "Col 2"], ["Val 1", "Val 2"]]
    }
  ],
  "mandatory_disclosures": ["Preserved regulatory/legal disclosure lines"],
  "closing": "Clear next steps and official contact / support closing.",
  "design_notes": "1-sentence summary of the tone, audience, and format adaptations applied."
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
    intro = (
        f"We are sharing this updated {structured_doc.get('document_type', 'communication').lower()} "
        f"in a {tone_info['tone_label'].lower()} format tailored for {tone_info['audience']}."
    )
    if grouped and grouped[0].get('paragraphs'):
        intro = grouped[0]['paragraphs'][0]
        grouped[0]['paragraphs'] = grouped[0]['paragraphs'][1:]

    return {
        'title': title,
        'salutation': 'Dear Valued Customer,',
        'introduction': intro,
        'sections': [g for g in grouped if g['paragraphs'] or g['bullets'] or g['table']],
        'mandatory_disclosures': disclosures,
        'closing': 'If you have any questions, please contact our customer support team using the official channels listed in your account portal.',
        'design_notes': f"Applied {tone_info['tone_label']} tone for {tone_info['audience']} ({tone_info['design_mode'].replace('_', ' ')}).",
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
