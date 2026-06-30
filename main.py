from core.tts import speak, preload

# Preload F5-TTS BEFORE any other ML libraries (like Whisper) are loaded.
# This avoids the pyarrow Windows access violation.
preload()

from config import RESPONSE_FILE
from core.stt import load_whisper, speech_to_text
from core.audio import record_audio
from core.memory import load_memory
from core.contacts import load_contacts
from core.brain import Brain

# ------------------------------------------
# LLM Provider — uncomment ONE of these:
# ------------------------------------------

# Option A: Local LLM (Ollama + qwen3:4b)
#from core.llm import Conversation

# Option B: Cloud LLM (Gemini 2.5 Flash) — faster, smarter
from core.cloud_llm import Conversation

# ------------------------------------------

from actions.registry import ToolRegistry
from actions.email_action import EmailTool
from actions.inbox_action import InboxTool


# ==========================================
# INIT
# ==========================================

whisper = load_whisper()

contacts = load_contacts()

# Register tools
tools = ToolRegistry()
tools.register("send_email", EmailTool(contacts=contacts))
tools.register("check_inbox", InboxTool())

# Create conversation with a placeholder prompt (Brain will set the real one)
convo = Conversation(system_prompt="Loading...")

# Create the brain — it builds the real system prompt
brain = Brain(conversation=convo, tools=tools)

print("Vexa Started\n")


# ==========================================
# MAIN LOOP
# ==========================================

while True:

    try:

        audio_file = record_audio()

        user_text = speech_to_text(whisper, audio_file)

        if not user_text:
            print("Didn't catch that.")
            continue

        print("\nYou:", user_text)

        # The brain handles EVERYTHING:
        # Think -> decide tool -> execute -> respond -> learn
        answer = brain.think(user_text)

        print("\nVexa:", answer)

        with open(RESPONSE_FILE, "w", encoding="utf-8") as f:
            f.write(answer)

        speak(answer)

    except KeyboardInterrupt:
        print("\nGoodbye.")
        break

    except Exception as e:
        print("\nERROR:", e)