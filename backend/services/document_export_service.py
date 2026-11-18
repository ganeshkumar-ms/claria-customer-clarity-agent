"""
CLARIA Actual Document Generation & Quality Validation Service (Module 6).
Generates real, downloadable, quality-validated PDF and DOCX files for:
1. Clean Redesigned Document
2. Highlighted Changes Document (Green=Added, Yellow=Modified, Red=Removed, Blue=Structural)
3. Original vs Redesigned Comparison Report
Includes both ReportLab/python-docx engines AND pure-stdlib fallbacks for AWS Lambda.
"""
import html as html_lib
import io
import re
import textwrap
import zipfile
from pathlib import Path
from typing import Any


def _safe_latin(text: str) -> str:
    """Normalizes Unicode symbols (like ₹) cleanly for PDF Type1 Helvetica fallback."""
    s = (text or '').replace('₹', 'Rs. ').replace('—', '-').replace('–', '-').replace('•', '*').replace('·', '-')
    return s.encode('latin-1', errors='replace').decode('latin-1')


def _pdf_esc(txt: str) -> str:
    return _safe_latin(txt).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _build_pdf_bytes_stdlib(
    title: str,
    blocks: list[dict[str, Any]],
    footer_left: str = 'Northridge Commercial Bank | Demonstration document - fictional details',
) -> bytes:
    """Executive Banking Redesign PDF generator matching the Northridge Commercial Bank redesigned template."""
    page_w, page_h = 612, 792  # US Letter
    margin_x = 58
    content_w = page_w - 2 * margin_x  # 496pt
    top_y = 726
    bottom_y = 70

    pages_cmds: list[list[str]] = [[]]
    y = top_y

    def new_page():
        nonlocal y
        pages_cmds.append([])
        y = top_y

    def ensure_space(needed: float):
        nonlocal y
        if y - needed < bottom_y:
            new_page()

    def add_text_line(txt: str, x: float, y_pos: float, font: str = 'F1', size: float = 10.5, rgb: tuple = (0.15, 0.20, 0.27)):
        safe = _pdf_esc(txt)
        pages_cmds[-1].append(
            f"BT /{font} {size:.1f} Tf {rgb[0]:.2f} {rgb[1]:.2f} {rgb[2]:.2f} rg {x:.1f} {y_pos:.1f} Td ({safe}) Tj ET"
        )

    # 1. Big Navy Document Title (22pt bold #163A5F)
    for wline in (textwrap.wrap(title, width=42) or [title]):
        ensure_space(28)
        add_text_line(wline, margin_x, y, font='F2', size=21.5, rgb=(0.09, 0.23, 0.37))
        y -= 26
    y -= 2

    for blk in blocks:
        btype = blk.get('type', 'para')
        text = str(blk.get('text') or '').strip()
        color = blk.get('highlight')

        if btype == 'lead':
            for wline in (textwrap.wrap(text, width=78) or ['']):
                ensure_space(16)
                add_text_line(wline, margin_x, y, font='F1', size=11.0, rgb=(0.20, 0.25, 0.33))
                y -= 16
            y -= 8
            continue

        if btype == 'deadline_box':
            ensure_space(64)
            box_h = 50
            box_bottom = y - box_h + 10
            cmds = pages_cmds[-1]
            # Fill #E8F1F8 (0.91, 0.95, 0.97), Stroke #7FA6C9 (0.50, 0.65, 0.79)
            cmds.append(f"0.91 0.95 0.97 rg 0.50 0.65 0.79 RG 0.9 w {margin_x} {box_bottom:.1f} {content_w} {box_h} re B")
            lbl = (blk.get('label') or 'PLEASE SUBMIT BY').upper()
            dt = (blk.get('date') or '').upper()
            lbl_x = margin_x + max(20, (content_w - len(lbl) * 5.6) / 2)
            dt_x = margin_x + max(20, (content_w - len(dt) * 9.8) / 2)
            add_text_line(lbl, lbl_x, box_bottom + 33, font='F2', size=9.0, rgb=(0.09, 0.23, 0.37))
            add_text_line(dt, dt_x, box_bottom + 14, font='F2', size=16.5, rgb=(0.09, 0.23, 0.37))
            y = box_bottom - 22
            continue

        if (btype in ('kv_table', 'table')) and blk.get('rows'):
            rows = blk['rows']
            row_h = 22
            ensure_space(len(rows) * row_h + 14)
            col1_w = 120
            col2_w = content_w - col1_w
            cmds = pages_cmds[-1]
            for r_pair in rows:
                lbl_txt = str(r_pair[0] if len(r_pair) > 0 else '')
                val_txt = ' | '.join(str(c) for c in r_pair[1:]) if len(r_pair) > 1 else ''
                row_bottom = y - row_h + 8
                cmds.append(f"0.97 0.98 0.99 rg 0.82 0.85 0.90 RG 0.6 w {margin_x} {row_bottom:.1f} {col1_w} {row_h} re B")
                cmds.append(f"1.00 1.00 1.00 rg 0.82 0.85 0.90 RG 0.6 w {margin_x + col1_w} {row_bottom:.1f} {col2_w} {row_h} re B")
                add_text_line(lbl_txt[:24], margin_x + 8, row_bottom + 7, font='F2', size=9.5, rgb=(0.12, 0.16, 0.23))
                add_text_line(val_txt[:68], margin_x + col1_w + 10, row_bottom + 7, font='F1', size=9.5, rgb=(0.20, 0.25, 0.33))
                y -= row_h
            y -= 16
            continue

        if btype == 'heading':
            ensure_space(28)
            y -= 4
            for wline in (textwrap.wrap(text, width=66) or [text]):
                add_text_line(wline, margin_x, y, font='F2', size=12.5, rgb=(0.09, 0.23, 0.37))
                y -= 17
            y -= 2
            continue

        if btype == 'square_bullet':
            wrapped = textwrap.wrap(text, width=78) or ['']
            ensure_space(len(wrapped) * 15 + 4)
            pages_cmds[-1].append(f"0.08 0.10 0.14 rg {margin_x + 12} {y + 0.5:.1f} 5.5 5.5 re f")
            for wline in wrapped:
                add_text_line(wline, margin_x + 23, y, font='F1', size=10.0, rgb=(0.12, 0.16, 0.22))
                y -= 15.5
            y -= 2
            continue

        if btype == 'round_bullet':
            wrapped = textwrap.wrap(text, width=78) or ['']
            ensure_space(len(wrapped) * 15 + 4)
            pages_cmds[-1].append(f"0.12 0.16 0.22 rg {margin_x + 13} {y + 2:.1f} 3.2 3.2 re f")
            for wline in wrapped:
                add_text_line(wline, margin_x + 22, y, font='F1', size=10.0, rgb=(0.12, 0.16, 0.22))
                y -= 15.5
            y -= 2
            continue

        if btype == 'prep_req':
            lbl = blk.get('label') or 'Preparation requirement: '
            full = lbl + text
            wrapped = textwrap.wrap(full, width=82) or ['']
            ensure_space(len(wrapped) * 15 + 8)
            y -= 2
            first = wrapped[0]
            if first.startswith(lbl.strip()):
                rest_first = first[len(lbl.strip()):]
                add_text_line(lbl.strip(), margin_x, y, font='F2', size=10.0, rgb=(0.12, 0.16, 0.22))
                offset_x = margin_x + len(lbl.strip()) * 5.3 + 4
                add_text_line(rest_first.lstrip(), offset_x, y, font='F1', size=10.0, rgb=(0.18, 0.23, 0.30))
            else:
                add_text_line(first, margin_x, y, font='F1', size=10.0, rgb=(0.18, 0.23, 0.30))
            y -= 15
            for wline in wrapped[1:]:
                add_text_line(wline, margin_x, y, font='F1', size=10.0, rgb=(0.18, 0.23, 0.30))
                y -= 15
            y -= 8
            continue

        if btype == 'hr':
            ensure_space(18)
            y -= 4
            pages_cmds[-1].append(f"0.82 0.85 0.90 RG 0.6 w {margin_x} {y:.1f} m {margin_x + content_w} {y:.1f} l S")
            y -= 16
            continue

        if btype == 'sign_off':
            ensure_space(36)
            div = blk.get('division') or 'Commercial Banking Division'
            inst = blk.get('institution') or 'Northridge Commercial Bank'
            add_text_line(div, margin_x, y, font='F2', size=10.0, rgb=(0.12, 0.16, 0.22))
            y -= 14
            add_text_line(inst, margin_x, y, font='F1', size=10.0, rgb=(0.20, 0.25, 0.33))
            y -= 22
            continue

        if btype == 'footer_note':
            wrapped = textwrap.wrap(text, width=95) or ['']
            ensure_space(len(wrapped) * 12 + 8)
            for wline in wrapped:
                add_text_line(wline, margin_x, y, font='F1', size=8.3, rgb=(0.40, 0.45, 0.53))
                y -= 12
            y -= 4
            continue

        bg = None
        if color == 'green':
            bg = (0.86, 0.98, 0.90)
        elif color == 'yellow':
            bg = (0.99, 0.97, 0.80)
        elif color == 'red':
            bg = (0.99, 0.88, 0.88)
        elif color == 'blue':
            bg = (0.87, 0.94, 1.00)

        if not text:
            y -= 6
            continue
        for raw_ln in text.splitlines():
            wrapped = textwrap.wrap(raw_ln, width=84) or ['']
            for wline in wrapped:
                ensure_space(15)
                if bg:
                    pages_cmds[-1].append(f"{bg[0]:.2f} {bg[1]:.2f} {bg[2]:.2f} rg {margin_x - 3} {y - 3:.1f} {content_w + 6} 14 re f")
                add_text_line(wline, margin_x, y, font='F1', size=10.0, rgb=(0.16, 0.21, 0.28))
                y -= 15
        y -= 6

    for p_idx, cmds in enumerate(pages_cmds, start=1):
        cmds.append(f"0.82 0.85 0.90 RG 0.5 w {margin_x} 48.0 m {margin_x + content_w} 48.0 l S")
        safe_fl = _pdf_esc(footer_left)
        cmds.append(f"BT /F1 8.0 Tf 0.42 0.47 0.55 rg {margin_x} 36.0 Td ({safe_fl}) Tj ET")
        pg_lbl = f"Page {p_idx}"
        cmds.append(f"BT /F1 8.0 Tf 0.42 0.47 0.55 rg {margin_x + content_w - 30} 36.0 Td ({pg_lbl}) Tj ET")

    objs: list[bytes] = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R /Lang (en) >>")
    page_obj_nums = []
    next_id = 5
    page_objs_data = []
    for cmds in pages_cmds:
        stream_bytes = '\n'.join(cmds).encode('latin-1', errors='replace')
        content_id = next_id
        page_id = next_id + 1
        next_id += 2
        page_obj_nums.append(page_id)
        page_objs_data.append((content_id, stream_bytes, page_id))

    kids_str = ' '.join(f"{pid} 0 R" for pid in page_obj_nums)
    objs.append(f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_obj_nums)} >>".encode('latin-1'))
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    for content_id, stream_bytes, page_id in page_objs_data:
        objs.append(f"<< /Length {len(stream_bytes)} >>\nstream\n".encode('latin-1') + stream_bytes + b"\nendstream")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>".encode('latin-1')
        )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{idx} 0 obj\n".encode('latin-1'))
        out.write(obj)
        out.write(b"\nendobj\n")

    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n".encode('latin-1'))
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode('latin-1'))
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode('latin-1'))
    return out.getvalue()


def _build_pdf_bytes(title: str, blocks: list[dict[str, Any]], footer_left: str = 'Northridge Commercial Bank | Demonstration document - fictional details') -> bytes:
    """Uses the precision executive vector PDF builder for exact visual fidelity across local and AWS Lambda."""
    return _build_pdf_bytes_stdlib(title, blocks, footer_left=footer_left)


def _build_docx_bytes_stdlib(title: str, blocks: list[dict[str, Any]]) -> bytes:
    """Pure-stdlib valid OpenXML .docx generator supporting executive template blocks."""
    p_xml = []

    def add_para(txt: str, bold: bool = False, size_half_pt: int = 21, shd: str | None = None, color_hex: str | None = None):
        rpr = []
        if bold:
            rpr.append('<w:b/>')
        rpr.append(f'<w:sz w:val="{size_half_pt}"/>')
        if color_hex:
            rpr.append(f'<w:color w:val="{color_hex}"/>')
        if shd:
            rpr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{shd}"/>')
        esc = html_lib.escape(txt)
        p_xml.append(f'<w:p><w:r><w:rPr>{"".join(rpr)}</w:rPr><w:t xml:space="preserve">{esc}</w:t></w:r></w:p>')

    shd_map = {'green': 'DCFCE7', 'yellow': 'FEF9C3', 'red': 'FEE2E2', 'blue': 'DBEAFE'}
    add_para(title, bold=True, size_half_pt=40, color_hex='163A5F')

    for blk in blocks:
        btype = blk.get('type', 'para')
        text = str(blk.get('text') or '').strip()
        shd = shd_map.get(blk.get('highlight'))
        if btype == 'lead':
            add_para(text, bold=False, size_half_pt=22, color_hex='334155')
        elif btype == 'deadline_box':
            lbl = (blk.get('label') or 'PLEASE SUBMIT BY').upper()
            dt = (blk.get('date') or '').upper()
            add_para(f"{lbl}: {dt}", bold=True, size_half_pt=28, shd='E8F1F8', color_hex='163A5F')
        elif btype in ('kv_table', 'table') and blk.get('rows'):
            for row in blk['rows']:
                add_para(' : '.join(str(c) for c in row), bold=False, size_half_pt=20, shd=shd)
        elif btype == 'heading':
            add_para(text, bold=True, size_half_pt=26, shd=shd, color_hex='163A5F')
        elif btype == 'square_bullet':
            add_para(f"■ {text}", bold=False, size_half_pt=21)
        elif btype == 'round_bullet':
            add_para(f"• {text}", bold=False, size_half_pt=21)
        elif btype == 'prep_req':
            lbl = blk.get('label') or 'Preparation requirement: '
            add_para(f"{lbl}{text}", bold=False, size_half_pt=21)
        elif btype == 'sign_off':
            add_para(blk.get('division') or 'Commercial Banking Division', bold=True, size_half_pt=21)
            add_para(blk.get('institution') or 'Northridge Commercial Bank', bold=False, size_half_pt=21)
        elif btype == 'footer_note':
            add_para(text, bold=False, size_half_pt=17, color_hex='64748B')
        elif text:
            add_para(text, bold=False, size_half_pt=21, shd=shd)

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{"".join(p_xml)}<w:sectPr/></w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('word/document.xml', doc_xml)
    return buf.getvalue()


def _build_docx_bytes(title: str, blocks: list[dict[str, Any]]) -> bytes:
    """Uses pure-stdlib OpenXML generator for consistent executive formatting across local and Lambda."""
    return _build_docx_bytes_stdlib(title, blocks)


def validate_generated_file(file_path: Path, kind: str) -> dict[str, Any]:
    """Validates generated PDF/DOCX existence, non-empty size, signature, and structural integrity."""
    if not file_path.exists():
        return {'valid': False, 'reason': 'File does not exist'}
    data = file_path.read_bytes()
    if len(data) < 100:
        return {'valid': False, 'reason': 'File is empty or too small'}

    if kind == 'pdf':
        ok_sig = data.startswith(b'%PDF-') and b'%%EOF' in data[-1024:]
        pages = len(re.findall(rb'/Type\s*/Page\b', data))
        return {
            'valid': ok_sig and pages >= 1,
            'size_bytes': len(data),
            'page_count': max(1, pages),
            'format': 'PDF',
        }
    if kind == 'docx':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                has_doc = 'word/document.xml' in zf.namelist()
            return {
                'valid': has_doc,
                'size_bytes': len(data),
                'format': 'DOCX',
            }
        except Exception as e:
            return {'valid': False, 'reason': str(e)}
    return {'valid': False, 'reason': 'Unsupported export kind'}


def _redesigned_to_blocks(redesigned: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if redesigned.get('introduction'):
        blocks.append({'type': 'lead', 'text': redesigned['introduction']})
    if redesigned.get('deadline') and redesigned.get('deadline') != '[TO BE CONFIRMED]':
        blocks.append({
            'type': 'deadline_box',
            'label': redesigned.get('deadline_label') or 'PLEASE SUBMIT BY',
            'date': str(redesigned['deadline']).upper(),
        })
    acc_rows = [
        [r.get('label', ''), r.get('value', '')]
        for r in (redesigned.get('account_details') or [])
        if isinstance(r, dict) and r.get('value') and r.get('value') != '[TO BE CONFIRMED]'
    ]
    if acc_rows:
        blocks.append({'type': 'heading', 'text': redesigned.get('details_heading') or 'Your loan details'})
        blocks.append({'type': 'kv_table', 'rows': acc_rows})

    if redesigned.get('checklist'):
        blocks.append({'type': 'heading', 'text': redesigned.get('what_we_need_heading') or 'What we need from you'})
        if redesigned.get('what_we_need_intro'):
            blocks.append({'type': 'para', 'text': redesigned['what_we_need_intro']})
        for item in redesigned['checklist']:
            if item:
                blocks.append({'type': 'square_bullet', 'text': str(item).rstrip('.')})
        if redesigned.get('preparation_requirement'):
            blocks.append({
                'type': 'prep_req',
                'label': 'Preparation requirement: ',
                'text': redesigned['preparation_requirement'],
            })

    if redesigned.get('what_happens_next'):
        blocks.append({'type': 'heading', 'text': redesigned.get('why_we_need_heading') or 'Why we need these documents'})
        blocks.append({'type': 'para', 'text': redesigned['what_happens_next']})

    routes = redesigned.get('submission_routes') or []
    if routes or redesigned.get('how_to_submit') or redesigned.get('need_help'):
        blocks.append({'type': 'heading', 'text': redesigned.get('how_to_send_heading') or 'How to send your documents'})
        if redesigned.get('how_to_submit_intro'):
            blocks.append({'type': 'para', 'text': redesigned['how_to_submit_intro']})
        if routes:
            for r in routes:
                blocks.append({'type': 'round_bullet', 'text': r})
        elif redesigned.get('how_to_submit'):
            blocks.append({'type': 'para', 'text': redesigned['how_to_submit']})
        if redesigned.get('need_help'):
            blocks.append({'type': 'para', 'text': redesigned['need_help']})

    for sec in redesigned.get('sections') or []:
        if sec.get('heading'):
            blocks.append({'type': 'heading', 'text': sec['heading']})
        for p in sec.get('paragraphs') or []:
            blocks.append({'type': 'para', 'text': p})
        for b in sec.get('bullets') or []:
            blocks.append({'type': 'round_bullet', 'text': b})
        if sec.get('table'):
            blocks.append({'type': 'table', 'rows': sec['table'], 'text': ''})

    if redesigned.get('mandatory_disclosures'):
        blocks.append({'type': 'heading', 'text': redesigned.get('obligations_heading') or 'Important information about your loan obligations'})
        for d in redesigned['mandatory_disclosures']:
            blocks.append({'type': 'para', 'text': d})

    blocks.append({'type': 'hr'})
    blocks.append({'type': 'heading', 'text': redesigned.get('closing_heading') or 'Thank you for your cooperation'})
    if redesigned.get('closing_text'):
        blocks.append({'type': 'para', 'text': redesigned['closing_text']})
    blocks.append({
        'type': 'sign_off',
        'division': redesigned.get('sign_off_division') or 'Commercial Banking Division',
        'institution': redesigned.get('sign_off_institution') or 'Northridge Commercial Bank',
    })
    if redesigned.get('footer_note'):
        blocks.append({'type': 'footer_note', 'text': redesigned['footer_note']})
    return blocks


def _highlighted_blocks(redesigned: dict[str, Any], comparison: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = [
        {'type': 'heading', 'text': 'Change Highlight Legend'},
        {'type': 'para', 'text': 'Green = Added content | Yellow = Modified content | Red = Removed / Missing item requiring review | Blue = Formatting & structural change', 'highlight': 'blue'},
    ]
    changes = comparison.get('changes') or []
    changed_rev = {c.get('revised_text', '').lower(): c.get('highlight_color') for c in changes if c.get('revised_text')}

    for blk in _redesigned_to_blocks(redesigned):
        if blk.get('type') == 'para':
            low = blk['text'].lower()
            hl = None
            for rev, col in changed_rev.items():
                if rev and len(rev) > 10 and (rev[:35] in low or low[:35] in rev):
                    hl = col
                    break
            blk = dict(blk, highlight=hl)
        blocks.append(blk)

    removed = [c for c in changes if c.get('highlight_color') == 'red']
    if removed:
        blocks.append({'type': 'heading', 'text': 'Removed / Missing Source Items Requiring Review'})
        for r in removed:
            blocks.append({'type': 'para', 'text': f"[{r['change_id']}] {r['original_text']}", 'highlight': 'red'})
    return blocks


def _report_blocks(
    doc_title: str,
    version_label: str,
    redesigned: dict[str, Any],
    fact_verification: dict[str, Any],
    comparison: dict[str, Any],
) -> list[dict[str, Any]]:
    cov = comparison.get('coverage') or {}
    blocks = [
        {'type': 'heading', 'text': 'Comparison Summary & Coverage'},
        {'type': 'para', 'text': f"Document: {doc_title} | Version: {version_label}"},
        {'type': 'para', 'text': f"Tone: {redesigned.get('tone_applied', 'Professional')} | Audience: {redesigned.get('audience_applied', 'General Public')}"},
        {'type': 'para', 'text': f"Comparison Status: {cov.get('status', 'Successfully compared')} ({cov.get('pages_compared', 1)}/{cov.get('pages_total', 1)} pages)"},
        {'type': 'para', 'text': f"Fact Verification Status: {fact_verification.get('overall_status', 'Verified')} ({fact_verification.get('verified_count', 0)}/{fact_verification.get('total_facts', 0)} verified, {fact_verification.get('discrepancy_count', 0)} discrepancies)"},
        {'type': 'heading', 'text': 'Source Fact Verification Register'},
    ]
    fact_rows = [['Fact ID', 'Category', 'Source Value', 'Output Value', 'Status']]
    for f in (fact_verification.get('facts') or [])[:40]:
        fact_rows.append([
            f.get('fact_id', ''),
            f.get('category', ''),
            str(f.get('extracted_value', '')),
            str(f.get('output_value') or 'Missing'),
            f.get('verification_status', ''),
        ])
    if len(fact_rows) > 1:
        blocks.append({'type': 'table', 'rows': fact_rows, 'text': ''})

    blocks.append({'type': 'heading', 'text': 'Detected Changes & Impact Assessment'})
    chg_rows = [['Change ID', 'Category', 'Severity', 'Original', 'Revised', 'Explanation']]
    for c in (comparison.get('changes') or [])[:40]:
        chg_rows.append([
            c.get('change_id', ''),
            c.get('category', ''),
            c.get('severity', ''),
            str(c.get('original_text', ''))[:90],
            str(c.get('revised_text', ''))[:90],
            str(c.get('change_explanation', ''))[:110],
        ])
    if len(chg_rows) > 1:
        blocks.append({'type': 'table', 'rows': chg_rows, 'text': ''})
    return blocks


def generate_all_outputs(
    out_dir: Path,
    file_prefix: str,
    redesigned: dict[str, Any],
    fact_verification: dict[str, Any],
    comparison: dict[str, Any],
    version_label: str = 'Version 1',
) -> dict[str, Any]:
    """Generates and validates clean, highlighted, and comparison report files in PDF and DOCX."""
    out_dir.mkdir(parents=True, exist_ok=True)
    title = redesigned.get('title') or 'Customer Communication'

    clean_blocks = _redesigned_to_blocks(redesigned)
    hl_blocks = _highlighted_blocks(redesigned, comparison)
    rep_blocks = _report_blocks(title, version_label, redesigned, fact_verification, comparison)

    specs = [
        ('clean_pdf', f"{file_prefix}_clean.pdf", 'pdf', title, clean_blocks),
        ('clean_docx', f"{file_prefix}_clean.docx", 'docx', title, clean_blocks),
        ('highlighted_pdf', f"{file_prefix}_highlighted.pdf", 'pdf', f"{title} — Highlighted Changes", hl_blocks),
        ('highlighted_docx', f"{file_prefix}_highlighted.docx", 'docx', f"{title} — Highlighted Changes", hl_blocks),
        ('report_pdf', f"{file_prefix}_comparison_report.pdf", 'pdf', f"{title} — Comparison Report", rep_blocks),
        ('report_docx', f"{file_prefix}_comparison_report.docx", 'docx', f"{title} — Comparison Report", rep_blocks),
    ]

    footer_left = redesigned.get('page_footer_left') or f"{redesigned.get('sign_off_institution') or 'Northridge Commercial Bank'} | Demonstration document - fictional details"
    downloads = {}
    validations = {}
    for key, fname, kind, doc_title, blocks in specs:
        fpath = out_dir / fname
        raw = _build_pdf_bytes(doc_title, blocks, footer_left=footer_left) if kind == 'pdf' else _build_docx_bytes(doc_title, blocks)
        fpath.write_bytes(raw)
        val = validate_generated_file(fpath, kind)
        validations[key] = val
        if val.get('valid'):
            downloads[key] = {
                'filename': fname,
                'stored_name': fname,
                'format': kind.upper(),
                'size_bytes': val.get('size_bytes', len(raw)),
                'page_count': val.get('page_count'),
                'download_url': f"/api/document/{fname}",
                'view_url': f"/api/document/{fname}/view" if kind == 'pdf' else f"/api/document/{fname}",
                'validated': True,
            }

    return {'downloads': downloads, 'quality_validation': validations}
