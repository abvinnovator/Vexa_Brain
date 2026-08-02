"""
Email-related request/response models for the Vexa Brain API.
"""

from pydantic import BaseModel
from typing import Optional, List


class EmailSendRequest(BaseModel):
    to: str
    subject: str = "(No Subject)"
    body: str = ""


class EmailSendResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    message: str = ""


class EmailEntry(BaseModel):
    sender: str       # "from" is a Python keyword, use "sender"
    subject: str
    date: str
    time: str
    body: str


class InboxRequest(BaseModel):
    search: str = ""
    maxResults: int = 5


class InboxResponse(BaseModel):
    success: bool
    emails: List[EmailEntry] = []
    error: Optional[str] = None
