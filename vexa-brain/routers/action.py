from fastapi import APIRouter
from models.request_models import RecoveryRequest, RecoveryResponse
from agents import recovery_agent
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
