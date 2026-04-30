"""
extract.py — Video extraction pipeline
Extracts audio (MP3) and keyframes (JPGs) from competitor video files.
"""

import os
import sys
import json
import logging
import hashlib
from pathlib import Path
from datetime import datetime

import ffmpeg

# Project root relative to this file
ROOT = Path(__file__).parent.parent

if sys.platform == 'darwin':
    LOGS_DIR = Path('/tmp/contentengine/logs')
    FRAMES_DIR = Path('/tmp/contentengine/logs/frames')
else:
    LOGS_DIR = ROOT / "logs"
    FRAMES_DIR = ROOT / "logs" / "frames"

LOGS_DIR.mkdir(parents=True, exist_ok=True)
FRAMES_DIR.mkdir(parents=True, exist_ok=True)


def setup_logger(video_id: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOGS_DIR / f"extract-{timestamp}.log"
    logger = logging.getLogger(f"extract.{video_id}")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def check_ffmpeg() -> bool:
    try:
        ffmpeg.probe.__module__  # sanity import check
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def get_video_id(video_path: Path) -> str:
    """Generate a stable short ID from the video filename."""
    stem = video_path.stem
    h = hashlib.md5(stem.encode()).hexdigest()[:6]
    return f"{stem[:40]}-{h}"


def extract_audio(video_path: Path, video_id: str, logger: logging.Logger) -> Path:
    """Extract audio as 16kHz mono MP3 optimized for Whisper."""
    out_dir = LOGS_DIR / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / f"{video_id}.mp3"

    logger.info(f"Extracting audio → {audio_path}")
    try:
        (
            ffmpeg
            .input(str(video_path))
            .output(
                str(audio_path),
                ac=1,          # mono
                ar=16000,      # 16kHz — Whisper optimal
                format="mp3",
                audio_bitrate="64k",
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        logger.error(f"FFmpeg audio extraction failed: {stderr}")
        raise RuntimeError(f"Audio extraction failed: {stderr}")

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        logger.error("Audio file is empty or was not created.")
        raise RuntimeError("Empty audio track — video may have no audio.")

    logger.info(f"Audio extracted: {audio_path.stat().st_size / 1024:.1f} KB")
    return audio_path


def extract_keyframes(video_path: Path, video_id: str, logger: logging.Logger) -> list[Path]:
    """Extract keyframes every 2 seconds as JPGs."""
    frames_out = FRAMES_DIR / video_id
    frames_out.mkdir(parents=True, exist_ok=True)

    logger.info(f"Extracting keyframes every 2s → {frames_out}")
    frame_pattern = str(frames_out / "frame_%04d.jpg")

    try:
        (
            ffmpeg
            .input(str(video_path))
            .filter("fps", fps=0.5)   # 1 frame per 2 seconds
            .output(frame_pattern, qscale=2)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        logger.error(f"FFmpeg keyframe extraction failed: {stderr}")
        raise RuntimeError(f"Keyframe extraction failed: {stderr}")

    frames = sorted(frames_out.glob("frame_*.jpg"))
    logger.info(f"Extracted {len(frames)} keyframes")
    return frames


def detect_scene_changes(video_path: Path, logger: logging.Logger) -> list[dict]:
    """Detect scene changes using FFmpeg scene detection filter."""
    logger.info("Running scene change detection...")
    try:
        out, err = (
            ffmpeg
            .input(str(video_path))
            .filter("select", "gt(scene,0.3)")
            .filter("showinfo")
            .output("null", f="null")
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        logger.warning(f"Scene detection produced warning (non-fatal): {stderr[:200]}")
        return []

    scenes = []
    stderr_text = err.decode("utf-8", errors="replace") if err else ""
    for line in stderr_text.splitlines():
        if "pts_time" in line:
            try:
                pts_part = [p for p in line.split() if "pts_time" in p]
                if pts_part:
                    t = float(pts_part[0].split(":")[1])
                    scenes.append({"timestamp_seconds": t})
            except (IndexError, ValueError):
                continue

    logger.info(f"Detected {len(scenes)} scene changes")
    return scenes


def get_video_duration(video_path: Path, logger: logging.Logger) -> float:
    """Probe video duration in seconds."""
    try:
        probe = ffmpeg.probe(str(video_path))
        duration = float(probe["format"].get("duration", 0))
        return duration
    except Exception as e:
        logger.warning(f"Could not probe video duration: {e}")
        return 0.0


def extract(video_path: str | Path) -> dict:
    """
    Main entry point.
    Returns metadata dict with paths to extracted assets.
    """
    video_path = Path(video_path).resolve()

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    video_id = get_video_id(video_path)
    logger = setup_logger(video_id)

    logger.info(f"=== ContentEngine Extraction Pipeline ===")
    logger.info(f"Video: {video_path}")
    logger.info(f"Video ID: {video_id}")

    if not check_ffmpeg():
        logger.error("FFmpeg not found. Install FFmpeg and ensure it is on your PATH.")
        logger.error("Download: https://ffmpeg.org/download.html")
        raise EnvironmentError("FFmpeg is required but not accessible.")

    duration = get_video_duration(video_path, logger)
    logger.info(f"Video duration: {duration:.2f}s")

    audio_path = extract_audio(video_path, video_id, logger)
    frames = extract_keyframes(video_path, video_id, logger)
    scenes = detect_scene_changes(video_path, logger)

    metadata = {
        "video_id": video_id,
        "source_path": str(video_path),
        "duration_seconds": duration,
        "audio_path": str(audio_path),
        "frames_dir": str(FRAMES_DIR / video_id),
        "frame_count": len(frames),
        "frame_paths": [str(f) for f in frames],
        "scene_changes": scenes,
        "scene_change_count": len(scenes),
        "extracted_at": datetime.now().isoformat(),
    }

    meta_path = LOGS_DIR / f"extract-meta-{video_id}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"Extraction metadata saved → {meta_path}")
    logger.info("=== Extraction complete ===")

    return metadata


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyzer/extract.py <video_path>")
        sys.exit(1)
    result = extract(sys.argv[1])
    print(json.dumps(result, indent=2))
