import uuid
import asyncio
from fastapi import APIRouter, HTTPException
from models.request_models import ChatRequest, ChatResponse, ActionPlan, ActionStep, VexaMemory
from agents import memory_agent, planner_agent
from services import learning_service, mongodb_service
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main Vexa Brain endpoint.

    Flow:
      1. Check if a saved agent matches this prompt (skip AI if found)
      2. Build VexaMemory from request
      3. MemoryAgent enriches with:
         - Saved agent context
         - OKF knowledge retrieval
         - Personality prompt
      4. PlannerAgent generates intent + action plan from LLM
      5. Return structured ChatResponse to Android app
      6. Post-conversation learning (async, non-blocking)
    """
    logger.info(f"Chat request from user={request.userId}: {request.prompt[:60]}...")

    # ── Check for saved agent match (bypass AI) ──
    try:
        matched_agent = await mongodb_service.match_agent(request.userId, request.prompt)
        if matched_agent:
            steps = [
                ActionStep(
                    step=s.get("step", i + 1),
                    type=s.get("type", "UNKNOWN"),
                    params=s.get("params", {}),
                    description=s.get("description", ""),
                    requiresConfirmation=s.get("requiresConfirmation", False),
                )
                for i, s in enumerate(matched_agent.get("steps", []))
            ]
            action_plan = ActionPlan(
                planId=str(uuid.uuid4()),
                userPrompt=request.prompt,
                intent=matched_agent.get("intent", "SAVED_AGENT"),
                confidence=1.0,
                actions=steps,
                requiresUserConfirmation=any(s.requiresConfirmation for s in steps),
            )
            agent_name = matched_agent.get("agentName", "Saved Agent")
            usage = matched_agent.get("usageCount", 0) + 1
            logger.info(f"Saved agent match: '{agent_name}' — skipping AI, returning {len(steps)} steps")
            return ChatResponse(
                reply=f"🔄 Using saved agent \"{agent_name}\" (used {usage} times). Executing directly — no AI needed!",
                actionPlan=action_plan,
                isAction=True,
                isSavedAgent=True,
            )
    except Exception as e:
        logger.error(f"Agent match check failed (continuing with AI): {e}")

    # ── No saved agent — use AI pipeline ──

    # Initialise shared memory
    memory = VexaMemory(
        user_id=request.userId,
        raw_prompt=request.prompt,
        conversation_history=request.conversationHistory or []
    )

    # --- Agent Pipeline ---
    memory = await memory_agent.enrich(memory)   # Step 1: build context (agent + OKF + personality)
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
