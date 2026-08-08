from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ChatRequest(BaseModel):
    userId: str
    prompt: str
    conversationHistory: Optional[List[Dict[str, str]]] = []  # [{role, content}]


class ActionStep(BaseModel):
    step: int
    type: str           # OPEN_APP | TAP_ELEMENT | TAP_FIELD | TYPE_TEXT | SCROLL_DOWN |
                        # PRESS_BACK | WAIT_FOR_SCREEN | WAIT_FOR_USER | QUERY_USER
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
    isSavedAgent: bool = False              # true if response came from a saved agent (no AI)
    error: Optional[str] = None


class VexaMemory(BaseModel):
    """Shared state passed between agents in the pipeline."""
    user_id: str
    raw_prompt: str
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

# ── Interactive Execution Loop Models ──

class ClickableElement(BaseModel):
    text: str
    resourceId: Optional[str] = None

class EditableField(BaseModel):
    hint: str
    value: Optional[str] = None

class ScreenSnapshot(BaseModel):
    screenTexts: List[str] = []
    clickableElements: List[ClickableElement] = []
    editableFields: List[EditableField] = []

class RecoveryRequest(BaseModel):
    userId: str
    goal: str
    snapshot: ScreenSnapshot
    failedStep: ActionStep
    retryCount: int
    error: str

class RecoveryResponse(BaseModel):
    action: Optional[ActionStep] = None  # The single recovery step
    abort: bool = False                  # True if unrecoverable
    error: Optional[str] = None

# ── Interactive Agent Models ──

class NextActionRequest(BaseModel):
    userId: str
    goal: str
    snapshot: ScreenSnapshot
    previousAction: Optional[str] = None
    plannedActions: Optional[List[Dict[str, Any]]] = None   # Planner's original action steps
    plannedContent: Optional[str] = None                     # Planner's drafted text (reply) for TYPE_TEXT
    stepNumber: Optional[int] = 1                            # Current execution step count
    maxSteps: Optional[int] = 15                             # Safety limit — abort after this many steps

class NextActionResponse(BaseModel):
    action: Optional[ActionStep] = None
    isDone: bool = False
    requiresUserConfirmation: bool = False
    error: Optional[str] = None


# ── Saved Agent Models ──

class SaveAgentRequest(BaseModel):
    userId: str
    agentName: str
    triggerPrompt: str          # the original user prompt
    intent: str
    steps: List[ActionStep]     # the full sequence of steps that worked

class SaveAgentResponse(BaseModel):
    agentId: str
    message: str

class SavedAgent(BaseModel):
    agentId: str
    agentName: str
    triggerPrompt: str
    intent: str
    steps: List[ActionStep]
    usageCount: int = 0
    createdAt: str = ""
    lastUsedAt: str = ""

class AgentListResponse(BaseModel):
    agents: List[SavedAgent]

class AgentMatchRequest(BaseModel):
    userId: str
    prompt: str

class AgentMatchResponse(BaseModel):
    found: bool = False
    agent: Optional[SavedAgent] = None


