from services import llm_service
from models.request_models import NextActionRequest, NextActionResponse, ActionStep
import json
import logging
import re

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Vexa Interactive Agent controlling an Android phone.
Given GOAL, PLANNED ACTIONS, PREVIOUS ACTION, and SCREEN SNAPSHOT, output the SINGLE best NEXT ACTION as JSON:

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
1. ONLY tap elements that are PRESENT in the SCREEN SNAPSHOT clickableElements list. If an element is NOT in clickableElements, do NOT try to tap it.
2. If the required app is not open (snapshot shows a different app or home screen), first action must be OPEN_APP.
3. If snapshot is empty or has no useful elements, output WAIT.
4. If action type is "DONE", always set "isDone": true.

TYPE_TEXT CONTENT RULE (VERY IMPORTANT):
- If PLANNED ACTIONS contain a TYPE_TEXT step with specific text content, you MUST use EXACTLY that text. Do NOT invent, rephrase, summarize, or hallucinate your own text.
- If PLANNED CONTENT is provided, use it as the TYPE_TEXT content for any text composition step (e.g., writing a post, composing a message).
- NEVER generate your own version of content that was already planned. Copy the planned text EXACTLY.

CONFIRMATION REQUIRED — MUST output WAIT_FOR_USER BEFORE these actions:
- Publishing or submitting social media posts (LinkedIn Post, Tweet, Instagram Post, etc.)
- Sending emails or messages to contacts
- Making payments, purchases, or money transfers
- Confirming bookings or reservations
- Deleting content permanently
- Any action that CANNOT be easily undone
When outputting WAIT_FOR_USER for confirmation, set "requiresUserConfirmation": true and include a clear message explaining what will happen next.

UNEXPECTED SCREEN HANDLING:
- If a bottom sheet, popup, dialog, or overlay appears that was NOT expected (not part of the PLANNED ACTIONS), try PRESS_BACK to dismiss it first.
- If you see a settings screen, permission dialog, or any screen unrelated to the goal, use PRESS_BACK.
- Only interact with unexpected screens if they are directly blocking the goal and PRESS_BACK won't work.

TASK COMPLETION — output "isDone": true with DONE when:
- The goal has been fully accomplished (message sent, post published after confirmation, search completed, app opened, etc.)
- The PREVIOUS action was the final step in the plan and it succeeded.
- WAIT_FOR_USER was shown and the user confirmed, AND the final action (like posting) has been executed successfully.

NO REPETITION:
- NEVER repeat the exact same action (same type + same params) if the PREVIOUS action succeeded.
- If TYPE_TEXT succeeded, move to the next step — do NOT type again.
- If TAP_ELEMENT succeeded, move to the next step — do NOT tap the same element.

STEP LIMIT:
- You are given a step number. If you have exceeded the maximum allowed steps, you MUST output DONE or WAIT_FOR_USER to stop. Do not continue indefinitely.

For payment/OTP steps, always output WAIT_FOR_USER."""


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


def _extract_planned_type_text(planned_actions: list) -> str:
    """Extract the TYPE_TEXT content from the planner's action steps."""
    if not planned_actions:
        return ""
    for action in planned_actions:
        if action.get("type") == "TYPE_TEXT":
            params = action.get("params", {})
            return params.get("text", "")
    return ""


def _format_planned_actions(planned_actions: list) -> str:
    """Format planner's action steps as a compact summary for the interactive agent."""
    if not planned_actions:
        return "No planned actions provided."
    
    lines = []
    for action in planned_actions:
        step = action.get("step", "?")
        action_type = action.get("type", "?")
        desc = action.get("description", "")
        needs_confirm = action.get("requiresConfirmation", False)
        
        line = f"  Step {step}: {action_type} — {desc}"
        if needs_confirm:
            line += " [NEEDS USER CONFIRMATION]"
        
        # For TYPE_TEXT, include the content so the interactive agent can reference it
        if action_type == "TYPE_TEXT":
            text_content = action.get("params", {}).get("text", "")
            if text_content:
                # Truncate for prompt space but keep enough to be useful
                preview = text_content[:200] + "..." if len(text_content) > 200 else text_content
                line += f"\n    Content: \"{preview}\""
        
        lines.append(line)
    
    return "\n".join(lines)


def _is_confirmation_step(planned_actions: list, current_step_type: str, current_params: dict) -> bool:
    """Check if the current action matches a planned step that requires confirmation."""
    if not planned_actions:
        return False
    
    for action in planned_actions:
        if action.get("requiresConfirmation", False):
            # Check if this is the step right before a confirmation-required step
            if action.get("type") == current_step_type:
                return True
    
    return False


def _is_publishing_action(action_type: str, action_params: dict, action_desc: str) -> bool:
    """Detect if an action is a publishing/submitting action that needs confirmation."""
    desc_lower = (action_desc or "").lower()
    text_lower = str(action_params.get("text", "")).lower()
    
    # Check for publishing-related tap actions
    publishing_keywords = [
        "post", "publish", "submit", "send", "tweet", "share",
        "confirm", "place order", "pay", "purchase", "delete"
    ]
    
    if action_type == "TAP_ELEMENT":
        for kw in publishing_keywords:
            if kw in text_lower or kw in desc_lower:
                return True
    
    return False


async def get_next_action(request: NextActionRequest, step_number: int) -> NextActionResponse:
    # ── Step limit enforcement ──
    current_step = request.stepNumber or step_number
    max_steps = request.maxSteps or 15
    
    if current_step > max_steps:
        logger.warning(f"InteractiveAgent: Step limit reached ({current_step}/{max_steps}). Aborting automation.")
        return NextActionResponse(
            action=ActionStep(
                step=current_step,
                type="DONE",
                params={},
                description=f"Automation stopped: step limit ({max_steps}) reached. The task may be partially complete.",
                requiresConfirmation=False
            ),
            isDone=True,
            requiresUserConfirmation=False
        )
    
    snapshot_json = _format_snapshot(request.snapshot)
    
    # ── Build planned actions context ──
    planned_actions_text = _format_planned_actions(request.plannedActions or [])
    
    # ── Extract planned TYPE_TEXT content ──
    planned_type_text = _extract_planned_type_text(request.plannedActions or [])
    planned_content = request.plannedContent or planned_type_text or ""
    
    # ── Build the prompt with full context ──
    prompt_parts = [f"GOAL: {request.goal}"]
    
    prompt_parts.append(f"PLANNED ACTIONS (from planner — follow this sequence):\n{planned_actions_text}")
    
    if planned_content:
        prompt_parts.append(f"PLANNED CONTENT (use this EXACT text for TYPE_TEXT, do NOT make up your own):\n\"{planned_content}\"")
    
    prompt_parts.append(f"STEP: {current_step} of {max_steps} max")
    prompt_parts.append(f"PREVIOUS: {request.previousAction or 'None'}")
    prompt_parts.append(f"SNAPSHOT: {snapshot_json}")
    prompt_parts.append("What is the next action?")
    
    prompt = "\n".join(prompt_parts)

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
        action_params = action_data.get("params", {})
        action_desc = action_data.get("description", "")

        # Auto-detect DONE action type
        if action_type == "DONE":
            is_done = True

        # ── SAFETY: Force confirmation for publishing/destructive actions ──
        if not is_done and action_type != "DONE" and action_type != "WAIT_FOR_USER":
            if _is_publishing_action(action_type, action_params, action_desc):
                logger.info(f"InteractiveAgent: Detected publishing action '{action_desc}'. Forcing WAIT_FOR_USER confirmation.")
                return NextActionResponse(
                    action=ActionStep(
                        step=current_step,
                        type="WAIT_FOR_USER",
                        params={"message": f"Ready to proceed? Next action: {action_desc}. Confirm to continue."},
                        description=f"Confirmation required before: {action_desc}",
                        requiresConfirmation=True
                    ),
                    isDone=False,
                    requiresUserConfirmation=True
                )
        
        # ── SAFETY: Enforce planned TYPE_TEXT content ──
        if action_type == "TYPE_TEXT" and planned_content:
            current_text = action_params.get("text", "")
            # If the LLM hallucinated different text, override with planned content
            if current_text and current_text != planned_content:
                # Check if it's substantially different (not just whitespace/formatting)
                if _texts_are_substantially_different(current_text, planned_content):
                    logger.warning(f"InteractiveAgent: TYPE_TEXT content differs from plan. Overriding with planned content.")
                    logger.warning(f"  LLM wanted: {current_text[:100]}...")
                    logger.warning(f"  Plan has:   {planned_content[:100]}...")
                    action_params["text"] = planned_content
        
        # ── Safety Loop Prevention: Check if previous action succeeded for a messaging reply goal ──
        prev_act = (request.previousAction or "").lower()
        goal_lower = (request.goal or "").lower()

        if "success" in prev_act and ("type_text" in prev_act or "send" in prev_act):
            if any(kw in goal_lower for kw in ["reply", "send a reply", "message dad", "text", "reply hi"]):
                logger.info("InteractiveAgent: Messaging reply already executed in previous step. Auto-completing task.")
                is_done = True

        # Goal Verification for Search Tasks:
        if "search" in goal_lower:
            # Check if query was specified in goal
            search_match = re.search(r'search\s+(?:for\s+)?["\x27]?([^"\x27]+)["\x27]?', goal_lower)
            target_query = search_match.group(1).strip() if search_match else ""

            if target_query:
                typed_in_prev = target_query in prev_act
                typed_in_curr = action_type == "TYPE_TEXT" and target_query in str(action_params).lower()
                if not (typed_in_prev or typed_in_curr) and is_done and action_type != "DONE":
                    logger.info(f"InteractiveAgent: Search query '{target_query}' not executed yet. Continuing automation.")
                    is_done = False

        # ── Build the response ──
        action_step = None
        if not is_done and action_type != "DONE":
            action_step = ActionStep(
                step=current_step,
                type=action_type,
                params=action_params,
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


def _texts_are_substantially_different(text_a: str, text_b: str) -> bool:
    """Check if two texts are substantially different (not just formatting changes)."""
    # Normalize both texts: strip whitespace, lowercase, remove special chars
    def normalize(t):
        t = t.lower().strip()
        t = re.sub(r'[^a-z0-9\s]', '', t)
        t = re.sub(r'\s+', ' ', t)
        return t
    
    norm_a = normalize(text_a)
    norm_b = normalize(text_b)
    
    if norm_a == norm_b:
        return False
    
    # Check word overlap — if less than 50% of words overlap, they're substantially different
    words_a = set(norm_a.split())
    words_b = set(norm_b.split())
    
    if not words_a or not words_b:
        return True
    
    overlap = words_a.intersection(words_b)
    smaller_set = min(len(words_a), len(words_b))
    
    if smaller_set == 0:
        return True
    
    overlap_ratio = len(overlap) / smaller_set
    return overlap_ratio < 0.5  # Less than 50% overlap = substantially different
