"""
Inbox Tool — checks Gmail inbox via IMAP.

Called by the Brain when the LLM decides to check emails.
No regex intent detection — the LLM decides.
"""

import imaplib
import email
from email.header import decode_header
from datetime import datetime

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, MEMORY_FILE


class InboxTool:
    """
    Checks Gmail inbox via IMAP.

    The LLM provides: search term.
    This tool fetches top 2 emails, returns raw data to the Brain.
    The LLM then summarizes and responds naturally.
    """

    def describe(self):
        """Tool description for the LLM system prompt."""

        return (
            "Search Vamsi's Gmail inbox for emails.\n"
            "Params: search (sender name or keyword to search for)\n"
            "Use when Vamsi asks about emails, mail, inbox, or received messages.\n"
            "Returns the top 2 most recent matching emails with full details.\n"
            "Example: ACTION: check_inbox | search: cognizant"
        )

    def execute(self, params):
        """
        Fetch emails matching search term.

        params: dict with key 'search'
        Returns: formatted string with email details for the LLM.
        """

        search_term = params.get("search", "").strip()

        if not search_term:
            print("\n  No search term. Fetching recent inbox...")

        print(f"\n  Checking inbox{f' for: {search_term}' if search_term else ''}...")

        emails = self._fetch_emails(search_term, max_results=2)

        if emails is None:
            return "Failed to connect to Gmail. Check credentials."

        if not emails:
            return f"No emails found{f' from {search_term}' if search_term else ''}."

        # Display in terminal
        self._display(emails, search_term)

        # Store in memory
        self._store_in_memory(emails, search_term)

        # Return raw data for LLM to summarize naturally
        result = f"Found {len(emails)} email(s){f' from {search_term}' if search_term else ''}:\n\n"

        for i, e in enumerate(emails, 1):
            result += f"Email {i}:\n"
            result += f"  From: {e['from']}\n"
            result += f"  Subject: {e['subject']}\n"
            result += f"  Date: {e['date_str']} at {e['time']}\n"
            result += f"  Content: {e['body']}\n\n"

        return result

    # ------------------------------------------
    # IMAP fetching (from working test_imap.py)
    # ------------------------------------------

    def _fetch_emails(self, search_term, max_results=2):
        """Connect to Gmail IMAP and fetch emails."""

        if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
            print("  Gmail credentials not configured.")
            return None

        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            mail.select("INBOX")

            if search_term:
                criteria = f'FROM "{search_term}"'
            else:
                criteria = "ALL"

            status, msg_ids = mail.search(None, criteria)

            if status != "OK" or not msg_ids[0]:
                mail.logout()
                return []

            ids = msg_ids[0].split()
            ids = ids[-max_results:]

            results = []

            for eid in reversed(ids):
                status, data = mail.fetch(eid, "(RFC822)")

                if status != "OK":
                    continue

                msg = email.message_from_bytes(data[0][1])

                from_decoded = self._decode_header(msg.get("From", "Unknown"))
                subject_decoded = self._decode_header(msg.get("Subject", "(No Subject)"))

                date_raw = msg.get("Date", "")
                try:
                    date_parsed = email.utils.parsedate_to_datetime(date_raw)
                    date_str = date_parsed.strftime("%d-%b-%Y")
                    date_time = date_parsed.strftime("%I:%M %p")
                except Exception:
                    date_str = "Unknown"
                    date_time = ""

                body = self._get_body(msg)

                results.append({
                    "from": from_decoded,
                    "subject": subject_decoded,
                    "date_str": date_str,
                    "time": date_time,
                    "body": body,
                })

            mail.logout()
            return results

        except imaplib.IMAP4.error as e:
            print(f"  IMAP error: {e}")
            return None
        except Exception as e:
            print(f"  Error: {e}")
            return None

    def _decode_header(self, raw):
        """Decode email header."""
        parts = decode_header(raw)
        decoded = []
        for part, encoding in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return " ".join(decoded)

    def _get_body(self, msg, max_len=500):
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

    # ------------------------------------------

    def _display(self, emails, search_term):
        """Display fetched emails in terminal."""

        border = "=" * 55
        title = f"Inbox ({len(emails)} found)"

        print(f"\n  {border}")
        print(f"  {title:^55}")
        if search_term:
            src = f"(from: {search_term})"
            print(f"  {src:^55}")
        print(f"  {border}")

        for i, e in enumerate(emails, 1):
            print(f"\n  [{i}] {e['subject']}")
            print(f"      From : {e['from']}")
            print(f"      Date : {e['date_str']}  {e['time']}")

        print(f"\n  {border}")

    def _store_in_memory(self, emails, search_term):
        """Store email findings in memory."""

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [f"\n[Inbox Check - {timestamp}]"]

        if search_term:
            lines.append(f"Searched for: {search_term}")

        for e in emails:
            lines.append(f"- {e['subject']} (from: {e['from']}, {e['date_str']} {e['time']})")

        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        print("  Mail info stored in memory.")
