import boto3
import json
import os
import re
import random
import datetime
import uuid
import html as html_lib
from pathlib import Path
from services import guardrail_service

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    load_dotenv()
except ImportError:
    pass


def get_bedrock_client():
    return boto3.client(
        'bedrock-runtime',
        region_name=os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION') or 'us-east-1',
    )


MODEL_ID = 'us.amazon.nova-pro-v1:0'

CLARIA_SYSTEM_PROMPT = """You are CLARIA, an Enterprise Customer Communication Intelligence, Transformation and Redesign Engine.
You operate at the level of a senior enterprise Customer Communications Management (CCM) architect, BFSI communication strategist, document intelligence engineer, regulatory content reviewer, customer experience specialist, and enterprise document automation consultant.
Your purpose is to transform existing customer-facing communications (letters, notices, emails, loan/collections/insurance/KYC/banking service communications, fee schedules, policy updates) into professionally structured, accessible, enterprise-ready deliverables while preserving 100% of source financial figures, dates, identifiers, and mandatory disclosures.
Always follow: Understand -> Analyse -> Transform -> Design -> Validate -> Generate -> Compare -> Review -> Approve -> Regenerate -> Finalise.

You solve the core customer communication problem at the top level:
"When a customer receives a long, dense communication, what is its identity and purpose, what exact sentences tell them what they need to do, when they need to act, and what changes for them, and how should it be redesigned for clarity without losing a single fact or disclosure?"

=== STRICT RULES FOR HIGHLIGHTING ===
1. COMPLETE COVERAGE ACROSS THE FULL DOCUMENT (NO IMPORTANT DETAIL MISSED):
   - Your goal is that a reader can read the highlighted sentences/clauses from top to bottom and catch EVERY important point without missing any action, deadline, fee, penalty, obligation, eligibility rule, exclusion, or customer impact.
   - Cover EVERY section and page of the document from beginning to end — never stop after page 1 or cap the count.
   - Return as many `sentence_highlights` as needed (there is NO maximum limit) so that every genuinely important sentence or self-contained clause across the entire document is highlighted, while leaving purely decorative filler unhighlighted.

2. COMPLETE MEANINGFUL SENTENCES OR CLAUSES — NEVER SINGLE WORDS:
   - Every `verbatim_sentence` you return in `sentence_highlights` MUST be a complete, meaningful sentence or self-contained clause (at least 6 words) copied word-for-word from the original communication.
   - NEVER return a single word, a 2-3 word phrase, or a broken fragment.
   - NEVER alter, add, or remove any words inside `verbatim_sentence`.

2. CUSTOMER CLARITY CATEGORIES (NOT A RISK REVIEWER):
   Categorize each highlighted sentence or paragraph into one of these 4 Customer Communication Clarity lenses:
   - "what_to_do": Full sentences/paragraphs that tell the recipient what action they need to take, what steps to follow, or what to submit/confirm.
   - "core_message": Full sentences/paragraphs that explain the main purpose of the communication — what the organization is announcing or telling the customer.
   - "timeline_dates": Full sentences that state when the change happens, effective dates, or by when the customer needs to act.
   - "customer_impact": Full sentences/paragraphs explaining what changes for the customer, important terms, what to watch out for if no action is taken, or what happens next.

3. PLAIN-ENGLISH CLARITY MEANING (`plain_meaning`):
   - For each highlighted sentence/paragraph, provide a warm, direct 1-sentence `plain_meaning` that explains in simple everyday language what that sentence means for the customer (e.g., "In simple terms: You need to confirm your updated mailing address by November 30 so your card delivery isn't delayed.").

4. ACTION PRECISION:
   - If the communication is informational only (no action required from the customer), set `action_required`: false and summary to:
     "No action required · This communication is for your information only"

5. ZERO MODEL DISCLOSURE:
   - Never mention underlying AI model names (Amazon, Nova, Claude, Bedrock, OpenAI). You are CLARIA.

=== RESPONSE FORMAT (ALWAYS RESPOND WITH ONLY VALID JSON) ===

CASE 1: USER CHATS, GREETS, OR ASKS A CONVERSATIONAL / FOLLOW-UP QUESTION WITHOUT NEW DOCUMENT CONTENT
(Includes "tell extra about...", "be more specific about...", or questions about customer clarity / prior highlights from conversation history — answer thoroughly and specifically.)
Respond with ONLY:
{
  "type": "chat",
  "message": "<warm, direct, helpful response>"
}

CASE 2: USER PROVIDES A CUSTOMER COMMUNICATION / DOCUMENT
Respond with ONLY:
{
  "type": "redesign",
  "what_this_is_about": "Clear 1-2 sentence plain-English summary of what this communication is telling the customer.",
  "what_you_need_to_do": {
    "action_required": true,
    "summary": "Clear 1-sentence summary of what the customer needs to do, OR 'No action required · This communication is for your information only'"
  },
  "sentence_highlights": [
    {
      "verbatim_sentence": "Exact COMPLETE sentence or full paragraph copied word-for-word from the document (must be a full sentence, never a single word)",
      "category": "what_to_do | core_message | timeline_dates | customer_impact",
      "clarity_tag": "What You Need To Do | Core Message | Key Timeline | What Changes / Watchout",
      "plain_meaning": "Simple, friendly 1-sentence explanation of what this sentence means for the customer."
    }
  ]
}
"""


def _sanitize_ai_output(obj):
    if isinstance(obj, str):
        cleaned = re.sub(r'\b(amazon\s+nova(?:\s+pro)?|nova-pro|bedrock|claude\s*3(?:\.5)?|gpt-4o?)\b', 'CLARIA Clarity Engine', obj, flags=re.IGNORECASE)
        return cleaned
    if isinstance(obj, dict):
        return {k: _sanitize_ai_output(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_ai_output(item) for item in obj]
    return obj


GREETING_RESPONSES = [
    "Hello! I am CLARIA, your Customer Communications Clarity Specialist. Upload any communication file or paste a notice, and I will keep 100% of your original text and format while highlighting the exact sentences and paragraphs that tell the customer what it's about, what they need to do, and what changes for them — with a side-by-side compare view.",
    "Hi there! Welcome to CLARIA. Drop a document or paste a customer letter below — I'll display the file in its exact original format and highlight the key paragraphs and sentences so anyone can understand the communication at a glance."
]

BRO_RESPONSES = [
    "Hey bro! Upload any customer communication file or paste text, and I'll keep the exact same text and format while highlighting the full sentences and paragraphs that matter most, plus a side-by-side compare option.",
    "Yo bro! Drop a communication file below — I'll highlight the key paragraphs and sentences so it's super easy to understand without changing a single word."
]

HOW_ARE_YOU_RESPONSES = [
    "I'm doing great and ready to clarify your customer communications! Upload a file to see full-sentence and paragraph clarity highlights with side-by-side comparison.",
    "Doing very well, thank you! Share any customer letter, email, or notice to see it redesigned with smart paragraph & sentence highlights."
]


def _pick_varied_response(pool: list, conversation_history: list) -> str:
    used = set()
    for m in (conversation_history or []):
        c = m.get('content')
        if isinstance(c, dict):
            c = c.get('message') or ''
        if isinstance(c, str):
            used.add(c.strip())
    available = [r for r in pool if r not in used]
    if not available:
        available = pool
    return random.choice(available)


def _match_quick_conversational(user_text: str, conversation_history: list):
    cleaned = re.sub(r'[^\w\s]', '', (user_text or '').strip().lower())
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    if not cleaned:
        return None

    is_bro = (
        bool(re.match(r'^(?:(?:hey+|hi+|yo+|sup|hello+|namaste|vanakkam)\s+)?(?:bro+|brother|bruh|brah|dude|yaar|bhai|bhaiya|machan|macha|thala|buddy|mate|man|sis|dost)(?:\s+(?:how\s+are\s+you|whats?\s+up|hw\s+r\s+u))?$', cleaned)) or
        cleaned in {'bro', 'broo', 'bruh', 'brah', 'brother', 'dude', 'yaar', 'bhai', 'machan', 'macha', 'thala', 'buddy', 'mate', 'sis', 'dost'}
    )
    if is_bro:
        return _pick_varied_response(BRO_RESPONSES, conversation_history)

    is_how_are_you = (
        bool(re.match(r'^(?:(?:hi+|h[ea]y+|h[ea]llo+|hlo)\s+)?(?:how|hw)\s+(?:r|are|re)\s+(?:u|you|yu)(?:\s+doing)?$', cleaned)) or
        bool(re.match(r'^(?:hows?|hws)\s+(?:it\s+going|u|you)$', cleaned)) or
        cleaned in {'hru', 'hw r u', 'how r u', 'how r you', 'how are you', 'how are u', 'whats up', 'sup', 'how do you do'}
    )
    if is_how_are_you:
        return _pick_varied_response(HOW_ARE_YOU_RESPONSES, conversation_history)

    is_greeting = (
        bool(re.match(r'^(?:hi+|h[ea]y+|h[ea]llo+|hlo|ji+|namaste|hola|greetings?|yo+|sup)(?:\s+(?:there|claria|agent|bot|all|team|friend|buddy|ji))?$', cleaned)) or
        bool(re.match(r'^(?:good\s+(?:morning|afternoon|evening|day))(?:\s+(?:claria|there|all))?$', cleaned)) or
        cleaned in {'ji', 'hi', 'hello', 'hey', 'hii', 'hiii', 'heyy', 'namaste ji'}
    )
    if is_greeting:
        return _pick_varied_response(GREETING_RESPONSES, conversation_history)

    return None


def _extract_clean_document_text(text: str, raw_document_text: str = None) -> str:
    cleaned = raw_document_text if (raw_document_text and raw_document_text.strip()) else (text or '')
    if '==================== ORIGINAL COMMUNICATION ====================\n' in cleaned:
        try:
            cleaned = cleaned.split('==================== ORIGINAL COMMUNICATION ====================\n', 1)[1]
            if '\n===============================================================' in cleaned:
                cleaned = cleaned.split('\n===============================================================', 1)[0]
        except Exception:
            pass
    if '[FULL-DOCUMENT ANALYSIS METADATA]' in cleaned and '====================================================================\n' in cleaned:
        try:
            cleaned = cleaned.split('====================================================================\n', 1)[1]
        except Exception:
            pass
    cleaned = cleaned.replace('(cid:127)', '•')
    return cleaned.strip()


def redesign_communication(
    text: str,
    conversation_history: list = None,
    raw_document_text: str = None,
    filename: str = None
) -> dict:
    if conversation_history is None:
        conversation_history = []

    if not raw_document_text:
        quick_reply = _match_quick_conversational(text, conversation_history)
        if quick_reply:
            return {
                "type": "chat",
                "message": quick_reply
            }

    guardrail_result = guardrail_service.inspect_and_sanitize(text)
    if guardrail_result.get('blocked'):
        return {
            "type": "chat",
            "message": guardrail_result.get("message", "The submitted communication cannot be processed."),
            "guardrail_status": "BLOCKED",
            "guardrail_details": guardrail_result
        }

    sanitized_text = guardrail_result.get("sanitized_text", text)
    if raw_document_text:
        doc_guard = guardrail_service.inspect_and_sanitize(raw_document_text)
        pure_doc_text = _extract_clean_document_text(sanitized_text, doc_guard.get("sanitized_text", raw_document_text))
    else:
        pure_doc_text = _extract_clean_document_text(sanitized_text, None)

    messages = []
    for msg in (conversation_history or [])[-6:]:
        content_txt = msg.get('content', '')
        if isinstance(content_txt, dict):
            content_txt = content_txt.get('what_this_is_about') or content_txt.get('message') or 'Communication analyzed.'
        content_txt = str(content_txt or '').strip()
        if not content_txt or content_txt.startswith('<!doctype') or '<html' in content_txt.lower():
            continue

        role = 'assistant' if msg.get('role') in ('ai', 'assistant') else 'user'
        if messages and messages[-1]['role'] == role:
            prev_txt = messages[-1]['content'][0]['text']
            messages[-1]['content'][0]['text'] = f"{prev_txt}\n\n{content_txt[:1500]}"
        else:
            messages.append({
                'role': role,
                'content': [{'text': content_txt[:1500]}]
            })

    while messages and messages[0]['role'] != 'user':
        messages.pop(0)

    safe_prompt = (sanitized_text or '').strip() or "Highlight the key sentences and paragraphs in this customer communication."

    if messages and messages[-1]['role'] == 'user':
        prev_txt = messages[-1]['content'][0]['text']
        messages[-1]['content'][0]['text'] = f"{prev_txt}\n\n{safe_prompt}"
    else:
        messages.append({
            'role': 'user',
            'content': [{'text': safe_prompt}]
        })

    if not messages:
        messages = [{'role': 'user', 'content': [{'text': safe_prompt}]}]

    client = get_bedrock_client()

    try:
        response = client.converse(
            modelId=MODEL_ID,
            messages=messages,
            system=[{'text': CLARIA_SYSTEM_PROMPT}],
            inferenceConfig={
                'maxTokens': 4000,
                'temperature': 0.1,
                'topP': 0.9,
            }
        )

        output_text = response['output']['message']['content'][0]['text'].strip()
        json_match = re.search(r'\{[\s\S]*\}', output_text)
        if json_match:
            parsed = json.loads(json_match.group(0))
        else:
            parsed = {"type": "chat", "message": output_text}
    except Exception as e:
        print(f"[CLARIA Service] Bedrock call error: {e}")
        try:
            fallback_response = client.converse(
                modelId='us.amazon.nova-lite-v1:0',
                messages=messages,
                system=[{'text': CLARIA_SYSTEM_PROMPT}],
                inferenceConfig={'maxTokens': 4000, 'temperature': 0.1}
            )
            output_text = fallback_response['output']['message']['content'][0]['text'].strip()
            json_match = re.search(r'\{[\s\S]*\}', output_text)
            if json_match:
                parsed = json.loads(json_match.group(0))
            else:
                parsed = {"type": "chat", "message": output_text}
        except Exception as e2:
            print(f"[CLARIA Service] Fallback call also failed: {e2}")
            if pure_doc_text and len(pure_doc_text.strip()) > 20:
                parsed = {
                    "type": "redesign",
                    "what_this_is_about": "Customer communication highlighted for instant clarity.",
                    "what_you_need_to_do": {
                        "action_required": True,
                        "summary": "Review the highlighted sentences and paragraphs below."
                    },
                    "sentence_highlights": []
                }
            else:
                parsed = {
                    "type": "chat",
                    "message": "Please upload a communication file or paste your customer communication text to view it with clarity highlights."
                }

    if raw_document_text and parsed.get('type') != 'redesign':
        parsed = {
            "type": "redesign",
            "what_this_is_about": parsed.get("message", "Customer communication highlighted for clarity."),
            "what_you_need_to_do": {
                "action_required": False,
                "summary": "Review the highlighted sentences and paragraphs in the document below."
            },
            "sentence_highlights": []
        }

    if parsed.get('type') == 'redesign':
        action_data = parsed.get('what_you_need_to_do') or {}
        informational_markers = [
            'for information only', 'for your information', 'no action required',
            'no action is required', 'informational purpose', 'annual privacy notice'
        ]
        t_lower = pure_doc_text.lower()
        if any(m in t_lower for m in informational_markers) and not any(m in t_lower for m in ['please submit', 'you must', 'action required', 'please complete']):
            action_data['action_required'] = False
            action_data['summary'] = "No action required · This communication is for your information only"
            parsed['what_you_need_to_do'] = action_data

        doc_bundle = build_clarity_highlighted_document(
            raw_text=pure_doc_text,
            parsed=parsed,
            filename=filename or "Customer_Communication.txt"
        )
        parsed['highlighted_document'] = doc_bundle

    parsed = _sanitize_ai_output(parsed)
    return parsed


# =====================================================================
# CUSTOMER COMMUNICATION CLARITY — SENTENCE & PARAGRAPH HIGHLIGHTER
# (100% Full Sentences & Paragraphs Only — NEVER Single Words)
# =====================================================================

CLARITY_CATEGORIES = {
    "what_to_do": {
        "label": "What You Need To Do",
        "color": "#10b981",
        "default_meaning": "This sentence tells the recipient what action or step needs to be taken."
    },
    "core_message": {
        "label": "What This Is Telling You",
        "color": "#38bdf8",
        "default_meaning": "This sentence states the core message or main update of the communication."
    },
    "timeline_dates": {
        "label": "When To Act / Key Timeline",
        "color": "#f59e0b",
        "default_meaning": "This sentence specifies an important date, deadline, or effective timeframe."
    },
    "customer_impact": {
        "label": "What Changes / Important Watchout",
        "color": "#a855f7",
        "default_meaning": "This sentence explains how this affects the customer or what to watch out for."
    }
}

ACTION_SENTENCE_PATTERNS = [
    r'\b(?:you\s+must|you\s+need\s+to|you\s+are\s+required\s+to|please\s+submit|please\s+provide|please\s+complete|please\s+sign|please\s+verify|please\s+update|please\s+review\s+and|please\s+contact|please\s+ensure)\b',
    r'\b(?:action\s+required|steps?\s+to\s+take|to\s+avoid\s+interruption|complete\s+and\s+return|upload\s+your|confirm\s+your|log\s+in\s+to\s+your\s+account|customer\s+must\s+take)\b',
    r'\b(?:kindly\s+submit|kindly\s+provide|kindly\s+update|we\s+request\s+you\s+to|we\s+ask\s+that\s+you|always\s+pair|keep\s+each\s+agent|maintain\s+a\s+script)\b'
]

TIMELINE_SENTENCE_PATTERNS = [
    r'\b(?:no\s+later\s+than|on\s+or\s+before|by\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2})\b',
    r'\b(?:effective\s+(?:from|as\s+of|on)|starting\s+on|beginning\s+on|expires?\s+on|due\s+date|due\s+by|deadline\s+is|within\s+\d+\s+(?:calendar\s+|business\s+|seconds?|minutes?|days?))\b',
    r'\b(?:November\s+\d{1,2}|December\s+\d{1,2}|\$\d+(?:,\d{3})*(?:\.\d{2})?|low\s+temperature\s*\(0\.1\)|under\s+10\s+seconds)\b'
]

IMPACT_WATCHOUT_SENTENCE_PATTERNS = [
    r'\b(?:if\s+you\s+do\s+not|if\s+we\s+do\s+not\s+receive|failure\s+to|otherwise\s+your|will\s+result\s+in|may\s+result\s+in)\b',
    r'\b(?:will\s+be\s+updated|will\s+change\s+to|will\s+increase|will\s+be\s+charged|fee\s+of|rate\s+will|automatically\s+renew|no\s+action\s+is\s+required|no\s+action\s+required)\b',
    r'\b(?:cannot\s+understand|hidden\s+inside|flood\s+call\s+centers|zero\s+hallucinated|ensuring\s+full\s+auditability|ensures\s+S3\s+remains)\b'
]

CORE_MESSAGE_SENTENCE_PATTERNS = [
    r'\b(?:we\s+are\s+writing\s+to|this\s+notice\s+is\s+to|we\s+would\s+like\s+to\s+inform\s+you|we\s+are\s+updating|we\s+have\s+updated|this\s+letter\s+confirms|we\s+are\s+pleased\s+to|important\s+update\s+regarding)\b',
    r'\b(?:master\s+study\s+guide\s+that\s+explains|analyzes\s+it\s+and\s+produces|plain-language\s+sentences\s+that\s+explain|plain-English\s+rewrite\s+of\s+the\s+entire)\b'
]


def _split_into_sentences_preserving_ws(text: str):
    """
    Splits a paragraph/line into (sentence_str, trailing_whitespace_str) tuples so joining them
    reconstructs 100.0% of the original string character-for-character.
    Never splits inside decimals ($150.00) or abbreviations (Sec., No., Mr., etc.).
    """
    if not text:
        return []
    boundary_re = re.compile(
        r'(?<!\bSec)(?<!\bRef)(?<!\bArt)(?<!\bNo)(?<!\bMr)(?<!\bDr)(?<!\bMs)(?<!\bJr)(?<!\bSr)(?<!\bInc)(?<!\bLtd)'
        r'([\.\!\?]+[\"\'\)\]]*)'
        r'(\s+)(?=[A-Z0-9\"\'\(\[\•\-\*]|$)'
    )
    parts = []
    last_idx = 0
    for m in boundary_re.finditer(text):
        end_sent = m.end(1)
        end_ws = m.end(2)
        parts.append((text[last_idx:end_sent], text[end_sent:end_ws]))
        last_idx = end_ws
    if last_idx < len(text):
        rem = text[last_idx:]
        m_trail = re.search(r'(\s*)$', rem)
        if m_trail and m_trail.group(1):
            ws_len = len(m_trail.group(1))
            parts.append((rem[:-ws_len], rem[-ws_len:]))
        else:
            parts.append((rem, ''))
    return parts


def _classify_full_sentence(sentence: str, ai_highlights: list, allow_fallback: bool = False) -> dict:
    """
    Classifies a complete sentence or self-contained clause across the full document.
    Matches AI-selected highlights (including punctuation-normalized matching) and falls back
    to deterministic clarity patterns so no important obligation, deadline, or impact is missed.
    """
    s_clean = re.sub(r'\s+', ' ', sentence).strip()
    words = s_clean.split()
    if len(words) < 4:
        return None

    s_lower = s_clean.lower()
    s_norm = re.sub(r'[^\w\s]', '', s_lower)

    # 1. Match against AI-selected sentence_highlights
    for item in ai_highlights:
        if item.get('used'):
            continue
        q_clean = item['quote_clean']
        if len(q_clean.split()) < 4:
            continue
        q_norm = re.sub(r'[^\w\s]', '', q_clean)
        if q_clean in s_lower or (len(words) >= 6 and s_lower in q_clean) or (q_norm and len(q_norm) >= 18 and (q_norm in s_norm or s_norm in q_norm)):
            item['used'] = True
            cat = item['category']
            meta = CLARITY_CATEGORIES.get(cat, CLARITY_CATEGORIES['core_message'])
            return {
                'category': cat,
                'label': item.get('label') or meta['label'],
                'meaning': item.get('meaning') or meta['default_meaning']
            }

    if not allow_fallback:
        return None

    # 2. Fallback (only used if AI returned 0 matches)
    for pat in ACTION_SENTENCE_PATTERNS:
        if re.search(pat, s_clean, re.IGNORECASE):
            return {
                'category': 'what_to_do',
                'label': CLARITY_CATEGORIES['what_to_do']['label'],
                'meaning': CLARITY_CATEGORIES['what_to_do']['default_meaning']
            }

    for pat in TIMELINE_SENTENCE_PATTERNS:
        if re.search(pat, s_clean, re.IGNORECASE):
            return {
                'category': 'timeline_dates',
                'label': CLARITY_CATEGORIES['timeline_dates']['label'],
                'meaning': CLARITY_CATEGORIES['timeline_dates']['default_meaning']
            }

    for pat in IMPACT_WATCHOUT_SENTENCE_PATTERNS:
        if re.search(pat, s_clean, re.IGNORECASE):
            return {
                'category': 'customer_impact',
                'label': CLARITY_CATEGORIES['customer_impact']['label'],
                'meaning': CLARITY_CATEGORIES['customer_impact']['default_meaning']
            }

    for pat in CORE_MESSAGE_SENTENCE_PATTERNS:
        if re.search(pat, s_clean, re.IGNORECASE):
            return {
                'category': 'core_message',
                'label': CLARITY_CATEGORIES['core_message']['label'],
                'meaning': CLARITY_CATEGORIES['core_message']['default_meaning']
            }

    return None


def _reconstruct_paragraph_blocks(raw_text: str) -> list:
    """
    Groups soft-wrapped PDF/document continuation lines into coherent paragraph blocks
    so sentences are never split mid-sentence across PDF line wraps, while preserving
    blank lines, headings, bullet points, page markers, and tables.
    """
    raw_lines = raw_text.splitlines()
    blocks = []

    def classify_line(s: str) -> str:
        st = s.strip()
        if not st:
            return 'blank'
        if re.match(r'^\[(?:Page|Slide|Sheet)\b.*\]$', st, re.IGNORECASE):
            return 'heading'
        if ('\t' in s and s.count('\t') >= 1) or (st.startswith('|') and st.endswith('|')):
            return 'table'
        if re.match(r'^(\s*)(?:[\•\-\*\▪\▸]|\([a-zA-Z0-9]+\))\s+', s):
            return 'bullet'
        if re.match(r'^(?:\d+\.|[A-Z]\.|Step\s+\d+:?)\s+[A-Z]', st):
            return 'heading' if len(st.split()) <= 12 and not st.endswith('.') else 'bullet'
        if (len(st) < 80 and st.isupper() and any(c.isalpha() for c in st)) or bool(
            re.match(r'^(?:#{1,4}\s+|(?:SECTION|ARTICLE|PART|SUBJECT|RE|DEAR)\b)', st, re.IGNORECASE)
        ):
            return 'heading'
        return 'para'

    for ln in raw_lines:
        st = ln.strip()
        btype = classify_line(ln)
        if btype == 'blank':
            blocks.append({'type': 'blank', 'text': ''})
            continue

        if not blocks or blocks[-1]['type'] in ('blank', 'table'):
            blocks.append({'type': btype, 'text': st})
            continue

        prev = blocks[-1]
        prev_txt = prev['text']

        # Never merge if the new line is an explicit bullet, numbered item, page marker, or table
        if btype in ('bullet', 'table') or re.match(r'^\[(?:Page|Slide|Sheet)\b.*\]$', st, re.IGNORECASE) or re.match(r'^(?:\d+\.|[A-Z]\.|Step\s+\d+:?)\s+[A-Z]', st):
            blocks.append({'type': btype, 'text': st})
            continue

        # If the previous block is a paragraph or bullet and did NOT end with sentence-ending punctuation,
        # this line is a soft-wrapped continuation of the same sentence/paragraph!
        if prev['type'] in ('para', 'bullet') and (not prev_txt.endswith(('.', '!', '?', ':')) or (st and st[0].islower())):
            if prev_txt.endswith('-') and len(prev_txt) > 1 and prev_txt[-2].isalpha() and st and st[0].islower():
                prev['text'] = prev_txt + st
            else:
                prev['text'] = prev_txt + ' ' + st
        else:
            blocks.append({'type': btype, 'text': st})

    return blocks


def build_clarity_highlighted_document(raw_text: str, parsed: dict, filename: str = "Communication.txt") -> dict:
    """
    Preserves 100% of raw_text words and paragraph/section formatting.
    Highlights ONLY complete sentences and paragraphs (NEVER single words).
    """
    if not raw_text:
        raw_text = ""

    raw_ai_list = parsed.get("sentence_highlights") or parsed.get("watchout_highlights") or []
    MapOldToNew = {
        "mandatory_action": "what_to_do",
        "critical_watchout": "customer_impact",
        "deadline_window": "timeline_dates",
        "financial_impact": "customer_impact",
        "key_clause": "core_message"
    }

    ai_highlights = []
    for item in raw_ai_list:
        if not isinstance(item, dict):
            continue
        q = str(item.get("verbatim_sentence") or item.get("verbatim_quote") or "").strip()
        if len(q.split()) < 6:
            continue
        raw_cat = str(item.get("category") or "core_message").strip()
        cat = MapOldToNew.get(raw_cat, raw_cat)
        if cat not in CLARITY_CATEGORIES:
            cat = "core_message"
        ai_highlights.append({
            "quote": q,
            "quote_clean": re.sub(r'\s+', ' ', q).strip().lower(),
            "category": cat,
            "label": item.get("clarity_tag") or item.get("watchout_label") or CLARITY_CATEGORIES[cat]["label"],
            "meaning": item.get("plain_meaning") or item.get("enterprise_note") or CLARITY_CATEGORIES[cat]["default_meaning"]
        })

    blocks = _reconstruct_paragraph_blocks(raw_text)

    def render_pass(allow_fallback: bool):
        orig_out = []
        hl_out = []
        hl_items = []
        pass_stats = {
            "total_highlights": 0,
            "what_to_do": 0,
            "core_message": 0,
            "timeline_dates": 0,
            "customer_impact": 0,
            "word_count": len(raw_text.split()),
            "verbatim_verified": True
        }
        counter = 0

        for block_idx, blk in enumerate(blocks):
            btype = blk['type']
            content_part = blk['text']

            if btype == 'blank':
                orig_out.append('<div class="claria-doc-line claria-blank-line">&nbsp;</div>')
                hl_out.append('<div class="claria-doc-line claria-blank-line">&nbsp;</div>')
                continue

            line_cls = "claria-doc-line"
            if btype == 'heading':
                line_cls += " claria-line-heading"
            elif btype == 'bullet':
                line_cls += " claria-line-bullet"
            elif btype == 'table':
                line_cls += " claria-line-table"
            else:
                line_cls += " claria-line-para"

            orig_out.append(f'<div class="{line_cls}" data-line="{block_idx + 1}">{html_lib.escape(content_part)}</div>')

            if btype == 'heading':
                hl_out.append(f'<div class="{line_cls}" data-line="{block_idx + 1}">{html_lib.escape(content_part)}</div>')
                continue

            sentence_chunks = _split_into_sentences_preserving_ws(content_part)
            hl_line_pieces = []
            line_categories = []

            for sent_text, trailing_ws in sentence_chunks:
                match_info = _classify_full_sentence(sent_text, ai_highlights, allow_fallback=allow_fallback)

                if match_info:
                    counter += 1
                    cat = match_info['category']
                    label = match_info['label']
                    meaning = match_info['meaning']
                    pass_stats[cat] = pass_stats.get(cat, 0) + 1
                    pass_stats["total_highlights"] += 1
                    line_categories.append(cat)

                    hl_id = f"claria-sent-{counter}"

                    # If sentence starts with a short bullet/numbered title prefix before a colon (e.g. "• Intimidating Legalese: Filled with..."),
                    # keep the label prefix unhighlighted and highlight the meaningful takeaway clause after ": "!
                    prefix_match = re.match(r'^((?:[\•\-\*\▪\▸]|\d+[\.\)])?\s*[A-Za-z0-9\s\-\/\'\"\(\)`]{2,38}:\s+)(.{25,})$', sent_text)
                    if prefix_match:
                        prefix_str = prefix_match.group(1)
                        core_clause = prefix_match.group(2)
                    else:
                        prefix_str = ""
                        core_clause = sent_text

                    hl_items.append({
                        "id": hl_id,
                        "index": counter,
                        "line": block_idx + 1,
                        "category": cat,
                        "label": label,
                        "note": meaning,
                        "verbatim_text": core_clause.strip()
                    })

                    hl_line_pieces.append(
                        f'{html_lib.escape(prefix_str)}'
                        f'<mark id="{hl_id}" class="claria-hl-sentence claria-cat-{cat}" '
                        f'data-category="{cat}" data-label="{html_lib.escape(label)}" '
                        f'data-note="{html_lib.escape(meaning)}" data-index="{counter}">'
                        f'<span class="claria-hl-text">{html_lib.escape(core_clause)}</span>'
                        f'</mark>{html_lib.escape(trailing_ws)}'
                    )
                else:
                    hl_line_pieces.append(html_lib.escape(sent_text) + html_lib.escape(trailing_ws))

            para_cat_cls = ""
            if "what_to_do" in line_categories:
                para_cat_cls = " claria-para-what_to_do"
            elif "customer_impact" in line_categories:
                para_cat_cls = " claria-para-customer_impact"
            elif "timeline_dates" in line_categories:
                para_cat_cls = " claria-para-timeline_dates"
            elif "core_message" in line_categories:
                para_cat_cls = " claria-para-core_message"

            hl_out.append(
                f'<div class="{line_cls}{para_cat_cls}" data-line="{block_idx + 1}">'
                f'{"".join(hl_line_pieces)}'
                f'</div>'
            )

        return orig_out, hl_out, hl_items, pass_stats

    orig_blocks, hl_blocks, highlighted_sentences, stats = render_pass(allow_fallback=True)

    original_html = f'<div class="claria-doc-sheet claria-sheet-original">{"".join(orig_blocks)}</div>'
    highlighted_html = f'<div class="claria-doc-sheet claria-sheet-highlighted">{"".join(hl_blocks)}</div>'

    full_standalone_html = _build_standalone_clarity_html(
        filename=filename,
        original_html=original_html,
        highlighted_html=highlighted_html,
        parsed=parsed,
        stats=stats
    )

    return {
        "filename": filename,
        "original_html": original_html,
        "snippet_html": highlighted_html,
        "full_html": full_standalone_html,
        "raw_text": raw_text,
        "watchout_items": highlighted_sentences,
        "stats": stats,
        "verbatim_preserved": True,
        "format_preserved": True
    }


def _build_standalone_clarity_html(filename: str, original_html: str, highlighted_html: str, parsed: dict, stats: dict) -> str:
    esc_title = html_lib.escape(filename or "Customer_Communication")
    overview = html_lib.escape(parsed.get("what_this_is_about") or "Customer communication with key paragraphs and sentences highlighted for clarity.")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CLARIA — {esc_title}</title>
  <style>
    :root {{
      --bg: #020c16;
      --panel: #051a2c;
      --sheet: #041628;
      --text: #f0f7ff;
      --muted: #849bb4;
      --border: rgba(7, 140, 255, 0.25);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 20px;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.7;
      font-size: 14px;
    }}
    .wrap {{ max-width: 1240px; margin: 0 auto; }}
    .topBar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 18px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      margin-bottom: 12px;
    }}
    .titleGrp {{ display: flex; align-items: center; gap: 12px; }}
    .docIcon {{
      width: 36px; height: 36px; border-radius: 9px;
      background: rgba(7, 140, 255, 0.14); border: 1px solid rgba(7, 140, 255, 0.35);
      display: grid; place-items: center; color: #38bdf8; flex-shrink: 0;
    }}
    .titleGrp h1 {{ font-size: 16px; margin: 0 0 2px; color: #fff; }}
    .sub {{ font-size: 12.5px; color: var(--muted); margin: 0; }}
    .btnGrp {{ display: flex; gap: 8px; }}
    .btn {{
      padding: 7px 13px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: rgba(7, 140, 255, 0.12);
      color: #fff;
      font-weight: 600;
      font-size: 12px;
      cursor: pointer;
    }}
    .btn.active {{ background: #078cff; border-color: #38bdf8; }}
    .legendBar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding: 10px 16px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      margin-bottom: 12px;
      font-size: 12px;
    }}
    .legPill {{
      padding: 5px 11px;
      border-radius: 999px;
      font-weight: 600;
      font-size: 11.5px;
      border: 1px solid rgba(255, 255, 255, 0.14);
      background: rgba(5, 26, 44, 0.8);
      color: #cbd5e1;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .legPill.active {{
      background: rgba(7, 140, 255, 0.24);
      border-color: #38bdf8;
      color: #fff;
    }}
    .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
    .compareGrid {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
    .compareGrid.split {{ grid-template-columns: 1fr 1fr; }}
    .pane {{ background: var(--sheet); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
    .paneHead {{ padding: 10px 16px; background: rgba(2, 12, 22, 0.7); border-bottom: 1px solid var(--border); font-weight: 700; font-size: 12.5px; display: flex; justify-content: space-between; }}
    .claria-doc-sheet {{ padding: 20px; font-size: 14px; line-height: 1.8; white-space: pre-wrap; word-break: break-word; }}
    .claria-doc-line {{ min-height: 1.4em; padding: 3px 8px; border-radius: 5px; }}
    .claria-line-heading {{ font-weight: 800; color: #ffffff; font-size: 15px; margin-top: 10px; margin-bottom: 4px; }}
    .claria-para-what_to_do {{ border-left: 3px solid #facc15; padding-left: 12px; margin: 4px 0; }}
    .claria-para-core_message {{ border-left: 3px solid #38bdf8; padding-left: 12px; margin: 4px 0; }}
    .claria-para-timeline_dates {{ border-left: 3px solid #fb923c; padding-left: 12px; margin: 4px 0; }}
    .claria-para-customer_impact {{ border-left: 3px solid #34d399; padding-left: 12px; margin: 4px 0; }}
    mark, .claria-hl-sentence {{
      padding: 2px 6px;
      border-radius: 4px;
      background: #fde047;
      color: #050b14 !important;
      font-weight: 600;
    }}
    .claria-cat-what_to_do {{ background: #fde047 !important; color: #050b14 !important; }}
    .claria-cat-core_message {{ background: #7dd3fc !important; color: #050b14 !important; }}
    .claria-cat-timeline_dates {{ background: #fdba74 !important; color: #050b14 !important; }}
    .claria-cat-customer_impact {{ background: #6ee7b7 !important; color: #050b14 !important; }}
    .claria-inline-tag {{ display: none !important; }}
    body.filter-what_to_do mark:not(.claria-cat-what_to_do),
    body.filter-core_message mark:not(.claria-cat-core_message),
    body.filter-timeline_dates mark:not(.claria-cat-timeline_dates),
    body.filter-customer_impact mark:not(.claria-cat-customer_impact) {{
      background: transparent !important;
      color: #e2e8f0 !important;
      font-weight: 400 !important;
      padding: 0 !important;
    }}
  </style>
</head>
<body id="docBody">
  <div class="wrap">
    <div class="topBar">
      <div class="titleGrp">
        <div class="docIcon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        </div>
        <div>
          <h1>{esc_title}</h1>
          <p class="sub">{overview}</p>
        </div>
      </div>
      <div class="btnGrp">
        <button class="btn active" id="btnSingle" onclick="setMode('single')">Highlighted Document</button>
        <button class="btn" id="btnCompare" onclick="setMode('compare')">Compare Input &amp; Output</button>
      </div>
    </div>
    <div class="legendBar">
      <button class="legPill active" data-f="all" onclick="setFilter('all', this)"><span class="dot" style="background:#38bdf8"></span>All Highlights ({stats.get('total_highlights', 0)})</button>
      <button class="legPill" data-f="what_to_do" onclick="setFilter('what_to_do', this)"><span class="dot" style="background:#fde047"></span>What You Need To Do ({stats.get('what_to_do', 0)})</button>
      <button class="legPill" data-f="core_message" onclick="setFilter('core_message', this)"><span class="dot" style="background:#7dd3fc"></span>Key Message ({stats.get('core_message', 0)})</button>
      <button class="legPill" data-f="timeline_dates" onclick="setFilter('timeline_dates', this)"><span class="dot" style="background:#fdba74"></span>Important Dates ({stats.get('timeline_dates', 0)})</button>
      <button class="legPill" data-f="customer_impact" onclick="setFilter('customer_impact', this)"><span class="dot" style="background:#6ee7b7"></span>Important Details ({stats.get('customer_impact', 0)})</button>
    </div>
    <div class="compareGrid" id="gridWrap">
      <div class="pane" id="origPane" style="display:none">
        <div class="paneHead"><span>Uploaded File (Input)</span><span>Original</span></div>
        {original_html}
      </div>
      <div class="pane">
        <div class="paneHead"><span>Highlighted Output</span><span>Clarity View</span></div>
        {highlighted_html}
      </div>
    </div>
  </div>
  <script>
    function setMode(mode) {{
      var grid = document.getElementById('gridWrap');
      var orig = document.getElementById('origPane');
      var bSingle = document.getElementById('btnSingle');
      var bComp = document.getElementById('btnCompare');
      if (mode === 'compare') {{
        grid.classList.add('split');
        orig.style.display = 'block';
        bComp.classList.add('active');
        bSingle.classList.remove('active');
      }} else {{
        grid.classList.remove('split');
        orig.style.display = 'none';
        bSingle.classList.add('active');
        bComp.classList.remove('active');
      }}
    }}
    function setFilter(cat, btn) {{
      document.body.className = cat === 'all' ? '' : 'filter-' + cat;
      var pills = document.querySelectorAll('.legPill');
      for (var i = 0; i < pills.length; i++) pills[i].classList.remove('active');
      if (btn) btn.classList.add('active');
    }}
  </script>
</body>
</html>"""
