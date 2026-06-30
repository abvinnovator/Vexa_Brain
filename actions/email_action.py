"""
Email Tool — sends emails via Gmail SMTP.

Called by the Brain when the LLM decides to send an email.
No regex intent detection — the LLM decides.
"""

import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD
from core.contacts import resolve_contact


class EmailTool:
    """
    Sends email via Gmail SMTP.

    The LLM provides: to, subject, body.
    This tool resolves contacts, shows preview, confirms, and sends.
    """

    def __init__(self, contacts=None):
        self.contacts = contacts or {}

    def describe(self):
        """Tool description for the LLM system prompt."""

        contact_list = ", ".join(self.contacts.keys()) if self.contacts else "none"

        return (
            f"Send an email from Vamsi's Gmail ({GMAIL_ADDRESS}).\n"
            f"Known contacts: {contact_list}\n"
            f"Params: to (name or email), subject, body\n"
            f"Use when Vamsi wants to send, compose, or write an email.\n"
            f"Example: ACTION: send_email | to: vamsi | subject: Quick hello | body: Hi there!"
        )

    def execute(self, params):
        """
        Send email with given params.

        params: dict with keys 'to', 'subject', 'body'
        """

        to_raw = params.get("to", "").strip()
        subject = params.get("subject", "(No Subject)").strip()
        body = params.get("body", "(No content)").strip()

        if not to_raw:
            return "No recipient specified."

        # Resolve address — contact name or direct email
        to_address = self._resolve(to_raw)

        if not to_address:
            return f"Could not resolve recipient: {to_raw}. Please try again."

        # Show preview
        self._show_preview(to_address, subject, body)

        # Confirm
        confirm = input("\n  Send this email? (y/n): ").strip().lower()

        if confirm != "y":
            print("\n  Email cancelled.")
            return "Email cancelled by user."

        # Send
        success, error = self._send(to_address, subject, body)

        if success:
            print(f"\n  Email sent to {to_address}!")
            return f"Email sent successfully to {to_address}."
        else:
            print(f"\n  Failed: {error}")
            return f"Failed to send email: {error}"

    # ------------------------------------------

    def _resolve(self, to_raw):
        """Resolve recipient — try contact lookup, then direct email."""

        # Check if it's already a valid email
        if re.match(r"[\w.-]+@[\w.-]+\.\w+", to_raw):
            return to_raw

        # Try contact lookup
        email = resolve_contact(to_raw, self.contacts)
        if email:
            print(f"\n  [Contact resolved] {to_raw} -> {email}")
            return email

        return None

    def _show_preview(self, to_address, subject, body):
        """Display email preview in terminal."""

        border = "=" * 45

        print(f"\n  {border}")
        print(f"  {'Email Preview':^45}")
        print(f"  {border}")
        print(f"  From    : {GMAIL_ADDRESS}")
        print(f"  To      : {to_address}")
        print(f"  Subject : {subject}")
        print(f"  Body    : {body}")
        print(f"  {border}")

    def _send(self, to_address, subject, body):
        """Send via Gmail SMTP. Returns (success, error)."""

        if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
            return False, "Gmail credentials not configured."

        try:
            msg = MIMEMultipart()
            msg["From"] = GMAIL_ADDRESS
            msg["To"] = to_address
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
                server.send_message(msg)

            return True, None

        except smtplib.SMTPAuthenticationError:
            return False, "Auth failed. Check Gmail App Password."
        except smtplib.SMTPException as e:
            return False, f"SMTP error: {e}"
        except Exception as e:
            return False, str(e)
