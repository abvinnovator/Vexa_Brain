from fastapi import APIRouter
from models.request_models import RecoveryRequest, RecoveryResponse, NextActionRequest, NextActionResponse
from agents import recovery_agent, interactive_agent
import logging
import time

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/action/recover", response_model=RecoveryResponse)
async def recover_action(request: RecoveryRequest):
    """
    AI Recovery Endpoint.
    Only called when the local deterministic executor exhausts its retries.
    Takes the failed state and provides a single recovery step.
    """
    logger.warning(f"Recovery requested for goal: '{request.goal}', failed at: '{request.failedStep.type}'")
    
    response = await recovery_agent.recover(request)
    
    if response.action:
        logger.info(f"Recovery action determined: {response.action.type} - {response.action.description}")
    else:
        logger.info(f"Recovery aborted or failed. Error: {response.error}")
        
    return response

@router.post("/action/next", response_model=NextActionResponse)
async def next_action(request: NextActionRequest):
    """
    Agentic Next Action Endpoint.
    Takes the overall goal and the current screen snapshot, and returns the next single action.
    Enforces step limits and passes planner context to the interactive agent.
    """
    step_num = request.stepNumber or 1
    max_steps = request.maxSteps or 15
    started = time.time()
    tag = f"[auto={request.automationId or '-'} step={request.stepId or step_num}]"
    lag = ""
    if request.snapshotTakenAtMs:
        # Device and server clocks may differ, so treat this as a hint, not a measurement
        lag = f" snapshot_age~{int(started * 1000) - request.snapshotTakenAtMs}ms"

    logger.info(f"{tag} Next action requested for goal: '{request.goal}' (step {step_num}/{max_steps}) "
                f"pkg={request.snapshot.packageName} activity={request.snapshot.activity}{lag}")

    # Step limit enforcement at router level
    if step_num > max_steps:
        logger.warning(f"{tag} Step limit exceeded ({step_num}/{max_steps}). Aborting automation.")
        response = NextActionResponse(
            isDone=True,
            error=f"Automation stopped: exceeded step limit of {max_steps}. Task may be partially complete."
        )
    else:
        response = await interactive_agent.get_next_action(request, step_number=step_num)

    server_ms = int((time.time() - started) * 1000)
    if response.isDone:
        logger.info(f"{tag} Agent determined goal is completed. ({server_ms}ms)")
    elif response.requiresUserConfirmation:
        logger.info(f"{tag} Agent requires user confirmation: {response.action.description if response.action else 'N/A'} ({server_ms}ms)")
    elif response.action:
        logger.info(f"{tag} Next action determined: {response.action.type} - {response.action.description} ({server_ms}ms)")
    else:
        logger.warning(f"{tag} Failed to determine next action: {response.error} ({server_ms}ms)")

    # Echo correlation fields so Android can reject a response that isn't for the step it is waiting on
    response.automationId = request.automationId
    response.stepId = request.stepId
    response.snapshotHash = request.snapshotHash
    response.serverMs = server_ms
    return response

from fastapi import Request

@router.post("/action/debug")
async def debug_action(request: Request):
    body = await request.body()
    print(f"\n--- DEBUG RAW BODY ---")
    print(f"Length: {len(body)}")
    print(f"Bytes: {body}")
    try:
        import json
        parsed = json.loads(body)
        print("Successfully parsed!")
    except Exception as e:
        print(f"Error parsing: {type(e)} - {e}")
    print(f"----------------------\n")
    return {"status": "received"}
