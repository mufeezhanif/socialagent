"""Synthesise the sound effects (assets/sfx/*.wav) and the emotional music bed (assets/music/emotional.mp3).

Everything is generated from scratch with numpy, so the files are original and free to ship. Run from the repo root:
    backend/.venv/Scripts/python scripts/make_sounds.py
"""

import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SFX_DIR, MUSIC_DIR = ROOT / "assets" / "sfx", ROOT / "assets" / "music"
SR = 48000
rng = np.random.default_rng(7)


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> None:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    x = x / max(np.abs(x).max(), 1e-9) * 0.89  # -1 dBFS peak
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes((x * 32767).astype("<i2").tobytes())


def t_axis(seconds: float, sr: int = SR) -> np.ndarray:
    return np.arange(int(seconds * sr)) / sr


def band_sweep(noise: np.ndarray, centre_hz, width: float, sr: int = SR) -> np.ndarray:
    """Noise through a band-pass whose centre follows centre_hz(t in 0..1) (short-time FFT, overlap-add)."""
    n, hop = 1024, 256
    win = np.hanning(n)
    out = np.zeros(len(noise) + n)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    for start in range(0, len(noise) - n, hop):
        c = centre_hz(start / len(noise))
        spec = np.fft.rfft(noise[start : start + n] * win)
        spec *= np.exp(-0.5 * ((freqs - c) / (c * width)) ** 2)
        out[start : start + n] += np.fft.irfft(spec) * win
    return out[: len(noise)]


def whoosh() -> np.ndarray:
    t = t_axis(0.6)
    x = band_sweep(rng.standard_normal(len(t)), lambda p: 350 + 2600 * np.sin(np.pi * p) ** 2, 0.45)
    env = np.sin(np.pi * np.clip(t / 0.6, 0, 1)) ** 1.6
    return x * env


def pop() -> np.ndarray:
    t = t_axis(0.14)
    freq = 300 + 700 * np.exp(-t * 45)
    x = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 32)
    return x + 0.15 * rng.standard_normal(len(t)) * np.exp(-t * 400)


def impact() -> np.ndarray:
    t = t_axis(1.3)
    freq = 42 + 90 * np.exp(-t * 14)
    body = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 3.2)
    crack = band_sweep(rng.standard_normal(len(t)), lambda p: 900 - 600 * p, 0.8) * np.exp(-t * 18)
    return np.tanh(2.2 * (body + 0.6 * crack / max(np.abs(crack).max(), 1e-9)))


def riser() -> np.ndarray:
    t = t_axis(1.5)
    p = t / 1.5
    air = band_sweep(rng.standard_normal(len(t)), lambda q: 400 + 5200 * q**2, 0.35)
    tone = np.sin(2 * np.pi * np.cumsum(220 + 900 * p**2) / SR)
    x = air / max(np.abs(air).max(), 1e-9) + 0.25 * tone
    return x * p**2.2 * (1 - np.clip((p - 0.97) / 0.03, 0, 1))


def ding() -> np.ndarray:
    t = t_axis(1.0)
    partials = [(1, 1.0, 4.0), (2.76, 0.45, 7.0), (5.4, 0.22, 11.0), (8.93, 0.1, 16.0)]
    x = sum(a * np.sin(2 * np.pi * 1320 * r * t) * np.exp(-t * d) for r, a, d in partials)
    return x * np.clip(t / 0.003, 0, 1)


def swell() -> np.ndarray:
    t = t_axis(2.6)
    p = t / 2.6
    chord = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f in (220.0, 261.63, 329.63, 440.0))
    air = band_sweep(rng.standard_normal(len(t)), lambda q: 500 + 1500 * q, 0.6)
    x = chord / 4 + 0.35 * air / max(np.abs(air).max(), 1e-9)
    return x * p**3 * (1 - np.clip((p - 0.93) / 0.07, 0, 1))


# ------------------------------------------------------------------ emotional music bed

def note_hz(name: str) -> float:
    names = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4, "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1,
             "B": 2}
    pitch, octave = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((names[pitch] + 12 * (octave - 4)) / 12)


def piano(freq: float, seconds: float, sr: int) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    x = sum(a * np.sin(2 * np.pi * freq * k * (1 + 0.0004 * k * k) * t) * np.exp(-t * (1.6 + 0.9 * k))
            for k, a in ((1, 1.0), (2, 0.42), (3, 0.2), (4, 0.1), (5, 0.05)))
    return x * np.clip(t / 0.004, 0, 1)


def pad(freqs: list[float], seconds: float, sr: int) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    x = sum(np.sin(2 * np.pi * f * d * t) + 0.3 * np.sin(4 * np.pi * f * d * t)
            for f in freqs for d in (0.997, 1.003))
    env = np.clip(t / 1.2, 0, 1) * np.clip((seconds - t) / 1.0, 0, 1)
    return x * env / (2 * len(freqs))


def emotional_bed(sr: int = 44100) -> np.ndarray:
    # Am - F - C - G, 4 s per chord at 60 bpm, four times round: a 64 s loop
    chords = [("A2", ["A3", "C4", "E4"], ["A4", "C5", "E5", "C5"]),
              ("F2", ["F3", "A3", "C4"], ["F4", "A4", "C5", "A4"]),
              ("C3", ["C4", "E4", "G4"], ["G4", "C5", "E5", "C5"]),
              ("G2", ["G3", "B3", "D4"], ["G4", "B4", "D5", "B4"])]
    bar, loops = 4.0, 4
    total = bar * len(chords) * loops
    out = np.zeros(int((total + 4) * sr))
    for i in range(len(chords) * loops):
        root, triad, arp = chords[i % len(chords)]
        at = int(i * bar * sr)
        bass = pad([note_hz(root)], bar + 0.8, sr) * 1.2
        out[at : at + len(bass)] += bass
        p = pad([note_hz(n) for n in triad], bar + 1.0, sr) * 0.55
        out[at : at + len(p)] += p
        for k in range(8):  # gentle eighth-note arpeggio, a little softer every other bar
            n = piano(note_hz(arp[k % 4]), 2.5, sr) * (0.32 if (i % 2 == 0 or k % 2 == 0) else 0.2)
            start = at + int(k * bar / 8 * sr)
            out[start : start + len(n)] += n[: len(out) - start]
    ir_t = np.arange(int(2.2 * sr)) / sr
    ir = rng.standard_normal(len(ir_t)) * np.exp(-ir_t * 2.6)
    ir[0] = 6.0
    size = 1 << int(np.ceil(np.log2(len(out) + len(ir))))
    wet = np.fft.irfft(np.fft.rfft(out, size) * np.fft.rfft(ir, size), size)[: len(out)]
    mix = 0.6 * out / np.abs(out).max() + 0.4 * wet / np.abs(wet).max()
    loop = mix[: int(total * sr)].copy()
    tail = mix[int(total * sr) :]
    loop[: len(tail)] += tail  # wrap the reverb tail so the loop restarts seamlessly
    fade = int(0.02 * sr)
    loop[-fade:] *= np.linspace(1, 0.6, fade)
    return loop


def main() -> None:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    for name, make in (("whoosh", whoosh), ("pop", pop), ("impact", impact), ("riser", riser), ("ding", ding),
                       ("swell", swell)):
        write_wav(SFX_DIR / f"{name}.wav", make())
        print("sfx", name)
    raw = SFX_DIR / "_emotional.wav"
    write_wav(raw, emotional_bed(), sr=44100)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", "loudnorm=I=-18:TP=-2",
                    "-ar", "44100", "-b:a", "128k", str(MUSIC_DIR / "emotional.mp3")], check=True)
    raw.unlink()
    print("music emotional.mp3")


if __name__ == "__main__":
    main()
