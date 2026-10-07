"""Vexa Org — how VXA organises the user's life into areas, tasks, reminders and follow-ups."""

from pydantic import BaseModel
from typing import List, Optional

# Fixed life areas shown as bubbles in the Org orbit. Money/banking is deliberately absent:
# VXA never handles financial data.
ORG_AREAS = {
    "office": "Office",
    "personal": "Personal",
    "learning": "Learning",
    "people": "People",
    "health": "Health",
}

# task: something to do · reminder: ping at a time · followup: a promise involving another
# person ("call Vivek back") · note: something to remember with no action
ORG_TYPES = ("task", "reminder", "followup", "note")


class OrgItem(BaseModel):
    id: str
    userId: str
    area: str
    type: str
    title: str
    detail: Optional[str] = None
    dueAt: Optional[str] = None        # ISO-8601 with UTC offset, e.g. 2026-10-09T17:00:00+05:30
    person: Optional[str] = None       # who a follow-up involves
    status: str = "open"               # open | done
    source: str = "manual"             # manual | capture | chat
    createdAt: str
    updatedAt: str


class OrgItemUpsert(BaseModel):
    """Create or update an item (manual add / edit / mark done). The client owns `id` (a UUID)
    so items made offline sync without duplicates."""
    userId: str
    area: str
    type: str = "task"
    title: str
    detail: Optional[str] = None
    dueAt: Optional[str] = None
    person: Optional[str] = None
    status: str = "open"
    source: str = "manual"


class OrgCaptureRequest(BaseModel):
    """'Tell VXA anything' — free text that VXA files into the right area(s)."""
    userId: str
    text: str
    now: Optional[str] = None          # device local time (ISO with offset) to resolve "tomorrow 5pm"
    area: Optional[str] = None         # set when added from inside an area's sheet — file it there


class OrgCaptureResponse(BaseModel):
    items: List[OrgItem]
    reply: str                         # short confirmation, e.g. "Filed under Personal · reminder Nov 11"


class OrgArea(BaseModel):
    key: str
    label: str
    situation: str                     # one line: what's going on in this area right now
    openCount: int
    dueTodayCount: int
    overdueCount: int
    needsAttention: bool               # something due today or overdue → bubble pulses


class OrgFact(BaseModel):
    """Something VXA knows about the user (from the knowledge base), shown in Org."""
    id: str
    area: str                          # an ORG_AREAS key, or "profile" for the YOU centre
    text: str
    source: str                        # knowledge node it came from, e.g. "memory/career_events.md"


class OrgOverview(BaseModel):
    areas: List[OrgArea]
    items: List[OrgItem]               # open items + items completed in the last 7 days
    next: Optional[OrgItem] = None     # the next thing that needs the user
    knowledge: List[OrgFact] = []      # what VXA knows, per area (+ "profile")


class OrgLearnHistoryRequest(BaseModel):
    """Old chat messages (user's side) for VXA to learn from once — fills Org on a fresh install."""
    userId: str
    messages: List[str]
