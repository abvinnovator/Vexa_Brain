"""
Self-Learning System — Vexa learns from every conversation.

After each turn, analyzes the user's message for:
- Key facts (personal info, events, milestones)
- Speech patterns (slang, phrasing, style)
- Preferences (how they like things done)

Stores insights in memory.txt and speech_profile.md.
"""

import os

from config import MEMORY_FILE, SPEECH_PROFILE_FILE
from core.prompts import build_learn_prompt


class Learner:
    """Extracts and stores insights from each conversation turn."""

    def __init__(self):
        # Ensure speech profile exists
        if not os.path.exists(SPEECH_PROFILE_FILE):
            with open(SPEECH_PROFILE_FILE, "w", encoding="utf-8") as f:
                f.write("# Vamsi's Speech Profile\n\n")

    def learn(self, user_text, quick_ask_fn):
        """
        Analyze user text and store any new insights.

        Args:
            user_text: What the user said
            quick_ask_fn: One-shot LLM call (doesn't affect conversation)
        """

        # Skip very short messages — nothing to learn
        if len(user_text.split()) < 4:
            return

        prompt = build_learn_prompt(user_text)

        try:
            response = quick_ask_fn(prompt)
        except Exception as e:
            print(f"  [Learner] Error: {e}")
            return

        # Parse response
        response = response.strip()

        if "NOTHING_NEW" in response:
            return

        facts = []
        speech_patterns = []
        preferences = []

        for line in response.split("\n"):
            line = line.strip()

            if line.startswith("KEY_FACT:"):
                fact = line[9:].strip()
                if fact:
                    facts.append(fact)

            elif line.startswith("SPEECH:"):
                pattern = line[7:].strip()
                if pattern:
                    speech_patterns.append(pattern)

            elif line.startswith("PREFERENCE:"):
                pref = line[11:].strip()
                if pref:
                    preferences.append(pref)

        # Store facts and preferences in memory.txt
        if facts or preferences:
            self._append_to_memory(facts, preferences)

        # Store speech patterns in speech_profile.md
        if speech_patterns:
            self._append_to_speech_profile(speech_patterns)

    def _append_to_memory(self, facts, preferences):
        """Append new facts and preferences to memory.txt."""

        lines = []

        if facts:
            for fact in facts:
                lines.append(fact)

        if preferences:
            for pref in preferences:
                lines.append(f"Preference: {pref}")

        if lines:
            with open(MEMORY_FILE, "a", encoding="utf-8") as f:
                f.write("\n" + "\n".join(lines))
            print(f"  [Learned] {len(lines)} new insight(s) stored in memory")

    def _append_to_speech_profile(self, patterns):
        """Append new speech patterns to speech_profile.md."""

        with open(SPEECH_PROFILE_FILE, "a", encoding="utf-8") as f:
            for pattern in patterns:
                f.write(f"\n- {pattern}")

        print(f"  [Learned] {len(patterns)} speech pattern(s) noted")
