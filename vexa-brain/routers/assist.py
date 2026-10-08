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


# ══════════════════════════════════════════════════════════════════════
# Bubble long-press actions: ① Prompt  ② Summarize  ③ Track
# ══════════════════════════════════════════════════════════════════════

import asyncio  # noqa: E402

from models.org_models import ORG_AREAS, OrgItem  # noqa: E402
from services import learning_service, org_service, personal_context  # noqa: E402

PAGE_BUDGET = 6000   # chars of page text for prompt/summarize (from the top — it's a page, not a chat)


def _page(lines: List[str]) -> List[str]:
    out, used = [], 0
    for line in (l.strip() for l in lines if l and l.strip()):
        if used + len(line) > PAGE_BUDGET:
            break
        out.append(line)
        used += len(line) + 1
    return out


def _local_now(now: Optional[str]) -> datetime:
    try:
        dt = datetime.fromisoformat((now or "").replace("Z", "+00:00"))
        if dt.tzinfo:
            return dt
    except ValueError:
        pass
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


async def _personal(user_id: str, query: str, user_now: datetime):
    """Same area-first context as chat: routed facts + Org items + knowledge sections."""
    r = await personal_context.route(query[:600])
    try:
        knowledge = await knowledge_service.query_relevant(query[:500], user_id, expanded_keywords=r.keywords,
                                                           priority_areas=r.areas)
    except Exception:
        knowledge = ""
    pc = await personal_context.build(user_id, query, r, user_now)
    return r, knowledge, pc


class AssistScreenRequest(BaseModel):
    userId: str
    app: Optional[str] = None
    lines: List[str]
    prompt: Optional[str] = None      # ① Prompt only
    now: Optional[str] = None


# ── ① Prompt: "help me fill this form based on what you know" ──

PROMPT_PROMPT = """You are VXA, Vamsi's personal assistant. He is looking at this screen in "{app}" and asks:
"{ask}"

Screen text (top to bottom; THEM:/ME: mark chat bubbles):
---
{screen}
---
What's going on in his life that this touches:
{personal}

What you know about him:
{knowledge}

Answer his request using the screen AND what you know about him — that is the point of VXA.
- Filling a form: list each field you can see with the value from what you know ("Full name: Brahma Vamsi").
  For anything you don't know, write "— ask Vamsi" instead of guessing. Never invent IDs, numbers, dates or addresses.
- Writing something: write it ready to paste, in his tone.
- Be concise and practical. Plain text with simple line breaks or "-" bullets; no long preamble.
"""


class AssistPromptResponse(BaseModel):
    answer: str


@router.post("/assist/prompt", response_model=AssistPromptResponse)
async def assist_prompt(request: AssistScreenRequest):
    ask = (request.prompt or "").strip()
    if not ask:
        raise HTTPException(status_code=400, detail="prompt is empty")
    screen = _page(request.lines)
    user_now = _local_now(request.now)
    _, knowledge, pc = await _personal(request.userId, ask + " " + " ".join(screen[:40]), user_now)
    app = APP_NAMES.get(request.app or "", request.app or "unknown app")
    answer = await llm_service.chat(
        [{"role": "user", "content": PROMPT_PROMPT.format(
            app=app, ask=ask.replace('"', "'"), screen="\n".join(screen) or "(no text on screen)",
            personal=pc or "(nothing specific)", knowledge=knowledge or "(nothing relevant)")}],
        temperature=0.4, max_tokens=900, agent_name="assist_prompt",
        metadata={"app": request.app or "unknown"}, prefer_models=["openai/gpt-oss-120b"], redact_trace=True)
    # Learn from HIS words (the prompt) — never from the screen
    if len(ask.split()) >= 4:
        asyncio.create_task(learning_service.process_conversation(ask, "", "BUBBLE_PROMPT"))
    return AssistPromptResponse(answer=answer.strip())


# ── ② Summarize: normal summary + what it means for HIM + save as a note ──

SUMMARY_PROMPT = """You are VXA, Vamsi's personal assistant. Summarize this screen from "{app}" for him.

Screen text (top to bottom):
---
{screen}
---
What's going on in his life that this might touch:
{personal}

What you know about him:
{knowledge}

1. "summary": 2-4 sentences, a neutral, accurate summary of what's on screen.
2. "keyPoints": 3-5 short bullets of the most useful details (dates, numbers, decisions, asks).
3. "forYou": 1-2 sentences on what this means for HIM specifically, using what you know (his job, plans, people, goals).
   Only real connections — if nothing genuinely relates, say what action (if any) he might take. Never invent facts.
4. "title": a short note title (max 8 words).
5. "area": where this note belongs: office, personal, learning, people, or health.

Respond ONLY with JSON: {{"title": "...", "summary": "...", "keyPoints": ["..."], "forYou": "...", "area": "..."}}
"""


class AssistSummaryResponse(BaseModel):
    title: str
    summary: str
    keyPoints: List[str] = []
    forYou: str = ""
    area: str = "personal"
    areaLabel: str = "Personal"


@router.post("/assist/summarize", response_model=AssistSummaryResponse)
async def assist_summarize(request: AssistScreenRequest):
    screen = _page(request.lines)
    if not screen:
        raise HTTPException(status_code=400, detail="no screen text")
    user_now = _local_now(request.now)
    _, knowledge, pc = await _personal(request.userId, " ".join(screen[:60]), user_now)
    app = APP_NAMES.get(request.app or "", request.app or "unknown app")
    raw = await llm_service.chat(
        [{"role": "user", "content": SUMMARY_PROMPT.format(
            app=app, screen="\n".join(screen), personal=pc or "(nothing specific)",
            knowledge=knowledge or "(nothing relevant)")}],
        temperature=0.3, max_tokens=900, json_mode=True, agent_name="assist_summarize",
        metadata={"app": request.app or "unknown"}, prefer_models=["openai/gpt-oss-120b"], redact_trace=True)
    data = json.loads(raw)
    area = data.get("area") if data.get("area") in ORG_AREAS else "personal"
    return AssistSummaryResponse(
        title=(data.get("title") or "Screen summary")[:120],
        summary=data.get("summary") or "",
        keyPoints=[str(p) for p in data.get("keyPoints", [])][:6],
        forYou=data.get("forYou") or "",
        area=area, areaLabel=ORG_AREAS[area],
    )


# ── ③ Track: anything actionable on screen → Org items with reminders ──

TRACK_PROMPT = """You are VXA, Vamsi's personal organiser. He long-pressed "Track" on this screen from "{app}".
Find what HE should act on or remember with a time attached: meetings, interviews, deadlines, due dates, events,
appointments, promises someone made to him or he made ("I'll send it tomorrow"), offers that expire.

Current local time: {now}
Screen text (top to bottom; THEM:/ME: mark chat bubbles):
---
{screen}
---

For each (max 3, most important first) output an item:
- area: office | personal | learning | people | health
- type: reminder (a time to be notified) | task (to do, maybe by a deadline) | followup (involves another person — set person)
- title: short, starts with a verb ("Attend Cognizant interview", "Pay hostel fee")
- detail: one line of useful context from the screen (place, link, who) or null
- dueAt: ISO-8601 with the same offset as the current time; resolve "tomorrow", "Friday", "15th". For an event,
  remind 1 hour before if a time is given, else 09:00 that day. null if no time at all.
- person: name or null
Never include account numbers, card details, OTPs or passwords. If nothing on screen needs tracking, return no items.

Respond ONLY with JSON: {{"items": [...], "reply": "one short line, e.g. Tracked: interview Fri 3 PM (reminder 2 PM)"}}
"""


class AssistTrackResponse(BaseModel):
    items: List[OrgItem]
    reply: str


@router.post("/assist/track", response_model=AssistTrackResponse)
async def assist_track(request: AssistScreenRequest):
    screen = _page(request.lines)
    if not screen:
        raise HTTPException(status_code=400, detail="no screen text")
    user_now = _local_now(request.now)
    app = APP_NAMES.get(request.app or "", request.app or "unknown app")
    raw = await llm_service.chat(
        [{"role": "user", "content": TRACK_PROMPT.format(
            app=app, now=org_service.now_with_calendar(user_now),
            screen="\n".join(screen))}],
        temperature=0.1, max_tokens=700, json_mode=True, agent_name="assist_track",
        metadata={"app": request.app or "unknown"}, prefer_models=["openai/gpt-oss-120b"], redact_trace=True)
    data = json.loads(raw)
    cleaned = org_service.clean_items(data.get("items", [])[:3])
    if not cleaned:
        return AssistTrackResponse(items=[], reply="Nothing on this screen to track.")
    items = await org_service.add_items(request.userId, cleaned, source="bubble")
    return AssistTrackResponse(items=items, reply=(data.get("reply") or f"Tracked {len(items)} item(s).").strip())
