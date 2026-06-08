#!/usr/bin/env python3.11
"""
tts.py — ElevenLabs voice synthesis with automatic silent stub.

Auto-stub activates when ELEVENLABS_AMANDA_VOICE_ID is unset/empty.
Stub produces a silent MP3 of duration estimated from word count.
Real mode activates automatically when the voice ID is configured.
No code changes needed when switching modes — only .env changes.
"""

import os
import re
import sys
import time
import logging
import subprocess
from datetime import datetime
from pathlib import Path

import requests
from mutagen.mp3 import MP3
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / "config" / ".env")

TEMP_DIR = ROOT / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"
ELEVENLABS_MODEL = "eleven_multilingual_v2"

WORDS_PER_SECOND = 2.8  # average conversational speaking rate

logger = logging.getLogger(__name__)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)
logger.setLevel(logging.INFO)


def _count_words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _stub_tts(script_text: str, output_path: Path) -> dict:
    """Generate a silent placeholder MP3 via ffmpeg."""
    word_count = _count_words(script_text)
    duration = max(1.0, round(word_count / WORDS_PER_SECOND, 2))

    logger.warning(
        f"⚠️  TTS STUB: ElevenLabs not configured — using silent audio ({duration:.1f}s)"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=mono",
        "-t", str(duration),
        "-q:a", "9",
        "-acodec", "libmp3lame",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg stub generation failed: {result.stderr[:300]}")

    actual_duration = MP3(str(output_path)).info.length
    size_kb = output_path.stat().st_size / 1024
    logger.info(f"  Stub: {output_path.name} | {actual_duration:.1f}s | {size_kb:.1f}KB")

    return {
        "audio_path": str(output_path),
        "duration_seconds": actual_duration,
        "char_count": len(script_text),
        "stub": True,
    }


def _call_elevenlabs(
    script_text: str,
    voice_id: str,
    api_key: str,
    output_path: Path,
) -> dict:
    """Call ElevenLabs API with exponential backoff on 429."""
    url = f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": script_text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    max_retries = 3
    for attempt in range(max_retries):
        t0 = time.time()
        resp = requests.post(url, json=payload, headers=headers, timeout=120)

        if resp.status_code == 200:
            output_path.write_bytes(resp.content)
            elapsed = time.time() - t0
            duration = MP3(str(output_path)).info.length
            size_kb = len(resp.content) / 1024
            logger.info(
                f"  ElevenLabs: {output_path.name} | {duration:.1f}s | "
                f"{size_kb:.1f}KB | {elapsed:.1f}s synthesis"
            )
            return {
                "audio_path": str(output_path),
                "duration_seconds": duration,
                "char_count": len(script_text),
                "stub": False,
            }

        if resp.status_code == 429:
            wait = 2 ** attempt
            logger.warning(f"  ElevenLabs 429 — retry {attempt+1}/{max_retries} in {wait}s")
            time.sleep(wait)
            continue

        raise RuntimeError(
            f"ElevenLabs API error {resp.status_code}: {resp.text[:300]}"
        )

    raise RuntimeError(
        f"ElevenLabs: all {max_retries} retries exhausted (429 rate limit)"
    )


def synthesize(script_text: str, brand: str) -> dict:
    """
    Synthesize TTS audio for a script.

    Automatically stubs if ELEVENLABS_AMANDA_VOICE_ID is not set.
    Returns identical dict shape in both real and stub modes.
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = TEMP_DIR / f"tts_{brand}_{timestamp}.mp3"

    voice_id = os.getenv("ELEVENLABS_AMANDA_VOICE_ID", "").strip()
    if not voice_id:
        return _stub_tts(script_text, output_path)

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        logger.warning("⚠️  ELEVENLABS_API_KEY not set — falling back to stub")
        return _stub_tts(script_text, output_path)

    return _call_elevenlabs(script_text, voice_id, api_key, output_path)


if __name__ == "__main__":
    test_text = (
        "This is a test of the Alpha Insurance voice clone. "
        "Protecting Mississippi families for thirty years. "
        "Call Alpha Insurance at 601-981-2911 today."
    )
    brand = "alpha-insurance"
    print(f"\nRunning TTS self-test for brand: {brand}")
    print(f"Script ({_count_words(test_text)} words): {test_text[:60]}...")

    result = synthesize(test_text, brand)

    path = Path(result["audio_path"])
    assert path.exists(), f"Output file not created: {path}"
    assert result["duration_seconds"] > 0, "Duration must be > 0"
    assert path.stat().st_size > 1000, f"File too small: {path.stat().st_size} bytes"
    assert result["char_count"] == len(test_text), "char_count mismatch"

    mode = "STUB" if result.get("stub") else "REAL ElevenLabs"
    print(f"\n✓ TTS self-test passed [{mode}]")
    print(f"  File:     {path.name}")
    print(f"  Duration: {result['duration_seconds']:.1f}s")
    print(f"  Size:     {path.stat().st_size / 1024:.1f}KB")
    print(f"  Chars:    {result['char_count']}")
    if result.get("stub"):
        print("  ⚠️  PENDING: ElevenLabs voice clone not yet configured")
        print("     Add ELEVENLABS_AMANDA_VOICE_ID to config/.env to activate real TTS")
