from services import llm_service
from models.request_models import NextActionRequest, NextActionResponse, ActionStep
import json
import logging
import re

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Vexa Interactive Agent controlling an Android phone.
Given GOAL, PREVIOUS ACTION, and SCREEN SNAPSHOT, output the SINGLE best NEXT ACTION as JSON:

{
  "isDone": false,
  "requiresUserConfirmation": false,
  "action": {
    "step": 1,
    "type": "OPEN_APP|TAP_ELEMENT|TAP_FIELD|TYPE_TEXT|SCROLL_DOWN|PRESS_BACK|WAIT_FOR_USER|WAIT|DONE",
    "params": {},
    "description": "Short step summary"
  }
}

PARAMS FORMAT:
- OPEN_APP: {"packageName": "com.whatsapp"}  (Use exact package names: com.whatsapp, com.ubercab, etc.)
- TAP_ELEMENT: {"text": "Exact element text"}
- TAP_FIELD: {"fieldHint": "Hint or label"}
- TYPE_TEXT: {"text": "String to type"}
- SCROLL_DOWN: {"times": 1}
- PRESS_BACK: {}
- WAIT: {"durationMs": 3000}
- WAIT_FOR_USER: {"message": "Reason"}
- DONE: {}

CRITICAL RULES:
1. ONLY tap elements present in SCREEN SNAPSHOT.
2. If required app is not open, first action must be OPEN_APP.
3. If snapshot is empty, output WAIT.
4. TASK COMPLETION: If the goal was to send a message/reply on WhatsApp/SMS (e.g. "reply Hi", "send Tinnava to dad") and PREVIOUS action was TYPE_TEXT or TAP_ELEMENT (Send) which succeeded, OR if the message appears sent, YOU MUST OUTPUT "isDone": true and action type "DONE"!
5. NO REPETITION: NEVER repeat the exact same TYPE_TEXT or TAP_ELEMENT action if PREVIOUS action succeeded.
6. If action type is "DONE", always set "isDone": true.
7. For payment/OTP, output WAIT_FOR_USER."""


def _format_snapshot(snapshot) -> str:
    """Compact snapshot formatter: deduplicates, truncates long text, caps array sizes."""
    seen_texts = set()
    compact_texts = []
    for t in snapshot.screenTexts:
        clean = (t or "").strip()[:50]
        if clean and clean not in seen_texts:
            seen_texts.add(clean)
            compact_texts.append(clean)
        if len(compact_texts) >= 12:
            break

    seen_clickables = set()
    compact_clickables = []
    for c in snapshot.clickableElements:
        txt = (c.text or "").strip()[:50]
        if txt and txt not in seen_clickables:
            seen_clickables.add(txt)
            elem = {"text": txt}
            if c.resourceId:
                elem["resourceId"] = c.resourceId
            compact_clickables.append(elem)
        if len(compact_clickables) >= 12:
            break

    compact_editables = []
    for e in snapshot.editableFields:
        hint = (e.hint or "").strip()[:40]
        val = (e.value or "").strip()[:40] if e.value else None
        item = {"hint": hint}
        if val:
            item["value"] = val
        compact_editables.append(item)
        if len(compact_editables) >= 5:
            break

    return json.dumps({
        "screenTexts": compact_texts,
        "clickableElements": compact_clickables,
        "editableFields": compact_editables
    }, separators=(',', ':'))


def _clean_json_response(raw: str) -> str:
    """Clean markdown code blocks and trailing characters from LLM json response."""
    raw = raw.strip()
    if raw.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL | re.IGNORECASE)
        if match:
            raw = match.group(1)
        else:
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end+1]
        
    return raw


async def get_next_action(request: NextActionRequest, step_number: int) -> NextActionResponse:
    snapshot_json = _format_snapshot(request.snapshot)
    
    prompt = f"GOAL: {request.goal}\nPREVIOUS: {request.previousAction or 'None'}\nSNAPSHOT: {snapshot_json}\nWhat is the next action?"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    try:
        raw = await llm_service.chat(messages, max_tokens=512, json_mode=True, agent_name="interactive")
        cleaned_raw = _clean_json_response(raw)
        
        try:
            data = json.loads(cleaned_raw)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse interactive agent JSON: {e}. Raw: {raw}")
            raise ValueError(f"Invalid JSON returned by LLM: {str(e)}")
            
        is_done = data.get("isDone", False)
        requires_confirm = data.get("requiresUserConfirmation", False)
        action_data = data.get("action") or {}
        
        action_type = action_data.get("type", "UNKNOWN")

        # Auto-detect DONE action type
        if action_type == "DONE":
            is_done = True

        # Safety Loop Prevention: Check if previous action succeeded for a messaging reply goal
        prev_act = (request.previousAction or "").lower()
        if "success" in prev_act and ("type_text" in prev_act or "send" in prev_act or "tap_element" in prev_act):
            goal_lower = (request.goal or "").lower()
            if any(kw in goal_lower for kw in ["reply", "send", "message", "text", "whatsapp", "hi", "dad"]):
                logger.info("InteractiveAgent: Messaging reply already executed in previous step. Auto-completing task.")
                is_done = True

        action_step = None
        if not is_done and action_type != "DONE":
            action_step = ActionStep(
                step=step_number,
                type=action_type,
                params=action_data.get("params", {}),
                description=action_data.get("description", "Next step"),
                requiresConfirmation=requires_confirm
            )
            
        return NextActionResponse(
            action=action_step,
            isDone=is_done,
            requiresUserConfirmation=requires_confirm
        )
        
    except Exception as e:
        logger.error(f"InteractiveAgent error: {e}")
        return NextActionResponse(
            error=f"Failed to determine next action: {str(e)}",
            isDone=True
        )
