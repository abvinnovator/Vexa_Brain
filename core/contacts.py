import json
import os

from config import CONTACTS_FILE


def load_contacts():
    """Load contacts from JSON file."""

    if not os.path.exists(CONTACTS_FILE):
        with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return {}

    with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_contact(name, contacts):
    """
    Fuzzy-match a spoken name to a contact.

    Handles cases like:
      - "vamsi" → vamsiaratipamula@gmail.com
      - "Vamsi" → vamsiaratipamula@gmail.com
      - "vampsi" → vamsiaratipamula@gmail.com (fuzzy)

    Returns the email address or None.
    """

    if not name or not contacts:
        return None

    name_lower = name.lower().strip()

    # Exact match (case-insensitive)
    for contact_name, email in contacts.items():
        if contact_name.lower() == name_lower:
            return email

    # Partial match — name starts with or contains contact name
    for contact_name, email in contacts.items():
        cn = contact_name.lower()
        if cn in name_lower or name_lower in cn:
            return email

    # Fuzzy match — simple edit distance for typos like "vampsi" → "vamsi"
    best_match = None
    best_score = float("inf")

    for contact_name, email in contacts.items():
        distance = _edit_distance(name_lower, contact_name.lower())
        # Allow up to 2 character edits for short names, 3 for longer
        max_allowed = 2 if len(contact_name) <= 5 else 3

        if distance <= max_allowed and distance < best_score:
            best_score = distance
            best_match = email

    return best_match


def _edit_distance(s1, s2):
    """Compute Levenshtein edit distance between two strings."""

    if len(s1) < len(s2):
        return _edit_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    prev_row = range(len(s2) + 1)

    for i, c1 in enumerate(s1):
        curr_row = [i + 1]

        for j, c2 in enumerate(s2):
            # Cost is 0 if characters match, 1 otherwise
            cost = 0 if c1 == c2 else 1
            curr_row.append(min(
                curr_row[j] + 1,        # Insert
                prev_row[j + 1] + 1,    # Delete
                prev_row[j] + cost      # Replace
            ))

        prev_row = curr_row

    return prev_row[-1]
