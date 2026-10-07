"""
Org Knowledge — "what VXA knows about you", shown inside Vexa Org.

The OKF knowledge base grows from every chat (learning_service) and every Org capture, but raw
nodes are noisy ("Vamsi is the user's name" ×8). This module turns each node into clean facts,
assigns each fact to an Org area, and lets the user forget a fact (which deletes the underlying
lines from the knowledge base + graph).

- Instant: a deterministic clean-up so Org is never empty.
- Background: an LLM pass per node rewrites facts cleanly; cached in Mongo `org_knowledge`
  by content hash, so it only re-runs when that node changes.
"""

import asyncio
import hashlib
import json
import logging
import re
from typing import Dict, List, Optional

from models.org_models import ORG_AREAS, OrgFact
from services import knowledge_service, llm_service, mongodb_service

logger = logging.getLogger(__name__)

PROFILE = "profile"   # the "YOU" centre of the orbit
FACT_AREAS = set(ORG_AREAS) | {PROFILE}

# Default area per knowledge node (the curation pass may move individual facts)
NODE_AREAS = {
    "identity/personal.md": PROFILE,
    "identity/professional.md": "office",
    "memory/career_events.md": "office",
    "memory/conversations.md": "personal",
    "memory/temporal.md": "personal",
    "preferences/apps_and_tools.md": PROFILE,
    "preferences/communication.md": PROFILE,
    "projects/architecture.md": "learning",
    "projects/technical.md": "learning",
    "relationships/contacts.md": "people",
    "speech/profile.md": PROFILE,
}

MAX_FACTS_PER_NODE = 25

CURATE_PROMPT = """These are raw memory lines an assistant learned about its user, Vamsi (from the "{node}" file).
Turn them into clean facts for a "What VXA knows about you" screen.

Rules:
- Merge duplicates and near-duplicates into one fact.
- Drop junk: lines that only state the user's name, meta-observations about the conversation ("user asked...", "bot replied..."), placeholders, or anything vague.
- Each fact: one short, specific sentence written TO the user ("You joined Cognizant on June 25, 2026").
- Assign each fact an area: profile (who they are, style, preferences), office (job, work), personal (home, plans, life), learning (skills, projects, study), people (specific people and relationships), health.
- "lines" = the numbers of ALL raw lines the fact came from (so deleting the fact can delete them).
- At most {max_facts} facts, most important first.

Raw lines:
{lines}

Respond ONLY with JSON: {{"facts": [{{"text": "...", "area": "...", "lines": [1, 2]}}]}}
"""

_JUNK = re.compile(
    r"(user'?s name|is the user|the user,|bot'?s (reply|response)|implied by|will be learned|"
    r"no other relationships|^\(.*\)$)", re.I)

_curating: set = set()           # nodes with a curation task in flight
_lock = asyncio.Lock()


def _col():
    db = mongodb_service.get_db()
    return db["org_knowledge"] if db is not None else None


def _raw_lines(content: str) -> List[str]:
    """Fact-like lines of a node: bullets and '**Key**: value' lines (original text, for deletion)."""
    out = []
    for line in content.split("\n"):
        s = line.strip()
        if s.startswith(("- ", "* ")) or re.match(r"^\*\*[^*]+\*\*\s*:", s):
            out.append(line)
    return out


def _plain(line: str) -> str:
    s = re.sub(r"^\s*[-*]\s*", "", line)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    return s.strip()


def _fact_id(rel: str, text: str) -> str:
    return hashlib.sha1(f"{rel}|{text}".encode()).hexdigest()[:12]


def _heuristic(rel: str, lines: List[str]) -> List[dict]:
    """Instant, model-free clean-up: strip markdown, drop junk, de-duplicate."""
    facts, seen = [], set()
    for line in lines:
        text = _plain(line)
        key = re.sub(r"[^a-z0-9 ]", "", text.lower())
        if len(text.split()) < 3 or _JUNK.search(text) or key in seen:
            continue
        seen.add(key)
        facts.append({"text": text, "area": NODE_AREAS.get(rel, "personal"), "lines": [line]})
    return facts[:MAX_FACTS_PER_NODE]


async def _curate(rel: str, lines: List[str], digest: str):
    """LLM pass for one node; stores the result in Mongo. Runs in the background."""
    try:
        numbered = "\n".join(f"{i + 1}. {_plain(l)}" for i, l in enumerate(lines[:120]))
        raw = await llm_service.chat(
            [{"role": "user", "content": CURATE_PROMPT.format(node=rel, lines=numbered, max_facts=MAX_FACTS_PER_NODE)}],
            temperature=0.1, max_tokens=1800, json_mode=True, agent_name="org_knowledge",
        )
        facts = []
        for f in json.loads(raw).get("facts", [])[:MAX_FACTS_PER_NODE]:
            text = str(f.get("text") or "").strip()
            idx = [int(n) - 1 for n in f.get("lines", []) if str(n).isdigit() and 0 < int(n) <= len(lines)]
            if not text or not idx:
                continue
            area = f.get("area") if f.get("area") in FACT_AREAS else NODE_AREAS.get(rel, "personal")
            facts.append({"text": text[:240], "area": area, "lines": [lines[i] for i in idx]})
        col = _col()
        if col is not None:
            await col.replace_one({"rel": rel}, {"rel": rel, "hash": digest, "facts": facts}, upsert=True)
        logger.info(f"Org knowledge curated: {rel} → {len(facts)} facts")
    except Exception as e:
        logger.warning(f"Org knowledge curation failed for {rel} (heuristic view stays): {e}")
    finally:
        _curating.discard(rel)


async def _run_curations(jobs: List[tuple]):
    # One node at a time — keeps us inside free-tier rate limits
    async with _lock:
        for rel, lines, digest in jobs:
            await _curate(rel, lines, digest)


async def facts() -> List[OrgFact]:
    """Every fact VXA knows, grouped by area. Uses curated facts where fresh, heuristic otherwise,
    and starts background curation for nodes that changed."""
    col = _col()
    cached: Dict[str, dict] = {}
    if col is not None:
        async for doc in col.find({}, {"_id": 0}):
            cached[doc["rel"]] = doc

    out: List[OrgFact] = []
    jobs = []
    for rel, content in sorted(knowledge_service.list_nodes().items()):
        lines = _raw_lines(content)
        if not lines:
            continue
        digest = hashlib.sha1("\n".join(lines).encode()).hexdigest()
        doc = cached.get(rel)
        if doc and doc.get("hash") == digest:
            node_facts = doc.get("facts", [])
        else:
            node_facts = _heuristic(rel, lines)
            if rel not in _curating and col is not None:
                _curating.add(rel)
                jobs.append((rel, lines, digest))
        out.extend(
            OrgFact(id=_fact_id(rel, f["text"]), area=f["area"], text=f["text"], source=rel)
            for f in node_facts
        )
    if jobs:
        asyncio.create_task(_run_curations(jobs))
    return out


async def forget(fact_id: str) -> bool:
    """Delete a fact: remove its source lines from the knowledge base (file + graph)."""
    col = _col()
    cached = {}
    if col is not None:
        async for doc in col.find({}, {"_id": 0}):
            cached[doc["rel"]] = doc

    for rel, content in knowledge_service.list_nodes().items():
        lines = _raw_lines(content)
        digest = hashlib.sha1("\n".join(lines).encode()).hexdigest()
        doc = cached.get(rel)
        node_facts = doc["facts"] if doc and doc.get("hash") == digest else _heuristic(rel, lines)
        for f in node_facts:
            if _fact_id(rel, f["text"]) == fact_id:
                removed = await knowledge_service.remove_lines(rel, f["lines"])
                if removed and col is not None and doc:
                    # Keep the curated view without re-running the model: drop the fact, re-key the hash
                    remaining = [x for x in node_facts if x is not f]
                    new_lines = _raw_lines(knowledge_service.list_nodes().get(rel, ""))
                    new_digest = hashlib.sha1("\n".join(new_lines).encode()).hexdigest()
                    await col.replace_one({"rel": rel}, {"rel": rel, "hash": new_digest, "facts": remaining}, upsert=True)
                return removed > 0
    return False


def top_facts_by_area(all_facts: List[OrgFact], per_area: int = 5) -> Dict[str, List[str]]:
    """A few facts per area, to give situation lines real context when an area has no items."""
    out: Dict[str, List[str]] = {}
    for f in all_facts:
        if f.area in ORG_AREAS and len(out.setdefault(f.area, [])) < per_area:
            out[f.area].append(f.text)
    return out
