from services import llm_service
from models.request_models import VexaMemory
import json
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Vexa, a personal AI assistant that automates tasks on the user's Android phone.
Your owner is Brahma Vamsi (also called Vamsi). You serve ONLY him.

You have access to the user's phone behavior data AND his personal knowledge base.
Based on this data and the user's request, decide EXACTLY what the phone should do — step by step.

Your ONLY job in this step is to:
1. Detect the user's intent
2. Plan the exact steps the phone should take (the "Happy Path" full execution plan)
3. Mark which steps need user confirmation (payments, bookings, OTP)
4. Give a natural, personalized reply that sounds like YOU know him

{personality_instructions}

Respond ONLY with valid JSON in this exact format:
{{
  "intent": "BOOK_RIDE | ORDER_FOOD | OPEN_APP | SEARCH | CONVERSATION | OTHER",
  "confidence": 0.0-1.0,
  "reply": "Natural language reply to user (max 2 sentences)",
  "actions": [
    {{
      "step": 1,
      "type": "OPEN_APP | TAP_ELEMENT | TAP_FIELD | TYPE_TEXT | SCROLL_DOWN | PRESS_BACK | WAIT_FOR_SCREEN | WAIT_FOR_USER | QUERY_USER",
      "params": {{}},
      "description": "What this step does",
      "requiresConfirmation": false
    }},
    {{
      "step": 2,
      "type": "...",
      "params": {{}},
      "description": "..."
    }}
  ]
}}

ACTION TYPE PARAMS:
- OPEN_APP: {{ "packageName": "com.ubercab" }} 
  (CRITICAL: You MUST use the exact, correct Android package name for the app. Do not hallucinate or guess. 
   Examples: Zomato is "com.zomato.android", Blinkit is "com.grofers.customerapp", Swiggy is "in.swiggy.android", Uber is "com.ubercab".
   If you output a fake/incorrect package name like "com.application.zomato", the agent will fail and crash!)
- TAP_ELEMENT: {{ "text": "Book Now" }}
- TAP_FIELD: {{ "fieldHint": "Where to?", "resourceId": "optional" }}
- TYPE_TEXT: {{ "text": "text to type" }}
- WAIT_FOR_SCREEN: {{ "screenName": "ActivityName", "screenTitle": "Title" }}
- WAIT_FOR_USER: {{ "message": "Please confirm payment" }}
- QUERY_USER: {{ "question": "Which vehicle type do you prefer?" }}
- SCROLL_DOWN: {{ "times": 1 }}
- PRESS_BACK: {{}}

SAFETY RULES:
- NEVER auto-execute payments. Always add WAIT_FOR_USER before any payment step.
- NEVER auto-execute final booking confirmation. Add WAIT_FOR_USER before confirm.
- For OTP steps, always add WAIT_FOR_USER.
- Low-risk actions (OPEN_APP, TAP_ELEMENT, TYPE_TEXT, SCROLL_DOWN) do NOT need confirmation.

If the user is just chatting (not requesting an action), set "actions": [] and intent to "CONVERSATION".
"""


async def plan(memory: VexaMemory) -> VexaMemory:
    """
    PlannerAgent + ActionAgent combined:
    Uses behavioral context + OKF knowledge + personality to generate
    a structured action plan.

    UNCHANGED: The JSON response format and action step types are exactly the same.
    CHANGED: Now includes knowledge context and personality instructions for better responses.
    """
    # Build system prompt with personality
    personality = memory.personality_prompt or "Be casual, brief, and helpful."
    system_prompt = SYSTEM_PROMPT.format(personality_instructions=personality)

    # Build user message with all context layers
    user_content_parts = []

    if memory.behavioral_context:
        user_content_parts.append(f"BEHAVIORAL CONTEXT:\n{memory.behavioral_context}")

    if memory.knowledge_context:
        user_content_parts.append(f"USER KNOWLEDGE (from brain memory):\n{memory.knowledge_context}")

    if memory.communication_profile:
        user_content_parts.append(f"COMMUNICATION STYLE:\n{memory.communication_profile}")

    user_content_parts.append(f'USER REQUEST:\n"{memory.raw_prompt}"')

    user_message = "\n\n".join(user_content_parts)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    # Include conversation history for multi-turn context
    if memory.conversation_history:
        # Insert history between system and current user message
        messages = [messages[0]] + memory.conversation_history + [messages[1]]

    try:
        raw = await llm_service.chat(messages, json_mode=True)
        data = json.loads(raw)

        memory.intent     = data.get("intent", "CONVERSATION")
        memory.confidence = float(data.get("confidence", 0.5))
        memory.reply      = data.get("reply", "I'm here to help!")
        memory.action_steps = data.get("actions", [])

        logger.info(
            f"PlannerAgent: intent={memory.intent}, "
            f"confidence={memory.confidence:.2f}, "
            f"steps={len(memory.action_steps)}"
        )

    except Exception as e:
        logger.error(f"PlannerAgent error: {e}")
        memory.intent       = "CONVERSATION"
        memory.confidence   = 0.0
        memory.reply        = "Sorry, I had trouble understanding that. Could you rephrase?"
        memory.action_steps = []
        memory.error        = str(e)

    return memory
