from fastapi import APIRouter
from models.request_models import RecoveryRequest, RecoveryResponse, NextActionRequest, NextActionResponse
from agents import recovery_agent, interactive_agent
import logging

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
    """
    logger.info(f"Next action requested for goal: '{request.goal}'")
    
    # We pass step_number=1 as it's not strictly necessary for the backend logic anymore
    response = await interactive_agent.get_next_action(request, step_number=1)
    
    if response.isDone:
        logger.info("Agent determined goal is completed.")
    elif response.action:
        logger.info(f"Next action determined: {response.action.type} - {response.action.description}")
    else:
        logger.warning(f"Failed to determine next action: {response.error}")
        
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
