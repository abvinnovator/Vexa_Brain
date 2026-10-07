"""Vexa Org endpoints — capture, overview (the orbit), and item CRUD."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from models.org_models import OrgCaptureRequest, OrgCaptureResponse, OrgItem, OrgItemUpsert, OrgOverview
from services import org_service

router = APIRouter()


@router.post("/org/capture", response_model=OrgCaptureResponse)
async def capture(request: OrgCaptureRequest):
    """'Tell VXA anything' — files free text into the right area(s) and learns from it."""
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text is empty")
    return await org_service.capture(request.userId, request.text.strip(), request.now, request.area)


@router.get("/org/{user_id}", response_model=OrgOverview)
async def overview(user_id: str, now: Optional[str] = None):
    """Areas with situation lines and attention flags, plus open (and recently done) items."""
    return await org_service.overview(user_id, now)


@router.put("/org/items/{item_id}", response_model=OrgItem)
async def upsert_item(item_id: str, body: OrgItemUpsert):
    """Create or update an item. The client owns the id so offline-created items sync cleanly."""
    return await org_service.upsert(item_id, body)


@router.delete("/org/items/{item_id}")
async def delete_item(item_id: str, userId: str):
    if not await org_service.delete(item_id, userId):
        raise HTTPException(status_code=404, detail="item not found")
    return {"deleted": item_id}
