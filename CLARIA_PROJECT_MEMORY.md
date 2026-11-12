# CLARIA: CUSTOMER COMMUNICATIONS REDESIGN — MASTER PROJECT MEMORY
**Author:** Antigravity AI Engineering Team  
**Agent:** CLARIA (Agent #1 in the 10 Content Intelligence Agents Library)  
**Parent Directory:** `c:\Users\ELCOT\OneDrive\Desktop\Agent\claria\`  
**AWS Account:** `984625844016` (us-east-1)  
**CloudFront URL:** `https://d3a54sx4bbzktn.cloudfront.net`  
**API Gateway URL:** `https://d71pirbml8.execute-api.us-east-1.amazonaws.com`  
**S3 Bucket:** `s3://claria-ui-984625844016`  
**Lambda Function:** `claria-backend-api`  

---

## 1. AGENT IDENTITY & CORE USE CASE
CLARIA is a dedicated enterprise AI specialist built according to **TCS BFSI Enterprise Standards**.
Its primary mission is to transform long, complex, jargon-heavy, legalistic, or intimidating business, banking, insurance, regulatory, and corporate communications into crystal-clear plain-language intelligence and immediate next actions.

### The Primary Customer Question
> **"What is this long communication actually telling me, and what do I need to do?"**

---

## 2. THE 6 ENTERPRISE DELIVERABLES
Every customer communication submitted to CLARIA (via pasted text, PDF, DOCX, or TXT) is processed into 6 structured deliverables:

1. **`what_this_is_about`**:
   - Plain-language explanation in 1 to 3 direct, human sentences.
   - Eliminates corporate fluff and legalese while retaining the exact subject and context.

2. **`what_you_need_to_do` (Action Precision Guardrail)**:
   - Prominently highlights the recipient's required actions in sequential order.
   - **Zero Hallucination Rule**: If the communication is informational only (e.g., annual privacy policy disclosure, interest rate schedule notice without action, system maintenance announcement), CLARIA MUST set `action_required: false` and state verbatim:
     > `✅ No action required · This communication is for information only`
   - CLARIA MUST NEVER invent or fabricate an action if none is required.
   - Includes deadline and urgency rating (High, Medium, Low, None).

3. **`important_details`**:
   - Structured chip grid extracting:
     * **Deadlines**: Cutoff dates and response deadlines.
     * **Amounts**: Monetary figures, tariff charges, waivers, or penalties.
     * **Required Documents**: Identification, utility bills, proofs.
     * **Conditions**: Prerequisites and eligibility rules.
     * **Warnings**: Penalties, account freeze warnings, lapses.
     * **Contact Information**: Verification helplines, official portals, reference IDs.

4. **`why_this_matters`**:
   - Explains why the sender is requesting this action or why this notice was issued (regulatory directives, security standards, account compliance).

5. **`what_happens_next`**:
   - Explains what happens once the customer takes action (turnaround time, confirmation) and what occurs if no action is taken (inaction consequences).

6. **`simplified_communication`**:
   - A complete rewrite of the entire communication in clean, modern, empathetic, plain English.
   - **Fact & Number Invariance**: Critical figures, dates, percentages, and mandatory legal notices are preserved verbatim.
   - Includes a one-click **"Copy Simplified Text"** button.

---

## 3. ENTERPRISE BFSI GUARDRAILS & SECURITY
1. **Action Precision Guardrail**: Automated verification preventing fabricated tasks on purely informational notices.
2. **Sensitive Identifier Redaction**: PCI-DSS v4.0 & DPDP compliance masks high-risk secrets (Credit Cards, PINs, CVVs, Passwords, full Bank Account numbers, SSN, Aadhaar, PAN) while preserving non-harmful personal details (names, cities, dates, statement entries).
3. **Traceability**: Every key point links back to a verbatim quote from the original source text.
4. **Zero Model Identification**: No underlying AI model names (Nova Pro, Claude, Bedrock, Anthropic, GPT) appear in responses, headers, metadata, or UI cards.

---

## 4. UI & DESIGN STANDARDS (MANDATED FOR ALL 10 AGENTS)
1. **Single Scrollbar Architecture**:
   - Fixed viewport (`position: fixed; inset: 0; overflow: hidden`).
   - Outer `html, body` do not double scroll.
   - ONLY `.messages` and `.histList` scroll independently using thin 6px custom scrollbars (`scrollbar-width: thin`).
2. **Readability & Typography Scale**:
   - No microscopic 7px-9px text.
   - Body & User/AI Bubbles: `15px - 16px` with `1.65` line-height.
   - Headings & Titles: `16px - 24px`.
   - Action Badges & Metadata: `12px - 13px`.
3. **Session Management (Rename & Delete)**:
   - Every agent sidebar must include:
     * **Rename**: Pencil icon button activating an inline `<input>` with Enter/Escape triggers.
     * **Delete Confirmation**: Trash icon button triggering an inline confirmation bar (`Delete this chat? Delete / Cancel`) to prevent accidental data loss.
     * Instant `localStorage` synchronization.

---

## 5. CODEBASE STRUCTURE (`c:\Users\ELCOT\OneDrive\Desktop\Agent\claria\`)
```
Agent/
├── taxora/   (Document & Taxonomy Intelligence Agent)
└── claria/   (Customer Communications Redesign Agent)
    ├── backend/
    │   ├── .env                       # AWS credentials & region configuration
    │   ├── main.py                    # Local FastAPI entrypoint (port 8001)
    │   ├── lambda_function.py         # Production AWS Lambda handler
    │   ├── requirements.txt           # Python dependencies (boto3, fastapi, etc.)
    │   ├── services/
    │   │   ├── claria_service.py      # Core CLARIA prompt, Bedrock Converse engine, guardrail verifier
    │   │   ├── guardrail_service.py   # Enterprise BFSI & PCI-DSS sanitization engine
    │   │   ├── document_service.py    # Multi-format text extraction (PDF, DOCX, TXT)
    │   │   └── viewer_service.py      # In-browser document viewer
    │   └── routers/
    │       └── claria_router.py       # FastAPI router (/api/redesign, /api/health)
    ├── frontend/
    │   ├── .env.production            # API Base pointing to live API Gateway
    │   ├── package.json               # React 18, Vite, Axios
    │   ├── vite.config.js             # Vite configuration
    │   ├── index.html                 # HTML with Inter & JetBrains fonts
    │   └── src/
    │       ├── main.jsx               # React DOM entry
    │       ├── App.jsx                # Full state, session memory, view transitions, drawer
    │       ├── App.css                # Polished single-scrollbar & typography styles
    │       ├── services/api.js        # API client for /api/redesign
    │       └── components/
    │           ├── ClariaSidebar.jsx  # Sidebar with Rename & Delete confirmation
    │           └── ClariaResultCard.jsx # 6 deliverables interactive card
    ├── deploy_aws.py                  # End-to-end AWS automated deployment script
    ├── test_claria.py                 # Automated test suite (all tests passing)
    ├── generate_pdf_guide.py          # Script generating the beginner study guide PDF
    ├── CLARIA_BEGINNER_STUDY_GUIDE.pdf # Printable PDF Study Guide
    └── CLARIA_PROJECT_MEMORY.md       # Master memory document
```

---

## 6. LIVE AWS DEPLOYMENT DETAILS
- **CloudFront URL**: `https://d3a54sx4bbzktn.cloudfront.net`
- **API Gateway URL**: `https://d71pirbml8.execute-api.us-east-1.amazonaws.com`
- **S3 Bucket**: `s3://claria-ui-984625844016`
- **Lambda Function**: `claria-backend-api`
- **IAM Role**: `claria-backend-lambda-role`
- **Region**: `us-east-1`
- **AWS Account ID**: `984625844016`
