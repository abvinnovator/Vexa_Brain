"""
Email Router — send emails and check inbox via API.

POST /api/email/send  — Send an email via Gmail SMTP
POST /api/email/inbox — Check Gmail inbox via IMAP
"""

from fastapi import APIRouter, Request, HTTPException
from models.email_models import (
    EmailSendRequest, EmailSendResponse,
    InboxRequest, InboxResponse, EmailEntry
)
from services import email_service
import json
import re
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def parse_request_json(body_str: str) -> dict:
    """
    Robust JSON parser for request bodies.
    Handles unescaped control characters (like literal newlines inside multiline strings),
    unicode dashes, smart quotes, etc., preventing Starlette's strict 400 Bad Request error.
    """
    try:
        return json.loads(body_str)
    except Exception:
        try:
            # Fallback 1: Allow raw control characters (newlines, tabs) inside string literals
            return json.loads(body_str, strict=False)
        except Exception:
            # Fallback 2: Replace raw unescaped control characters with escaped equivalents
            cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', lambda m: f'\\u{ord(m.group(0)):04x}', body_str)
            return json.loads(cleaned, strict=False)


@router.post("/email/send", response_model=EmailSendResponse)
async def send_email(request: Request):
    """
    Send an email via Gmail SMTP.

    Called by the Android app after the user approves the email draft.
    Uses lenient JSON parsing to safely handle multiline email bodies.
    """
    try:
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8", errors="replace")
        data = parse_request_json(body_str)
        req = EmailSendRequest(**data)
    except Exception as e:
        logger.error(f"Failed to parse email send request: {e}")
        return EmailSendResponse(
            success=False,
            error=f"Invalid request format: {e}",
            message=""
        )

    logger.info(f"Email send request: to={req.to}, subject={req.subject[:50]}")

    result = await email_service.send_email(
        to=req.to,
        subject=req.subject,
        body=req.body
    )

    return EmailSendResponse(
        success=result["success"],
        error=result.get("error"),
        message=result.get("message", "")
    )


@router.post("/email/inbox", response_model=InboxResponse)
async def check_inbox(request: Request):
    """
    Check Gmail inbox via IMAP.

    Returns the most recent emails matching the search term.
    """
    try:
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8", errors="replace")
        data = parse_request_json(body_str)
        req = InboxRequest(**data)
    except Exception as e:
        logger.error(f"Failed to parse inbox request: {e}")
        return InboxResponse(
            success=False,
            emails=[],
            error=f"Invalid request format: {e}"
        )

    logger.info(f"Inbox check request: search='{req.search}', max={req.maxResults}")

    result = await email_service.check_inbox(
        search_term=req.search,
        max_results=req.maxResults
    )

    emails = []
    for e in result.get("emails", []):
        emails.append(EmailEntry(
            sender=e.get("from", "Unknown"),
            subject=e.get("subject", "(No Subject)"),
            date=e.get("date", ""),
            time=e.get("time", ""),
            body=e.get("body", "")
        ))

    return InboxResponse(
        success=result["success"],
        emails=emails,
        error=result.get("error")
    )
