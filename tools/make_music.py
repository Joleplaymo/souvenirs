"""Génère les musiques de fond du projet par synthèse (aucun droit d'auteur tiers).

    python tools/make_music.py   →   music/{detendu,sportif,humour,emotion}.mp3
"""
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "music"
NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def hz(name: str) -> float:
    semis = NOTE[name[0]] + (1 if "#" in name else 0) + 12 * (int(name[-1]) + 1)
    return 440.0 * 2 ** ((semis - 69) / 12)


def tone(freq, dur, kind):
    t = np.arange(int(SR * dur)) / SR
    if kind == "pad":
        w = sum(np.sin(2 * np.pi * freq * d * t) for d in (0.997, 1.0, 1.004)) / 3
        w += 0.25 * np.sin(2 * np.pi * freq * 2 * t)
        a = int(SR * min(0.6, dur / 3))
        env = np.ones_like(t)
        env[:a] = np.linspace(0, 1, a)
        env[-a:] = np.linspace(1, 0, a)
    elif kind == "pluck":
        w = np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(4 * np.pi * freq * t) + 0.15 * np.sin(6 * np.pi * freq * t)
        env = np.exp(-t * 5.5) * np.minimum(1, t * 400)
    elif kind == "piano":
        w = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(4 * np.pi * freq * t) * np.exp(-t * 3)
        env = np.exp(-t * 2.2) * np.minimum(1, t * 300)
    elif kind == "pizz":
        w = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(6 * np.pi * freq * t)
        env = np.exp(-t * 14) * np.minimum(1, t * 500)
    elif kind == "bass":
        w = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)
        env = np.exp(-t * 3) * np.minimum(1, t * 200)
    return w * env


def kick(dur=0.3):
    t = np.arange(int(SR * dur)) / SR
    return np.sin(2 * np.pi * (45 * t + 60 * (1 - np.exp(-t * 28)) / 28)) * np.exp(-t * 11)


def hat(dur=0.06, rng=np.random.default_rng(1)):
    n = rng.standard_normal(int(SR * dur))
    return np.diff(n, prepend=0) * np.exp(-np.arange(len(n)) / SR * 70) * 0.5


def put(buf, at, w, gain):
    i = int(at * SR)
    if i < len(buf):
        w = w[: len(buf) - i]
        buf[i:i + len(w)] += w * gain


def track(bpm, chords, kind, bars_repeat):
    beat = 60 / bpm
    bar = 4 * beat
    total = bar * len(chords) * bars_repeat
    buf = np.zeros(int(SR * (total + 2)))
    for r in range(bars_repeat):
        for c, notes in enumerate(chords):
            t0 = (r * len(chords) + c) * bar
            lift = r % 2 == 1  # une octave d'arpège en plus un tour sur deux
            if kind in ("detendu", "emotion"):
                for n in notes[1:]:
                    put(buf, t0, tone(hz(n), bar * 1.05, "pad"), 0.11)
            put(buf, t0, tone(hz(notes[0]), bar * 0.9, "bass"), 0.3)
            if kind == "detendu":
                seq = [1, 2, 3, 2, 1, 3, 2, 3]
                for k, idx in enumerate(seq):
                    f = hz(notes[idx]) * (2 if lift and k % 4 == 3 else 1)
                    put(buf, t0 + k * beat / 2, tone(f, beat * 1.5, "pluck"), 0.2)
            elif kind == "emotion":
                seq = [1, 2, 3, 2]
                for k, idx in enumerate(seq):
                    put(buf, t0 + k * beat, tone(hz(notes[idx]) * (2 if lift else 1), beat * 3, "piano"), 0.24)
            elif kind == "sportif":
                for k in range(4):
                    put(buf, t0 + k * beat, kick(), 0.75)
                    put(buf, t0 + k * beat + beat / 2, hat(), 0.35)
                for k in range(8):
                    put(buf, t0 + k * beat / 2, tone(hz(notes[0]) * (2 if k % 2 else 1), beat / 2, "bass"), 0.26)
                seq = [1, 2, 3, 2] * 4
                for k, idx in enumerate(seq):
                    put(buf, t0 + k * beat / 4, tone(hz(notes[idx]) * (2 if lift else 1), beat / 2, "pluck"), 0.13)
                for n in notes[1:]:
                    put(buf, t0, tone(hz(n), bar, "pad"), 0.05)
            elif kind == "humour":
                swing = [0, 0.66, 1, 1.66, 2, 2.66, 3, 3.66]
                seq = [1, 3, 2, 3, 1, 3, 2, 1]
                for k, idx in enumerate(seq):
                    put(buf, t0 + swing[k] * beat, tone(hz(notes[idx]) * 2, beat / 2, "pizz"), 0.3)
                put(buf, t0 + 2 * beat, tone(hz(notes[0]) * 1.5, beat, "bass"), 0.26)
    buf = buf[: int(SR * total)]
    # petite réverbération : quelques échos amortis
    wet = np.zeros_like(buf)
    for delay, g in ((0.11, 0.3), (0.23, 0.2), (0.37, 0.12)):
        d = int(delay * SR)
        wet[d:] += buf[:-d] * g
    buf = buf + wet
    stereo = np.stack([buf, np.roll(buf, int(0.012 * SR))], axis=1)
    return stereo / np.abs(stereo).max() * 0.85


TRACKS = {
    "detendu": (84, [["C2", "E4", "G4", "B4"], ["A1", "C4", "E4", "G4"], ["F1", "A3", "C4", "E4"], ["G1", "B3", "D4", "E4"]], 8),
    "sportif": (124, [["A1", "A3", "C4", "E4"], ["F1", "A3", "C4", "F4"], ["C2", "G3", "C4", "E4"], ["G1", "G3", "B3", "D4"]], 12),
    "humour": (108, [["C2", "E4", "G4", "C5"], ["F2", "F4", "A4", "C5"], ["G2", "G4", "B4", "D5"], ["C2", "E4", "G4", "C5"]], 10),
    "emotion": (66, [["A1", "A3", "C4", "E4"], ["F1", "A3", "C4", "F4"], ["C2", "G3", "C4", "E4"], ["E1", "G3", "B3", "E4"]], 6),
}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, (bpm, chords, rep) in TRACKS.items():
        pcm = (track(bpm, chords, name, rep) * 32767).astype(np.int16)
        wav = OUT / f"{name}.wav"
        with wave.open(str(wav), "wb") as f:
            f.setnchannels(2)
            f.setsampwidth(2)
            f.setframerate(SR)
            f.writeframes(pcm.tobytes())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "128k", str(OUT / f"{name}.mp3")],
                       check=True)
        wav.unlink()
        print(name, f"{len(pcm) / SR:.0f} s", file=sys.stderr)
