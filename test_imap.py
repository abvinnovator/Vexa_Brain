import imaplib

from config import (
    GMAIL_ADDRESS,
    GMAIL_APP_PASSWORD
)
mail = imaplib.IMAP4_SSL(
    "imap.gmail.com",
    993
)

mail.login(
    GMAIL_ADDRESS,
    GMAIL_APP_PASSWORD
)

mail.select("INBOX")

status, msg_ids = mail.search(
    None,
    'FROM "cognizant"'
)

print(status)
print(msg_ids)

mail.logout()