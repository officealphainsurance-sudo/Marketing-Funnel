"""
run.py — Master pipeline CLI
Chains extract → transcribe → ocr → analyze → generate

Usage:
    python analyzer/run.py --video "competitor-videos/filename.mp4" --brand w-real-estate
"""

import os
import sys
import json
import argparse
import logging
import subprocess
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"

load_dotenv(ROOT / "config" / ".env")

VALID_BRANDS = ["w-real-estate", "alpha-insurance"]


# ─── Logging ──────────────────────────────────────────────────────────────────

def setup_run_logger(run_id: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"run-{run_id}.log"
    logger = logging.getLogger(f"run.{run_id}")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ─── Pre-flight Checks ────────────────────────────────────────────────────────

def check_ffmpeg(logger: logging.Logger) -> bool:
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        if result.returncode == 0:
            version_line = result.stdout.splitlines()[0] if result.stdout else "ffmpeg found"
            logger.info(f"✓ FFmpeg: {version_line[:60]}")
            return True
    except FileNotFoundError:
        pass
    logger.error("✗ FFmpeg not found. Install from https://ffmpeg.org/download.html and add to PATH.")
    return False


def check_tesseract(logger: logging.Logger) -> bool:
    try:
        import pytesseract
        version = pytesseract.get_tesseract_version()
        logger.info(f"✓ Tesseract: v{version}")
        return True
    except Exception:
        logger.error(
            "✗ Tesseract not found.\n"
            "  Install from: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  Then add Tesseract to your PATH."
        )
        return False


def check_python_deps(logger: logging.Logger) -> bool:
    required = ["anthropic", "openai", "dotenv", "pytesseract", "PIL", "ffmpeg"]
    missing = []
    for dep in required:
        try:
            __import__(dep)
        except ImportError:
            missing.append(dep)
    if missing:
        logger.error(f"✗ Missing Python packages: {missing}")
        logger.error("  Run: pip install -r requirements.txt")
        return False
    logger.info("✓ Python dependencies: all present")
    return True


def check_api_keys(logger: logging.Logger) -> bool:
    ok = True
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not anthropic_key:
        logger.error("✗ ANTHROPIC_API_KEY not set in config/.env")
        ok = False
    else:
        logger.info("✓ ANTHROPIC_API_KEY: set")

    if not openai_key:
        logger.error("✗ OPENAI_API_KEY not set in config/.env")
        ok = False
    else:
        logger.info("✓ OPENAI_API_KEY: set")

    if not ok:
        logger.error("  Copy config/.env.template to config/.env and fill in your API keys.")

    return ok


def step(label: str, logger: logging.Logger) -> None:
    logger.info(f"\n{'─'*50}")
    logger.info(f"  STEP: {label}")
    logger.info(f"{'─'*50}")


# ─── Main Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(video_path: str, brand: str) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = timestamp
    logger = setup_run_logger(run_id)
    cumulative_cost = 0.0

    logger.info("=" * 60)
    logger.info("  ContentEngine Pipeline")
    logger.info(f"  Run ID: {run_id}")
    logger.info(f"  Video: {video_path}")
    logger.info(f"  Brand: {brand}")
    logger.info("=" * 60)

    # ── Validate inputs ──────────────────────────────────────────────────────

    video_file = ROOT / video_path
    if not video_file.exists():
        # Try absolute path
        video_file = Path(video_path).resolve()
    if not video_file.exists():
        logger.error(f"Video file not found: {video_path}")
        sys.exit(1)

    if brand not in VALID_BRANDS:
        logger.error(f"Invalid brand '{brand}'. Must be one of: {VALID_BRANDS}")
        sys.exit(1)

    # ── Pre-flight ───────────────────────────────────────────────────────────

    step("Pre-flight environment checks", logger)
    checks = [
        check_ffmpeg(logger),
        check_tesseract(logger),
        check_python_deps(logger),
        check_api_keys(logger),
    ]
    if not all(checks):
        logger.error("\nPre-flight checks failed. Fix the above issues before running.")
        sys.exit(1)
    logger.info("✓ All pre-flight checks passed.")

    # ── Import pipeline modules ───────────────────────────────────────────────
    sys.path.insert(0, str(ROOT))
    from analyzer.extract import extract
    from analyzer.transcribe import transcribe
    from analyzer.ocr import run_ocr
    from analyzer.analyze import analyze
    from analyzer.generate import generate

    # ── Step 1: Extract ──────────────────────────────────────────────────────

    step("1/5 — Extracting audio and keyframes", logger)
    t0 = datetime.now()
    try:
        extract_meta = extract(video_file)
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        sys.exit(1)
    video_id = extract_meta["video_id"]
    duration = extract_meta["duration_seconds"]
    logger.info(f"✓ Extract complete in {(datetime.now()-t0).seconds}s | {extract_meta['frame_count']} frames | {extract_meta['scene_change_count']} scenes")

    # Save extract meta for downstream steps
    extract_meta_path = LOGS_DIR / f"extract-meta-{video_id}.json"

    # ── Step 2: Transcribe ───────────────────────────────────────────────────

    step("2/5 — Transcribing audio via Whisper", logger)
    t0 = datetime.now()
    audio_path = extract_meta["audio_path"]
    try:
        transcript = transcribe(audio_path, video_id, duration)
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        sys.exit(1)
    whisper_cost = transcript.get("estimated_cost_usd", 0)
    cumulative_cost += whisper_cost
    transcript_path = LOGS_DIR / "transcripts" / f"{video_id}.json"
    logger.info(f"✓ Transcribe complete in {(datetime.now()-t0).seconds}s | Cost: ${whisper_cost:.4f}")

    # ── Step 3: OCR ──────────────────────────────────────────────────────────

    step("3/5 — Running OCR on keyframes", logger)
    t0 = datetime.now()
    frames_dir = extract_meta["frames_dir"]
    try:
        ocr_result = run_ocr(frames_dir, video_id)
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        sys.exit(1)
    ocr_path = LOGS_DIR / f"ocr-{video_id}.json"
    logger.info(f"✓ OCR complete in {(datetime.now()-t0).seconds}s | {ocr_result['unique_text_blocks']} text blocks found")

    # ── Step 4: Analyze ──────────────────────────────────────────────────────

    step("4/5 — Analyzing with Claude", logger)
    t0 = datetime.now()
    try:
        analysis_result = analyze(extract_meta_path, transcript_path, ocr_path)
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        sys.exit(1)
    analyze_cost = analysis_result["api_usage"]["estimated_cost_usd"]
    cumulative_cost += analyze_cost

    # Find the saved analysis file
    scripts_dir = ROOT / "scripts"
    analysis_files = sorted(scripts_dir.glob(f"analysis-{video_id}-*.json"), reverse=True)
    if not analysis_files:
        logger.error("Analysis output file not found in /scripts.")
        sys.exit(1)
    analysis_path = analysis_files[0]
    logger.info(f"✓ Analysis complete in {(datetime.now()-t0).seconds}s | Cost: ${analyze_cost:.6f}")

    # ── Step 5: Generate ─────────────────────────────────────────────────────

    step("5/5 — Generating brand content", logger)
    t0 = datetime.now()
    try:
        gen_result = generate(analysis_path, brand)
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        sys.exit(1)
    gen_cost = gen_result["api_usage"]["estimated_cost_usd"]
    cumulative_cost += gen_cost

    script_files = sorted(scripts_dir.glob(f"{brand}-{video_id}-*.json"), reverse=True)
    script_path = script_files[0] if script_files else "unknown"
    logger.info(f"✓ Generation complete in {(datetime.now()-t0).seconds}s | Cost: ${gen_cost:.6f}")

    # ── Summary ──────────────────────────────────────────────────────────────

    logger.info("\n" + "=" * 60)
    logger.info("  PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Brand:        {brand}")
    logger.info(f"  Video ID:     {video_id}")
    logger.info(f"  Script saved: {script_path}")
    logger.info(f"  Cost summary:")
    logger.info(f"    Whisper:    ${whisper_cost:.4f}")
    logger.info(f"    Claude:     ${analyze_cost + gen_cost:.6f}")
    logger.info(f"    TOTAL:      ${cumulative_cost:.4f}")
    logger.info(f"  Run log:      {LOGS_DIR}/run-{run_id}.log")
    logger.info("=" * 60)

    # Append cost data to cost log for costs.py
    cost_log_path = LOGS_DIR / "api-costs.jsonl"
    cost_entry = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "brand": brand,
        "video_id": video_id,
        "costs": {
            "whisper_usd": whisper_cost,
            "claude_analyze_usd": analyze_cost,
            "claude_generate_usd": gen_cost,
            "total_usd": cumulative_cost,
        }
    }
    with open(cost_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(cost_entry) + "\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ContentEngine — Competitor video analysis and brand script generation"
    )
    parser.add_argument(
        "--video", required=True,
        help='Path to competitor video, e.g. "competitor-videos/example.mp4"'
    )
    parser.add_argument(
        "--brand", required=True, choices=VALID_BRANDS,
        help="Brand to generate content for"
    )
    args = parser.parse_args()
    run_pipeline(args.video, args.brand)


if __name__ == "__main__":
    main()
