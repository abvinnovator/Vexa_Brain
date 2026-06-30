"""Quick pattern test for the exact phrases Whisper transcribed."""
import sys
sys.path.insert(0, ".")

from actions.inbox_action import InboxAction

a = InboxAction()

# These are the EXACT phrases from the terminal logs
whisper_phrases = [
    "Check any mails that come from commission.",
    "Check any mails that come from Cognizant.",
    "Check any mails that come from cognizant today.",
    "check my mail from cognizant",
    "any mails from google",
    "did I get any email from HR",
    "check inbox",
]

print("Intent matching:")
for t in whisper_phrases:
    matched = a.can_handle(t)
    term = a._extract_search_term(t) if matched else "-"
    status = "PASS" if matched else "FAIL"
    print(f"  {status}: '{t}' -> search: '{term}'")
