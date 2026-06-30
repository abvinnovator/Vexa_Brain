"""
Cloud LLM Provider — Google Gemini

Manages conversation with Gemini (2.5 Flash or any Gemini model).
Accepts external system prompt from Brain.

Switch in main.py:
    # from core.llm import Conversation        # Local (Ollama)
    from core.cloud_llm import Conversation     # Cloud (Gemini)
"""

from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL, MAX_HISTORY,GROQ_API_KEY
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


# Configure Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)


class Conversation:
    """Manages Gemini conversation with externally-provided system prompt."""

    def __init__(self, system_prompt):
        self.system_prompt = system_prompt

        self.chat = client.chats.create(
            model=GEMINI_MODEL,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt
            )
        )

    def update_system_prompt(self, system_prompt):
        """Update system prompt (called when memory/profile changes)."""
        self.system_prompt = system_prompt

        # Preserve conversation history
        old_history = list(self.chat._curated_history) if self.chat._curated_history else []

        self.chat = client.chats.create(
            model=GEMINI_MODEL,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt
            ),
            history=old_history
        )

    def ask(self, user_text):
        """Send a message and get a response (adds to conversation history)."""

        # Trim history if too long
        if self.chat._curated_history and len(self.chat._curated_history) > MAX_HISTORY * 2:
            trimmed = list(self.chat._curated_history)[-(MAX_HISTORY * 2):]
            self.chat = client.chats.create(
                model=GEMINI_MODEL,
                config=genai.types.GenerateContentConfig(
                    system_instruction=self.system_prompt
                ),
                history=trimmed
            )

        try:
            response = self.chat.send_message(user_text)
            return response.text
        except Exception as e:
            print(f"Gemini API error ({e}). Falling back to Groq API...")
            return self._fallback_groq(user_text, include_system=True)

    def quick_ask(self, prompt):
        """One-shot LLM call — no history, used for learning/analysis."""

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            return response.text
        except Exception as e:
            print(f"Gemini API error ({e}). Falling back to Groq API...")
            return self._fallback_groq(prompt, include_system=False)

    def _fallback_groq(self, prompt, include_system=True):
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if include_system and self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
            
        messages.append({"role": "user", "content": prompt})
            
        payload = {
            "model": GROQ_MODEL,
            "messages": messages,
            "temperature": 0.7
        }
        
        try:
            res = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"]
        except Exception as fallback_err:
            print(f"Groq Fallback API error: {fallback_err}")
            return "I'm having trouble connecting to both my primary and fallback AI services right now."
