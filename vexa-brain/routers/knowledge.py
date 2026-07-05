"""
Knowledge Router — endpoints for inspecting and managing the OKF knowledge base.

Useful for debugging, monitoring brain growth, and manual knowledge management.
"""

from fastapi import APIRouter
from services import knowledge_service
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/knowledge/stats")
async def knowledge_stats():
    """Return knowledge base statistics — useful for monitoring brain growth."""
    stats = knowledge_service.get_stats()
    return {
        "status": "ok",
        "knowledge_base": stats
    }


@router.get("/knowledge/tags")
async def knowledge_tags():
    """Return all indexed tags — useful for debugging retrieval."""
    tags = knowledge_service.get_all_tags()
    return {
        "total": len(tags),
        "tags": tags
    }


@router.get("/knowledge/query")
async def knowledge_query(q: str):
    """
    Test knowledge retrieval — shows what context would be injected
    for a given query. Useful for debugging.
    """
    context = await knowledge_service.query_relevant(q)
    return {
        "query": q,
        "context_length": len(context),
        "context": context
    }
