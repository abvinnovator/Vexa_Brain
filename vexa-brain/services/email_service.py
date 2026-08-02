"""
Email Service — async Gmail SMTP send + IMAP inbox.

Ported from the original Vexa actions/email_action.py and actions/inbox_action.py
for use in the FastAPI-based vexa-brain architecture.
"""

import re
import smtplib
import imaplib
import email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
import asyncio
import logging

from config import settings

logger = logging.getLogger(__name__)


# ── Send Email via Gmail SMTP ──────────────────────────────

async def send_email(to: str, subject: str, body: str) -> dict:
    """
    Send an email via Gmail SMTP SSL.

    Returns: {"success": bool, "error": str|None, "message": str}
    """
    if not settings.gmail_address or not settings.gmail_app_password:
        return {
            "success": False,
            "error": "Gmail credentials not configured. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD.",
            "message": ""
        }

    # Validate email format
    if not re.match(r"[\w.\-+]+@[\w.\-]+\.\w+", to):
        return {
            "success": False,
            "error": f"Invalid email address: {to}",
            "message": ""
        }

    # Run blocking SMTP in thread pool
    loop = asyncio.get_event_loop()
    success, error = await loop.run_in_executor(None, _smtp_send, to, subject, body)

    if success:
        logger.info(f"Email sent to {to}: {subject}")
        return {
            "success": True,
            "error": None,
            "message": f"Email sent successfully to {to}."
        }
    else:
        logger.error(f"Email send failed to {to}: {error}")
        return {
            "success": False,
            "error": error,
            "message": ""
        }


def _smtp_send(to: str, subject: str, body: str) -> tuple:
    """Blocking SMTP send. Returns (success: bool, error: str|None)."""
    try:
        msg = MIMEMultipart()
        msg["From"] = settings.gmail_address
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.gmail_address, settings.gmail_app_password)
            server.send_message(msg)

        return True, None

    except smtplib.SMTPAuthenticationError:
        return False, "Auth failed. Check Gmail App Password."
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except Exception as e:
        return False, str(e)


# ── Check Inbox via Gmail IMAP ─────────────────────────────

async def check_inbox(search_term: str = "", max_results: int = 5) -> dict:
    """
    Fetch emails from Gmail inbox via IMAP.

    Returns: {"success": bool, "emails": list[dict], "error": str|None}
    """
    if not settings.gmail_address or not settings.gmail_app_password:
        return {
            "success": False,
            "emails": [],
            "error": "Gmail credentials not configured."
        }

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _imap_fetch, search_term, max_results)

    return result


def _imap_fetch(search_term: str, max_results: int) -> dict:
    """Blocking IMAP fetch. Returns dict with emails list."""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(settings.gmail_address, settings.gmail_app_password)
        mail.select("INBOX")

        if search_term:
            criteria = f'FROM "{search_term}"'
        else:
            criteria = "ALL"

        status, msg_ids = mail.search(None, criteria)

        if status != "OK" or not msg_ids[0]:
            mail.logout()
            return {"success": True, "emails": [], "error": None}

        ids = msg_ids[0].split()
        ids = ids[-max_results:]

        results = []

        for eid in reversed(ids):
            status, data = mail.fetch(eid, "(RFC822)")

            if status != "OK":
                continue

            msg = email_lib.message_from_bytes(data[0][1])

            from_decoded = _decode_header_value(msg.get("From", "Unknown"))
            subject_decoded = _decode_header_value(msg.get("Subject", "(No Subject)"))

            date_raw = msg.get("Date", "")
            try:
                date_parsed = email_lib.utils.parsedate_to_datetime(date_raw)
                date_str = date_parsed.strftime("%d-%b-%Y")
                date_time = date_parsed.strftime("%I:%M %p")
            except Exception:
                date_str = "Unknown"
                date_time = ""

            body = _get_body(msg)

            results.append({
                "from": from_decoded,
                "subject": subject_decoded,
                "date": date_str,
                "time": date_time,
                "body": body,
            })

        mail.logout()

        logger.info(f"Inbox fetched: {len(results)} emails (search='{search_term}')")
        return {"success": True, "emails": results, "error": None}

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error: {e}")
        return {"success": False, "emails": [], "error": f"IMAP error: {e}"}
    except Exception as e:
        logger.error(f"Inbox fetch error: {e}")
        return {"success": False, "emails": [], "error": str(e)}


def _decode_header_value(raw: str) -> str:
    """Decode email header value."""
    parts = decode_header(raw)
    decoded = []
    for part, encoding in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _get_body(msg, max_len: int = 500) -> str:
    """Extract text body from email."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body = part.get_payload(decode=True)
                    text = body.decode("utf-8", errors="replace").strip()
                    text = " ".join(text.split())
                    return text[:max_len]
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True)
            text = body.decode("utf-8", errors="replace").strip()
            text = " ".join(text.split())
            return text[:max_len]
        except Exception:
            pass

    return "(No content)"
