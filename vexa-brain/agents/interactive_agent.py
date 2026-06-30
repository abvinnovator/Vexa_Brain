from services import llm_service
from models.request_models import NextActionRequest, NextActionResponse, ActionStep
import json
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Vexa Interactive Agent. You control an Android phone to complete a goal.
You are given the user's overall GOAL, the PREVIOUS ACTION you took, and the CURRENT SCREEN SNAPSHOT.
Your job is to decide the single best NEXT ACTION to take.

RESPOND ONLY WITH VALID JSON in this format:
{
  "isDone": false,
  "requiresUserConfirmation": false,
  "action": {
    "step": 1,
    "type": "TAP_ELEMENT | TAP_FIELD | TYPE_TEXT | SCROLL_DOWN | PRESS_BACK | WAIT_FOR_USER | WAIT | DONE",
    "params": {},
    "description": "What this step does"
  }
}

ACTION TYPE PARAMS:
- TAP_ELEMENT: { "text": "Exact text of the button/element to tap" }
- TAP_FIELD: { "fieldHint": "Hint or description of the field to tap" }
- TYPE_TEXT: { "text": "Text to type into the currently focused field" }
- SCROLL_DOWN: { "times": 1 }
- PRESS_BACK: {}
- WAIT: { "durationMs": 3000 }
- WAIT_FOR_USER: { "message": "Please confirm payment or details" }
- DONE: {}

RULES:
1. NEVER HALLUCINATE: You must ONLY pick elements (buttons, fields, texts) that EXACTLY match what is provided in the CURRENT SCREEN SNAPSHOT arrays. If a field or button is not in the snapshot, IT DOES NOT EXIST.
2. If the snapshot arrays (screenTexts, clickableElements, editableFields) are completely EMPTY, it means the app is still loading or rendering. You MUST output a WAIT action!
3. If the goal is fully completed, set "isDone": true and type "DONE".
4. If a payment, OTP, or final booking screen is reached, you MUST output WAIT_FOR_USER. Do not auto-execute payments.
"""

async def get_next_action(request: NextActionRequest, step_number: int) -> NextActionResponse:
    # Format the snapshot for the LLM
    snapshot_data = {
        "screenTexts": request.snapshot.screenTexts,
        "clickableElements": [{"text": e.text, "resourceId": e.resourceId} for e in request.snapshot.clickableElements],
        "editableFields": [{"hint": f.hint, "value": f.value} for f in request.snapshot.editableFields]
    }
    
    prompt = f"""
GOAL: {request.goal}
PREVIOUS ACTION: {request.previousAction or 'None (App just opened)'}

CURRENT SCREEN SNAPSHOT:
{json.dumps(snapshot_data, indent=2)}

What is the single best next action to take to progress towards the goal?
"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    try:
        raw = await llm_service.chat(messages, json_mode=True)
        data = json.loads(raw)
        
        is_done = data.get("isDone", False)
        requires_confirm = data.get("requiresUserConfirmation", False)
        action_data = data.get("action")
        
        action_step = None
        if action_data and action_data.get("type") != "DONE":
            action_step = ActionStep(
                step=step_number,
                type=action_data.get("type", "UNKNOWN"),
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
