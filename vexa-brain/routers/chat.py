import uuid
from fastapi import APIRouter, HTTPException
from models.request_models import ChatRequest, ChatResponse, ActionPlan, ActionStep, VexaMemory
from agents import memory_agent, planner_agent
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main Vexa Brain endpoint.
    
    Flow:
      1. Build VexaMemory from request
      2. MemoryAgent enriches with MongoDB behavioral context
      3. PlannerAgent generates intent + action plan from LLM
      4. Return structured ChatResponse to Android app
    """
    logger.info(f"Chat request from user={request.userId}: {request.prompt[:60]}...")

    # Initialise shared memory
    memory = VexaMemory(
        user_id=request.userId,
        raw_prompt=request.prompt,
        conversation_history=request.conversationHistory or []
    )

    # --- Agent Pipeline ---
    memory = await memory_agent.enrich(memory)   # Step 1: build behavioral context
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

    return ChatResponse(
        reply=memory.reply,
        actionPlan=action_plan,
        isAction=action_plan is not None
    )


@router.get("/health")
async def health():
    return {"status": "ok", "agent": "Vexa Brain"}
