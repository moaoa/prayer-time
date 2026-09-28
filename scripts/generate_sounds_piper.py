#!/usr/bin/env python3
"""Neural prayer-sound generator using Piper TTS (text -> speech).

Synthesizes spoken Arabic prayer announcements for the five prayers with a local
Piper voice (no cloud, no API). Produces a couple of phrasing variations so one
can be approved before being copied into ``src-tauri/sounds/``.

Run inside the project venv that has piper-tts installed::

    source .venv-piper/bin/activate
    python scripts/generate_sounds_piper.py
    python scripts/generate_sounds_piper.py --only announce
    python scripts/generate_sounds_piper.py --wav        # keep WAV, skip mp3

Voice model is expected at ``models/piper/<voice>.onnx`` (+ .onnx.json). Download
with: ``python -m piper.download_voices ar_JO-kareem-medium --data-dir models/piper``
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "sounds_generated"
MODEL_DIR = ROOT / "models" / "piper"

# Available voice models (timbres).
VOICES = {
    "medium": MODEL_DIR / "ar_JO-kareem-medium.onnx",
    "low": MODEL_DIR / "ar_JO-kareem-low.onnx",
}

# Arabic display name per prayer key used by the app.
PRAYER_NAMES = {
    "fajer":   "الفَجْر",
    "dhuhr":   "الظُّهْر",
    "asr":     "العَصْر",
    "maghrib": "المَغْرِب",
    "isha":    "العِشَاء",
}

# Variations = different phrasing / pacing / voice combos. {name} -> prayer name.
# length_scale > 1.0 speaks slower (calmer); < 1.0 speaks faster.
VARIATIONS = {
    # Requested phrasing: "حان الآن موعد أذان صلاة ..."
    "piper_announce": dict(
        voice="medium",
        length_scale=1.12,
        template="حانَ الآنَ موعِدُ أذانِ صلاةِ {name}.",
        fajr_template="حانَ الآنَ موعِدُ أذانِ صلاةِ الفجر. الصلاةُ خيرٌ من النوم.",
    ),
    # Same phrasing, calmer/slower pacing.
    "piper_announce_calm": dict(
        voice="medium",
        length_scale=1.32,
        noise_w_scale=0.9,
        template="حانَ الآنَ موعِدُ أذانِ صلاةِ {name}.",
        fajr_template="حانَ الآنَ موعِدُ أذانِ صلاةِ الفجر. الصلاةُ خيرٌ من النوم.",
    ),
    # Same phrasing, lighter/low-quality voice timbre.
    "piper_announce_low": dict(
        voice="low",
        length_scale=1.12,
        template="حانَ الآنَ موعِدُ أذانِ صلاةِ {name}.",
        fajr_template="حانَ الآنَ موعِدُ أذانِ صلاةِ الفجر. الصلاةُ خيرٌ من النوم.",
    ),
    # Short and direct.
    "piper_short": dict(
        voice="medium",
        length_scale=1.10,
        template="أذانُ صلاةِ {name}.",
        fajr_template="أذانُ صلاةِ الفجر. الصلاةُ خيرٌ من النوم.",
    ),
    # Adhan-style opening with takbir, then the requested announcement.
    "piper_adhan": dict(
        voice="medium",
        length_scale=1.18,
        template="اللهُ أكبر، اللهُ أكبر. حيَّ على الصلاة، حيَّ على الفلاح. حانَ الآنَ موعِدُ أذانِ صلاةِ {name}.",
        fajr_template="اللهُ أكبر، اللهُ أكبر. حيَّ على الصلاة، حيَّ على الفلاح. الصلاةُ خيرٌ من النوم. حانَ الآنَ موعِدُ أذانِ صلاةِ الفجر.",
    ),
}


def text_for(variation: dict, prayer: str, name: str) -> str:
    if prayer == "fajer" and variation.get("fajr_template"):
        return variation["fajr_template"]
    return variation["template"].format(name=name)


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
    ap = argparse.ArgumentParser(description="Generate spoken prayer sounds with Piper.")
    ap.add_argument("--only", choices=list(VARIATIONS), help="render a single variation")
    ap.add_argument("--wav", action="store_true", help="keep WAV (skip MP3 encode)")
    args = ap.parse_args()

    have_ffmpeg = shutil.which("ffmpeg") is not None and not args.wav
    print(f"Output: {OUT_DIR}")
    print(f"Encoder: {'mp3 (ffmpeg)' if have_ffmpeg else 'wav'}\n")

    variations = {args.only: VARIATIONS[args.only]} if args.only else VARIATIONS

    # Lazily load each voice once and reuse across variations.
    loaded: dict[str, PiperVoice] = {}

    def get_voice(key: str) -> PiperVoice:
        if key not in loaded:
            path = VOICES[key]
            if not path.is_file():
                raise SystemExit(
                    f"Voice model not found: {path}\n"
                    f"Download it with:\n"
                    f"  python -m piper.download_voices ar_JO-kareem-{key} --data-dir models/piper"
                )
            print(f"Loading voice '{key}' ({path.name})...")
            v = PiperVoice.load(path)
            if hasattr(v, "use_tashkeel"):
                v.use_tashkeel = True  # auto-diacritize Arabic for better pronunciation
            loaded[key] = v
        return loaded[key]

    for vname, vcfg in variations.items():
        vdir = OUT_DIR / vname
        vdir.mkdir(parents=True, exist_ok=True)
        voice = get_voice(vcfg.get("voice", "medium"))
        syn = SynthesisConfig(
            length_scale=vcfg["length_scale"],
            noise_scale=vcfg.get("noise_scale"),
            noise_w_scale=vcfg.get("noise_w_scale"),
        )
        for prayer, name in PRAYER_NAMES.items():
            text = text_for(vcfg, prayer, name)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            with wave.open(str(tmp_path), "wb") as wf:
                voice.synthesize_wav(text, wf, syn_config=syn)

            if have_ffmpeg:
                out = vdir / f"{prayer}.mp3"
                if not encode_mp3(tmp_path, out):
                    out = vdir / f"{prayer}.wav"
                    shutil.move(str(tmp_path), out)
                else:
                    tmp_path.unlink()
            else:
                out = vdir / f"{prayer}.wav"
                shutil.move(str(tmp_path), out)
            print(f"  {vname:14s} {prayer:8s} -> {out.relative_to(ROOT)}")

    print("\nDone. Audition the packs, then approve one to copy into src-tauri/sounds/.")


if __name__ == "__main__":
    main()
