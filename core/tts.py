"""
TTS Module — F5-TTS Voice Cloning with Piper Fallback.

Primary: F5-TTS (speaks in Vamsi's cloned voice)
Fallback: Piper (generic English voice)

F5-TTS needs:
- Reference audio: 10-15s clip of your voice (voices/vamsi_reference.wav)
- Reference text: What you said in that clip (set in config.py)
- ffmpeg installed (winget install Gyan.FFmpeg)
"""

import os

# Must be set before torch/torchaudio import anything that touches OpenMP.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import faulthandler
faulthandler.enable()

import shutil
import subprocess
import soundfile as sf
import torchaudio
import torch

from config import (
    OUTPUT_AUDIO,
    F5_REFERENCE_AUDIO,
    F5_REFERENCE_TEXT,
    PIPER_PATH,
    VOICE_PATH,
)

def _sf_load(filepath, *args, **kwargs):
    data, sr = sf.read(str(filepath), dtype="float32", always_2d=True)
    waveform = torch.from_numpy(data.T).contiguous()
    return waveform, sr

def _sf_save(filepath, src, sample_rate, *args, **kwargs):
    wav = src.detach().cpu().numpy()
    if wav.ndim == 2:
        wav = wav.T
    sf.write(str(filepath), wav, sample_rate)

torchaudio.load = _sf_load
torchaudio.save = _sf_save

# ==========================================
# F5-TTS Engine
# ==========================================
_f5_model = None
_f5_checked = False


def _load_f5():
    global _f5_model, _f5_checked

    if _f5_checked:
        return _f5_model is not None

    _f5_checked = True

    if not os.path.exists(F5_REFERENCE_AUDIO):
        print("  [TTS] Reference audio missing.")
        return False

    if not F5_REFERENCE_TEXT:
        print("  [TTS] F5_REFERENCE_TEXT missing.")
        return False

    try:
        print("  [TTS] Loading local F5-TTS model...")

        from f5_tts.api import F5TTS

        _f5_model = F5TTS(device="cpu")

        print("  [TTS] F5-TTS loaded successfully.")
        return True

    except Exception as e:
        print(f"  [TTS] Failed to load F5-TTS: {e}")
        return False


def preload():
    """
    Loads F5-TTS immediately, in whatever process state exists right now.

    Call this ONCE, as the very first thing in main.py, before Whisper or
    any other heavy ML library is loaded. F5-TTS transitively imports
    HuggingFace `datasets` -> `pyarrow.dataset`, and pyarrow's native
    extension has shown to crash (Windows access violation) when other
    native libraries (e.g. Whisper/ctranslate2) are already resident in
    the process. Loading F5-TTS first, in a clean process, avoids that
    conflict — same reason test_tts.py works standalone.
    """
    _load_f5()


def _speak_f5(text):
    try:
        _f5_model.infer(
            ref_file=F5_REFERENCE_AUDIO,
            ref_text=F5_REFERENCE_TEXT,
            gen_text=text,
            file_wave=OUTPUT_AUDIO
        )

        return os.path.exists(OUTPUT_AUDIO)

    except Exception as e:
        print(f"  [TTS] F5 generation error: {e}")
        return False

# ==========================================
# Piper TTS Engine (Fallback)
# ==========================================

def _speak_piper(text):
    """Generate speech using Piper TTS (fallback)."""

    try:
        subprocess.run(
            [
                PIPER_PATH,
                "--model",
                VOICE_PATH,
                "--output_file",
                OUTPUT_AUDIO
            ],
            input=text.encode("utf-8"),
            check=True
        )
        return True

    except Exception as e:
        print(f"  [TTS] Piper error: {e}")
        return False


# ==========================================
# Public API
# ==========================================
def speak(text):
    print("[DEBUG] speak() called")

    success = False

    print("[DEBUG] Trying F5...")
    if _load_f5():
        print("[DEBUG] F5 loaded")
        success = _speak_f5(text)
    else:
        print("[DEBUG] F5 not available")

    if not success:
        print("[DEBUG] Trying Piper...")
        success = _speak_piper(text)

    if not success:
        print("[DEBUG] All engines failed")
        return

    print("[DEBUG] Playing audio...")

    try:
        if not os.path.exists(OUTPUT_AUDIO):
            print("  [TTS] Output audio not found.")
            return

        data, samplerate = sf.read(OUTPUT_AUDIO)

        import sounddevice as sd
        sd.stop()
        sd.play(data, samplerate)
        sd.wait()

    except Exception as e:
        print(f"  [TTS] Playback error: {e}")