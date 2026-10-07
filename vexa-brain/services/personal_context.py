"""
Personal Context — the bridge between a question and the user's life.

ChatGPT answers "how many calories in a banana?" with a fact. VXA should also know he started
going to the gym last week and say so in one natural line. This module finds the parts of his
life a question touches, cheaply:

1. route()  — ONE small LLM call (the retrieval call we already made) returns the life areas the
              question belongs to + search keywords. "banana calories" → health, personal.
2. build()  — searches those areas FIRST: curated facts (org_knowledge) and Org items (tasks,
              reminders, follow-ups). Only if nothing relevant is found there does it widen to
              every area. Returns a short PERSONAL CONTEXT block for the planner.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from models.org_models import ORG_AREAS
from services import llm_service, mongodb_service, org_knowledge

logger = logging.getLogger(__name__)

AREAS = list(ORG_AREAS) + ["profile"]

ROUTE_PROMPT = """Classify this message from a user to their personal assistant, and expand it into search terms.

Life areas:
- health: food, diet, calories, exercise, gym, sleep, medicine, body
- office: job, work, colleagues, career, interviews, salary
- personal: home, family plans, travel, shopping, money habits, errands, events
- learning: courses, skills, books, side projects, tech
- people: specific people, relationships, friends, family members
- profile: who the user is, preferences, style, background

Message: "{prompt}"

Respond ONLY with JSON: {{"areas": ["1-3 most relevant areas, best first"], "keywords": ["8-12 search terms: synonyms, related concepts, and the life activities this connects to (e.g. banana -> fruit, diet, nutrition, gym, workout)"]}}"""

STOP = {"the", "and", "for", "with", "you", "your", "are", "was", "how", "what", "did", "does", "have", "has",
        "this", "that", "from", "about", "many", "much", "can", "will", "his", "him", "she", "her", "they"}

MAX_FACTS = 6
MAX_ITEMS = 4
WIDEN_BELOW = 1.0     # nothing relevant in the routed areas → search every area
AREA_ITEM_SCORE = 1.5 # open Org items in a routed area are context even without shared words


@dataclass
class Route:
    areas: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in STOP}


async def route(prompt: str) -> Route:
    """Areas + expanded keywords for a message (one fast LLM call; falls back to plain keywords)."""
    try:
        raw = await llm_service.chat(
            [{"role": "user", "content": ROUTE_PROMPT.format(prompt=prompt.replace('"', "'")[:600])}],
            temperature=0.1, max_tokens=160, json_mode=True, agent_name="retrieval",
        )
        data = json.loads(raw)
        areas = [a for a in data.get("areas", []) if a in AREAS][:3]
        keywords = []
        for term in data.get("keywords", []):
            keywords.extend(_words(str(term)))
        r = Route(areas=areas, keywords=list(dict.fromkeys(keywords))[:20])
    except Exception as e:
        logger.warning(f"Route failed, using plain keywords: {e}")
        r = Route(areas=[], keywords=list(_words(prompt)))
    logger.info(f"Route: '{prompt[:50]}' → areas={r.areas} keywords={r.keywords[:10]}")
    return r


def _score(text: str, query: set, base: set) -> float:
    words = _words(text)
    hits = query & words
    # Word-prefix matches only (calorie ↔ calories, gym ↔ gymming) — substring matching let
    # "prep" match "prefer" and pulled in unrelated facts
    partial = {q for q in query - hits if len(q) >= 4 and any(w.startswith(q) or q.startswith(w) for w in words if len(w) >= 4)}
    return len(hits & base) * 2.0 + len(hits - base) * 1.0 + len(partial) * 0.6


async def build(user_id: str, prompt: str, r: Route, user_now: Optional[datetime] = None) -> str:
    """PERSONAL CONTEXT block: the few facts and Org items this question touches (area-first)."""
    base = _words(prompt)
    query = base | set(r.keywords)
    if not query:
        return ""

    try:
        facts = await org_knowledge.facts()
    except Exception as e:
        logger.warning(f"Personal context: facts unavailable ({e})")
        facts = []
    items = []
    db = mongodb_service.get_db()
    if db is not None:
        try:
            items = await db["org_items"].find(
                {"userId": user_id, "status": "open"}, {"_id": 0}
            ).to_list(length=300)
        except Exception as e:
            logger.warning(f"Personal context: org items unavailable ({e})")

    is_item = lambda c: isinstance(c, dict)

    def ranked(candidates, text_of, area_of, areas: Optional[List[str]]):
        out = []
        for c in candidates:
            if areas is not None and area_of(c) not in areas:
                continue
            s = _score(text_of(c), query, base)
            if area_of(c) in r.areas:
                s += 0.5          # prefer the routed areas even when widened
                # What's going on in that area right now matters even without shared words:
                # "banana calories" (health) should surface the open "start evening gym" task
                if is_item(c):
                    s = max(s, AREA_ITEM_SCORE)
            if s > 0:
                out.append((s, c))
        return sorted(out, key=lambda x: x[0], reverse=True)

    fact_text = lambda f: f.text
    item_text = lambda i: " ".join(str(i.get(k) or "") for k in ("title", "detail", "person", "type"))

    # 1. Search the routed areas first
    areas = r.areas or None
    top_facts = ranked(facts, fact_text, lambda f: f.area, areas)
    top_items = ranked(items, item_text, lambda i: i.get("area"), areas)
    best = max([s for s, _ in top_facts[:1] + top_items[:1]] or [0])

    # 2. Nothing relevant there → widen to every area
    widened = False
    if areas and best < WIDEN_BELOW:
        top_facts = ranked(facts, fact_text, lambda f: f.area, None)
        top_items = ranked(items, item_text, lambda i: i.get("area"), None)
        widened = True

    lines = []
    fact_floor = 2.0 if widened else 1.0   # widened results must be clearly relevant
    for s, f in top_facts[:MAX_FACTS]:
        if s >= fact_floor:
            lines.append(f"- [{f.area}] {f.text}")
    for s, i in top_items[:MAX_ITEMS]:
        if s >= 1.0:
            when = _when_label(i.get("dueAt"), user_now)
            lines.append(f"- [{i.get('area')} · open {i.get('type')}] {i.get('title')}{' — ' + when if when else ''}")

    logger.info(f"Personal context: areas={r.areas}{' (widened)' if widened else ''} → {len(lines)} lines")
    return "\n".join(lines)


def _when_label(due: Optional[str], user_now: Optional[datetime]) -> str:
    if not due or not user_now:
        return ""
    try:
        from services.org_service import _parse_dt, _when
        return _when(_parse_dt(due), user_now)
    except Exception:
        return ""
