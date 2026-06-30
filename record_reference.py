"""
Record a reference audio clip for F5-TTS voice cloning.

This records 10-15 seconds of your voice. Speak clearly and naturally.
The recording will be saved to voices/vamsi_reference.wav.

After recording, set F5_REFERENCE_TEXT in config.py to EXACTLY what you said.

Usage: python record_reference.py
"""

import os
import sounddevice as sd
import soundfile as sf
import numpy as np

from config import F5_REFERENCE_AUDIO


SAMPLE_RATE = 24000  # F5-TTS prefers 24kHz
DURATION_HINT = 20   # Suggest ~12 seconds


def record():
    """Record a reference audio clip for voice cloning."""

    # Ensure voices directory exists
    os.makedirs(os.path.dirname(F5_REFERENCE_AUDIO), exist_ok=True)

    print("=" * 55)
    print("  F5-TTS Voice Reference Recording")
    print("=" * 55)
    print()
    print("  This records a ~12 second clip of your voice.")
    print("  Speak clearly and naturally. Say a few sentences.")
    print()
    print("  Example text you could read:")
    print('  "Hi, my name is Brahma Vamsi. I am a full stack')
    print('   developer working at Cognizant. I love building')
    print('   AI assistants and automation tools. Vexa is my')
    print('   personal AI assistant that I am building."')
    print()
    print("  IMPORTANT: After recording, set F5_REFERENCE_TEXT")
    print("  in config.py to EXACTLY what you said.")
    print()

    input("  Press ENTER when ready to record...")

    print(f"\n  Recording for {DURATION_HINT} seconds...")
    print("  Speak now!\n")

    audio = sd.rec(
        int(DURATION_HINT * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )

    sd.wait()

    print("  Recording complete!")

    # Trim silence from the end
    audio = audio.flatten()

    # Normalize volume
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = audio / max_val * 0.9

    # Save
    sf.write(F5_REFERENCE_AUDIO, audio, SAMPLE_RATE)

    print(f"\n  Saved to: {F5_REFERENCE_AUDIO}")
    print(f"  Duration: {len(audio) / SAMPLE_RATE:.1f} seconds")
    print()
    print("  Next step:")
    print("  Open config.py and set F5_REFERENCE_TEXT to")
    print("  EXACTLY what you said in this recording.")
    print()


if __name__ == "__main__":
    record()
