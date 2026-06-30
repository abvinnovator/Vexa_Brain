import os
from dotenv import load_dotenv

load_dotenv()


# ==========================================
# GMAIL
# ==========================================

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")


# ==========================================
# PATHS
# ==========================================

MEMORY_FILE = "memory.txt"
CONTACTS_FILE = "contacts.json"
SPEECH_PROFILE_FILE = "speech_profile.md"
INPUT_AUDIO = "input.wav"
OUTPUT_AUDIO = "response.wav"
RESPONSE_FILE = "response.txt"


# ==========================================
# MODELS
# ==========================================

WHISPER_MODEL = "medium"
WHISPER_COMPUTE_TYPE = "int8"
WHISPER_THREADS = 4

LLM_MODEL = "qwen3:4b"
MAX_HISTORY = 20


# ==========================================
# CLOUD LLM (Gemini)
# ==========================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.5-flash"


# ==========================================
# TTS — F5-TTS (Voice Cloning)
# ==========================================

# Reference audio: 10-15 sec clip of YOUR voice
# Run: python record_reference.py to create this
F5_REFERENCE_AUDIO = "voices/vamsi_reference.wav"
F5_REFERENCE_TEXT = "Hi, my name is Brahma Vamsi. I am a full stack developer working at Cognizant. I love building AI assistants and automation tools. Vexa is my personal AI assistant that I am building"  # Set this to what you said in the reference audio

# ==========================================
# TTS — Piper (Fallback)
# ==========================================

PIPER_PATH = "piper/piper.exe"
VOICE_PATH = "voices/en_US-lessac-medium.onnx"
