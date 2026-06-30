from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db = None


async def connect(uri: str, db_name: str):
    global _client, _db
    _client = AsyncIOMotorClient(uri)
    _db = _client[db_name]
    logger.info(f"Connected to MongoDB: {db_name}")


async def disconnect():
    if _client:
        _client.close()


async def get_recent_events(user_id: str, hours: int = 48) -> List[Dict]:
    """Fetch recent accessibility events for behavioral context."""
    if _db is None:
        return []
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    cursor = _db.events.find(
        {"userId": user_id, "timestamp": {"$gte": cutoff_ms}},
        # Only fetch fields needed for context (not screenTexts bloat)
        {"packageName": 1, "appName": 1, "eventType": 1,
         "typedText": 1, "fieldHint": 1, "buttonLabel": 1,
         "screenTitle": 1, "screenName": 1, "timestamp": 1,
         "sessionId": 1, "screenTexts": 1, "_id": 0}
    ).sort("timestamp", -1).limit(200)

    return await cursor.to_list(length=200)


async def get_app_usage_frequency(user_id: str, days: int = 7) -> List[Dict]:
    """Returns top apps by event count over the last N days."""
    if _db is None:
        return []
    cutoff_ms = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)

    pipeline = [
        {"$match": {"userId": user_id, "timestamp": {"$gte": cutoff_ms}}},
        {"$group": {"_id": "$packageName", "appName": {"$first": "$appName"},
                    "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    cursor = _db.events.aggregate(pipeline)
    return await cursor.to_list(length=10)


async def get_uber_destinations(user_id: str) -> List[str]:
    """Extract recent Uber destination searches from events."""
    if _db is None:
        return []
    cursor = _db.events.find(
        {"userId": user_id, "packageName": "com.ubercab",
         "typedText": {"$exists": True, "$ne": None}},
        {"typedText": 1, "_id": 0}
    ).sort("timestamp", -1).limit(20)
    events = await cursor.to_list(length=20)
    return list({e["typedText"] for e in events if e.get("typedText")})


async def get_recent_sessions(user_id: str, limit: int = 5) -> List[Dict]:
    """Get recent session summaries for workflow reconstruction."""
    if _db is None:
        return []
    pipeline = [
        {"$match": {"userId": user_id}},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": "$sessionId",
            "apps": {"$addToSet": "$appName"},
            "startTime": {"$min": "$timestamp"},
            "endTime": {"$max": "$timestamp"},
            "eventCount": {"$sum": 1}
        }},
        {"$sort": {"startTime": -1}},
        {"$limit": limit}
    ]
    cursor = _db.events.aggregate(pipeline)
    return await cursor.to_list(length=limit)


async def get_typed_searches(user_id: str, package_name: str) -> List[str]:
    """Get text typed in a specific app (e.g. food searches in Blinkit)."""
    if _db is None:
        return []
    cursor = _db.events.find(
        {"userId": user_id, "packageName": package_name,
         "typedText": {"$exists": True, "$ne": None}},
        {"typedText": 1, "_id": 0}
    ).sort("timestamp", -1).limit(20)
    events = await cursor.to_list(length=20)
    return list({e["typedText"] for e in events if e.get("typedText")})
