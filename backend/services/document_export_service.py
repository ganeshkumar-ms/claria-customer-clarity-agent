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


def _build_pdf_bytes_stdlib(title: str, blocks: list[dict[str, Any]]) -> bytes:
    """Spec-compliant accessible Letter PDF (1-inch margins, 18pt heading, 16pt section, 12pt body, no footers)."""
    page_w, page_h = 612, 792  # US Letter
    margin_x, top_y, bottom_y = 72, 720, 72  # 1 inch = 72pt on all sides
    line_h = 16

    pages_cmds: list[list[str]] = [[]]
    y = top_y

    def new_page():
        nonlocal y
        pages_cmds.append([])
        y = top_y

    def add_line(txt: str, font: str = 'F1', size: int = 12, rgb: tuple = (0.1, 0.14, 0.2), bg_rgb: tuple | None = None):
        nonlocal y
        if y < bottom_y:
            new_page()
        safe = _safe_latin(txt).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        cmds = pages_cmds[-1]
        if bg_rgb:
            cmds.append(f"{bg_rgb[0]:.2f} {bg_rgb[1]:.2f} {bg_rgb[2]:.2f} rg {margin_x - 4} {y - 3} {page_w - 2 * margin_x + 8} {line_h} re f")
        cmds.append(f"BT /{font} {size} Tf {rgb[0]:.2f} {rgb[1]:.2f} {rgb[2]:.2f} rg {margin_x} {y} Td ({safe}) Tj ET")
        y -= (line_h + (4 if size >= 16 else 0))

    add_line(title, font='F2', size=18, rgb=(0.04, 0.24, 0.48))
    y -= 6

    for blk in blocks:
        btype = blk.get('type', 'para')
        text = str(blk.get('text') or '').strip()
        color = blk.get('highlight')
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
        if btype == 'heading':
            y -= 6
            for wline in textwrap.wrap(text, width=62):
                add_line(wline, font='F2', size=16, rgb=(0.05, 0.20, 0.42), bg_rgb=bg)
            y -= 2
        else:
            for raw_ln in text.splitlines():
                wrapped = textwrap.wrap(raw_ln, width=74) or ['']
                for wline in wrapped:
                    add_line(wline, font='F1', size=12, rgb=(0.12, 0.16, 0.22), bg_rgb=bg)
            y -= 3

    # Assemble accessible PDF objects (Catalog with /Lang (en))
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


def _build_pdf_bytes(title: str, blocks: list[dict[str, Any]]) -> bytes:
    """Uses ReportLab when available for rich typography/tables, falling back to stdlib PDF."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=letter,
            leftMargin=72,
            rightMargin=72,
            topMargin=72,
            bottomMargin=72,
            title=_safe_latin(title),
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('ClariaTitle', parent=styles['Heading1'], fontSize=18, leading=22, textColor=colors.HexColor('#0B3C78'), spaceAfter=12)
        head_style = ParagraphStyle('ClariaHead', parent=styles['Heading2'], fontSize=16, leading=20, textColor=colors.HexColor('#0F4C81'), spaceBefore=12, spaceAfter=6)
        body_style = ParagraphStyle('ClariaBody', parent=styles['Normal'], fontSize=12, leading=16.5, textColor=colors.HexColor('#1E293B'), spaceAfter=6)

        bg_map = {
            'green': colors.HexColor('#DCFCE7'),
            'yellow': colors.HexColor('#FEF9C3'),
            'red': colors.HexColor('#FEE2E2'),
            'blue': colors.HexColor('#DBEAFE'),
        }

        story = [Paragraph(html_lib.escape(_safe_latin(title)), title_style)]
        for blk in blocks:
            btype = blk.get('type', 'para')
            text = str(blk.get('text') or '').strip()
            color = blk.get('highlight')
            if btype == 'table' and blk.get('rows'):
                tbl_data = [[Paragraph(html_lib.escape(_safe_latin(str(c))), body_style) for c in row] for row in blk['rows']]
                t = Table(tbl_data, repeatRows=1)
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2E8F0')),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('PADDING', (0, 0), (-1, -1), 5),
                ]))
                story.append(t)
                story.append(Spacer(1, 8))
                continue
            if not text:
                story.append(Spacer(1, 6))
                continue
            st = head_style if btype == 'heading' else body_style
            if color in bg_map:
                st = ParagraphStyle(f'Hl_{color}_{btype}', parent=st, backColor=bg_map[color])
            story.append(Paragraph(html_lib.escape(_safe_latin(text)).replace('\n', '<br/>'), st))

        doc.build(story)
        return buf.getvalue()
    except Exception:
        return _build_pdf_bytes_stdlib(title, blocks)


def _build_docx_bytes_stdlib(title: str, blocks: list[dict[str, Any]]) -> bytes:
    """Pure-stdlib valid OpenXML .docx generator (zero external dependencies)."""
    p_xml = []

    def add_para(txt: str, bold: bool = False, size_half_pt: int = 21, shd: str | None = None):
        rpr = []
        if bold:
            rpr.append('<w:b/>')
        rpr.append(f'<w:sz w:val="{size_half_pt}"/>')
        if shd:
            rpr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{shd}"/>')
        esc = html_lib.escape(txt)
        p_xml.append(f'<w:p><w:r><w:rPr>{"".join(rpr)}</w:rPr><w:t xml:space="preserve">{esc}</w:t></w:r></w:p>')

    shd_map = {'green': 'DCFCE7', 'yellow': 'FEF9C3', 'red': 'FEE2E2', 'blue': 'DBEAFE'}
    add_para(title, bold=True, size_half_pt=28)

    for blk in blocks:
        btype = blk.get('type', 'para')
        text = str(blk.get('text') or '').strip()
        shd = shd_map.get(blk.get('highlight'))
        if btype == 'table' and blk.get('rows'):
            for row in blk['rows']:
                add_para(' | '.join(str(c) for c in row), bold=False, size_half_pt=19, shd=shd)
        elif btype == 'heading':
            add_para(text, bold=True, size_half_pt=23, shd=shd)
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
    """Uses python-docx when available for rich tables/headings, falling back to stdlib OpenXML."""
    try:
        from docx import Document
        from docx.enum.text import WD_COLOR_INDEX

        doc = Document()
        doc.add_heading(title, level=1)
        hl_map = {
            'green': WD_COLOR_INDEX.BRIGHT_GREEN,
            'yellow': WD_COLOR_INDEX.YELLOW,
            'red': WD_COLOR_INDEX.RED,
            'blue': WD_COLOR_INDEX.TURQUOISE,
        }
        for blk in blocks:
            btype = blk.get('type', 'para')
            text = str(blk.get('text') or '').strip()
            color = blk.get('highlight')
            if btype == 'table' and blk.get('rows'):
                rows = blk['rows']
                ncols = max(len(r) for r in rows)
                if ncols > 0:
                    tbl = doc.add_table(rows=len(rows), cols=ncols)
                    tbl.style = 'Table Grid'
                    for r_i, row in enumerate(rows):
                        for c_i in range(ncols):
                            tbl.cell(r_i, c_i).text = str(row[c_i]) if c_i < len(row) else ''
                continue
            if not text:
                continue
            if btype == 'heading':
                doc.add_heading(text, level=2)
            else:
                p = doc.add_paragraph()
                run = p.add_run(text)
                if color in hl_map:
                    run.font.highlight_color = hl_map[color]

        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
    except Exception:
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
    blocks = []
    if redesigned.get('salutation'):
        blocks.append({'type': 'para', 'text': redesigned['salutation']})
    if redesigned.get('introduction'):
        blocks.append({'type': 'para', 'text': redesigned['introduction']})
    if redesigned.get('deadline') and redesigned.get('deadline') != '[TO BE CONFIRMED]':
        blocks.append({'type': 'heading', 'text': f"Your Submission Deadline: {redesigned['deadline']}"})
    if redesigned.get('checklist'):
        blocks.append({'type': 'heading', 'text': 'Your Document & Action Checklist'})
        for item in redesigned['checklist']:
            if item:
                blocks.append({'type': 'para', 'text': f"• {item}"})
    if redesigned.get('what_happens_next'):
        blocks.append({'type': 'heading', 'text': 'What happens next?'})
        blocks.append({'type': 'para', 'text': redesigned['what_happens_next']})
    if redesigned.get('how_to_submit'):
        blocks.append({'type': 'heading', 'text': 'How to submit'})
        blocks.append({'type': 'para', 'text': redesigned['how_to_submit']})
    if redesigned.get('need_help'):
        blocks.append({'type': 'heading', 'text': 'Need help?'})
        blocks.append({'type': 'para', 'text': redesigned['need_help']})
    for sec in redesigned.get('sections') or []:
        if sec.get('heading'):
            blocks.append({'type': 'heading', 'text': sec['heading']})
        for p in sec.get('paragraphs') or []:
            blocks.append({'type': 'para', 'text': p})
        for b in sec.get('bullets') or []:
            blocks.append({'type': 'para', 'text': f"• {b}"})
        if sec.get('table'):
            blocks.append({'type': 'table', 'rows': sec['table'], 'text': ''})
    if redesigned.get('mandatory_disclosures'):
        blocks.append({'type': 'heading', 'text': 'Important Obligations & Legal Disclosures'})
        for d in redesigned['mandatory_disclosures']:
            blocks.append({'type': 'para', 'text': d})
    if redesigned.get('closing'):
        blocks.append({'type': 'para', 'text': redesigned['closing']})
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

    downloads = {}
    validations = {}
    for key, fname, kind, doc_title, blocks in specs:
        fpath = out_dir / fname
        raw = _build_pdf_bytes(doc_title, blocks) if kind == 'pdf' else _build_docx_bytes(doc_title, blocks)
        fpath.write_bytes(raw)
        val = validate_generated_file(fpath, kind)
        validations[key] = val
        if val.get('valid'):
            downloads[key] = {
                'filename': fname,
                'format': kind.upper(),
                'size_bytes': val.get('size_bytes', len(raw)),
                'page_count': val.get('page_count'),
                'download_url': f"/api/document/{fname}",
                'view_url': f"/api/document/{fname}/view" if kind == 'pdf' else f"/api/document/{fname}",
                'validated': True,
            }

    return {'downloads': downloads, 'quality_validation': validations}
