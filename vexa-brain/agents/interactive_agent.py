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
- OPEN_APP: {"packageName": "com.whatsapp"}  (Use exact package names: com.whatsapp, com.linkedin.android, com.ubercab, etc.)
- TAP_ELEMENT: {"text": "Exact element text"}
- TAP_FIELD: {"fieldHint": "Hint or label"}
- TYPE_TEXT: {"text": "String to type"}
- SCROLL_DOWN: {"times": 1}
- PRESS_BACK: {}
- WAIT: {"durationMs": 3000}
- WAIT_FOR_USER: {"message": "Reason"}
- QUERY_USER: {"question": "Question for user"}
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
- Match the text to the FIELD: a search box gets ONLY the search term (e.g. a contact name like "Vivek"), never a message, post or sentence. The message/post body goes ONLY into the chat/post composer.
- If an editable field has "focused": true, it is already active — TYPE_TEXT directly, do not tap it again.

COMPOSING A REPLY YOURSELF (when the goal asks to reply/respond based on someone's message and no PLANNED CONTENT exists):
1. Open the person's chat first (search their name, tap their chat).
2. Read their latest message(s) in SNAPSHOT screenTexts.
3. Write a short, natural reply (1-2 sentences, casual tone, same language they used) that actually responds to what they said. Never type your own status/assistant chatter like "Opening WhatsApp..." or "Ready to test".
4. Tap the message box if it is not focused, TYPE_TEXT the reply, then output WAIT_FOR_USER so the user can review before sending.

MULTI-STEP SOCIAL MEDIA POSTING (e.g. LinkedIn, Twitter, Instagram):
You must follow this exact multi-step progression — DO NOT skip any step:
1. Open App (OPEN_APP) — just opens the app, proceed immediately.
2. Find and tap the compose/post button (e.g., "Post 3 of 5", "Start a post", "tab_post", "share") — this is a NAVIGATION tap, NOT a publish action. Proceed immediately WITHOUT confirmation.
3. Once on the post composition screen, tap the text field first (TAP_FIELD) if needed, then TYPE_TEXT with the PLANNED CONTENT. Proceed immediately.
4. After typing is complete: output WAIT_FOR_USER with "requiresUserConfirmation": true to ask: "Post content is ready. Would you like to attach any images/videos before posting? Confirm to post now, or cancel to add attachments."
5. After user confirms: tap the final "Post" / "Share" / "Tweet" button. This is the ONLY publish action.
6. After the publish button tap succeeds: output DONE with "isDone": true.

CRITICAL DISTINCTIONS:
- Tapping "Post" or compose icon to OPEN the composer = NAVIGATION (no confirmation needed)
- Tapping "Post" or "Share" to SUBMIT/PUBLISH after content is typed = PUBLISHING (needs prior confirmation)
- How to tell the difference: if TYPE_TEXT has NOT been executed yet in the action history, then "Post" taps are NAVIGATION. If TYPE_TEXT HAS been executed, then "Post" taps are PUBLISHING.

CONFIRMATION RULES (STRICT):
- ONLY output WAIT_FOR_USER with requiresUserConfirmation=true in these cases:
  1. AFTER typing post content, BEFORE the final publish/submit tap
  2. Before any payment, purchase, or money transfer
  3. Before confirming a booking or reservation
  4. Before deleting content permanently
  5. Before sending OTP or entering sensitive credentials
- NEVER output WAIT_FOR_USER for:
  1. Opening apps
  2. Navigating to compose/post screens
  3. Tapping input fields
  4. Scrolling
  5. Any navigation that is NOT a final irreversible action

UNEXPECTED SCREEN HANDLING:
- If a bottom sheet, popup, dialog, or overlay appears that was NOT expected (not part of the PLANNED ACTIONS), try PRESS_BACK to dismiss it first.
- If you see a settings screen, permission dialog, or any screen unrelated to the goal, use PRESS_BACK.
- Only interact with unexpected screens if they are directly blocking the goal and PRESS_BACK won't work.

TASK COMPLETION — output "isDone": true with DONE when:
- The goal has been fully accomplished (message sent, post published after confirmation, search completed, app opened, etc.)
- The PREVIOUS action was the final step in the plan and it succeeded.
- WAIT_FOR_USER was shown and the user confirmed, AND the final action (like posting) has been executed successfully.

ACTION OUTCOMES (in PREVIOUS / RECENT ACTION HISTORY, reported by the phone after verifying the screen):
- "Success" = the action ran AND the screen changed.
- "No effect" = the action ran but the screen did NOT change. If the element is still clearly the right target, you may repeat the SAME tap ONCE — the phone retries it with a real touch. If it has no effect twice, pick a different element, SCROLL_DOWN, or PRESS_BACK.
- "Skipped" = the screen changed before your action could run, so it was not executed. Decide again from the new SNAPSHOT.
- "Failed" = the action could not be performed (e.g. element not found).
SNAPSHOT.packageName is the app in the foreground. A clickable with "selected": true is the tab/option that is ALREADY active — do not tap it to navigate there.

STRICT NO REPETITION & NO LOOPS:
- NEVER repeat the exact same action (same type + same params) if the PREVIOUS action succeeded.
- If an action FAILED or if PREVIOUS says "screen did not change" or contains "[LOOP ALERT]":
  Do NOT repeat that same action! You MUST adapt:
  1. If element not visible on screen, output SCROLL_DOWN or WAIT.
  2. If a popup/sheet is blocking, output PRESS_BACK.
  3. If another relevant element exists in clickableElements, try that element instead.
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
            if c.selected:
                elem["selected"] = True
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
        if getattr(e, "focused", None):
            item["focused"] = True
        compact_editables.append(item)
        if len(compact_editables) >= 5:
            break

    result = {}
    if getattr(snapshot, "packageName", None):
        result["packageName"] = snapshot.packageName
    if getattr(snapshot, "activity", None):
        result["activity"] = snapshot.activity.rsplit(".", 1)[-1]
    return json.dumps({
        **result,
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


# A TYPE_TEXT at least this long is a message/post body; shorter ones are search terms, names, etc.
BODY_MIN_CHARS = 40


def _planned_type_texts(planned_actions: list) -> list:
    """All TYPE_TEXT contents from the planner's action steps, in order."""
    texts = []
    for action in planned_actions or []:
        if action.get("type") == "TYPE_TEXT":
            text = (action.get("params") or {}).get("text") or ""
            if text.strip():
                texts.append(text)
    return texts


def _planned_body(planned_actions: list, client_planned_content: str = None) -> str:
    """The message/post body the planner drafted, if any.

    Only the plan's own TYPE_TEXT steps count. Older Android builds send the planner's *chat
    reply* ("On it, opening WhatsApp...") as plannedContent; that text must never be typed, so
    client content is accepted only when it is one of the plan's TYPE_TEXT texts.
    """
    texts = _planned_type_texts(planned_actions)
    if client_planned_content and client_planned_content in texts:
        return client_planned_content if len(client_planned_content) >= BODY_MIN_CHARS else ""
    bodies = [t for t in texts if len(t) >= BODY_MIN_CHARS]
    return bodies[0] if bodies else ""


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


def _successful_type_count(action_history: list) -> int:
    """How many TYPE_TEXT steps actually succeeded (history entries look like
    'TYPE_TEXT: <description> (Success — ...)')."""
    return sum(
        1 for h in (action_history or [])
        if h.upper().startswith("TYPE_TEXT") and "(success" in h.lower()
    )


def _has_typed_content(action_history: list, planned_actions: list, planned_body: str) -> bool:
    """Has the message/post BODY been typed yet? (Typing a search term or a name doesn't count.)

    - Plan drafted a body: every planned TYPE_TEXT up to and including the body has succeeded.
    - No drafted body (e.g. "reply based on his last message"): a TYPE_TEXT beyond the plan's
      short entries succeeded — that one is the agent-composed message.
    """
    typed = _successful_type_count(action_history)
    planned = _planned_type_texts(planned_actions)
    if planned_body:
        return typed >= planned.index(planned_body) + 1
    return typed >= len(planned) + 1


def _is_critical_confirmation_needed(action_type: str, action_params: dict, action_desc: str) -> bool:
    """Detect if an action requires mandatory confirmation (payments, OTP, bookings, deletion).
    
    This does NOT include social media posting — that is handled by context-aware logic.
    """
    desc_lower = (action_desc or "").lower()
    text_lower = str(action_params.get("text", "")).lower()
    combined = desc_lower + " " + text_lower
    
    # Critical actions that ALWAYS need confirmation regardless of context
    critical_keywords = [
        "pay", "payment", "purchase", "buy", "checkout",
        "place order", "confirm order", "complete purchase",
        "delete", "remove permanently",
        "confirm booking", "book now", "reserve",
        "otp", "verify", "enter code",
        "transfer", "send money"
    ]
    
    if action_type in ("TAP_ELEMENT", "TAP_FIELD"):
        for kw in critical_keywords:
            if kw in combined:
                return True
    
    return False


def _is_final_publish_action(action_type: str, action_params: dict, action_desc: str,
                              has_typed: bool) -> bool:
    """Detect if this action is the FINAL publish/submit tap (after content has been typed).
    
    Key distinction: Only returns True if content has already been typed.
    If content hasn't been typed yet, a "Post" tap is navigation, not publishing.
    """
    if not has_typed:
        return False  # Can't be a publish action if nothing has been typed
    
    if action_type != "TAP_ELEMENT":
        return False
    
    desc_lower = (action_desc or "").lower()
    text_lower = str(action_params.get("text", "")).lower()
    
    publishing_keywords = [
        "post", "publish", "submit", "send", "tweet", "share"
    ]
    
    # Check description for "final", "publish", "submit" indicators
    is_final_desc = any(kw in desc_lower for kw in ["final", "publish", "submit"])
    is_publish_text = any(kw in text_lower for kw in publishing_keywords)
    is_publish_desc = any(kw in desc_lower for kw in publishing_keywords)
    
    return is_publish_text or is_publish_desc or is_final_desc


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
    
    # ── Planned message/post body (only ever from the plan's own TYPE_TEXT steps) ──
    planned_content = _planned_body(request.plannedActions or [], request.plannedContent)
    goal_lower = (request.goal or "").lower()
    is_messaging_goal = any(kw in goal_lower for kw in ["reply", "message", "text ", "whatsapp", "telegram", "dm ", "chat with"])
    must_compose = not planned_content and any(kw in goal_lower for kw in ["reply", "respond", "message", "write", "comment"])

    # ── Derive execution state from history ──
    has_typed = _has_typed_content(request.actionHistory, request.plannedActions or [], planned_content)
    
    # ── Build the prompt with full context ──
    prompt_parts = [f"GOAL: {request.goal}"]
    
    prompt_parts.append(f"PLANNED ACTIONS (from planner — follow this sequence):\n{planned_actions_text}")
    
    if planned_content:
        prompt_parts.append(f"PLANNED CONTENT (the message/post body — type this EXACT text into the composer, never into a search field):\n\"{planned_content}\"")

    # Inject execution state so the LLM knows what has been done
    state_hints = []
    if planned_content or must_compose:
        if has_typed:
            state_hints.append("THE MESSAGE/POST BODY HAS BEEN TYPED — next step is confirmation, then the final send/publish tap")
        elif must_compose:
            state_hints.append("NO REPLY TEXT IS PLANNED — navigate to the right chat/thread, read the latest messages in SNAPSHOT, then compose the reply yourself and TYPE_TEXT it into the message box")
        else:
            state_hints.append("THE MESSAGE/POST BODY HAS NOT BEEN TYPED YET — navigate to the composer, then type the PLANNED CONTENT")
    if state_hints:
        prompt_parts.append(f"EXECUTION STATE: {'; '.join(state_hints)}")
    
    prompt_parts.append(f"STEP: {current_step} of {max_steps} max")
    prompt_parts.append(f"PREVIOUS: {request.previousAction or 'None'}")
    if request.actionHistory:
        history_lines = "\n".join([f"  - {h}" for h in request.actionHistory[-6:]])
        prompt_parts.append(f"RECENT ACTION HISTORY:\n{history_lines}")
    prompt_parts.append(f"SNAPSHOT: {snapshot_json}")
    prompt_parts.append("What is the next action?")
    
    prompt = "\n".join(prompt_parts)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    try:
        trace_metadata = {
            # thread_id groups every step of one automation into a single LangSmith thread
            "thread_id": request.automationId,
            "automation_id": request.automationId,
            "step_id": request.stepId,
            "step_number": current_step,
            "snapshot_hash": request.snapshotHash,
            "package": request.snapshot.packageName,
        }
        raw = await llm_service.chat(messages, max_tokens=512, json_mode=True, agent_name="interactive",
                                     metadata={k: v for k, v in trace_metadata.items() if v is not None})
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

        # ── SAFETY: Force confirmation for CRITICAL actions (payments, OTP, bookings, deletions) ──
        # These ALWAYS need confirmation regardless of context
        if not is_done and action_type != "DONE" and action_type != "WAIT_FOR_USER":
            if _is_critical_confirmation_needed(action_type, action_params, action_desc):
                logger.info(f"InteractiveAgent: Critical action detected '{action_desc}'. Forcing WAIT_FOR_USER.")
                return NextActionResponse(
                    action=ActionStep(
                        step=current_step,
                        type="WAIT_FOR_USER",
                        params={"message": f"This action requires your confirmation: {action_desc}. Confirm to proceed."},
                        description=f"Confirmation required: {action_desc}",
                        requiresConfirmation=True
                    ),
                    isDone=False,
                    requiresUserConfirmation=True
                )
        
        # ── SAFETY: Context-aware confirmation for PUBLISHING actions ──
        # Only trigger if content has been typed AND this is the final publish tap
        if not is_done and action_type != "DONE" and action_type != "WAIT_FOR_USER":
            if _is_final_publish_action(action_type, action_params, action_desc, has_typed):
                # Check if user has already confirmed in a previous step
                prev_lower = (request.previousAction or "").lower()
                already_confirmed = "user confirmed" in prev_lower or "wait_for_user" in prev_lower
                
                if not already_confirmed:
                    logger.info(f"InteractiveAgent: Final publish action detected after content typed. Requesting confirmation.")
                    confirm_msg = (
                        "Message is ready. Review it on screen — confirm to send, or cancel to edit it yourself."
                        if is_messaging_goal else
                        "Post content is ready. Would you like to add any images/videos before posting? Confirm to post now, or cancel to add attachments."
                    )
                    return NextActionResponse(
                        action=ActionStep(
                            step=current_step,
                            type="WAIT_FOR_USER",
                            params={"message": confirm_msg},
                            description="Confirm before publishing",
                            requiresConfirmation=True
                        ),
                        isDone=False,
                        requiresUserConfirmation=True
                    )
                else:
                    logger.info(f"InteractiveAgent: User already confirmed. Proceeding with publish action: {action_desc}")
        
        # ── SAFETY: Enforce planned TYPE_TEXT content ──
        # Only for body text: if the model is typing a long message/post that differs from the
        # drafted body, it hallucinated its own version. Short entries (search terms, contact
        # names) are never overridden — overriding those is what pasted the chat reply into
        # WhatsApp's search box.
        if action_type == "TYPE_TEXT" and planned_content:
            current_text = action_params.get("text", "")
            planned_short = set(_planned_type_texts(request.plannedActions or [])) - {planned_content}
            is_body_attempt = len(current_text) >= BODY_MIN_CHARS and current_text not in planned_short
            if is_body_attempt and current_text != planned_content:
                # Check if it's substantially different (not just whitespace/formatting)
                if _texts_are_substantially_different(current_text, planned_content):
                    logger.warning(f"InteractiveAgent: TYPE_TEXT content differs from plan. Overriding with planned content.")
                    logger.warning(f"  LLM wanted: {current_text[:100]}...")
                    logger.warning(f"  Plan has:   {planned_content[:100]}...")
                    action_params["text"] = planned_content

        # ── Safety Guard: Prevent Premature Completion for Social Posts / Publishing ──
        prev_act = (request.previousAction or "").lower()
        is_posting_goal = any(kw in goal_lower for kw in ["post", "publish", "share", "tweet", "linkedin"])

        if is_posting_goal and (is_done or action_type == "DONE"):
            if not has_typed and planned_content:
                logger.warning("InteractiveAgent: Premature DONE detected before post content was typed! Redirecting to post composition.")
                is_done = False
                # Check if current snapshot has editable fields (compose screen)
                if request.snapshot.editableFields:
                    action_type = "TYPE_TEXT"
                    action_params = {"text": planned_content}
                    action_desc = "Enter the post content into the composition field"
                elif any("post" in (c.text or "").lower() or "start" in (c.text or "").lower()
                         for c in request.snapshot.clickableElements):
                    post_elem = next(
                        (c.text for c in request.snapshot.clickableElements
                         if "post" in (c.text or "").lower() or "start" in (c.text or "").lower()),
                        "Post"
                    )
                    action_type = "TAP_ELEMENT"
                    action_params = {"text": post_elem}
                    action_desc = f"Tap '{post_elem}' to open post composer"
                else:
                    action_type = "WAIT"
                    action_params = {"durationMs": 2000}
                    action_desc = "Wait for post compose screen to load"
        
        # ── Messaging: the task is complete once the SEND tap succeeded ──
        # (Previously ANY successful TYPE_TEXT ended a "reply" task — e.g. typing a name into
        # the search box — so the reply was never written.)
        if is_messaging_goal and prev_act.startswith("tap_element") and "send" in prev_act and "(success" in prev_act:
            logger.info("InteractiveAgent: Send tap succeeded for a messaging goal. Auto-completing task.")
            is_done = True

        # Goal Verification for Search Tasks:
        if "search" in goal_lower:
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
                description=action_data.get("description", action_desc or "Next step"),
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
            isDone=False
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
