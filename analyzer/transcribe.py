"""
transcribe.py — Whisper transcription pipeline
Sends extracted MP3 to OpenAI Whisper API with word-level timestamps.
"""

import os
import sys
import json
import math
import logging
import time
from io import BytesIO
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
import openai

ROOT = Path(__file__).parent.parent

if sys.platform == 'darwin':
    LOGS_DIR = Path('/tmp/contentengine/logs')
    TRANSCRIPTS_DIR = Path('/tmp/contentengine/logs/transcripts')
else:
    LOGS_DIR = ROOT / "logs"
    TRANSCRIPTS_DIR = ROOT / "logs" / "transcripts"

LOGS_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# Whisper API pricing: $0.006 per minute
WHISPER_COST_PER_MINUTE = 0.006
# Whisper max file size in bytes (25MB)
WHISPER_MAX_BYTES = 25 * 1024 * 1024

load_dotenv(ROOT / "config" / ".env")


def get_logger(video_id: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOGS_DIR / f"transcribe-{timestamp}.log"
    logger = logging.getLogger(f"transcribe.{video_id}")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def get_openai_client() -> openai.OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY not set. Copy config/.env.template to config/.env and add your key."
        )
    return openai.OpenAI(api_key=api_key)


def estimate_cost(duration_seconds: float) -> float:
    minutes = duration_seconds / 60
    return round(minutes * WHISPER_COST_PER_MINUTE, 6)


def transcribe_single(client: openai.OpenAI, audio_path: Path, logger: logging.Logger) -> dict:
    """Transcribe a single audio file (must be under 25MB)."""
    logger.info("Sending to Whisper API")
    start = time.time()

    audio_bytes = open(audio_path, "rb").read()
    buf = BytesIO(audio_bytes)
    buf.name = "audio.mp3"

    for attempt in range(3):
        try:
            buf.seek(0)
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=buf,
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )
            elapsed = time.time() - start
            logger.info(f"Transcription complete in {elapsed:.1f}s")
            return response.model_dump() if hasattr(response, "model_dump") else dict(response)
        except openai.RateLimitError as e:
            wait = 2 ** attempt * 5
            logger.warning(f"Rate limit hit (attempt {attempt+1}/3). Waiting {wait}s... {e}")
            time.sleep(wait)
        except openai.APIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    raise RuntimeError("Whisper API failed after 3 attempts (rate limit).")


def chunk_audio(audio_path: Path, logger: logging.Logger) -> list[Path]:
    """
    Split audio into <25MB chunks using FFmpeg segment filter.
    Chunks saved alongside original with _chunk_N suffix.
    """
    import subprocess

    chunk_dir = audio_path.parent / f"{audio_path.stem}_chunks"
    chunk_dir.mkdir(exist_ok=True)
    chunk_pattern = str(chunk_dir / "chunk_%03d.mp3")

    logger.info(f"Audio exceeds 25MB — chunking to {chunk_dir}")

    # Use 10-minute segments to stay well under 25MB at 64kbps
    cmd = [
        "ffmpeg", "-i", str(audio_path),
        "-f", "segment",
        "-segment_time", "600",
        "-c", "copy",
        chunk_pattern,
        "-y"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Chunking failed: {result.stderr}")
        raise RuntimeError("Audio chunking failed.")

    chunks = sorted(chunk_dir.glob("chunk_*.mp3"))
    logger.info(f"Created {len(chunks)} chunks")
    return chunks


def merge_transcripts(parts: list[dict]) -> dict:
    """Merge chunked transcript parts into a single result."""
    merged_text = " ".join(p.get("text", "").strip() for p in parts)
    all_words = []
    time_offset = 0.0

    for part in parts:
        words = part.get("words", [])
        duration = part.get("duration", 0.0)
        for w in words:
            w_copy = dict(w)
            w_copy["start"] = w_copy.get("start", 0) + time_offset
            w_copy["end"] = w_copy.get("end", 0) + time_offset
            all_words.append(w_copy)
        time_offset += duration

    return {
        "text": merged_text,
        "words": all_words,
        "duration": time_offset,
        "language": parts[0].get("language", "en") if parts else "en",
        "chunked": True,
        "chunk_count": len(parts),
    }


def transcribe(audio_path: str | Path, video_id: str, duration_seconds: float = 0.0) -> dict:
    """
    Main entry point.
    Returns transcript dict, saves JSON to /logs/transcripts/[video-id].json.
    """
    audio_path = Path(audio_path).resolve()
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    logger = get_logger(video_id)
    logger.info(f"=== Transcription Pipeline ===")
    logger.info(f"Audio: {audio_path}")
    logger.info(f"Video ID: {video_id}")

    client = get_openai_client()

    file_size = audio_path.stat().st_size
    logger.info(f"Audio size: {file_size / 1024:.1f} KB")

    if file_size > WHISPER_MAX_BYTES:
        logger.info("File exceeds 25MB limit — chunking required.")
        chunks = chunk_audio(audio_path, logger)
        parts = []
        for chunk in chunks:
            part = transcribe_single(client, chunk, logger)
            parts.append(part)
        result = merge_transcripts(parts)
    else:
        result = transcribe_single(client, audio_path, logger)

    # Estimate duration from result or fallback to provided
    dur = result.get("duration", duration_seconds) or duration_seconds
    cost = estimate_cost(dur)

    result["video_id"] = video_id
    result["audio_source"] = str(audio_path)
    result["estimated_cost_usd"] = cost
    result["transcribed_at"] = datetime.now().isoformat()

    out_path = TRANSCRIPTS_DIR / f"{video_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    logger.info(f"Transcript saved → {out_path}")
    logger.info(f"Estimated Whisper cost: ${cost:.4f} (~{dur/60:.2f} min audio)")
    logger.info("=== Transcription complete ===")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analyzer/transcribe.py <audio_path> <video_id> [duration_seconds]")
        sys.exit(1)
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    result = transcribe(sys.argv[1], sys.argv[2], dur)
    print(f"Transcript: {result.get('text', '')[:200]}...")
    print(f"Cost: ${result.get('estimated_cost_usd', 0):.4f}")
