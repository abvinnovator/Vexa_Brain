"""
MongoDB service — Agent-focused data layer.

v3.0: Removed all event-observation queries (no longer tracking phone events).
Now stores and retrieves saved agents — reusable automation sequences
that can be replayed without AI calls.

Collections:
  - agents: Saved agent step sequences
"""

from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Dict, Any, Optional
from datetime import datetime
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db = None


async def connect(uri: str, db_name: str):
    global _client, _db
    _client = AsyncIOMotorClient(uri)
    _db = _client[db_name]
    logger.info(f"Connected to MongoDB: {db_name}")

    # Ensure indexes on the agents collection
    await _db.agents.create_index([("userId", 1), ("triggerPrompt", 1)])
    await _db.agents.create_index([("userId", 1), ("intent", 1)])
    await _db.agents.create_index([("userId", 1), ("createdAt", -1)])
    logger.info("MongoDB indexes ensured on 'agents' collection")


async def disconnect():
    if _client:
        _client.close()


# ── Agent CRUD ──────────────────────────────────────────────

async def save_agent(
    user_id: str,
    agent_name: str,
    trigger_prompt: str,
    intent: str,
    steps: List[Dict[str, Any]],
) -> str:
    """Save a new agent (reusable automation sequence) to MongoDB.

    Returns the agent ID.
    """
    if _db is None:
        raise Exception("MongoDB not connected")

    doc = {
        "userId": user_id,
        "agentName": agent_name,
        "triggerPrompt": trigger_prompt,
        "normalizedPrompt": _normalize(trigger_prompt),
        "intent": intent,
        "steps": steps,
        "usageCount": 0,
        "createdAt": datetime.utcnow().isoformat(),
        "lastUsedAt": datetime.utcnow().isoformat(),
    }
    result = await _db.agents.insert_one(doc)
    agent_id = str(result.inserted_id)
    logger.info(f"Agent saved: '{agent_name}' (id={agent_id}) for user {user_id}")
    return agent_id


async def get_agents(user_id: str) -> List[Dict]:
    """Get all saved agents for a user, most recent first."""
    if _db is None:
        return []

    cursor = _db.agents.find(
        {"userId": user_id},
        {"_id": 1, "agentName": 1, "triggerPrompt": 1, "intent": 1,
         "usageCount": 1, "createdAt": 1, "lastUsedAt": 1,
         "steps": 1}
    ).sort("createdAt", -1)

    agents = []
    async for doc in cursor:
        doc["agentId"] = str(doc.pop("_id"))
        agents.append(doc)
    return agents


async def get_agent_by_id(agent_id: str) -> Optional[Dict]:
    """Get a single agent by its MongoDB ID."""
    if _db is None:
        return None
    try:
        doc = await _db.agents.find_one({"_id": ObjectId(agent_id)})
        if doc:
            doc["agentId"] = str(doc.pop("_id"))
        return doc
    except Exception:
        return None


async def match_agent(user_id: str, prompt: str) -> Optional[Dict]:
    """Find a saved agent matching the given prompt.

    Uses normalized prompt for fuzzy matching.
    Returns the best match (highest usage count) or None.
    """
    if _db is None:
        return None

    normalized = _normalize(prompt)

    # Try exact normalized match first
    doc = await _db.agents.find_one(
        {"userId": user_id, "normalizedPrompt": normalized},
        sort=[("usageCount", -1)]
    )

    if doc:
        doc["agentId"] = str(doc.pop("_id"))
        return doc

    # Try keyword-based partial match
    keywords = normalized.split()
    if len(keywords) >= 2:
        regex_pattern = ".*".join(keywords[:3])  # first 3 keywords
        doc = await _db.agents.find_one(
            {"userId": user_id, "normalizedPrompt": {"$regex": regex_pattern}},
            sort=[("usageCount", -1)]
        )
        if doc:
            doc["agentId"] = str(doc.pop("_id"))
            return doc

    return None


async def update_agent_usage(agent_id: str):
    """Increment usage count and update last-used timestamp."""
    if _db is None:
        return
    try:
        await _db.agents.update_one(
            {"_id": ObjectId(agent_id)},
            {
                "$inc": {"usageCount": 1},
                "$set": {"lastUsedAt": datetime.utcnow().isoformat()}
            }
        )
    except Exception as e:
        logger.error(f"Failed to update agent usage: {e}")


async def delete_agent(agent_id: str) -> bool:
    """Delete a saved agent by ID."""
    if _db is None:
        return False
    try:
        result = await _db.agents.delete_one({"_id": ObjectId(agent_id)})
        return result.deleted_count > 0
    except Exception:
        return False


async def get_agent_summary(user_id: str) -> str:
    """Build a text summary of saved agents for context injection into prompts.

    Returns a string listing all saved agents the user has.
    """
    agents = await get_agents(user_id)
    if not agents:
        return "No saved agents yet."

    lines = [f"User has {len(agents)} saved agent(s):"]
    for a in agents[:10]:
        lines.append(
            f"  - \"{a['agentName']}\" (intent={a['intent']}, "
            f"used {a['usageCount']} times, "
            f"{len(a.get('steps', []))} steps)"
        )
    return "\n".join(lines)


def _normalize(text: str) -> str:
    """Normalize a prompt string for matching — lowercase, strip punctuation."""
    import re
    return re.sub(r"[^a-z0-9\s]", "", text.lower().strip())
