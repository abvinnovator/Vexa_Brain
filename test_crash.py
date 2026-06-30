import torchaudio
import soundfile as sf
import torch

def _sf_load(filepath, *args, **kwargs):
    data, sr = sf.read(str(filepath), dtype="float32", always_2d=True)
    waveform = torch.from_numpy(data.T).contiguous()
    return waveform, sr

def _sf_save(filepath, src, sample_rate, *args, **kwargs):
    wav = src.detach().cpu().numpy()
    if wav.ndim == 2:
        wav = wav.T  # soundfile expects (frames, channels)
    sf.write(str(filepath), wav, sample_rate)

torchaudio.load = _sf_load
torchaudio.save = _sf_save

from f5_tts.api import F5TTS

tts = F5TTS(device="cpu")
print("MODEL LOADED")
