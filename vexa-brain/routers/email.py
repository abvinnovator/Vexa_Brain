"""
Email Router — send emails and check inbox via API.

POST /api/email/send  — Send an email via Gmail SMTP
POST /api/email/inbox — Check Gmail inbox via IMAP
"""

from fastapi import APIRouter
from models.email_models import (
    EmailSendRequest, EmailSendResponse,
    InboxRequest, InboxResponse, EmailEntry
)
from services import email_service
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/email/send", response_model=EmailSendResponse)
async def send_email(request: EmailSendRequest):
    """
    Send an email via Gmail SMTP.

    Called by the Android app after the user approves the email draft.
    """
    logger.info(f"Email send request: to={request.to}, subject={request.subject[:50]}")

    result = await email_service.send_email(
        to=request.to,
        subject=request.subject,
        body=request.body
    )

    return EmailSendResponse(
        success=result["success"],
        error=result.get("error"),
        message=result.get("message", "")
    )


@router.post("/email/inbox", response_model=InboxResponse)
async def check_inbox(request: InboxRequest):
    """
    Check Gmail inbox via IMAP.

    Returns the most recent emails matching the search term.
    """
    logger.info(f"Inbox check request: search='{request.search}', max={request.maxResults}")

    result = await email_service.check_inbox(
        search_term=request.search,
        max_results=request.maxResults
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
