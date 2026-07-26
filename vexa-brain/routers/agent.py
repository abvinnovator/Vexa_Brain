"""
Agent Router — CRUD endpoints for saved agents.

Saved agents are reusable automation step sequences that
can be replayed without AI calls.
"""

from fastapi import APIRouter, HTTPException
from models.request_models import (
    SaveAgentRequest, SaveAgentResponse,
    SavedAgent, AgentListResponse,
    AgentMatchRequest, AgentMatchResponse,
    ActionStep,
)
from services import mongodb_service
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/agent/save", response_model=SaveAgentResponse)
async def save_agent(request: SaveAgentRequest):
    """Save a new agent (reusable automation sequence).

    Called by the Android app after the user confirms they want to
    save a successfully-executed step sequence.
    """
    logger.info(f"Saving agent '{request.agentName}' for user={request.userId}")

    try:
        steps_dicts = [step.model_dump() for step in request.steps]

        agent_id = await mongodb_service.save_agent(
            user_id=request.userId,
            agent_name=request.agentName,
            trigger_prompt=request.triggerPrompt,
            intent=request.intent,
            steps=steps_dicts,
        )
        return SaveAgentResponse(
            agentId=agent_id,
            message=f"Agent '{request.agentName}' saved successfully!"
        )
    except Exception as e:
        logger.error(f"Failed to save agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent/list/{userId}", response_model=AgentListResponse)
async def list_agents(userId: str):
    """List all saved agents for a user."""
    logger.info(f"Listing agents for user={userId}")

    agents_raw = await mongodb_service.get_agents(userId)

    agents = []
    for a in agents_raw:
        steps = [
            ActionStep(
                step=s.get("step", i + 1),
                type=s.get("type", "UNKNOWN"),
                params=s.get("params", {}),
                description=s.get("description", ""),
                requiresConfirmation=s.get("requiresConfirmation", False),
            )
            for i, s in enumerate(a.get("steps", []))
        ]
        agents.append(SavedAgent(
            agentId=a["agentId"],
            agentName=a.get("agentName", "Unnamed"),
            triggerPrompt=a.get("triggerPrompt", ""),
            intent=a.get("intent", ""),
            steps=steps,
            usageCount=a.get("usageCount", 0),
            createdAt=a.get("createdAt", ""),
            lastUsedAt=a.get("lastUsedAt", ""),
        ))

    return AgentListResponse(agents=agents)


@router.post("/agent/match", response_model=AgentMatchResponse)
async def match_agent(request: AgentMatchRequest):
    """Find a saved agent matching the given prompt.

    Called by the Android app before asking AI, to check if
    a saved agent can handle this task directly.
    """
    logger.info(f"Matching agent for user={request.userId}, prompt='{request.prompt[:50]}'")

    matched = await mongodb_service.match_agent(request.userId, request.prompt)

    if matched:
        steps = [
            ActionStep(
                step=s.get("step", i + 1),
                type=s.get("type", "UNKNOWN"),
                params=s.get("params", {}),
                description=s.get("description", ""),
                requiresConfirmation=s.get("requiresConfirmation", False),
            )
            for i, s in enumerate(matched.get("steps", []))
        ]

        # Track usage
        await mongodb_service.update_agent_usage(matched["agentId"])

        agent = SavedAgent(
            agentId=matched["agentId"],
            agentName=matched.get("agentName", ""),
            triggerPrompt=matched.get("triggerPrompt", ""),
            intent=matched.get("intent", ""),
            steps=steps,
            usageCount=matched.get("usageCount", 0) + 1,
            createdAt=matched.get("createdAt", ""),
            lastUsedAt=matched.get("lastUsedAt", ""),
        )

        logger.info(f"Agent match found: '{agent.agentName}' (id={agent.agentId})")
        return AgentMatchResponse(found=True, agent=agent)

    logger.info("No matching agent found")
    return AgentMatchResponse(found=False)


@router.delete("/agent/{agentId}")
async def delete_agent(agentId: str):
    """Delete a saved agent by ID."""
    logger.info(f"Deleting agent: {agentId}")

    deleted = await mongodb_service.delete_agent(agentId)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {"message": "Agent deleted", "agentId": agentId}
