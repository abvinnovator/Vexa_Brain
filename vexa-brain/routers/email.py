"""
Email Router — send emails and check inbox via API.

POST /api/email/send  — Send an email via Gmail SMTP
POST /api/email/inbox — Check Gmail inbox via IMAP
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from models.email_models import (
    EmailSendRequest, EmailSendResponse,
    InboxRequest, InboxResponse, EmailEntry
)
from services import email_service
import logging
import json
import re

router = APIRouter()
logger = logging.getLogger(__name__)


def robust_parse_json(body_str: str) -> dict:
    try:
        return json.loads(body_str)
    except json.JSONDecodeError:
        try:
            # Allow raw control characters like unescaped newlines
            return json.loads(body_str, strict=False)
        except json.JSONDecodeError:
            # Fallback: manually escape unescaped newlines and tabs
            cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', lambda m: f'\\u{ord(m.group(0)):04x}', body_str)
            return json.loads(cleaned, strict=False)


@router.post("/email/send")
async def send_email(request: Request):
    """
    Send an email via Gmail SMTP.
    """
    body_bytes = b""
    try:
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8", errors="replace")
        
        try:
            data = robust_parse_json(body_str)
        except Exception as e:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": f"JSON Decode Error: {str(e)}",
                    "raw_body_received": body_str,
                    "body_length": len(body_bytes)
                }
            )
            
        payload = EmailSendRequest(**data)
        logger.info(f"Email send request: to={payload.to}, subject={payload.subject[:50]}")

        result = await email_service.send_email(
            to=payload.to,
            subject=payload.subject,
            body=payload.body
        )

        return EmailSendResponse(
            success=result["success"],
            error=result.get("error"),
            message=result.get("message", "")
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Server Error: {str(e)}",
                "body_length": len(body_bytes)
            }
        )


@router.post("/email/inbox")
async def check_inbox(request: Request):
    """
    Check Gmail inbox via IMAP.
    """
    body_bytes = b""
    try:
        body_bytes = await request.body()
        data = robust_parse_json(body_bytes.decode("utf-8", errors="replace"))
        payload = InboxRequest(**data)
    except Exception as e:
        return JSONResponse(
            status_code=400, 
            content={
                "success": False, 
                "error": f"Inbox JSON Error: {str(e)}",
                "body_length": len(body_bytes)
            }
        )

    logger.info(f"Inbox check request: search='{payload.search}', max={payload.maxResults}")

    result = await email_service.check_inbox(
        search_term=payload.search,
        max_results=payload.maxResults
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
