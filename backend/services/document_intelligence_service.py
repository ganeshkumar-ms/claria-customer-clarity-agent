"""
CLARIA Document Intelligence & Source Fact Verification Engine (Modules 2, 3, 5, 13).
Performs full-document structural parsing, customer-vs-internal content separation,
tone/audience safety checks, and deterministic source fact extraction & verification.
"""
import re
import hashlib
from typing import Any


INTERNAL_SECTION_MARKERS = (
    'internal implementation',
    'internal use only',
    'employee checklist',
    'staff instructions',
    'governance approval',
    'internal operational',
    'internal notes',
    'reviewer notes',
    'back-office',
    'escalation matrix (internal)',
    'do not distribute',
)

DISCLOSURE_MARKERS = (
    'disclosure',
    'terms and conditions',
    'important notice',
    'regulatory',
    'ombudsman',
    'grievance',
    'privacy notice',
    'mandatory',
    'disclaimer',
    'fdic',
    'rbi',
    'sebi',
    'apr',
    'annual percentage rate',
)

SENSITIVE_TONE_TOPICS = (
    'debt',
    'default',
    'hardship',
    'fraud',
    'legal action',
    'lawsuit',
    'foreclosure',
    'collections',
    'complaint',
    'rejected',
    'rejection',
    'declined',
    'payment failure',
    'overdue',
    'termination',
    'penalty',
)

SUPPORTED_TONES = (
    'professional', 'formal', 'friendly', 'conversational', 'empathetic',
    'simple', 'concise', 'persuasive', 'reassuring', 'engaging',
    'humorous', 'funny', 'corporate', 'premium',
)

SUPPORTED_AUDIENCES = (
    'first-time banking customers', 'first-time loan customers',
    'existing account holders', 'senior citizens', 'loan applicants',
    'credit card customers', 'insurance customers', 'business customers',
    'general public',
)


def parse_tone_and_audience(instruction: str, doc_text: str) -> dict[str, Any]:
    """Extracts requested tone, audience, design mode, and evaluates tone safety."""
    inst = (instruction or '').lower()
    doc_lower = (doc_text or '').lower()

    requested_tones = [t for t in SUPPORTED_TONES if re.search(rf'\b{re.escape(t)}\b', inst)]
    if not requested_tones:
        requested_tones = ['professional', 'clear']

    requested_audience = 'general public'
    for aud in SUPPORTED_AUDIENCES:
        if aud in inst:
            requested_audience = aud
            break
    if 'senior' in inst:
        requested_audience = 'senior citizens'
    elif 'first-time' in inst or 'beginner' in inst:
        requested_audience = 'first-time banking customers'
    elif 'loan' in inst:
        requested_audience = 'loan applicants'
    elif 'credit card' in inst:
        requested_audience = 'credit card customers'
    elif 'insurance' in inst:
        requested_audience = 'insurance customers'
    elif 'business' in inst or 'corporate' in inst:
        requested_audience = 'business customers'

    design_mode = 'preserve_format'
    if any(k in inst for k in ('complete redesign', 'completely new design', 'modern corporate', 'premium banking', 'minimal professional', 'full redesign', 'more attractive')):
        if 'premium' in inst:
            design_mode = 'premium_banking'
        elif 'minimal' in inst:
            design_mode = 'minimal_professional'
        else:
            design_mode = 'modern_corporate'

    # Tone safety guard: never trivialize hardship/debt/fraud/legal notices
    tone_safety_warning = None
    if any(t in requested_tones for t in ('humorous', 'funny')) and any(s in doc_lower for s in SENSITIVE_TONE_TOPICS):
        tone_safety_warning = (
            "Humorous or lighthearted tone is unsuitable because this document covers sensitive financial, "
            "legal, hardship, or enforcement obligations. Applied a clear, respectful, and empathetic tone instead "
            "while preserving all warnings and disclosures."
        )
        requested_tones = [t for t in requested_tones if t not in ('humorous', 'funny')]
        if not requested_tones:
            requested_tones = ['empathetic', 'professional']

    preserve_fee_table = any(k in inst for k in ('preserve the original fee', 'keep fee table', 'preserve fee table', 'same format'))

    return {
        'tones': requested_tones,
        'tone_label': ' & '.join(t.title() for t in requested_tones[:2]),
        'audience': requested_audience,
        'design_mode': design_mode,
        'preserve_fee_table': preserve_fee_table,
        'tone_safety_warning': tone_safety_warning,
    }


def _classify_element(text: str, heading_ctx: str = '') -> tuple[str, str]:
    """Classifies a document element into enterprise content category + sensitivity."""
    combined = f"{heading_ctx} {text}".lower()
    if any(m in combined for m in INTERNAL_SECTION_MARKERS):
        return 'internal_only', 'Internal'
    if any(m in combined for m in DISCLOSURE_MARKERS):
        return 'mandatory_disclosure', 'Customer-Public'
    if re.search(r'(?:₹|\$|€|£|\binr\b|\busd\b)\s*[\d,]+(?:\.\d+)?|\b\d+(?:\.\d+)?%\s*(?:apr|interest|fee|p\.a\.)?', combined):
        return 'financial_info', 'Customer-Sensitive'
    if any(w in combined for w in ('pursuant to', 'clause ', 'hereby', 'liability', 'indemnif', 'arbitration', 'governing law', 'terms')):
        return 'legal_contractual', 'Customer-Public'
    if any(w in combined for w in ('staff must', 'internal workflow', 'back office', 'escalation team')):
        return 'operational_instruction', 'Internal'
    return 'customer_facing', 'Customer-Public'


def parse_structured_document(raw_text: str, filename: str = 'document.txt', doc_id: str = '') -> dict[str, Any]:
    """
    Parses the FULL document (all pages) into structured page/section/paragraph/table elements,
    separates customer-facing vs internal-only content, and builds the Source Fact Register.
    """
    text = (raw_text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not doc_id:
        doc_id = f"doc-{hashlib.sha256((filename + text[:500]).encode('utf-8', 'ignore')).hexdigest()[:10]}"

    lines = text.split('\n')
    elements = []
    customer_elements = []
    internal_elements = []
    headings = []
    tables = []

    current_page = 1
    total_pages = 1
    page_markers = re.findall(r'\[Page\s+(\d+)\s+of\s+(\d+)\]', text, re.IGNORECASE)
    if page_markers:
        total_pages = max(int(m[1]) for m in page_markers)

    current_section = 'Document Overview'
    current_is_internal = False
    para_buf = []
    table_buf = []
    elem_counter = 0

    def flush_para():
        nonlocal elem_counter, para_buf
        if not para_buf:
            return
        joined = ' '.join(para_buf).strip()
        para_buf = []
        if not joined:
            return
        elem_counter += 1
        cat, sens = _classify_element(joined, current_section)
        if current_is_internal and cat == 'customer_facing':
            cat, sens = 'internal_only', 'Internal'
        el = {
            'element_id': f"{doc_id}-el-{elem_counter}",
            'page': current_page,
            'section': current_section,
            'element_type': 'bullet' if re.match(r'^(?:[•\-\*▪▸]|\d+[\.\)])\s+', joined) else 'paragraph',
            'text': joined,
            'classification': cat,
            'sensitivity': sens,
            'extraction_confidence': 'Verified',
        }
        elements.append(el)
        if cat in ('internal_only', 'operational_instruction'):
            internal_elements.append(el)
        else:
            customer_elements.append(el)

    def flush_table():
        nonlocal elem_counter, table_buf
        if not table_buf:
            return
        rows = [r for r in table_buf if r.strip()]
        table_buf = []
        if not rows:
            return
        elem_counter += 1
        t_text = '\n'.join(rows)
        cat, sens = _classify_element(t_text, current_section)
        if current_is_internal:
            cat, sens = 'internal_only', 'Internal'
        el = {
            'element_id': f"{doc_id}-tbl-{elem_counter}",
            'page': current_page,
            'section': current_section,
            'element_type': 'table',
            'text': t_text,
            'rows': [[c.strip() for c in re.split(r'\s*\|\s*|\t+', r)] for r in rows],
            'classification': cat,
            'sensitivity': sens,
            'extraction_confidence': 'Verified',
        }
        elements.append(el)
        tables.append(el)
        if cat in ('internal_only', 'operational_instruction'):
            internal_elements.append(el)
        else:
            customer_elements.append(el)

    for raw_ln in lines:
        st = raw_ln.strip()
        if not st:
            flush_para()
            flush_table()
            continue

        pm = re.match(r'^\[Page\s+(\d+)\s+of\s+(\d+)\]$', st, re.IGNORECASE)
        if pm:
            flush_para()
            flush_table()
            current_page = int(pm.group(1))
            total_pages = max(total_pages, int(pm.group(2)))
            continue

        if '|' in st or '\t' in raw_ln:
            flush_para()
            table_buf.append(st)
            continue
        else:
            flush_table()

        is_heading = (
            st.startswith('#')
            or (len(st) <= 85 and st.isupper() and any(c.isalpha() for c in st))
            or (len(st) <= 80 and st.endswith(':') and not re.match(r'^(?:Note|Warning|Tip)\b', st, re.I))
            or bool(re.match(r'^(?:Section|Clause|Part|Article)\s+\d+', st, re.I))
        )
        if is_heading:
            flush_para()
            clean_h = st.lstrip('#').strip()
            current_section = clean_h
            current_is_internal = any(m in clean_h.lower() for m in INTERNAL_SECTION_MARKERS)
            elem_counter += 1
            cat = 'internal_only' if current_is_internal else _classify_element(clean_h)[0]
            el = {
                'element_id': f"{doc_id}-hd-{elem_counter}",
                'page': current_page,
                'section': clean_h,
                'element_type': 'heading',
                'text': clean_h,
                'classification': cat,
                'sensitivity': 'Internal' if current_is_internal else 'Customer-Public',
                'extraction_confidence': 'Verified',
            }
            elements.append(el)
            headings.append({'page': current_page, 'text': clean_h, 'internal': current_is_internal})
            if current_is_internal:
                internal_elements.append(el)
            else:
                customer_elements.append(el)
            continue

        if re.match(r'^(?:[•\-\*▪▸]|\d+[\.\)])\s+', st):
            flush_para()
            para_buf.append(st)
            flush_para()
            continue

        para_buf.append(st)

    flush_para()
    flush_table()

    # Infer document title & type
    doc_title = headings[0]['text'] if headings else Path_stem(filename)
    doc_lower = text.lower()
    if any(k in doc_lower for k in ('fee schedule', 'tariff', 'account statement', 'billing')):
        doc_type = 'Financial / Fee Notice'
    elif any(k in doc_lower for k in ('loan', 'emi', 'repayment', 'mortgage')):
        doc_type = 'Loan / Credit Communication'
    elif any(k in doc_lower for k in ('privacy', 'disclosure', 'terms', 'policy')):
        doc_type = 'Regulatory / Policy Disclosure'
    elif any(k in doc_lower for k in ('study guide', 'blueprint', 'architecture')):
        doc_type = 'Technical / Educational Guide'
    else:
        doc_type = 'Enterprise Customer Communication'

    source_facts = extract_source_facts(elements, doc_id)

    return {
        'document_id': doc_id,
        'filename': filename,
        'document_title': doc_title,
        'document_type': doc_type,
        'total_pages': total_pages,
        'word_count': len(text.split()),
        'elements': elements,
        'customer_elements': customer_elements,
        'internal_elements': internal_elements,
        'headings': headings,
        'tables': tables,
        'source_facts': source_facts,
        'has_internal_content': len(internal_elements) > 0,
        'audience_clarification_needed': len(customer_elements) == 0 and len(elements) > 0,
    }


def Path_stem(name: str) -> str:
    base = (name or 'Document').rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    return base.rsplit('.', 1)[0] if '.' in base else base


def extract_source_facts(elements: list[dict], doc_id: str) -> list[dict[str, Any]]:
    """Extracts verifiable financial amounts, percentages/rates, dates, and mandatory obligations."""
    facts = []
    seen = set()
    fact_idx = 0

    money_re = re.compile(r'((?:₹|\$|€|£|INR|USD|EUR|GBP)\s*\d[\d,]*(?:\.\d{1,2})?)', re.IGNORECASE)
    pct_re = re.compile(r'(\b\d+(?:\.\d+)?%\s*(?:p\.a\.|apr|interest|fee|discount|penalty)?)', re.IGNORECASE)
    date_re = re.compile(
        r'(\b(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}'
        r'|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}'
        r'|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b)',
        re.IGNORECASE,
    )

    for el in elements:
        if el.get('classification') in ('internal_only', 'operational_instruction'):
            continue
        txt = el.get('text', '')
        page = el.get('page', 1)
        sec = el.get('section', 'Body')

        for cat, rx in (('financial_amount', money_re), ('rate_percentage', pct_re), ('date_deadline', date_re)):
            for m in rx.finditer(txt):
                val = re.sub(r'\s+', ' ', m.group(1)).strip()
                norm = re.sub(r'[\s,]', '', val.lower())
                key = (cat, norm, sec)
                if key in seen:
                    continue
                seen.add(key)
                fact_idx += 1
                facts.append({
                    'fact_id': f"{doc_id}-F{fact_idx:03d}",
                    'category': cat,
                    'extracted_value': val,
                    'normalized_value': norm,
                    'source_page': page,
                    'source_section': sec,
                    'source_text': txt[:260],
                    'extraction_confidence': 'Verified',
                    'verification_status': 'Pending output check',
                })

    return facts


def verify_output_facts(source_facts: list[dict], redesigned_text: str) -> dict[str, Any]:
    """
    Compares every source fact against the redesigned output text.
    Detects Verified, Discrepancy detected (e.g., modified fee amount), and Missing facts.
    """
    out_lower = (redesigned_text or '').lower()
    out_compact = re.sub(r'[\s,]', '', out_lower)

    # Extract all monetary amounts in output to detect modified amounts
    out_money = re.findall(r'((?:₹|\$|€|£|inr|usd)\s*\d[\d,]*(?:\.\d{1,2})?)', redesigned_text or '', re.IGNORECASE)
    out_money_norms = [re.sub(r'[\s,]', '', x.lower()) for x in out_money]

    verified_facts = []
    discrepancies = []
    missing_count = 0
    verified_count = 0

    for f in source_facts:
        norm = f['normalized_value']
        val = f['extracted_value']
        item = dict(f)

        if norm in out_compact:
            item['verification_status'] = 'Verified'
            item['output_value'] = val
            verified_count += 1
        else:
            # Check if a nearby label exists with a different numeric value
            sec_words = [w for w in re.findall(r'[a-z]{4,}', f.get('source_text', '').lower()) if w not in ('with', 'from', 'that', 'this', 'will', 'your')]
            output_candidate = None
            for line in (redesigned_text or '').splitlines():
                ll = line.lower()
                if any(w in ll for w in sec_words[:3]):
                    m = re.search(r'((?:₹|\$|€|£|INR|USD)\s*\d[\d,]*(?:\.\d{1,2})?|\b\d+(?:\.\d+)?%)', line, re.IGNORECASE)
                    if m and re.sub(r'[\s,]', '', m.group(1).lower()) != norm:
                        output_candidate = m.group(1).strip()
                        break

            if output_candidate:
                item['verification_status'] = 'Discrepancy detected'
                item['output_value'] = output_candidate
                discrepancies.append({
                    'issue_id': f"ISS-{f['fact_id']}",
                    'fact_id': f['fact_id'],
                    'category': 'Financial Fact Inconsistency' if f['category'] != 'date_deadline' else 'Date / Deadline Inconsistency',
                    'severity': 'Critical' if f['category'] == 'financial_amount' else 'High',
                    'original_value': val,
                    'output_value': output_candidate,
                    'source_page': f['source_page'],
                    'source_section': f['source_section'],
                    'source_evidence': f['source_text'],
                    'explanation': f"The redesigned document states '{output_candidate}' instead of the source value '{val}'.",
                    'recommended_correction': f"Restore the original value '{val}' unless this change is an authorized policy update.",
                    'review_status': 'pending',
                })
            else:
                item['verification_status'] = 'Missing'
                item['output_value'] = None
                missing_count += 1
                discrepancies.append({
                    'issue_id': f"ISS-{f['fact_id']}",
                    'fact_id': f['fact_id'],
                    'category': 'Missing Source Fact',
                    'severity': 'High' if f['category'] == 'financial_amount' else 'Medium',
                    'original_value': val,
                    'output_value': 'Not found in redesigned output',
                    'source_page': f['source_page'],
                    'source_section': f['source_section'],
                    'source_evidence': f['source_text'],
                    'explanation': f"Source {f['category'].replace('_', ' ')} '{val}' from Page {f['source_page']} ({f['source_section']}) is missing from the redesigned communication.",
                    'recommended_correction': f"Restore '{val}' into the corresponding section of the redesigned document.",
                    'review_status': 'pending',
                })

        verified_facts.append(item)

    overall_status = 'Verified'
    if discrepancies:
        overall_status = 'Discrepancy detected' if any(d['severity'] == 'Critical' for d in discrepancies) else 'Requires manual review'

    return {
        'overall_status': overall_status,
        'total_facts': len(source_facts),
        'verified_count': verified_count,
        'discrepancy_count': len(discrepancies),
        'missing_count': missing_count,
        'facts': verified_facts,
        'issues': discrepancies,
        'out_money_count': len(out_money_norms),
    }
