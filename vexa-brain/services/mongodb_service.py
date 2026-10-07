"""
MongoDB service — shared connection for Vexa Brain (Org items, situations).

Saved agents (phone automation replays) were removed along with phone automation.
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


async def disconnect():
    if _client:
        _client.close()


def get_db():
    """The connected database, or None if MongoDB isn't connected."""
    return _db
