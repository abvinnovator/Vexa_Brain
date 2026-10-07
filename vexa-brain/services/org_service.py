"""
Org Service — Vexa Org: the user's life organised into areas.

Storage: MongoDB `org_items` (source of truth across devices; the app also keeps a local copy)
and `org_situations` (cached one-line "what's going on" per area).

Anything the user adds is also handed to the learning service, so the knowledge base / graph
learns from it the same way it learns from chat.
"""

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from models.org_models import (
    ORG_AREAS, ORG_TYPES, OrgArea, OrgCaptureResponse, OrgItem, OrgItemUpsert, OrgOverview,
)
from services import knowledge_service, learning_service, llm_service, mongodb_service, org_knowledge

logger = logging.getLogger(__name__)

RECENT_DONE_DAYS = 7

CAPTURE_PROMPT = """You organise a person's life. They typed a quick note into their organiser.
Turn it into 1-3 items. Most notes are exactly ONE item — only split when they clearly list separate things.

Areas (pick the best fit):
- office: job, work tasks, colleagues in a work context, interviews, onboarding
- personal: home, family plans, errands, travel, shopping, events
- learning: courses, reading, skills, side projects
- people: promises/follow-ups with specific people, birthdays, keeping in touch
- health: exercise, medicine, doctor, sleep, food habits

Types:
- task: something to do (may have a deadline)
- reminder: notify at a specific time
- followup: a promise involving another person, in EITHER direction — "call Vivek back", "send Ravi the doc",
  or "Vivek said he'll call tomorrow" / "Ravi will send the offer by Monday". Set "person", and set "dueAt" to the
  promised time so the user is reminded to check it happened (evening = 18:00, morning = 09:00, afternoon = 14:00).
- note: something to remember with NO action and NO time involved. Never use note when a time or promise is mentioned.

Current local time: {now}
Resolve relative dates ("tomorrow", "next Friday", "in 2 hours", "12th") against it.
"dueAt" is ISO-8601 WITH the same UTC offset as the current time, or null if no time is implied.
If only a date is given for a reminder/birthday, use 09:00 that day. A birthday is "people" + "reminder" one day before at 09:00 unless they say otherwise.

What you know about the person:
{identity}

Respond ONLY with JSON:
{{"items": [{{"area": "...", "type": "...", "title": "short, starts with a verb when it's an action", "detail": "extra context or null", "dueAt": "... or null", "person": "name or null"}}],
  "reply": "one short friendly line confirming where it was filed, e.g. 'Got it — Personal · reminder Nov 11, 9 AM'"}}

Note: "{text}"
"""

SITUATION_PROMPT = """Write a one-line situation summary (max 12 words) for each life area of this person,
based on their open items. Sound like a helpful assistant glancing at their board, e.g.
"Onboarding docs pending; HR reply due today" or "Quiet — nothing urgent".
Current local time: {now}
Use the timing labels exactly as given in brackets (today / tomorrow / OVERDUE / weekday) — never compute dates yourself.
Only say "overdue" when the label says OVERDUE.

Open items by area:
{items}

What you already know about each area:
{knowledge}

When an area has NO open items, don't say "quiet" — summarise where they stand from what you know,
e.g. office: "Program Analyst Trainee at Cognizant · nothing due". Only say "Nothing here yet" when you know nothing.

Respond ONLY with JSON mapping EVERY area key to its line: {{"office": "...", "personal": "...", "learning": "...", "people": "...", "health": "..."}}
"""


def _col(name: str):
    db = mongodb_service.get_db()
    if db is None:
        raise RuntimeError("MongoDB is not connected")
    return db[name]


async def ensure_indexes():
    await _col("org_items").create_index([("userId", 1), ("status", 1), ("dueAt", 1)])
    await _col("org_items").create_index([("id", 1)], unique=True)
    await _col("org_situations").create_index([("userId", 1)], unique=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _user_now(now: Optional[str]) -> datetime:
    """The user's local 'now' (device time with offset); falls back to IST."""
    return _parse_dt(now) or datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _clean_item(raw: Dict) -> Optional[Dict]:
    area = (raw.get("area") or "").strip().lower()
    item_type = (raw.get("type") or "task").strip().lower()
    title = (raw.get("title") or "").strip()
    if not title:
        return None
    return {
        "area": area if area in ORG_AREAS else "personal",
        "type": item_type if item_type in ORG_TYPES else "task",
        "title": title[:200],
        "detail": (raw.get("detail") or None),
        "dueAt": raw.get("dueAt") if _parse_dt(raw.get("dueAt")) else None,
        "person": (raw.get("person") or None),
    }


def _learn(text: str, filed: str):
    """Hand what the user added to the learning service (fire-and-forget)."""
    async def run():
        try:
            await learning_service.process_conversation(text, filed, "ORG_CAPTURE")
        except Exception as e:
            logger.error(f"Org learning error: {e}")
    asyncio.create_task(run())


# ── Capture ──────────────────────────────────────────────────────────

async def capture(user_id: str, text: str, now: Optional[str], area: Optional[str] = None,
                  source: str = "capture", learn: bool = True) -> OrgCaptureResponse:
    cleaned, data = await _parse_with_reply(text, now, area)
    if not cleaned:
        cleaned = [{"area": area if area in ORG_AREAS else "personal", "type": "note", "title": text.strip()[:200],
                    "detail": None, "dueAt": None, "person": None}]

    stamp = _now_iso()
    items, new_docs = [], []
    for c in cleaned:
        # Same title at the same time already open → reuse it instead of adding a duplicate
        existing = await _find_duplicate(user_id, c)
        if existing:
            items.append(existing)
            continue
        item = OrgItem(id=str(uuid.uuid4()), userId=user_id, status="open", source=source,
                       createdAt=stamp, updatedAt=stamp, **c)
        items.append(item)
        new_docs.append(item.model_dump())
    if new_docs:
        await _col("org_items").insert_many(new_docs)

    reply = (data.get("reply") or "").strip() or f"Filed under {ORG_AREAS[items[0].area]}."
    if learn:
        _learn(text, reply)
    logger.info(f"Org capture: {len(items)} item(s) for {user_id}: {[i.title for i in items]}")
    return OrgCaptureResponse(items=items, reply=reply)


def _norm(text: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


async def _find_duplicate(user_id: str, item: Dict) -> Optional[OrgItem]:
    due = _parse_dt(item.get("dueAt"))
    async for d in _col("org_items").find({"userId": user_id, "status": "open"}, {"_id": 0}):
        same_time = (due is None and not d.get("dueAt")) or (
            due is not None and (other := _parse_dt(d.get("dueAt"))) is not None and abs((other - due).total_seconds()) < 60)
        if same_time and _norm(d.get("title")) == _norm(item.get("title")):
            return OrgItem(**d)
    return None


async def _parse_with_reply(text: str, now: Optional[str], area: Optional[str] = None):
    """LLM: free text → cleaned item dicts (+ the model's one-line reply)."""
    user_now = _user_now(now)
    prompt = CAPTURE_PROMPT.format(
        now=user_now.isoformat(timespec="minutes") + f" ({user_now.strftime('%A')})",
        identity=knowledge_service._get_compact_identity() or "Unknown",
        text=text.replace('"', "'")[:1000],
    )
    if area in ORG_AREAS:
        prompt += f'\nThe user added this inside the "{area}" area — use area "{area}" for every item.\n'
    raw = await llm_service.chat([{"role": "user", "content": prompt}], temperature=0.1,
                                 max_tokens=600, json_mode=True, agent_name="org_capture")
    data = json.loads(raw)
    cleaned = [c for c in (_clean_item(i) for i in data.get("items", [])[:3]) if c]
    if area in ORG_AREAS:
        for c in cleaned:
            c["area"] = area
    return cleaned, data


# ── CRUD ─────────────────────────────────────────────────────────────

async def upsert(item_id: str, body: OrgItemUpsert) -> OrgItem:
    existing = await _col("org_items").find_one({"id": item_id}, {"_id": 0})
    stamp = _now_iso()
    fields = body.model_dump()
    fields["area"] = fields["area"] if fields["area"] in ORG_AREAS else "personal"
    fields["type"] = fields["type"] if fields["type"] in ORG_TYPES else "task"
    item = OrgItem(id=item_id, createdAt=existing["createdAt"] if existing else stamp, updatedAt=stamp, **fields)
    await _col("org_items").replace_one({"id": item_id}, item.model_dump(), upsert=True)

    if existing is None and body.source == "manual":
        when = f" due {body.dueAt}" if body.dueAt else ""
        _learn(f"{body.title}. {body.detail or ''}".strip(), f"Added to {ORG_AREAS[item.area]} as a {item.type}{when}.")
    return item


async def update_matching(user_id: str, match: str, text: str, now: Optional[str]) -> Optional[OrgItem]:
    """Find the open item `match` refers to and apply the change in `text` (new time/title).
    Used by chat for "my trainer meet moved to 1:15 AM". Returns the updated item or None."""
    words = {w for w in re.findall(r"[a-z0-9]+", match.lower()) if len(w) > 2}
    if not words:
        return None
    docs = await _col("org_items").find({"userId": user_id, "status": "open"}, {"_id": 0}).to_list(length=500)

    def score(d):
        hay = " ".join(str(d.get(k) or "") for k in ("title", "detail", "person")).lower()
        return sum(1 for w in words if w in hay)

    # Best keyword match; ties go to the most recently touched item
    best = max(docs, key=lambda d: (score(d), d.get("updatedAt", "")), default=None)
    if not best or score(best) == 0:
        return None

    parsed, _ = await _parse_with_reply(text, now, area=best["area"])
    change = parsed[0] if parsed else {}
    fields = {k: v for k, v in change.items() if k in ("title", "dueAt", "detail", "person") and v}
    fields["updatedAt"] = _now_iso()
    await _col("org_items").update_one({"id": best["id"]}, {"$set": fields})
    best.update(fields)
    logger.info(f"Org update: '{best['title']}' -> {fields}")
    return OrgItem(**best)


async def delete(item_id: str, user_id: str) -> bool:
    res = await _col("org_items").delete_one({"id": item_id, "userId": user_id})
    return res.deleted_count > 0


# ── Overview (the orbit) ─────────────────────────────────────────────

async def overview(user_id: str, now: Optional[str]) -> OrgOverview:
    user_now = _user_now(now)
    since = (datetime.now(timezone.utc) - timedelta(days=RECENT_DONE_DAYS)).isoformat()
    docs = await _col("org_items").find(
        {"userId": user_id, "$or": [{"status": "open"}, {"updatedAt": {"$gte": since}}]},
        {"_id": 0},
    ).to_list(length=500)
    items = [OrgItem(**d) for d in docs]
    open_items = [i for i in items if i.status == "open"]

    end_of_today = user_now.replace(hour=23, minute=59, second=59)
    try:
        knowledge = await org_knowledge.facts()
    except Exception as e:
        logger.warning(f"Org knowledge unavailable: {e}")
        knowledge = []
    situations = await _situations(user_id, open_items, user_now, org_knowledge.top_facts_by_area(knowledge))

    areas = []
    for key, label in ORG_AREAS.items():
        mine = [i for i in open_items if i.area == key]
        overdue = sum(1 for i in mine if (d := _parse_dt(i.dueAt)) and d < user_now)
        due_today = sum(1 for i in mine if (d := _parse_dt(i.dueAt)) and user_now <= d <= end_of_today)
        areas.append(OrgArea(
            key=key, label=label,
            situation=situations.get(key) or ("Nothing on your plate." if not mine else f"{len(mine)} open"),
            openCount=len(mine), dueTodayCount=due_today, overdueCount=overdue,
            needsAttention=(overdue + due_today) > 0,
        ))

    timed = sorted((i for i in open_items if _parse_dt(i.dueAt)), key=lambda i: _parse_dt(i.dueAt))
    upcoming = [i for i in timed if _parse_dt(i.dueAt) >= user_now - timedelta(hours=12)]
    nxt = (upcoming or timed or open_items or [None])[0]

    items.sort(key=lambda i: (i.status != "open", _parse_dt(i.dueAt) or datetime.max.replace(tzinfo=timezone.utc)))
    return OrgOverview(areas=areas, items=items, next=nxt, knowledge=knowledge)


def _when(due: Optional[datetime], user_now: datetime) -> str:
    """Human label computed in code — models get relative dates wrong ("overdue" for a 6 PM gym at 10 AM)."""
    if due is None:
        return "no date"
    local = due.astimezone(user_now.tzinfo)
    days = (local.date() - user_now.date()).days
    clock = local.strftime("%I:%M %p").lstrip("0")
    if local < user_now:
        return f"OVERDUE since {local.strftime('%a %d %b')} {clock}" if days < 0 else f"OVERDUE since {clock} today"
    if days == 0:
        return f"today {clock}"
    if days == 1:
        return f"tomorrow {clock}"
    if days < 7:
        return f"{local.strftime('%A')} {clock}"
    return f"{local.strftime('%d %b')} (in {days} days)"


async def _situations(user_id: str, open_items: List[OrgItem], user_now: datetime,
                      known: Optional[Dict[str, List[str]]] = None) -> Dict[str, str]:
    """One line per area, regenerated only when the open items change (one LLM call for all areas)."""
    by_area: Dict[str, List[str]] = {k: [] for k in ORG_AREAS}
    for i in open_items:
        due = f" ({_when(_parse_dt(i.dueAt), user_now)})" if i.dueAt else ""
        by_area[i.area].append(f"{i.type}: {i.title}{due}")
    known = known or {}
    digest_src = json.dumps([by_area, known], sort_keys=True) + user_now.strftime("%Y-%m-%d")
    digest = hashlib.sha1(digest_src.encode()).hexdigest()

    cached = await _col("org_situations").find_one({"userId": user_id}, {"_id": 0})
    if cached and cached.get("hash") == digest:
        return cached.get("situations", {})
    if not open_items and not any(known.values()):
        return {}

    listing = "\n".join(f"{k}: " + ("; ".join(v) if v else "(nothing)") for k, v in by_area.items())
    try:
        raw = await llm_service.chat(
            [{"role": "user", "content": SITUATION_PROMPT.format(
                now=user_now.strftime("%A %d %b, %I:%M %p"), items=listing,
                knowledge="\n".join(f"{k}: " + "; ".join(v) for k, v in known.items() if v) or "(nothing)")}],
            temperature=0.3, max_tokens=300, json_mode=True, agent_name="org_situation",
        )
        situations = {k: str(v)[:120] for k, v in json.loads(raw).items() if k in ORG_AREAS}
    except Exception as e:
        logger.warning(f"Org situation summary failed (using counts): {e}")
        return cached.get("situations", {}) if cached else {}

    await _col("org_situations").replace_one(
        {"userId": user_id}, {"userId": user_id, "hash": digest, "situations": situations}, upsert=True)
    return situations
