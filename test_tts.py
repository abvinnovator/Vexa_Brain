"""Test local TTS module implementation."""
import sys
sys.path.insert(0, ".")

from core.tts import speak
print("Testing TTS Engine...")
speak("Hello VEXAS, this is a test of the local voice cloning system from vexa running f5 tts test.")
print("TTS test complete.")