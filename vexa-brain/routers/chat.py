import uuid
import asyncio
from fastapi import APIRouter, HTTPException
from models.request_models import ChatRequest, ChatResponse, ActionPlan, ActionStep, VexaMemory
from agents import memory_agent, planner_agent
from services import learning_service
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main Vexa Brain endpoint.
    
    Flow:
      1. Build VexaMemory from request
      2. MemoryAgent enriches with:
         - MongoDB behavioral context (UNCHANGED)
         - OKF knowledge retrieval (NEW)
         - Personality prompt (NEW)
      3. PlannerAgent generates intent + action plan from LLM
      4. Return structured ChatResponse to Android app
      5. Post-conversation learning (async, non-blocking) (NEW)
    """
    logger.info(f"Chat request from user={request.userId}: {request.prompt[:60]}...")

    # Initialise shared memory
    memory = VexaMemory(
        user_id=request.userId,
        raw_prompt=request.prompt,
        conversation_history=request.conversationHistory or []
    )

    # --- Agent Pipeline ---
    memory = await memory_agent.enrich(memory)   # Step 1: build context (behavioral + OKF + personality)
    memory = await planner_agent.plan(memory)    # Step 2: plan + format action steps

    if memory.error and not memory.action_steps:
        # Non-fatal error — return conversational reply
        return ChatResponse(
            reply=memory.reply or "Something went wrong. Please try again.",
            isAction=False,
            error=memory.error
        )

    # Build ActionPlan if there are steps
    action_plan = None
    if memory.action_steps:
        steps = []
        has_confirmation = False

        for raw_step in memory.action_steps:
            needs_confirm = raw_step.get("requiresConfirmation", False)
            if needs_confirm:
                has_confirmation = True
            steps.append(ActionStep(
                step=raw_step.get("step", len(steps) + 1),
                type=raw_step.get("type", "UNKNOWN"),
                params=raw_step.get("params", {}),
                description=raw_step.get("description", ""),
                requiresConfirmation=needs_confirm
            ))

        action_plan = ActionPlan(
            planId=str(uuid.uuid4()),
            userPrompt=request.prompt,
            intent=memory.intent,
            confidence=memory.confidence,
            actions=steps,
            requiresUserConfirmation=has_confirmation
        )

    # --- Post-conversation Learning (async, non-blocking) ---
    # Fire-and-forget: learn from this conversation turn without blocking the response
    asyncio.create_task(
        _learn_from_conversation(request.prompt, memory.reply, memory.intent)
    )

    return ChatResponse(
        reply=memory.reply,
        actionPlan=action_plan,
        isAction=action_plan is not None
    )


async def _learn_from_conversation(user_prompt: str, bot_reply: str, intent: str):
    """Background task: extract and store new knowledge from this conversation."""
    try:
        await learning_service.process_conversation(user_prompt, bot_reply, intent)
    except Exception as e:
        # Learning should NEVER crash — log and move on
        logger.error(f"Post-conversation learning error: {e}")


@router.get("/health")
async def health():
    return {"status": "ok", "agent": "Vexa Brain"}
