from services import llm_service
from models.request_models import RecoveryRequest, RecoveryResponse, ActionStep
import json
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Vexa Recovery Agent.
An action step failed. Suggest ONE recovery action as JSON or abort:

{
  "abort": false,
  "action": {
    "type": "TAP_ELEMENT|TYPE_TEXT|SCROLL_DOWN|PRESS_BACK|WAIT_FOR_USER|WAIT",
    "params": {},
    "description": "Recovery action description"
  }
}

PARAMS:
- TAP_ELEMENT: {"text": "Exact text"}
- TYPE_TEXT: {"text": "Text"}
- SCROLL_DOWN: {"times": 1}
- PRESS_BACK: {}
- WAIT_FOR_USER: {"message": "Reason"}
- WAIT: {"durationMs": 3000}

RULES:
1. ONLY tap elements present in SCREEN SNAPSHOT.
2. If empty screen, output WAIT.
3. If unrecoverable, set "abort": true."""

def _format_snapshot(snapshot) -> str:
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

async def recover(request: RecoveryRequest) -> RecoveryResponse:
    snapshot_json = _format_snapshot(request.snapshot)
    
    prompt = f"GOAL: {request.goal}\nFAILED STEP: {request.failedStep.type} - {request.failedStep.description}\nERROR: {request.error}\nRETRY: {request.retryCount}\nSNAPSHOT: {snapshot_json}\nWhat is the recovery action?"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    try:
        raw = await llm_service.chat(messages, max_tokens=512, json_mode=True, agent_name="recovery")
        data = json.loads(raw)
        
        is_abort = data.get("abort", False)
        action_data = data.get("action")
        
        action_step = None
        if action_data and not is_abort:
            action_step = ActionStep(
                step=-1,  # Special marker for recovery steps
                type=action_data.get("type", "UNKNOWN"),
                params=action_data.get("params", {}),
                description=action_data.get("description", "Recovery step"),
                requiresConfirmation=action_data.get("type") == "WAIT_FOR_USER"
            )
            
        return RecoveryResponse(
            action=action_step,
            abort=is_abort
        )
        
    except Exception as e:
        logger.error(f"RecoveryAgent error: {e}")
        return RecoveryResponse(
            error=f"Failed to determine recovery action: {str(e)}",
            abort=True
        )

