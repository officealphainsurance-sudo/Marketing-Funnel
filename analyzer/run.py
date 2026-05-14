"""
run.py v2.2 — Master pipeline CLI (Brain-Aware + Remotion Render)
Chains extract → transcribe → ocr → analyze → score → synthesize → generate → render

CHANGELOG v2.2:
- ADDED: Step 8 Remotion video render — full MP4 output after generation.
- Render failures are non-fatal — pipeline output (script JSON) still usable.

CHANGELOG v2.1:
- FIXED: Restored 'ffmpeg' to required Python deps (regression from v2.0).
- FIXED: git pull --rebase before push to prevent race condition between
  Windows desktop and MacBook brain-sync commits.

Usage:
    python analyzer/run.py --video "competitor-videos/filename.mp4" --brand w-real-estate

Or with intake (URL-first workflow):
    python analyzer/intake.py --url "https://youtube.com/watch?v=xxxx" --brand w-real-estate
    python analyzer/run.py --video "competitor-videos/<filename-from-intake>.mp4" --brand w-real-estate
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

if sys.platform == 'darwin':
    LOGS_DIR = Path('/tmp/contentengine/logs')
else:
    LOGS_DIR = ROOT / "logs"

LOGS_DIR.mkdir(parents=True, exist_ok=True)

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

    youtube_key = os.getenv("YOUTUBE_API_KEY")
    if not youtube_key:
        logger.info("ℹ  YOUTUBE_API_KEY not set — YouTube auto-metadata disabled (manual entry required)")
    else:
        logger.info("✓ YOUTUBE_API_KEY: set")

    if not ok:
        logger.error("  Copy config/.env.template to config/.env and fill in your API keys.")

    return ok


def step(label: str, logger: logging.Logger) -> None:
    logger.info(f"\n{'─'*50}")
    logger.info(f"  STEP: {label}")
    logger.info(f"{'─'*50}")


# ─── Git Sync ─────────────────────────────────────────────────────────────────

def git_pull_brain(logger: logging.Logger) -> None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=str(ROOT)
        )
        if result.returncode != 0:
            return

        result = subprocess.run(
            ["git", "pull", "--rebase", "--autostash"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=30
        )
        if result.returncode == 0:
            if "Already up to date" in result.stdout or "is up to date" in result.stdout:
                logger.info("✓ Repo up to date — no remote brain changes")
            else:
                logger.info("✓ Pulled latest brain from GitHub")
        else:
            logger.info(f"ℹ  Git pull skipped: {result.stderr[:120].strip()}")

    except FileNotFoundError:
        logger.info("ℹ  Git not found in PATH — skipping pull")
    except subprocess.TimeoutExpired:
        logger.info("ℹ  Git pull timed out — continuing offline")
    except Exception as e:
        logger.info(f"ℹ  Git pull skipped: {e}")


def git_commit_brain(logger: logging.Logger) -> None:
    brain_path = ROOT / "data" / "agent-brain.json"
    if not brain_path.exists():
        return

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=str(ROOT)
        )
        if result.returncode != 0:
            logger.info("ℹ  Not a git repo — skipping brain auto-commit")
            return

        subprocess.run(["git", "add", str(brain_path)], capture_output=True, cwd=str(ROOT))

        commit_msg = f"brain update {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            capture_output=True, text=True, cwd=str(ROOT)
        )

        if result.returncode != 0:
            if "nothing to commit" in (result.stdout + result.stderr).lower():
                logger.info("ℹ  Brain unchanged — no commit needed")
            else:
                logger.info(f"ℹ  Git commit skipped: {result.stderr[:120].strip()}")
            return

        pull_result = subprocess.run(
            ["git", "pull", "--rebase", "--autostash"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=30
        )
        if pull_result.returncode != 0:
            logger.info(f"ℹ  Pre-push pull failed: {pull_result.stderr[:120].strip()}")
            logger.info("   Brain committed locally but not pushed — resolve manually")
            return

        push_result = subprocess.run(
            ["git", "push"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=30
        )
        if push_result.returncode == 0:
            logger.info("✓ Brain synced to GitHub")
        else:
            logger.info(f"ℹ  Push failed: {push_result.stderr[:120].strip()}")
            logger.info("   Brain committed locally — push manually when online")

    except FileNotFoundError:
        logger.info("ℹ  Git not found in PATH — skipping brain auto-commit")
    except subprocess.TimeoutExpired:
        logger.info("ℹ  Git operation timed out — brain committed locally")
    except Exception as e:
        logger.info(f"ℹ  Brain auto-commit skipped: {e}")


# ─── Main Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(video_path: str, brand: str) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = timestamp
    logger = setup_run_logger(run_id)
    cumulative_cost = 0.0

    logger.info("=" * 60)
    logger.info("  ContentEngine Pipeline v2.2 — Brain-Aware + Remotion")
    logger.info(f"  Run ID: {run_id}")
    logger.info(f"  Video: {video_path}")
    logger.info(f"  Brand: {brand}")
    logger.info("=" * 60)

    video_file = ROOT / video_path
    if not video_file.exists():
        video_file = Path(video_path).resolve()
    if not video_file.exists():
        logger.error(f"Video file not found: {video_path}")
        sys.exit(1)

    if brand not in VALID_BRANDS:
        logger.error(f"Invalid brand '{brand}'. Must be one of: {VALID_BRANDS}")
        sys.exit(1)

    # Pre-flight
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

    # Pull latest brain BEFORE any work — prevents race condition
    step("Brain pre-sync", logger)
    git_pull_brain(logger)

    # Import pipeline modules
    sys.path.insert(0, str(ROOT))
    from analyzer.extract import extract
    from analyzer.transcribe import transcribe
    from analyzer.ocr import run_ocr
    from analyzer.analyze import analyze
    from analyzer.score import score
    from analyzer.synthesize import synthesize
    from analyzer.generate import generate

    # Step 1: Extract
    step("1/8 — Extracting audio and keyframes", logger)
    t0 = datetime.now()
    try:
        extract_meta = extract(video_file)
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        sys.exit(1)
    video_id = extract_meta["video_id"]
    duration = extract_meta["duration_seconds"]
    logger.info(f"✓ Extract complete in {(datetime.now()-t0).seconds}s | {extract_meta['frame_count']} frames | {extract_meta['scene_change_count']} scenes")

    extract_meta_path = LOGS_DIR / f"extract-meta-{video_id}.json"

    # Step 2: Transcribe
    step("2/8 — Transcribing audio via Whisper", logger)
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

    # Step 3: OCR
    step("3/8 — Running OCR on keyframes", logger)
    t0 = datetime.now()
    frames_dir = extract_meta["frames_dir"]
    try:
        ocr_result = run_ocr(frames_dir, video_id)
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        sys.exit(1)
    ocr_path = LOGS_DIR / f"ocr-{video_id}.json"
    logger.info(f"✓ OCR complete in {(datetime.now()-t0).seconds}s | {ocr_result['unique_text_blocks']} text blocks found")

    # Step 4: Analyze
    step("4/8 — Analyzing with Claude", logger)
    t0 = datetime.now()
    try:
        analysis_result = analyze(extract_meta_path, transcript_path, ocr_path)
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        sys.exit(1)
    analyze_cost = analysis_result["api_usage"]["estimated_cost_usd"]
    cumulative_cost += analyze_cost

    scripts_dir = ROOT / "scripts"
    analysis_files = sorted(scripts_dir.glob(f"analysis-{video_id}-*.json"), reverse=True)
    if not analysis_files:
        logger.error("Analysis output file not found in /scripts.")
        sys.exit(1)
    analysis_path = analysis_files[0]
    logger.info(f"✓ Analysis complete in {(datetime.now()-t0).seconds}s | Cost: ${analyze_cost:.6f}")

    # Step 5: Score
    step("5/8 — Scoring hooks via HookGenie", logger)
    t0 = datetime.now()
    try:
        score_result = score(analysis_path, brand)
    except Exception as e:
        logger.error(f"Scoring failed: {e}")
        sys.exit(1)

    primary_hook = score_result.get("primary_hook_score", {})
    top_patterns = score_result.get("top_3_recommended_patterns", [])
    companion_found = score_result.get("performance_context", {}).get("companion_found", False)
    if not companion_found:
        logger.warning("⚠  No companion JSON found — view weighting disabled. Run intake.py before run.py for performance learning.")
    logger.info(
        f"✓ Score complete in {(datetime.now()-t0).seconds}s | "
        f"Hook: {primary_hook.get('hook_type')} ({primary_hook.get('composite_score')}) | "
        f"Top: {[p['hook_type'] for p in top_patterns]}"
    )

    # Step 6: Synthesize
    step("6/8 — Synthesizing agent brain", logger)
    t0 = datetime.now()
    try:
        synth_result = synthesize(brand)
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        sys.exit(1)

    brain_context = synth_result.get("brain_context", {})
    brain_active = brain_context.get("has_learned_patterns", False)
    videos_synthesized = synth_result.get("videos_synthesized", 0)
    logger.info(
        f"✓ Synthesize complete in {(datetime.now()-t0).seconds}s | "
        f"Brain: {'ACTIVE' if brain_active else 'BUILDING'} | "
        f"{videos_synthesized} videos aggregated"
    )

    # Step 7: Generate
    step("7/8 — Generating brand content", logger)
    t0 = datetime.now()
    try:
        gen_result = generate(analysis_path, brand, brain_context)
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        sys.exit(1)
    gen_cost = gen_result["api_usage"]["estimated_cost_usd"]
    cumulative_cost += gen_cost

    script_files = sorted(scripts_dir.glob(f"{brand}-{video_id}-*.json"), reverse=True)
    script_path = script_files[0] if script_files else "unknown"
    logger.info(f"✓ Generation complete in {(datetime.now()-t0).seconds}s | Cost: ${gen_cost:.6f}")

    # Brain post-sync to GitHub
    step("Brain post-sync", logger)
    git_commit_brain(logger)

    # Step 8: Remotion render
    step("8/8 — Rendering Remotion video", logger)
    t0 = datetime.now()
    render_result = None
    try:
        from analyzer.remotion_render import render_remotion
        script_files_latest = sorted(
            scripts_dir.glob(f"{brand}-{video_id}-*.json"), reverse=True
        )
        if script_files_latest:
            render_result = render_remotion(
                str(script_files_latest[0]), brand, logger
            )
            logger.info(f"✓ Remotion render complete in {(datetime.now()-t0).seconds}s")
        else:
            logger.warning("⚠  No script file found for Remotion render")
    except Exception as e:
        logger.error(f"✗ Remotion render failed: {e}")
        logger.info("  Pipeline output (script JSON) still usable — render manually:")
        logger.info(f"  python analyzer/remotion_render.py <script.json> {brand}")

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("  PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Brand:          {brand}")
    logger.info(f"  Video ID:       {video_id}")
    logger.info(f"  Script saved:   {script_path}")
    logger.info(f"  Brain active:   {brain_active} ({videos_synthesized} videos)")
    logger.info(f"  Companion JSON: {'found' if companion_found else 'missing — performance weighting OFF'}")
    logger.info(f"  Cost summary:")
    logger.info(f"    Whisper:      ${whisper_cost:.4f}")
    logger.info(f"    Claude:       ${analyze_cost + gen_cost:.6f}")
    logger.info(f"    TOTAL:        ${cumulative_cost:.4f}")
    logger.info(f"  Run log:        {LOGS_DIR}/run-{run_id}.log")
    if render_result:
        logger.info(f"  Video:          {render_result['video_path']} ({render_result['video_size_mb']:.1f} MB)")
    logger.info("=" * 60)

    cost_log_path = LOGS_DIR / "api-costs.jsonl"
    cost_entry = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "brand": brand,
        "video_id": video_id,
        "brain_active": brain_active,
        "companion_found": companion_found,
        "costs": {
            "whisper_usd": whisper_cost,
            "claude_analyze_usd": analyze_cost,
            "claude_generate_usd": gen_cost,
            "total_usd": cumulative_cost,
        }
    }
    with open(cost_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(cost_entry) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="ContentEngine v2.2 — Brain-aware competitor video analysis, script generation, and Remotion render"
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
 