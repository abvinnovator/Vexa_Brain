from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ChatRequest(BaseModel):
    userId: str
    prompt: str
    conversationHistory: Optional[List[Dict[str, str]]] = []  # [{role, content}]
    now: Optional[str] = None   # device local time, ISO with offset — the server clock is UTC


class ActionStep(BaseModel):
    step: int
    type: str           # SEND_EMAIL | CHECK_INBOX | ORG_ADD | ORG_UPDATE
    params: Dict[str, Any]
    description: str
    requiresConfirmation: bool = False  # true for payments, bookings


class ActionPlan(BaseModel):
    planId: str
    userPrompt: str
    intent: str
    confidence: float
    actions: List[ActionStep]
    requiresUserConfirmation: bool  # true if ANY step has payment/booking


class ChatResponse(BaseModel):
    reply: str                              # natural language reply to user
    actionPlan: Optional[ActionPlan] = None # None if just a conversation, not an action
    isAction: bool = False                  # true if actionPlan is present
    orgItems: List[Dict[str, Any]] = []     # Org items created/updated by this message (reminders etc.)
    error: Optional[str] = None


class VexaMemory(BaseModel):
    """Shared state passed between agents in the pipeline."""
    user_id: str
    raw_prompt: str
    user_now: Optional[str] = None      # device local time (ISO with offset)
    conversation_history: List[Dict[str, str]] = []
    behavioral_context: str = ""        # built by MemoryAgent
    knowledge_context: str = ""         # OKF-retrieved relevant knowledge
    communication_profile: str = ""     # user's speaking style/tone
    personality_prompt: str = ""        # dynamic personality instructions
    intent: str = "CONVERSATION"        # detected by PlannerAgent
    action_steps: List[Dict] = []       # built by ActionAgent
    reply: str = ""                     # natural language response
    confidence: float = 0.0
    error: Optional[str] = None
