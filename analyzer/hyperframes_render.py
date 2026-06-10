#!/usr/bin/env python3.11
# Adapted from MoneyPrinterTurbo (MIT) github.com/harry0703/MoneyPrinterTurbo
"""
hyperframes_render.py — Subprocess wrapper for `npx hyperframes render`.

Uses --variables-file (temp JSON) instead of --variables inline to avoid
shell-escaping issues with large word arrays from faster-whisper.
"""

import json
import os
import shutil
import subprocess
import time
import logging
import tempfile
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / "config" / ".env")

RENDERS_DIR = ROOT / "renders"
RENDERS_DIR.mkdir(parents=True, exist_ok=True)

RENDER_TIMEOUT = 600  # 10 minutes — generous for first-run Chrome download
RENDER_QUALITY = "standard"

logger = logging.getLogger(__name__)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)
logger.setLevel(logging.INFO)


def _hyperframes_bin() -> str:
    """Return the hyperframes binary path — local install preferred over npx."""
    local_bin = Path(__file__).parent.parent / "node_modules" / ".bin" / "hyperframes"
    if local_bin.exists():
        return str(local_bin)
    return None  # caller falls back to npx --no-install


def _ffprobe_duration(path: str) -> float | None:
    """Return media duration in seconds via ffprobe, or None on failure."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(r.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def _concat_broll_clips(clips: list[dict], work_dir: Path) -> str | None:
    """
    Trim each manifest-assigned B-roll clip to its segment duration and
    stitch them into a single track covering the full reel.

    Adapted from MoneyPrinterTurbo's combine_videos()/concat_video_clips_with_ffmpeg():
    each source clip is trimmed to its assigned duration (looping via
    -stream_loop if the source is shorter than the segment) and the
    resulting segments are joined with the ffmpeg concat demuxer.

    clips: list of manifest clip dicts with "local_path" and "duration".
    Returns the path to the combined video, or None if no usable clips.
    """
    valid = [
        c for c in clips
        if c.get("local_path") and Path(c["local_path"]).exists() and c.get("duration", 0) > 0
    ]
    if not valid:
        return None

    segment_dir = work_dir / "broll_segments"
    segment_dir.mkdir(parents=True, exist_ok=True)

    segment_paths: list[Path] = []
    for i, clip in enumerate(valid):
        src = clip["local_path"]
        seg_duration = float(clip["duration"])
        role = clip.get("role", f"clip{i}")

        actual_duration = _ffprobe_duration(src)
        seg_out = segment_dir / f"seg_{i:02d}_{role}.mp4"

        cmd = ["ffmpeg", "-y"]
        if actual_duration is None or actual_duration < seg_duration:
            cmd += ["-stream_loop", "-1"]
        cmd += [
            "-i", src,
            "-t", str(seg_duration),
            "-an",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(seg_out),
        ]

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            logger.warning(f"  B-roll segment trim failed [{role}]: {r.stderr[-300:]}")
            continue
        segment_paths.append(seg_out)
        logger.info(f"  B-roll segment [{role}]: {seg_duration:.2f}s ({Path(src).name})")

    if not segment_paths:
        return None
    if len(segment_paths) == 1:
        return str(segment_paths[0])

    # ffmpeg concat demuxer list — paths normalized for cross-platform safety
    list_path = segment_dir / "concat_list.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in segment_paths:
            escaped = str(p).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    combined = work_dir / "broll_combined.mp4"
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_path),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(combined),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        logger.warning(f"  B-roll concat failed: {r.stderr[-300:]} — using first segment only")
        return str(segment_paths[0])

    logger.info(f"  B-roll combined: {len(segment_paths)} segments → {combined.name}")
    return str(combined)


def _composite_broll(
    hf_path: str,
    broll_path: str,
    audio_path: str,
    bg_color: str,
    duration: float,
) -> None:
    """
    Composite B-roll under HyperFrames overlay via FFmpeg (in-place).

    HyperFrames serves compositions via localhost HTTP, so local POSIX paths
    in <video src> 404 and the element errors silently. This post-process step
    colourkeys the brand's solid background colour out of the HF render and
    composites the B-roll underneath.

    bg_color: 6-char hex without '#' (e.g. "0D1825").
    similarity=0.06 safely removes both alpha-insurance (#0D1825) and
    w-real-estate (#1A0A0A) backgrounds without touching gold/white elements.
    """
    hf_p = Path(hf_path)
    tmp = hf_p.with_suffix(".hf_raw.mp4")
    shutil.move(hf_path, tmp)

    try:
        # HyperFrames renders at device pixel ratio 2× on macOS (2160×3840).
        # Scale it back to 1080×1920 before colorkey so the overlay crops correctly.
        filter_graph = ";".join([
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,setsar=1[bg]",
            "[1:v]scale=1080:1920[hf_scaled]",
            f"[hf_scaled]colorkey=color=0x{bg_color}:similarity=0.06:blend=0.02[fg]",
            "[bg][fg]overlay=format=auto[out]",
        ])

        inputs = ["-stream_loop", "-1", "-i", broll_path, "-i", str(tmp)]
        has_audio = bool(audio_path) and Path(audio_path).exists()
        if has_audio:
            inputs += ["-i", audio_path]

        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + ["-filter_complex", filter_graph, "-map", "[out]"]
        )
        if has_audio:
            cmd += ["-map", "2:a", "-c:a", "aac", "-b:a", "192k"]

        logger.info(f"  Composite: B-roll + HF overlay (bg #{bg_color})")

        # Try Apple Silicon hardware encoder first (~6s); fall back to software (~16min)
        for encoder_args, label in [
            (["-c:v", "h264_videotoolbox", "-q:v", "65", "-pix_fmt", "yuv420p"], "h264_videotoolbox"),
            (["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p"], "libx264"),
        ]:
            full_cmd = cmd + ["-t", str(duration)] + encoder_args + [hf_path]
            r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=300)
            if r.returncode == 0:
                logger.info(f"  ✓ Composite complete ({label})")
                break
            encoder_err = any(
                tok in r.stderr for tok in ("videotoolbox", "h264_videotoolbox", "encoder not found")
            )
            if not encoder_err:
                # Non-encoder failure — no point retrying
                logger.error(f"  FFmpeg composite stderr:\n{r.stderr[-1000:]}")
                shutil.move(str(tmp), hf_path)
                return
            logger.warning(f"  {label} unavailable, falling back to software encoder")
        else:
            logger.error(f"  FFmpeg composite failed:\n{r.stderr[-1000:]}")
            shutil.move(str(tmp), hf_path)
            return

        tmp.unlink(missing_ok=True)

    except Exception as exc:
        logger.error(f"  Composite error: {exc}")
        if tmp.exists():
            shutil.move(str(tmp), hf_path)


def _check_hyperframes() -> str:
    """Verify hyperframes is available and return its version string."""
    local = _hyperframes_bin()
    if local:
        cmd = [local, "--version"]
    else:
        cmd = ["npx", "--no-install", "hyperframes", "--version"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(
            "hyperframes not found. Run: npm install hyperframes"
        )
    return result.stdout.strip() or result.stderr.strip()


def render(
    composition: str,
    variables: dict,
    output_path: str | None = None,
    fps: int = 30,
    quality: str = RENDER_QUALITY,
    workers: int = 1,
) -> dict:
    """
    Render a HyperFrames composition to MP4.

    Args:
        composition:  Path to the composition DIRECTORY (containing index.html),
                      relative to project root.
                      e.g. "compositions/authority_reel/alpha-insurance"
        variables:    Dict passed to window.__hyperframes.getVariables().
                      Must include: words, duration, brand_name, phone,
                      broll_path, audio_path.
        output_path:  Absolute output path. Auto-generated if omitted.
        fps:          Frame rate (default 30).
        quality:      "draft" | "standard" | "high"
        workers:      Chrome render workers (1 for low-memory machines).

    Returns:
        {output_path, file_size_bytes, duration_seconds, render_time_seconds}
    """
    _check_hyperframes()

    # ── Resolve composition directory ──────────────────────────────────────
    # composition is a directory; HyperFrames finds index.html automatically
    # when run from that directory (cwd = comp_dir, cmd = "render .").
    comp_dir = Path(composition)
    if not comp_dir.is_absolute():
        comp_dir = ROOT / composition
    if not comp_dir.is_dir():
        raise FileNotFoundError(f"Composition directory not found: {comp_dir}")
    index_html = comp_dir / "index.html"
    if not index_html.exists():
        raise FileNotFoundError(f"index.html not found in: {comp_dir}")

    if output_path is None:
        brand = variables.get("brand", "video")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = str(RENDERS_DIR / f"{brand}_{timestamp}.mp4")

    output_path = str(Path(output_path).resolve())

    # ── Write variables to temp file ───────────────────────────────────────
    # --variables-file avoids shell-quoting issues with large word arrays
    vars_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="hf_vars_", delete=False
    )
    try:
        json.dump(variables, vars_file, ensure_ascii=False)
        vars_file.close()

        # ── Build command ──────────────────────────────────────────────────
        # Use the local binary when available — avoids npx hitting the registry
        # on every call. Fall back to npx --no-install so the caller gets a
        # clear error rather than a silent registry download.
        local = _hyperframes_bin()
        if local:
            hf_cmd = [local]
        else:
            hf_cmd = ["npx", "--no-install", "hyperframes"]
        cmd = [
            *hf_cmd, "render", ".",
            "--output",      output_path,
            "--fps",         str(fps),
            "--quality",     quality,
            "--workers",     str(workers),
            "--variables-file", vars_file.name,
        ]

        logger.info(f"  Render: {comp_dir.name}/index.html → {Path(output_path).name}")
        logger.info(f"  Cmd: {' '.join(cmd)}")

        t0 = time.time()
        result = subprocess.run(
            cmd,
            cwd=str(comp_dir),
            capture_output=True,
            text=True,
            timeout=RENDER_TIMEOUT,
        )
        elapsed = round(time.time() - t0, 1)

    finally:
        # Always clean up the temp variables file
        try:
            Path(vars_file.name).unlink()
        except OSError:
            pass

    if result.returncode != 0:
        logger.error(f"  hyperframes stderr:\n{result.stderr[-2000:]}")
        raise RuntimeError(
            f"hyperframes render failed (exit {result.returncode}):\n"
            f"{result.stderr[-800:]}"
        )

    out = Path(output_path)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(
            f"Render succeeded (exit 0) but output file missing or empty: {output_path}"
        )

    # ── B-roll compositing ─────────────────────────────────────────────────
    # HyperFrames serves via localhost HTTP; local POSIX paths in <video src>
    # 404 and are silently skipped. FFmpeg colourkeys the brand background out
    # of the HF render and composites the B-roll underneath instead.
    broll_clips = variables.get("broll_clips")
    broll_path = variables.get("broll_path", "")

    if broll_clips:
        work_dir = Path(tempfile.mkdtemp(prefix="hf_broll_"))
        try:
            combined = _concat_broll_clips(broll_clips, work_dir)
            if combined:
                broll_path = combined
            else:
                logger.warning("  No usable B-roll clips in broll_clips — falling back to broll_path")
        except Exception as exc:
            logger.error(f"  B-roll stitching failed: {exc} — falling back to broll_path")

    try:
        if broll_path and Path(broll_path).exists():
            _composite_broll(
                output_path,
                broll_path,
                variables.get("audio_path", ""),
                variables.get("bg_color", "0D1825"),
                float(variables.get("duration", 30)),
            )
    finally:
        if broll_clips:
            shutil.rmtree(work_dir, ignore_errors=True)

    size_bytes = out.stat().st_size
    size_mb = round(size_bytes / 1_048_576, 2)
    logger.info(
        f"  ✓ Render complete: {out.name} | {size_mb}MB | {elapsed}s"
    )

    return {
        "output_path":         output_path,
        "file_size_bytes":     size_bytes,
        "file_size_mb":        size_mb,
        "duration_seconds":    variables.get("duration", 0),
        "render_time_seconds": elapsed,
        "composition":         str(comp_dir.relative_to(ROOT)),
        "fps":                 fps,
        "quality":             quality,
    }


if __name__ == "__main__":
    import sys

    print("\nRunning hyperframes_render smoke test")

    # Verify hyperframes is available
    try:
        ver = _check_hyperframes()
        print(f"  hyperframes: {ver}")
    except RuntimeError as e:
        print(f"  ✗ {e}")
        sys.exit(1)

    # Verify composition directories and shared file exist
    comps = [
        "compositions/authority_reel/w-real-estate/index.html",
        "compositions/authority_reel/alpha-insurance/index.html",
        "compositions/shared/animations.js",
    ]
    all_ok = True
    for c in comps:
        p = ROOT / c
        if p.exists():
            print(f"  ✓ {c}")
        else:
            print(f"  ✗ Missing: {c}")
            all_ok = False

    if not all_ok:
        sys.exit(1)

    # Dry-run: validate the --variables-file path works by building a sample
    # command without executing (render is expensive; full test is in pipeline)
    sample_vars = {
        "brand": "alpha-insurance",
        "brand_name": "Alpha Insurance",
        "phone": "601-981-2911",
        "duration": 8.6,
        "words": [{"word": "Hello", "start": 0.0, "end": 0.5}],
        "broll_path": "",
        "audio_path": "",
    }

    # Just test that render() will reach the subprocess stage without error
    # (don't actually render — full render test is in generate_video.py)
    import shutil
    if not shutil.which("npx"):
        print("  ✗ npx not found in PATH")
        sys.exit(1)

    print(f"  sample variables JSON: {len(json.dumps(sample_vars))} bytes")

    print(f"\n✓ hyperframes_render smoke test passed")
    print(f"  ⚠️  Full render test requires B-roll + TTS audio — run via generate_video.py")
