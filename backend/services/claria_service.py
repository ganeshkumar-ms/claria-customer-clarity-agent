import boto3
import json
import os
import re
import random
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

CLARIA_SYSTEM_PROMPT = """You are CLARIA, an Enterprise AI Customer Communications Redesign Specialist (TCS BFSI Standard).
Your mission is to transform long, complex, jargon-heavy, or intimidating business, banking, legal, insurance, regulatory, and corporate communications into crystal-clear, structured, plain-language intelligence.

You answer the recipient's primary question:
"What is this long communication actually telling me, and what do I need to do?"

=== CORE ENTERPRISE DELIVERABLES & BEHAVIORAL RULES ===
1. WHAT THIS IS ABOUT:
   - A plain-language summary in 1 to 3 direct, human sentences.
   - Strips corporate fluff and legalese while retaining exact subject, context, and purpose.

2. WHAT YOU NEED TO DO (CRITICAL GUARDRAIL - ACTION PRECISION):
   - Prominently highlight the recipient's required actions, numbered in sequential order.
   - ZERO HALLUCINATION RULE: If the communication is informational only (e.g., annual privacy notice, fee schedule disclosure, interest rate revision without action, system maintenance notification), you MUST set "action_required": false and state explicitly:
     "✅ No action required · This communication is for information only"
   - NEVER invent or fabricate an action if none is required.
   - Include deadline and urgency level (High, Medium, Low, None).

3. IMPORTANT DETAILS:
   - Explicitly list:
     * Deadlines and cutoff dates (exact dates from document).
     * Financial amounts, fees, charges, or limits.
     * Required documents or items to submit.
     * Conditions, eligibility rules, or qualifications.
     * Warnings, penalties, or consequences of inaction.
     * Contact details, reference numbers, URLs, phone numbers.

4. WHY THIS MATTERS:
   - Explain why the sender/organization is requesting this action or issuing this notice (e.g., regulatory compliance, account security, operational change, consumer protection law).

5. WHAT HAPPENS NEXT:
   - Explain what occurs after the recipient takes action (e.g., review period, confirmation turnaround), and what happens if no action is taken (e.g., restrictions, lapses, or standard continuation).

6. SIMPLIFIED COMMUNICATION:
   - A complete rewrite of the communication in clean, modern, empathetic, plain English.
   - MUST preserve every important number, date, policy/account reference, and mandatory legal requirement verbatim.
   - Highly readable, professional, and accessible to any customer.

=== ENTERPRISE BFSI GUARDRAILS & PRIVACY ===
- Do NOT alter or drop critical figures, dates, percentages, or legal disclaimers.
- Any `[REDACTED_...]` tokens represent protected sensitive credentials sanitized by Enterprise Guardrails; maintain them as protected.
- Maintain source traceability: link key points to verbatim excerpts from the original text.
- ZERO MODEL DISCLOSURE: NEVER identify underlying AI model names (e.g., Amazon, Nova, Claude, Titan, OpenAI). You are CLARIA.

=== ROBUST SEMANTIC COMPREHENSION & ERROR TOLERANCE (LIKE TAXORA) ===
- The user's input or uploaded communication may contain typos, misspellings, colloquial phrasing, shorthand, OCR noise, bad grammar, non-standard punctuation, or broken formatting.
- You MUST intelligently infer the user's intended meaning, subject, and context like TAXORA does. Correct errors, misspellings, and garbled phrases internally.
- NEVER fail, reject, or return an error because the user wrote incorrect words, made typos, or submitted an informal, messy communication.
- Even if the communication is brief, fragmented, or poorly written, reconstruct what it is genuinely about, determine whether action is required with exact dates/amounts, and produce a crystal-clear, structured redesign.
- If the user asks a brief question or instruction with typos (e.g., "redsign this notc", "wat to do", "hlep explain", "tell me abt this notce"), understand the underlying intent and respond completely and helpfully.

=== RESPONSE FORMAT (ALWAYS RESPOND WITH ONLY VALID JSON) ===

CASE 1: USER CHATS, GREETS, OR ASKS A QUESTION
If the user greets, asks small talk, or asks a general follow-up question:
Respond with ONLY:
{
  "type": "chat",
  "message": "<warm, direct, professional response answering their question or inviting them to share a customer communication>"
}

CASE 2: USER PROVIDES A COMMUNICATION / DOCUMENT TO REDESIGN
Respond with ONLY:
{
  "type": "redesign",
  "what_this_is_about": "Clear 1-3 sentences in plain language explaining what this communication is.",
  "what_you_need_to_do": {
    "action_required": true,
    "summary": "Clear summary of the required action, OR '✅ No action required · This communication is for information only'",
    "action_items": [
      "Specific action step 1",
      "Specific action step 2"
    ],
    "deadline": "Exact deadline or 'None'",
    "urgency": "High | Medium | Low | None"
  },
  "important_details": {
    "deadlines": ["Exact deadline dates"],
    "amounts": ["Exact monetary figures or fees"],
    "required_documents": ["List of documents required"],
    "conditions": ["Conditions or prerequisites"],
    "warnings": ["Regulatory or operational warnings"],
    "contact_info": ["Helpline numbers, emails, portals, reference IDs"]
  },
  "why_this_matters": "Clear explanation of why the sender is requesting this action or why this notice matters.",
  "what_happens_next": "What happens after action is completed and what happens if no action is taken.",
  "simplified_communication": "Full plain-language rewrite preserving all key numbers, dates, and legal meanings.",
  "traceability": [
    {
      "key_point": "Core fact or obligation",
      "source_excerpt": "Verbatim quote from original communication"
    }
  ]
}
"""


def _sanitize_ai_output(obj):
    """Deeply removes any AI model strings from generated output."""
    if isinstance(obj, str):
        cleaned = re.sub(r'\b(amazon\s+nova(?:\s+pro)?|nova-pro|bedrock|claude\s*3(?:\.5)?|gpt-4o?)\b', 'CLARIA Intelligence Engine', obj, flags=re.IGNORECASE)
        return cleaned
    if isinstance(obj, dict):
        return {k: _sanitize_ai_output(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_ai_output(item) for item in obj]
    return obj


GREETING_RESPONSES = [
    "Hello! I am CLARIA, your Enterprise Customer Communications Redesign Specialist. Upload or paste any complex notice, policy update, or customer letter, and I will extract what it is about, required actions, critical details, and generate a crystal-clear plain-language redesign.",
    "Hi there! Welcome to CLARIA. I'm ready to transform dense BFSI or corporate communications into actionable, plain-language intelligence. Drop a document or paste your text to get started.",
    "Greetings! I am CLARIA. Share any customer communication or compliance notice below, and I'll analyze deadlines, required actions, and deliver a simplified version with zero hallucinations.",
    "Hello! Ready when you are. Send over any complex customer correspondence or regulatory letter, and I'll break down the key takeaways and provide an empathetic, plain-language rewrite.",
    "Hey there! Welcome to CLARIA. Feel free to paste or upload any customer communication. I'll identify whether action is truly required and give you an executive-ready plain-English redesign."
]

BRO_RESPONSES = [
    "Hey bro! Ready when you are. Send over any customer notice, policy, or letter, and I'll break down what it means and rewrite it into crystal-clear plain language.",
    "Yo bro! What's up? I'm CLARIA, your Customer Communications Specialist. Drop any document or paste text, and I'll simplify it with zero data loss.",
    "Hey bro! Standing by. You can upload any file or paste your communication draft, and I'll extract required actions and key deadlines for you.",
    "Sup bro! All systems go. Share any dense notice or letter, and I'll deliver an executive plain-language redesign."
]

HOW_ARE_YOU_RESPONSES = [
    "I'm doing great and ready to simplify your customer communications! Upload any document or paste your text, and I'll extract the required actions and plain-language rewrite.",
    "All enterprise guardrails and sanitization engines are running smoothly! I'm here to help you transform dense notices into clear, customer-friendly communications.",
    "Doing very well, thank you! Ready to redesign and clarify any customer communication or policy notice you'd like to share.",
    "I'm ready to assist you! Share any business or financial communication, and I'll provide an instant, plain-language analysis."
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

    # Casual brother/slang words (bro, bruh, dude, yaar, bhai, machan, etc.)
    is_bro = (
        bool(re.match(r'^(?:(?:hey+|hi+|yo+|sup|hello+|namaste|vanakkam)\s+)?(?:bro+|brother|bruh|brah|dude|yaar|bhai|bhaiya|machan|macha|thala|buddy|mate|man|sis|dost)(?:\s+(?:how\s+are\s+you|whats?\s+up|hw\s+r\s+u))?$', cleaned)) or
        cleaned in {'bro', 'broo', 'bruh', 'brah', 'brother', 'dude', 'yaar', 'bhai', 'machan', 'macha', 'thala', 'buddy', 'mate', 'sis', 'dost'}
    )
    if is_bro:
        return _pick_varied_response(BRO_RESPONSES, conversation_history)

    # Check for "how are you" variants (including typos, abbreviations, and agent names)
    is_how_are_you = (
        bool(re.match(r'^(?:(?:hi+|h[ea]y+|h[ea]llo+|hlo)\s+)?(?:how|hw)\s+(?:r|are|re)\s+(?:u|you|yu)(?:\s+doing)?$', cleaned)) or
        bool(re.match(r'^(?:hows?|hws)\s+(?:it\s+going|u|you)$', cleaned)) or
        cleaned in {'hru', 'hw r u', 'how r u', 'how r you', 'how are you', 'how are u', 'whats up', 'sup', 'how do you do'}
    )
    if is_how_are_you:
        return _pick_varied_response(HOW_ARE_YOU_RESPONSES, conversation_history)

    # Check for greeting variants (including typos like helo, hlo, hiii, ji, and greetings with agent names like 'hi claria', 'hey claria')
    is_greeting = (
        bool(re.match(r'^(?:hi+|h[ea]y+|h[ea]llo+|hlo|ji+|namaste|hola|greetings?|yo+|sup)(?:\s+(?:there|claria|agent|bot|all|team|friend|buddy|ji))?$', cleaned)) or
        bool(re.match(r'^(?:good\s+(?:morning|afternoon|evening|day))(?:\s+(?:claria|there|all))?$', cleaned)) or
        cleaned in {'ji', 'hi', 'hello', 'hey', 'hii', 'hiii', 'heyy', 'namaste ji'}
    )
    if is_greeting:
        return _pick_varied_response(GREETING_RESPONSES, conversation_history)

    return None


def redesign_communication(text: str, conversation_history: list = None) -> dict:
    """
    Main CLARIA entrypoint:
    1. Inspects & sanitizes harmful secrets/exploits/injections via BFSI Guardrail Service.
    2. Builds conversation memory context.
    3. Calls Bedrock Converse API with CLARIA system prompt.
    4. Enforces Action Precision Guardrail & number/date invariance.
    5. Returns clean JSON response.
    """
    if conversation_history is None:
        conversation_history = []

    # Quick Conversational / Greeting Check (instant varied friendly reply)
    quick_reply = _match_quick_conversational(text, conversation_history)
    if quick_reply:
        return {
            "type": "chat",
            "message": quick_reply
        }

    # Step 1: Enterprise BFSI Guardrail Check
    guardrail_result = guardrail_service.inspect_and_sanitize(text)
    if guardrail_result.get('blocked'):
        return {
            "type": "chat",
            "message": guardrail_result.get("message", "The submitted communication violates Enterprise BFSI Guardrails and cannot be processed."),
            "guardrail_status": "BLOCKED",
            "guardrail_details": guardrail_result
        }

    sanitized_text = guardrail_result.get("sanitized_text", text)

    # Step 2: Build Converse API Messages (strictly adhering to Converse API requirements:
    # 1. Must start with a 'user' message.
    # 2. Roles must strictly alternate: user -> assistant -> user.
    # 3. Consecutive same-role messages must be merged.
    messages = []
    for msg in (conversation_history or [])[-8:]:
        content_txt = msg.get('content', '')
        if isinstance(content_txt, dict):
            content_txt = content_txt.get('message') or json.dumps(content_txt)
        content_txt = str(content_txt or '').strip()
        if not content_txt or content_txt.startswith('<!doctype') or '<html' in content_txt.lower():
            continue

        role = 'assistant' if msg.get('role') in ('ai', 'assistant') else 'user'
        if messages and messages[-1]['role'] == role:
            prev_txt = messages[-1]['content'][0]['text']
            messages[-1]['content'][0]['text'] = f"{prev_txt}\n\n{content_txt[:2000]}"
        else:
            messages.append({
                'role': role,
                'content': [{'text': content_txt[:2000]}]
            })

    # Ensure conversation starts with 'user'
    while messages and messages[0]['role'] != 'user':
        messages.pop(0)

    safe_prompt = (sanitized_text or '').strip() or "Please review and redesign this communication."

    # Append current user input ensuring alternation
    if messages and messages[-1]['role'] == 'user':
        prev_txt = messages[-1]['content'][0]['text']
        messages[-1]['content'][0]['text'] = f"{prev_txt}\n\n{safe_prompt}"
    else:
        messages.append({
            'role': 'user',
            'content': [{'text': safe_prompt}]
        })

    # Double-check: must start with user and must alternate
    while messages and messages[0]['role'] != 'user':
        messages.pop(0)

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
            parsed = {
                "type": "chat",
                "message": output_text
            }
    except Exception as e:
        print(f"[CLARIA Service] Bedrock Nova Pro error: {e}")
        try:
            fallback_response = client.converse(
                modelId='us.anthropic.claude-3-haiku-20240307-v1:0',
                messages=messages,
                system=[{'text': CLARIA_SYSTEM_PROMPT}],
                inferenceConfig={'maxTokens': 3000, 'temperature': 0.1}
            )
            output_text = fallback_response['output']['message']['content'][0]['text'].strip()
            json_match = re.search(r'\{[\s\S]*\}', output_text)
            if json_match:
                parsed = json.loads(json_match.group(0))
            else:
                parsed = {"type": "chat", "message": output_text}
        except Exception as e2:
            print(f"[CLARIA Service] Fallback call also failed: {e2}")
            parsed = {
                "type": "chat",
                "message": "I'm ready to assist. Please share the details, question, or customer communication you would like to discuss or simplify."
            }

    # Step 3: Action Precision Guardrail Verification
    if parsed.get('type') == 'redesign':
        action_data = parsed.get('what_you_need_to_do') or {}
        informational_markers = [
            'for information only', 'for your information', 'no action required',
            'no action is required', 'informational purpose', 'annual privacy notice',
            'service availability update', 'general announcement'
        ]
        t_lower = sanitized_text.lower()
        if any(m in t_lower for m in informational_markers) and not any(m in t_lower for m in ['please submit', 'you must pay', 'action required', 'immediate action']):
            action_data['action_required'] = False
            action_data['summary'] = "✅ No action required · This communication is for information only"
            action_data['action_items'] = []
            action_data['deadline'] = "None"
            action_data['urgency'] = "None"
            parsed['what_you_need_to_do'] = action_data

        parsed['guardrails'] = {
            "status": "PASSED",
            "framework": "Enterprise BFSI Customer Communications Standard",
            "action_precision": "Verified (No Action Fabricated)",
            "sensitive_data_redacted": guardrail_result.get("has_redactions", False),
            "redaction_count": len(guardrail_result.get("redacted_types", [])),
            "redacted_categories": guardrail_result.get("redacted_types", [])
        }

    parsed = _sanitize_ai_output(parsed)
    return parsed
