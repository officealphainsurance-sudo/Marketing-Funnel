"""
render.py — Pure FFmpeg rendering pipeline (Phase 2)
No Rendervid. No Puppeteer. Just FFmpeg doing what it's best at.

Architecture: For each segment:
  1. Load b-roll clip, scale + crop to 1080x1920
  2. Trim to segment duration, loop if shorter
  3. Apply 45% dark overlay
  4. Burn text with fade-in/fade-out animations
  5. CTA segment: add pill background + lower third
Then concatenate all segments into final MP4.

Usage:
    python analyzer/render.py <script.json> <brand>
    python analyzer/render.py <script.json> <brand> --broll-dir <path>
"""

import os
import sys
import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# =============================================================================
# CONFIG
# =============================================================================

ROOT          = Path(__file__).parent.parent
LOGS_DIR      = ROOT / "logs"
VIDEOS_DIR    = ROOT / "videos"
BROLL_DIR     = ROOT / "broll"
TEMP_DIR      = ROOT / "temp"

VALID_BRANDS = ["w-real-estate", "alpha-insurance"]

OUTPUT_WIDTH    = 1080
OUTPUT_HEIGHT   = 1920
OUTPUT_FPS      = 30

DARK_OVERLAY_OPACITY = 0.45
TEXT_FONT_SIZE       = 60
TEXT_LINE_HEIGHT     = 86
TEXT_FADE_IN         = 0.5      # seconds
TEXT_FADE_OUT        = 0.4      # seconds
TEXT_MAX_CHARS_LINE  = 26       # word-wrap target

CTA_FONT_SIZE        = 42
CTA_PILL_HEIGHT      = 160
CTA_PILL_WIDTH       = 900
CTA_PILL_Y           = 1620

# Try common Windows fonts in order
FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",   # Segoe UI Bold
    "C:/Windows/Fonts/seguisb.ttf",    # Segoe UI Semibold
    "C:/Windows/Fonts/segoeui.ttf",    # Segoe UI Regular
    "C:/Windows/Fonts/arialbd.ttf",    # Arial Bold
    "C:/Windows/Fonts/arial.ttf",      # Arial
]


def find_font() -> str:
    """Find first available font, return ffmpeg-safe path with escaped colons."""
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            # Escape colon for ffmpeg filter syntax
            return candidate.replace(":", "\\:")
    raise RuntimeError("No usable font found in C:/Windows/Fonts/")


# =============================================================================
# HELPERS
# =============================================================================

def get_logger(video_id: str, brand: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file  = LOGS_DIR / f"render-{brand}-{timestamp}.log"
    logger    = logging.getLogger(f"render.{brand}.{video_id}.{timestamp}")
    logger.setLevel(logging.DEBUG)
    fh  = logging.FileHandler(log_file, encoding="utf-8")
    ch  = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def parse_time_range(time_str: str) -> tuple[int, int]:
    start, end = time_str.split("-")
    return (int(start), int(end))


def load_broll_manifest(video_id: str, broll_override=None) -> dict:
    if broll_override:
        broll_dir = Path(broll_override)
        if not broll_dir.is_absolute():
            broll_dir = (ROOT / broll_override).resolve()
    else:
        broll_dir = BROLL_DIR / video_id

    if not broll_dir.exists():
        return {}

    for manifest_name in ["manifest.json", "pexels_manifest.json"]:
        manifest_path = broll_dir / manifest_name
        if manifest_path.exists():
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            clips     = manifest.get("clips", {})
            abs_clips = {}
            for label, rel_path in clips.items():
                abs_path = ROOT / rel_path
                if not abs_path.exists():
                    abs_path = Path(rel_path)
                if abs_path.exists():
                    abs_clips[label] = str(abs_path.resolve())
            return abs_clips

    mp4_files = sorted(broll_dir.glob("*.mp4"))
    if mp4_files:
        scene_labels = ["scene-0s", "scene-3s", "scene-8s", "scene-16s"]
        return {
            (scene_labels[i] if i < len(scene_labels) else f"scene-{i}"): str(f.resolve())
            for i, f in enumerate(mp4_files)
        }
    return {}


def map_segment_to_broll(label: str, seconds: str, broll_clips: dict):
    if not broll_clips:
        return None
    start_sec = seconds.split("-")[0]
    scene_key = f"scene-{start_sec}s"
    if scene_key in broll_clips:
        return broll_clips[scene_key]
    if label in broll_clips:
        return broll_clips[label]
    seg_index = {"hook": 0, "problem": 1, "pain": 1, "solution": 2, "cta": 3}
    keys      = list(broll_clips.keys())
    idx       = seg_index.get(label, 0)
    if idx < len(keys):
        return broll_clips[keys[idx]]
    return list(broll_clips.values())[0]


def get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return float(result.stdout.strip()) if result.returncode == 0 else 0.0


def wrap_text(text: str, max_chars: int = TEXT_MAX_CHARS_LINE) -> list[str]:
    """Word-wrap text into lines of ~max_chars characters."""
    words = text.split()
    lines = []
    current = []
    current_len = 0
    for word in words:
        word_len = len(word)
        if current and current_len + word_len + 1 > max_chars:
            lines.append(" ".join(current))
            current     = [word]
            current_len = word_len
        else:
            current.append(word)
            current_len += word_len + (1 if current_len > 0 else 0)
    if current:
        lines.append(" ".join(current))
    return lines


def escape_drawtext(s: str) -> str:
    """Escape characters for ffmpeg drawtext filter (text inside single quotes)."""
    # Order matters: backslash first
    s = s.replace("\\", "\\\\")
    # Apostrophe handling: close quote, escaped literal, reopen quote
    # In FFmpeg syntax: 'doesn'\''t' means doesn't inside single quotes
    s = s.replace("'", r"'\''")
    s = s.replace(":", r"\:")
    s = s.replace("[", r"\[")
    s = s.replace("]", r"\]")
    s = s.replace(";", r"\;")
    s = s.replace("%", r"\%")
    # Comma inside quoted text doesn't need escaping at filter level,
    # but we escape anyway as some FFmpeg versions are strict
    s = s.replace(",", r"\,")
    return s


def build_text_drawtext(
    text: str,
    duration: float,
    font_path: str,
    font_size: int = TEXT_FONT_SIZE,
    line_height: int = TEXT_LINE_HEIGHT,
    y_center: int = OUTPUT_HEIGHT // 2,
) -> str:
    """
    Build a comma-separated chain of drawtext filters for multi-line text.
    Each line is positioned centered horizontally and stacked vertically around y_center.
    Text fades in and fades out within the segment duration.
    """
    lines = wrap_text(text)
    n_lines = len(lines)
    total_height = n_lines * line_height
    start_y = y_center - total_height // 2

    # Alpha expression: fade in over TEXT_FADE_IN, hold, fade out over TEXT_FADE_OUT
    # Commas inside expressions MUST be backslash-escaped so FFmpeg's filter parser
    # doesn't split them as filter separators
    fade_in  = TEXT_FADE_IN
    fade_out = TEXT_FADE_OUT
    alpha_expr = (
        rf"if(lt(t\,{fade_in})\,t/{fade_in}\,"
        rf"if(gt(t\,{duration - fade_out})\,({duration}-t)/{fade_out}\,1))"
    )

    drawtext_filters = []
    for i, line in enumerate(lines):
        y = start_y + i * line_height
        line_escaped = escape_drawtext(line)
        filter_str = (
            f"drawtext="
            f"fontfile='{font_path}':"
            f"text='{line_escaped}':"
            f"fontsize={font_size}:"
            f"fontcolor=white:"
            f"x=(w-text_w)/2:"
            f"y={y}:"
            f"shadowcolor=black@0.85:"
            f"shadowx=3:shadowy=3:"
            f"alpha='{alpha_expr}'"
        )
        drawtext_filters.append(filter_str)

    return ",".join(drawtext_filters)


def build_cta_drawtext(brand: str, duration: float, font_path: str) -> str:
    """Build the CTA pill background + lower third text overlay."""
    if brand == "w-real-estate":
        line1 = "W Real Estate, LLC"
        line2 = "601-499-0952"
    else:
        line1 = "Alpha Insurance"
        line2 = "601-981-2911"

    pill_x      = (OUTPUT_WIDTH - CTA_PILL_WIDTH) // 2
    pill_y      = CTA_PILL_Y
    text1_y     = pill_y + 30
    text2_y     = pill_y + 88

    # Pill bg fades in slightly delayed (commas escaped for filter parser)
    pill_alpha = (
        rf"if(lt(t\,0.3)\,0\,"
        rf"if(lt(t\,0.8)\,(t-0.3)/0.5*0.75\,0.75))"
    )
    text_alpha = (
        rf"if(lt(t\,0.5)\,0\,"
        rf"if(lt(t\,1.0)\,(t-0.5)/0.5\,1))"
    )

    line1_escaped = escape_drawtext(line1)
    line2_escaped = escape_drawtext(line2)

    filters = [
        # Pill background (semi-transparent black box)
        f"drawbox=x={pill_x}:y={pill_y}:w={CTA_PILL_WIDTH}:h={CTA_PILL_HEIGHT}:"
        f"color=black@0.75:t=fill",
        # Line 1
        f"drawtext=fontfile='{font_path}':text='{line1_escaped}':"
        f"fontsize={CTA_FONT_SIZE}:fontcolor=white:"
        f"x=(w-text_w)/2:y={text1_y}:"
        f"alpha='{text_alpha}'",
        # Line 2
        f"drawtext=fontfile='{font_path}':text='{line2_escaped}':"
        f"fontsize={CTA_FONT_SIZE}:fontcolor=white:"
        f"x=(w-text_w)/2:y={text2_y}:"
        f"alpha='{text_alpha}'",
    ]
    return ",".join(filters)


# =============================================================================
# RENDER ONE SEGMENT
# =============================================================================

def render_segment(
    segment:    dict,
    clip_path:  str,
    brand:      str,
    font_path:  str,
    out_path:   Path,
    logger:     logging.Logger,
) -> None:
    """Render a single segment (b-roll + dark overlay + text) to out_path."""
    label       = segment.get("label", "segment")
    time_str    = segment.get("seconds", "0-3")
    spoken_text = segment.get("spoken_text", "")
    start_sec, end_sec = parse_time_range(time_str)
    duration    = end_sec - start_sec

    src_dur = get_video_duration(clip_path) if clip_path else 0
    needs_loop = src_dur > 0 and src_dur < duration

    logger.info(f"  [{label}] {Path(clip_path).name if clip_path else 'NO CLIP'} "
                f"({src_dur:.1f}s -> {duration}s, loop={needs_loop})")

    # Build text overlay filter
    text_filter = build_text_drawtext(spoken_text, duration, font_path)

    # CTA gets additional lower third
    if label == "cta":
        cta_filter = build_cta_drawtext(brand, duration, font_path)
        text_filter = f"{text_filter},{cta_filter}"

    # Filter graph:
    #   [0:v] scale + crop to 1080x1920 -> trim -> setpts
    #   add 45% dark overlay
    #   burn text via drawtext chain
    filter_complex = (
        f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
        f"trim=duration={duration},setpts=PTS-STARTPTS,fps={OUTPUT_FPS}[bg];"
        f"color=c=black@{DARK_OVERLAY_OPACITY}:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:d={duration}:r={OUTPUT_FPS}[dark];"
        f"[bg][dark]overlay=0:0:format=auto[darkened];"
        f"[darkened]{text_filter}[out]"
    )

    # Write filter graph to a script file to avoid command-line escaping issues
    # This bypasses FFmpeg's comma-parsing problem with expressions containing commas
    filter_script_path = TEMP_DIR / f"filter_{label}.txt"
    filter_script_path.write_text(filter_complex, encoding="utf-8")

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1" if needs_loop else "0",
        "-i", clip_path,
        "-filter_complex_script", str(filter_script_path),
        "-map", "[out]",
        "-an",
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "21",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    filter_script_path.unlink(missing_ok=True)
    if result.returncode != 0:
        logger.error(f"  Filter graph: {filter_complex[:500]}...")
        logger.error(f"  Segment render error: {result.stderr[-1500:]}")
        raise RuntimeError(f"Segment {label} render failed")


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def render_video(script_path, brand, broll_override=None):
    if brand not in VALID_BRANDS:
        raise ValueError(f"Brand must be one of: {VALID_BRANDS}")

    script_path = Path(script_path).resolve()
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    with open(script_path, encoding="utf-8") as f:
        script_data = json.load(f)

    video_id = script_data.get("video_id", script_data.get("content", {}).get("video_id", "unknown"))
    logger   = get_logger(video_id, brand)

    logger.info("=" * 60)
    logger.info("RENDER PIPELINE - Pure FFmpeg")
    logger.info("=" * 60)
    logger.info(f"Brand:     {brand}")
    logger.info(f"Video ID:  {video_id}")

    broll_clips = load_broll_manifest(video_id, broll_override)
    logger.info(f"B-roll clips loaded: {len(broll_clips)}")
    if not broll_clips:
        raise RuntimeError("No b-roll clips found")

    content     = script_data.get("content", script_data)
    full_script = content.get("full_script", {})
    segments    = full_script.get("segments", [])
    if not segments:
        raise RuntimeError("Script has no segments")

    font_path = find_font()
    logger.info(f"Font: {font_path}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: render each segment
    logger.info("")
    logger.info("Step 1: Render segments")
    segment_files = []
    for idx, segment in enumerate(segments):
        label     = segment.get("label", f"segment-{idx}")
        time_str  = segment.get("seconds", "0-3")
        clip_path = map_segment_to_broll(label, time_str, broll_clips)
        if not clip_path:
            raise RuntimeError(f"No b-roll clip mapped for segment {label}")

        out_path = TEMP_DIR / f"seg_{idx:02d}_{label}.mp4"
        render_segment(segment, clip_path, brand, font_path, out_path, logger)
        segment_files.append(out_path)

    # Step 2: concatenate segments
    logger.info("")
    logger.info("Step 2: Concatenate segments")
    concat_list = TEMP_DIR / "concat.txt"
    with open(concat_list, "w") as f:
        for s in segment_files:
            f.write(f"file '{s.as_posix()}'\n")

    final_path = VIDEOS_DIR / f"{brand}-{video_id}-{timestamp}.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(final_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.error(f"Concat error: {result.stderr[-1000:]}")
        raise RuntimeError("FFmpeg concat failed")

    # Cleanup temp
    for s in segment_files:
        s.unlink(missing_ok=True)
    concat_list.unlink(missing_ok=True)

    final_size = final_path.stat().st_size / 1024 / 1024
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"RENDER COMPLETE: {final_path.name}")
    logger.info(f"Size: {final_size:.2f} MB")
    logger.info("=" * 60)

    return {
        "video_path":    str(final_path.relative_to(ROOT)),
        "video_size_mb": final_size,
        "brand":         brand,
        "video_id":      video_id,
        "broll_clips":   len(broll_clips),
        "segments":      len(segments),
    }


# CLI
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Render ContentEngine video (pure FFmpeg)")
    parser.add_argument("script",      help="Path to generated script JSON")
    parser.add_argument("brand",       help=f"Brand: {VALID_BRANDS}")
    parser.add_argument("--broll-dir", help="Override b-roll directory", default=None)
    args = parser.parse_args()

    result = render_video(args.script, args.brand, args.broll_dir)
    print(f"\nVideo:    {result['video_path']}")
    print(f"Size:     {result['video_size_mb']:.2f} MB")
    print(f"Segments: {result['segments']}")
    print(f"Clips:    {result['broll_clips']}")
