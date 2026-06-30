"""
Local LLM Provider — Ollama

Manages conversation with Ollama (qwen3:4b or any local model).
Accepts external system prompt from Brain.
"""

from ollama import chat

from config import LLM_MODEL, MAX_HISTORY


class Conversation:
    """Manages Ollama conversation with externally-provided system prompt."""

    def __init__(self, system_prompt):
        self.system_prompt = system_prompt
        self.history = [{"role": "system", "content": system_prompt}]

    def update_system_prompt(self, system_prompt):
        """Update system prompt (called when memory/profile changes)."""
        self.system_prompt = system_prompt
        self.history[0] = {"role": "system", "content": system_prompt}

    def ask(self, user_text):
        """Send a message and get a response (adds to conversation history)."""

        self.history.append({
            "role": "user",
            "content": user_text
        })

        # Trim history
        if len(self.history) > MAX_HISTORY:
            self.history = [self.history[0]] + self.history[-(MAX_HISTORY - 1):]

        response = chat(
            model=LLM_MODEL,
            messages=self.history
        )

        answer = response["message"]["content"]

        self.history.append({
            "role": "assistant",
            "content": answer
        })

        return answer

    def quick_ask(self, prompt):
        """One-shot LLM call — no history, used for learning/analysis."""

        response = chat(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}]
        )

        return response["message"]["content"]
