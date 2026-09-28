#!/usr/bin/env python3
"""Procedural prayer-sound generator.

Synthesizes adhan-inspired alert sounds for the five prayers in four distinct
styles (variations). Output lands in ``sounds_generated/<variation>/<prayer>.mp3``
so packs can be auditioned before one is copied into ``src-tauri/sounds/``.

Dependencies: numpy + ffmpeg (on PATH). WAV is written with the stdlib ``wave``
module; ffmpeg encodes to MP3. If ffmpeg is missing, WAV files are kept instead.

Usage::

    python3 scripts/generate_sounds.py                 # render everything
    python3 scripts/generate_sounds.py --only B_maqam  # one variation
    python3 scripts/generate_sounds.py --wav           # force WAV output
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "sounds_generated"

VARIATIONS = ["A_chime", "B_maqam", "C_gong", "D_marimba"]

# Per-prayer identity: root frequency (Hz), target duration (s), peak gain.
PRAYERS = {
    "fajer":   dict(root=220.00, dur=8.0, gain=0.60),  # gentle wake (A3)
    "dhuhr":   dict(root=293.66, dur=6.0, gain=0.85),  # bright midday (D4)
    "asr":     dict(root=261.63, dur=6.0, gain=0.85),  # warm afternoon (C4)
    "maghrib": dict(root=220.00, dur=7.0, gain=0.80),  # warm dusk (A3)
    "isha":    dict(root=196.00, dur=8.0, gain=0.60),  # calm night (G3)
}

RNG = np.random.default_rng(1453)  # deterministic output


# --------------------------------------------------------------------------- #
# DSP helpers
# --------------------------------------------------------------------------- #
def semis(root: float, n: float) -> float:
    """Frequency n semitones above root."""
    return root * (2.0 ** (n / 12.0))


def adsr(n: int, a: float, d: float, s: float, r: float, sus: float = 0.7) -> np.ndarray:
    """Sample-accurate ADSR envelope of length n (a/d/r in seconds)."""
    a_n = max(1, int(a * SR))
    d_n = max(1, int(d * SR))
    r_n = max(1, int(r * SR))
    s_n = max(0, n - a_n - d_n - r_n)
    env = np.zeros(n, dtype=np.float64)
    i = 0
    env[i:i + a_n] = np.linspace(0.0, 1.0, a_n)
    i += a_n
    env[i:i + d_n] = np.linspace(1.0, sus, d_n)
    i += d_n
    if s_n:
        env[i:i + s_n] = sus
        i += s_n
    end = min(n, i + r_n)
    env[i:end] = np.linspace(sus, 0.0, end - i)
    return env[:n]


def exp_decay(n: int, tau: float) -> np.ndarray:
    """Exponential decay envelope, time-constant tau seconds."""
    t = np.arange(n) / SR
    return np.exp(-t / max(1e-4, tau))


def vibrato_phase(freq: float, n: int, rate: float, depth: float) -> np.ndarray:
    """Phase array for a sine with vibrato (depth as fraction of freq)."""
    t = np.arange(n) / SR
    inst = freq * (1.0 + depth * np.sin(2 * np.pi * rate * t))
    return 2 * np.pi * np.cumsum(inst) / SR


def soft_clip(x: np.ndarray, drive: float = 1.0) -> np.ndarray:
    return np.tanh(x * drive)


def comb(x: np.ndarray, delay: int, g: float) -> np.ndarray:
    """Feedback comb filter (block-vectorized: y[n] = x[n] + g*y[n-delay])."""
    y = x.astype(np.float64).copy()
    for start in range(delay, len(y), delay):
        end = min(start + delay, len(y))
        y[start:end] += g * y[start - delay:start - delay + (end - start)]
    return y


def allpass(x: np.ndarray, delay: int, g: float) -> np.ndarray:
    """Schroeder allpass filter, block-vectorized."""
    xd = np.concatenate([np.zeros(delay), x])[:len(x)]
    y = (-g * x + xd).astype(np.float64)
    for start in range(delay, len(y), delay):
        end = min(start + delay, len(y))
        y[start:end] += g * y[start - delay:start - delay + (end - start)]
    return y


def reverb(x: np.ndarray, wet: float = 0.25, room: float = 0.84) -> np.ndarray:
    """Cheap Schroeder reverb (4 parallel combs -> 2 series allpass)."""
    combs = [1116, 1188, 1277, 1356]
    aps = [556, 441]
    acc = np.zeros_like(x, dtype=np.float64)
    for d in combs:
        acc += comb(x, d, room)
    acc /= len(combs)
    for d in aps:
        acc = allpass(acc, d, 0.5)
    return (1.0 - wet) * x + wet * acc


def to_stereo(mono: np.ndarray, width: float = 0.012) -> np.ndarray:
    """Subtle Haas-style widening into a (N, 2) array."""
    d = int(width * SR)
    right = np.concatenate([np.zeros(d), mono])[:len(mono)]
    return np.stack([mono, 0.6 * mono + 0.4 * right], axis=1)


def finalize(mono: np.ndarray, gain: float) -> np.ndarray:
    """Fade, normalize, widen, peak-limit to ~-1 dBFS."""
    n = len(mono)
    fi = min(int(0.006 * SR), n // 2)
    fo = min(int(0.30 * SR), n // 2)
    mono = mono.copy()
    mono[:fi] *= np.linspace(0, 1, fi)
    mono[-fo:] *= np.linspace(1, 0, fo)
    peak = np.max(np.abs(mono)) or 1.0
    mono = mono / peak * gain
    stereo = to_stereo(mono)
    peak = np.max(np.abs(stereo)) or 1.0
    if peak > 0.891:
        stereo = stereo / peak * 0.891
    return stereo


def place(buf: np.ndarray, sig: np.ndarray, at: float) -> None:
    """Mix sig into buf starting at time `at` seconds (in place)."""
    start = int(at * SR)
    end = min(len(buf), start + len(sig))
    buf[start:end] += sig[:end - start]


# --------------------------------------------------------------------------- #
# Instrument voices
# --------------------------------------------------------------------------- #
def bell_voice(freq: float, dur: float, gain: float = 1.0) -> np.ndarray:
    """Risset-style additive bell."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    ratios = [0.56, 0.92, 1.19, 1.71, 2.00, 2.74, 3.00, 3.76, 4.07]
    amps = [1.00, 0.67, 1.00, 1.80, 2.67, 1.67, 1.46, 1.33, 0.75]
    decs = [1.00, 0.90, 0.65, 0.55, 0.33, 0.35, 0.25, 0.20, 0.15]
    out = np.zeros(n)
    for r, a, dec in zip(ratios, amps, decs):
        out += a * np.sin(2 * np.pi * freq * r * t) * np.exp(-t / (dur * dec * 0.5))
    return out / max(amps) * gain


def reed_voice(freq: float, dur: float, gain: float = 1.0) -> np.ndarray:
    """Breathy ney/reed via FM + vibrato + a touch of breath noise."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    mod = np.sin(2 * np.pi * freq * t)
    idx = 2.2 * adsr(n, 0.10, 0.20, 0.6, 0.4, sus=0.8)
    phase = vibrato_phase(freq, n, rate=5.2, depth=0.006)
    tone = np.sin(phase + idx * mod)
    breath = RNG.standard_normal(n)
    breath = np.convolve(breath, np.ones(40) / 40, mode="same")  # low-passed hiss
    env = adsr(n, 0.10, 0.25, 0.65, 0.5, sus=0.75)
    sig = (tone + 0.05 * breath) * env
    return sig * gain


def gong_voice(freq: float, dur: float, gain: float = 1.0) -> np.ndarray:
    """Warm gong / singing bowl: inharmonic partials with slow beating."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    base_ratios = [1.0, 1.52, 2.0, 2.41, 3.46, 4.07, 5.4]
    for k, r in enumerate(base_ratios):
        detune = 1.0 + RNG.uniform(-0.004, 0.004)
        beat = 1.0 + 0.06 * np.sin(2 * np.pi * (0.4 + 0.3 * k) * t)  # shimmer
        amp = 1.0 / (1.0 + k * 0.7)
        out += amp * np.sin(2 * np.pi * freq * r * detune * t) * beat * np.exp(-t / (dur * (0.9 - k * 0.09)))
    attack = adsr(n, 0.02, 0.05, 1.0, 0.0, sus=1.0)
    return out / np.max(np.abs(out)) * attack * gain


def marimba_voice(freq: float, dur: float, gain: float = 1.0) -> np.ndarray:
    """Marimba bar: fundamental + bar overtones, fast percussive decay."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    ratios = [1.0, 3.93, 9.22]
    amps = [1.0, 0.34, 0.12]
    decs = [0.9, 0.4, 0.2]
    out = np.zeros(n)
    for r, a, dec in zip(ratios, amps, decs):
        out += a * np.sin(2 * np.pi * freq * r * t) * np.exp(-t / (dur * dec * 0.5))
    click = RNG.standard_normal(n) * np.exp(-t / 0.004) * 0.25  # mallet attack
    return (out / max(amps) + click) * gain


# --------------------------------------------------------------------------- #
# Variation arrangers
# --------------------------------------------------------------------------- #
def render_chime(root: float, dur: float) -> np.ndarray:
    """Variation A: overlapping bell arpeggio (major pentatonic)."""
    buf = np.zeros(int(dur * SR))
    scale = [0, 4, 7, 12, 16, 12, 7, 4]  # gentle up-and-down
    step = dur / (len(scale) + 3)
    for i, s in enumerate(scale):
        note = bell_voice(semis(root, s), dur - i * step, gain=0.9 - 0.04 * i)
        place(buf, note, i * step)
    return reverb(buf, wet=0.32, room=0.86)


def render_maqam(root: float, dur: float) -> np.ndarray:
    """Variation B: legato reed phrase on Hijaz scale."""
    buf = np.zeros(int(dur * SR))
    hijaz = [0, 1, 4, 5, 7, 8, 11, 12]  # semitone steps of Hijaz
    # (degree index, length-in-beats)
    motif = [(0, 1), (1, 1), (2, 1.5), (4, 1), (5, 2), (4, 1), (2, 1), (1, 1.5), (0, 2)]
    beat = dur / sum(d for _, d in motif)
    at = 0.0
    for deg, beats in motif:
        ln = beats * beat
        note = reed_voice(semis(root, hijaz[deg]), ln + 0.25, gain=0.85)
        place(buf, note, at)
        at += ln * 0.92  # slight overlap for legato
    return reverb(buf, wet=0.28, room=0.85)


def render_gong(root: float, dur: float) -> np.ndarray:
    """Variation C: two warm gong strikes, octave apart."""
    buf = np.zeros(int(dur * SR))
    place(buf, gong_voice(root, dur, gain=1.0), 0.0)
    place(buf, gong_voice(semis(root, 12), dur * 0.55, gain=0.45), dur * 0.42)
    return reverb(buf, wet=0.30, room=0.88)


def render_marimba(root: float, dur: float) -> np.ndarray:
    """Variation D: brisk marimba arpeggio (major pentatonic, up + down)."""
    buf = np.zeros(int(dur * SR))
    pattern = [0, 4, 7, 9, 12, 9, 7, 4, 0]
    note_len = 0.5
    step = (dur - note_len) / (len(pattern) + 1)
    for i, s in enumerate(pattern):
        note = marimba_voice(semis(root, s), note_len + 0.2, gain=0.9)
        place(buf, note, i * step)
    return reverb(buf, wet=0.22, room=0.80)


ARRANGERS = {
    "A_chime": render_chime,
    "B_maqam": render_maqam,
    "C_gong": render_gong,
    "D_marimba": render_marimba,
}


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def write_wav(path: Path, stereo: np.ndarray) -> None:
    data = np.clip(stereo, -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def encode_mp3(wav_path: Path, mp3_path: Path) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
             "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3_path)],
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate prayer alert sounds.")
    ap.add_argument("--only", choices=VARIATIONS, help="render a single variation")
    ap.add_argument("--wav", action="store_true", help="keep WAV (skip MP3 encode)")
    args = ap.parse_args()

    have_ffmpeg = shutil.which("ffmpeg") is not None and not args.wav
    variations = [args.only] if args.only else VARIATIONS

    print(f"Output: {OUT_DIR}")
    print(f"Encoder: {'mp3 (ffmpeg)' if have_ffmpeg else 'wav'}\n")

    for variation in variations:
        vdir = OUT_DIR / variation
        vdir.mkdir(parents=True, exist_ok=True)
        for prayer, p in PRAYERS.items():
            mono = ARRANGERS[variation](p["root"], p["dur"])
            stereo = finalize(mono, p["gain"])
            wav_path = vdir / f"{prayer}.wav"
            write_wav(wav_path, stereo)
            if have_ffmpeg:
                mp3_path = vdir / f"{prayer}.mp3"
                if encode_mp3(wav_path, mp3_path):
                    wav_path.unlink()
                    out = mp3_path
                else:
                    out = wav_path
            else:
                out = wav_path
            print(f"  {variation:10s} {prayer:8s} -> {out.relative_to(ROOT)}")
    print("\nDone. Audition the packs, then approve one to copy into src-tauri/sounds/.")


if __name__ == "__main__":
    main()
