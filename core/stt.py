import os
import warnings

from faster_whisper import WhisperModel

from config import WHISPER_MODEL, WHISPER_COMPUTE_TYPE, WHISPER_THREADS

# Suppress noisy HuggingFace symlink warning on Windows
warnings.filterwarnings("ignore", message=".*symlinks.*")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


def load_whisper():
    """Load Whisper model once at startup."""

    print(f"Loading Whisper ({WHISPER_MODEL})...")
    print("  First run downloads the model (~1.5GB). One-time only.")

    model = WhisperModel(
        WHISPER_MODEL,
        compute_type=WHISPER_COMPUTE_TYPE,
        cpu_threads=WHISPER_THREADS
    )

    print("  Whisper loaded.")
    return model


def speech_to_text(model, file_path):
    """Transcribe audio file to text."""

    segments, _ = model.transcribe(
        file_path,
        beam_size=5,
        vad_filter=True,
        language="en",
        initial_prompt=(
            "Vexa AI assistant. "
            "Send email to vamsi at gmail dot com. "
            "Subject, body, content, message. "
            "at the rate, at sign, dot com, dot in. "
            "gmail.com, outlook.com, yahoo.com."
        )
    )

    text = ""

    for segment in segments:
        text += segment.text

    return text.strip()
