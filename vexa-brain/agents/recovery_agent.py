from services import llm_service
from models.request_models import RecoveryRequest, RecoveryResponse, ActionStep
import json
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Vexa Recovery Agent.
The local deterministic executor was trying to execute a plan but got stuck.
Your job is to analyze the situation and suggest EXACTLY ONE recovery action to help it get unstuck, OR abort if it's completely unrecoverable.

RESPOND ONLY WITH VALID JSON in this format:
{
  "abort": false,
  "action": {
    "type": "TAP_ELEMENT | TYPE_TEXT | SCROLL_DOWN | PRESS_BACK | WAIT_FOR_USER | WAIT",
    "params": {},
    "description": "What this recovery step does"
  }
}

ACTION TYPE PARAMS:
- TAP_ELEMENT: { "text": "Exact text of the button/element to tap" }
- TYPE_TEXT: { "text": "Text to type into the currently focused field" }
- SCROLL_DOWN: { "times": 1 }
- PRESS_BACK: {}
- WAIT_FOR_USER: { "message": "Please confirm payment or details manually" }
- WAIT: { "durationMs": 3000 }

RULES:
1. NEVER HALLUCINATE: Only pick elements (buttons, fields, texts) that EXACTLY match what is provided in the CURRENT SCREEN SNAPSHOT.
2. If the screen is still a loading screen or completely empty, output a WAIT action.
3. If the user goal is already achieved, or it's completely unrecoverable (e.g. app crashed or requires manual login), set "abort": true.
"""

async def recover(request: RecoveryRequest) -> RecoveryResponse:
    snapshot_data = {
        "screenTexts": request.snapshot.screenTexts,
        "clickableElements": [{"text": e.text, "resourceId": e.resourceId} for e in request.snapshot.clickableElements],
        "editableFields": [{"hint": f.hint, "value": f.value} for f in request.snapshot.editableFields]
    }
    
    prompt = f"""
GOAL: {request.goal}
FAILED STEP: {request.failedStep.type} - {request.failedStep.description}
ERROR: {request.error}
RETRY COUNT: {request.retryCount}

CURRENT SCREEN SNAPSHOT:
{json.dumps(snapshot_data, indent=2)}

What is the single best recovery action to take?
"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    try:
        raw = await llm_service.chat(messages, json_mode=True)
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
