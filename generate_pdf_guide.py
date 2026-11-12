import os
import sys
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, total_pages):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#73645E"))

        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "CLARIA · Customer Communications Redesign (TCS BFSI Standard)")
            self.setStrokeColor(colors.HexColor("#E5D5CE"))
            self.setLineWidth(0.5)
            self.line(54, 744, 558, 744)

        # Footer (all pages)
        self.setStrokeColor(colors.HexColor("#E5D5CE"))
        self.setLineWidth(0.5)
        self.line(54, 45, 558, 45)
        page_str = f"Page {self._pageNumber} of {total_pages}"
        self.drawRightString(558, 32, page_str)
        self.drawString(54, 32, "Confidential & Enterprise Learning Material · Antigravity AI Engineering")
        self.restoreState()


def build_pdf(filename="CLARIA_BEGINNER_STUDY_GUIDE.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#D9381E"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#554440"),
        spaceAfter=15,
    )
    h1_style = ParagraphStyle(
        'H1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#1A0A06"),
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )
    h2_style = ParagraphStyle(
        'H2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#D9381E"),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#2B2320"),
        spaceAfter=6,
    )
    bullet_style = ParagraphStyle(
        'Bullet',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13.5,
        textColor=colors.HexColor("#2B2320"),
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=4,
    )
    callout_style = ParagraphStyle(
        'Callout',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#8C2B14"),
    )
    code_style = ParagraphStyle(
        'CodeSpan',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1A1A1A"),
    )

    story = []

    # Title & Metadata
    story.append(Spacer(1, 10))
    story.append(Paragraph("CLARIA: Customer Communications Redesign", title_style))
    story.append(Paragraph("A Complete Beginner's Blueprint for Building & Deploying Enterprise Content Intelligence AI Agents", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#D9381E"), spaceAfter=14))

    # Executive Summary Card
    summary_text = (
        "<b>What is this document?</b> This is an end-to-end, step-by-step master study guide that explains "
        "how we created <b>CLARIA</b> (Agent #1 in the 10 Content Intelligence Agents library) entirely from scratch. "
        "It breaks down enterprise BFSI guardrails, backend architecture with AWS Bedrock, React frontend integration, "
        "testing strategies, and full cloud deployment on AWS CloudFront, API Gateway, and Lambda."
    )
    summary_table = Table(
        [[Paragraph(summary_text, body_style)]],
        colWidths=[504],
    )
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#FDF3F0")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#F0B8AE")),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 14))

    # SECTION 1
    story.append(Paragraph("1. The Real-World Problem: Why We Built CLARIA", h1_style))
    story.append(Paragraph(
        "In the banking, financial services, insurance, and legal sectors (BFSI), customers receive hundreds of pages "
        "of regulatory notices, fee updates, terms revisions, and compliance demands every year. These communications "
        "suffer from major real-world flaws:",
        body_style
    ))
    story.append(Paragraph("• <b>Intimidating Legalese:</b> Filled with statutory jargon, disclaimers, and formal corporate clauses that ordinary customers cannot understand.", bullet_style))
    story.append(Paragraph("• <b>Buried Action Items:</b> Critical deadlines, required documents, or payment penalties are hidden inside multi-page paragraphs.", bullet_style))
    story.append(Paragraph("• <b>False Alarms:</b> Many communications are purely for information (like annual privacy notices), but because they look formal, anxious customers flood call centers asking <i>'Do I need to do something?'</i>", bullet_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>CLARIA's Core Mission:</b> Answer the customer's two fundamental questions in under 10 seconds: "
        "<i>'What is this long message actually telling me?'</i> and <i>'What do I need to do right now?'</i>",
        body_style
    ))

    # SECTION 2
    story.append(Spacer(1, 10))
    story.append(Paragraph("2. The 6 Enterprise Deliverables Explained Simply", h1_style))
    story.append(Paragraph(
        "Whenever a customer uploads a PDF, DOCX, or pastes a letter, CLARIA analyzes it and produces 6 distinct deliverables:",
        body_style
    ))

    deliv_data = [
        ["#", "Deliverable Name", "What It Does & Why It Matters"],
        ["1", "What This Is About", "1 to 3 clear, plain-language sentences that explain the core subject and context without corporate fluff."],
        ["2", "What You Need To Do\n(Action Precision)", "Sequential numbered steps the customer must take. CRITICAL: If no action is needed, it explicitly outputs '✅ No action required · This communication is for information only' — NEVER invents actions."],
        ["3", "Important Details", "A structured chip grid extracting exact Deadlines, Monetary amounts, Required documents, Warnings/Penalties, and Official helpline contacts."],
        ["4", "Why This Matters", "Explains why the sender is requesting this action (e.g., central bank KYC regulations, fraud prevention, tariff adjustments)."],
        ["5", "What Happens Next", "Explains what happens once the customer takes action (verification time) and what happens if no action is taken (account restrictions)."],
        ["6", "Simplified Communication", "A full plain-English rewrite of the entire notice, keeping all numbers, dates, and legal protections 100% intact with a one-click copy button."],
    ]
    t_deliv = Table(deliv_data, colWidths=[24, 140, 340])
    t_deliv.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#D9381E")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E5D5CE")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor("#FFFFFF")),
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor("#FDF8F6")),
        ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor("#FFFFFF")),
        ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor("#FDF8F6")),
        ('BACKGROUND', (0, 5), (-1, 5), colors.HexColor("#FFFFFF")),
        ('BACKGROUND', (0, 6), (-1, 6), colors.HexColor("#FDF8F6")),
    ]))
    story.append(t_deliv)

    story.append(PageBreak())

    # SECTION 3
    story.append(Paragraph("3. Enterprise BFSI Guardrails (TCS Standard)", h1_style))
    story.append(Paragraph(
        "In enterprise banking and finance, you cannot simply send customer communications to a generic AI model. "
        "Strict compliance standards (PCI-DSS v4.0, RBI Digital Security, DPDP Act) require dedicated safety guardrails:",
        body_style
    ))

    story.append(Paragraph("<b>A. Action Precision Guardrail (Zero Hallucination)</b>", h2_style))
    story.append(Paragraph(
        "A common flaw in generic LLMs is that they try to be 'helpful' by making up suggestions even when the letter is just informational. "
        "CLARIA enforces a dual-boundary check: If a document contains phrases like <i>'for information only'</i>, <i>'no action required'</i>, "
        "or <i>'annual privacy disclosure'</i>, CLARIA overrides any speculative actions and locks the badge to "
        "<b>'✅ No action required · This communication is for information only'</b>.",
        body_style
    ))

    story.append(Paragraph("<b>B. Sensitive Identifier Redaction (PCI-DSS Compliance)</b>", h2_style))
    story.append(Paragraph(
        "Customers often paste communications containing sensitive account numbers or credentials. Before sending any text to the AI model:",
        body_style
    ))
    story.append(Paragraph("• <b>Masked:</b> Credit card numbers, CVVs, ATM PINs, passwords, full 16-digit bank accounts (masked to last 4), Aadhaar, PAN, SSN.", bullet_style))
    story.append(Paragraph("• <b>Preserved:</b> Non-harmful business details like customer names, bank branch names, dates, amounts, and transaction narratives.", bullet_style))

    story.append(Paragraph("<b>C. Zero Model Identification</b>", h2_style))
    story.append(Paragraph(
        "Enterprise enterprise clients require that proprietary infrastructure remains strictly brand-aligned. "
        "CLARIA scrubs all references to underlying model names (e.g. Amazon Nova, Claude, Titan, OpenAI, Bedrock) "
        "from the UI, system prompts, API responses, and exported outputs.",
        body_style
    ))

    story.append(Paragraph("<b>D. Source Traceability</b>", h2_style))
    story.append(Paragraph(
        "Every single extracted deadline, penalty fee, or requirement includes an interactive link to the verbatim quote "
        "from the original uploaded text, ensuring full auditability.",
        body_style
    ))

    # SECTION 4
    story.append(Spacer(1, 10))
    story.append(Paragraph("4. Step-by-Step Implementation Breakdown", h1_style))

    story.append(Paragraph("<b>Step 1: Dedicated Standalone Directory Structure</b>", h2_style))
    story.append(Paragraph(
        "Instead of mixing files with TAXORA, we created a brand-new directory: "
        "<code>c:\\Users\\ELCOT\\OneDrive\\Desktop\\Agent\\claria-customer-clarity-agent\\</code>. "
        "This keeps TAXORA (Document Taxonomy) and CLARIA (Communications Redesign) completely independent and modular.",
        body_style
    ))

    story.append(Paragraph("<b>Step 2: Backend Development (`claria/backend/`)</b>", h2_style))
    story.append(Paragraph(
        "• <b>`claria_service.py`:</b> Configures the Bedrock Converse API using Amazon Nova Pro (`us.amazon.nova-pro-v1:0`) "
        "with low temperature (0.1) for high factual accuracy. Enforces the JSON schema and Action Precision rules.<br/>"
        "• <b>`guardrail_service.py`:</b> Scans for prompt injection attacks, malware requests, and redacts PCI-DSS credentials.<br/>"
        "• <b>`document_service.py`:</b> Extracts text from PDF, Word documents, text files, and images.<br/>"
        "• <b>`lambda_function.py`:</b> The serverless entrypoint for AWS Lambda, handling multi-part file uploads and routing.",
        body_style
    ))

    story.append(Paragraph("<b>Step 3: Frontend Development (`claria/frontend/`)</b>", h2_style))
    story.append(Paragraph(
        "• Converted the provided prototype HTML/CSS into modern React 18 + Vite components.<br/>"
        "• Implemented the coral/amber visual theme (<code>#ff5a36</code>, <code>#ffbd4a</code>, dark background <code>#160704</code>).<br/>"
        "• Built <b>`ClariaResultCard.jsx`</b> which renders the 6 deliverables with clean badges, responsive action cards, and a copy button.<br/>"
        "• Added session persistence via <code>localStorage</code> so past redesigned communications remain accessible in the left sidebar.",
        body_style
    ))

    story.append(PageBreak())

    # SECTION 5
    story.append(Paragraph("5. Automated Testing & Verification", h1_style))
    story.append(Paragraph(
        "Before deploying to production, we created <b>`test_claria.py`</b> to verify both core use cases:",
        body_style
    ))

    test_box = (
        "<b>Automated Test Case 1: Purely Informational Notice</b><br/>"
        "• Input: Annual privacy policy disclosure with text 'This communication is for your information only. No action is required on your part.'<br/>"
        "• Assertion: <code>res['what_you_need_to_do']['action_required'] == False</code> and summary contains <i>'No action required'</i>.<br/>"
        "• Result: <b>PASSED (Zero invented actions)</b>.<br/><br/>"
        "<b>Automated Test Case 2: Action-Required Compliance Notice</b><br/>"
        "• Input: Mandatory re-KYC notice with $45 penalty, November 30 deadline, and required ID documents.<br/>"
        "• Assertion: <code>res['what_you_need_to_do']['action_required'] == True</code>, extracts deadline 'November 30, 2026', and checklists documents.<br/>"
        "• Result: <b>PASSED (All details, amounts, and dates preserved)</b>."
    )
    t_test = Table([[Paragraph(test_box, body_style)]], colWidths=[504])
    t_test.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F4FAF6")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#A8E5C4")),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(t_test)
    story.append(Spacer(1, 14))

    # SECTION 6
    story.append(Paragraph("6. AWS Cloud Deployment Architecture", h1_style))
    story.append(Paragraph(
        "CLARIA was deployed to live enterprise infrastructure on AWS Account <code>984625844016</code> (us-east-1):",
        body_style
    ))

    aws_data = [
        ["AWS Component", "Resource Name / URL", "Role in CLARIA"],
        ["CloudFront", "https://d3a54sx4bbzktn.cloudfront.net", "Global edge CDN delivering the UI with HTTPS, low latency, and caching."],
        ["S3 Bucket", "s3://claria-ui-984625844016", "Stores the compiled React static frontend files (HTML, CSS, JS)."],
        ["Origin Access Control (OAC)", "claria-oac-984625844016", "Ensures S3 remains 100% private; only CloudFront can read files."],
        ["API Gateway", "https://d71pirbml8.execute-api.us-east-1.amazonaws.com", "Serverless HTTP API Gateway routing /api/redesign to Lambda."],
        ["AWS Lambda", "claria-backend-api", "Executes the Python backend, handles guardrails, and calls Bedrock."],
        ["Amazon Bedrock", "us.amazon.nova-pro-v1:0", "Universal foundation model powering the plain-language redesign."],
    ]
    t_aws = Table(aws_data, colWidths=[100, 210, 194])
    t_aws.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A0A06")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8.5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E5D5CE")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor("#FFFFFF")),
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor("#FDF8F6")),
        ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor("#FFFFFF")),
        ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor("#FDF8F6")),
        ('BACKGROUND', (0, 5), (-1, 5), colors.HexColor("#FFFFFF")),
        ('BACKGROUND', (0, 6), (-1, 6), colors.HexColor("#FDF8F6")),
    ]))
    story.append(t_aws)
    story.append(Spacer(1, 14))

    # SECTION 7
    story.append(Paragraph("7. Essential UI Refinements & Bug Fixes (Carried Across All Agents)", h1_style))
    story.append(Paragraph(
        "During testing, we eliminated common UI flaws that degrade user experience across AI agents:",
        body_style
    ))
    story.append(Paragraph("• <b>Eliminating Double Scrollbars:</b> Set <code>overflow: hidden</code> on the chat layout shell and let ONLY the <code>.messages</code> container scroll with a thin, theme-styled scrollbar (6px).", bullet_style))
    story.append(Paragraph("• <b>Typography Readability:</b> Eliminated microscopic 7px-9px text. Standardized body text to 15px-16px, headings to 16px-24px, and labels to 12px for effortless reading.", bullet_style))
    story.append(Paragraph("• <b>Session Management (Rename & Delete):</b> Added inline renaming (pencil icon) and delete confirmation (trash icon) to the sidebar so users have complete control over conversation history.", bullet_style))
    story.append(Paragraph("• <b>Single Fixed Viewport:</b> Anchored the chat layout with <code>position: fixed; inset: 0;</code> to prevent page shaking or scrolling behind the chat composer.", bullet_style))
    story.append(Spacer(1, 10))

    # SECTION 8
    story.append(Paragraph("8. Key Beginner Takeaways & Best Practices", h1_style))
    story.append(Paragraph("1. <b>Separate Concerns:</b> Keep each agent in its own standalone folder (<code>taxora</code> vs <code>claria</code>) so changes in one agent never break another.", bullet_style))
    story.append(Paragraph("2. <b>Never Rely on Raw AI Prompts for Compliance:</b> Always pair LLMs with programmatic guardrails (like regex sanitizers and post-generation assertion checks) to guarantee zero hallucinated actions.", bullet_style))
    story.append(Paragraph("3. <b>Build for Factual Precision:</b> Use low temperature (0.1) when dealing with financial figures, dates, and legal clauses to avoid creative embellishments.", bullet_style))
    story.append(Paragraph("4. <b>Automate Deployments:</b> Maintain a script like <code>deploy_aws.py</code> so you can re-build, package, and update the cloud in one command without manual AWS console clicks.", bullet_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF generated successfully: {filename}")


if __name__ == '__main__':
    out = "c:/Users/ELCOT/OneDrive/Desktop/Agent/claria-customer-clarity-agent/CLARIA_BEGINNER_STUDY_GUIDE.pdf"
    build_pdf(out)

