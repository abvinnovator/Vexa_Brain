"""
Assist — reply drafts for whatever is on the user's screen (VXA floating bubble).

The phone sends the text Android gives a default assistant (no screenshot, no accessibility).
Each line is tagged by where it sits on screen: THEM (left — incoming), ME (right — outgoing),
or plain. VXA works out the conversation and drafts replies in the user's voice.

Privacy: screen text is used for this one request only — it is never stored or learned from,
because it contains other people's messages.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import knowledge_service, llm_service, personality_service

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_SCREEN_CHARS = 5000

ASSIST_PROMPT = """You are VXA, the personal assistant of Vamsi. He tapped the VXA bubble while looking at this screen
in the app "{app}" and wants reply drafts he can paste.

Screen text, top to bottom. THEM = message on the left (from the other person), ME = message on the right (from Vamsi),
lines without a tag are other UI text (names, times, buttons):
---
{screen}
---
{instruction}
What you know about Vamsi and the people in his life:
{knowledge}

{personality}

Write {count} different reply drafts to the most recent message(s) from the other person:
- Answer what they actually said. If they asked something you can't know, write a natural reply that leaves the detail for Vamsi (e.g. "Let me check and tell you").
- Sound like Vamsi: same language and script the conversation uses (English, Telugu, or Telugu-English mix), casual for friends/family, polite for work.
- Chat replies are short (1-2 sentences). Each draft takes a different angle (e.g. yes / not now / ask a question).
- Never invent specific times, dates, numbers, places or commitments that aren't on screen or in what you know —
  write "let me check my schedule" or leave a blank like "I'm free on ___" for Vamsi to fill.
- No preamble, no quotes around the draft, no emojis unless the conversation uses them.

Telugu notes: parents call their son "nanna" or "ra" affectionately — "nanna bhojanam chesava?" means "did you eat, dear?" (not "father").
Write Telugu-English the way Andhra people text in Latin script, e.g. "Ha amma, tinnanu", "Inka undi amma, pampakandi", "Sare", "Ippude".

Respond ONLY with JSON:
{{"person": "who he is replying to, or null", "context": "one line: what they said / want", "drafts": ["...", "..."]}}
"""


class AssistReplyRequest(BaseModel):
    userId: str
    app: Optional[str] = None            # package name, e.g. com.whatsapp
    lines: List[str]                     # screen text, top to bottom, prefixed "THEM: " / "ME: " where known
    instruction: Optional[str] = None    # optional nudge: "shorter", "more formal", "say no politely"
    now: Optional[str] = None
    count: int = 3


class AssistReplyResponse(BaseModel):
    person: Optional[str] = None
    context: str = ""
    drafts: List[str]


APP_NAMES = {
    "com.whatsapp": "WhatsApp", "com.whatsapp.w4b": "WhatsApp Business", "com.linkedin.android": "LinkedIn",
    "com.instagram.android": "Instagram", "com.google.android.gm": "Gmail", "org.telegram.messenger": "Telegram",
    "com.google.android.apps.messaging": "Messages", "com.twitter.android": "X",
}


@router.post("/assist/reply", response_model=AssistReplyResponse)
async def assist_reply(request: AssistReplyRequest):
    lines = [l.strip() for l in request.lines if l and l.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="no screen text")

    # Keep the most recent part of the conversation (bottom of the screen) within budget
    screen, used = [], 0
    for line in reversed(lines):
        if used + len(line) > MAX_SCREEN_CHARS:
            break
        screen.append(line)
        used += len(line) + 1
    screen.reverse()

    recent = " ".join(l for l in screen[-12:] if l.startswith(("THEM:", "ME:"))) or " ".join(screen[-12:])
    try:
        knowledge = await knowledge_service.query_relevant(recent[:500], request.userId)
    except Exception:
        knowledge = ""
    try:
        personality = await personality_service.build_personality_prompt()
    except Exception:
        personality = ""

    app = APP_NAMES.get(request.app or "", request.app or "unknown app")
    instruction = f"Vamsi's instruction for these drafts: {request.instruction}\n" if request.instruction else ""
    prompt = ASSIST_PROMPT.format(
        app=app, screen="\n".join(screen), instruction=instruction,
        knowledge=knowledge or "(nothing relevant)", personality=personality,
        count=max(1, min(request.count, 4)),
    )
    raw = await llm_service.chat([{"role": "user", "content": prompt}], temperature=0.6,
                                 max_tokens=500, json_mode=True, agent_name="assist_reply",
                                 metadata={"app": request.app or "unknown"},
                                 prefer_models=["openai/gpt-oss-120b"],
                                 redact_trace=True)   # screen text = other people's messages: never traced
    data = json.loads(raw)
    drafts = [str(d).strip().strip('"') for d in data.get("drafts", []) if str(d).strip()]
    if not drafts:
        raise HTTPException(status_code=502, detail="no drafts produced")
    logger.info(f"Assist reply: {app}, {len(screen)} lines → {len(drafts)} drafts")
    return AssistReplyResponse(person=data.get("person"), context=data.get("context") or "", drafts=drafts[:4])
