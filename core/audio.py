import sounddevice as sd
import soundfile as sf
import numpy as np

from config import INPUT_AUDIO


def record_audio():
    """Record audio from microphone until user presses ENTER."""

    print("\nPress ENTER to start recording...")
    input()

    print("Listening...")

    recording = []

    def callback(indata, frames, time, status):
        recording.append(indata.copy())

    stream = sd.InputStream(
        samplerate=16000,
        channels=1,
        callback=callback
    )

    stream.start()

    print("Press ENTER when finished speaking...")
    input()

    stream.stop()
    stream.close()

    audio = np.concatenate(recording, axis=0)

    sf.write(INPUT_AUDIO, audio, 16000)

    return INPUT_AUDIO
