import os

from config import MEMORY_FILE


def load_memory():
    """Load memory from file. Creates file if it doesn't exist."""

    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            pass

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return f.read()


def update_memory(user_text):
    """Save user text to memory if it contains trigger phrases."""

    triggers = [
        "remember",
        "my name is",
        "i am",
        "my favorite",
        "don't forget"
    ]

    lower = user_text.lower()

    if any(trigger in lower for trigger in triggers):
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write("\n" + user_text)

        print("Memory Updated")
