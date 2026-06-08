#!/usr/bin/env python3.11
"""
mcp_server.py — ContentEngine MCP server.

Exposes 4 tools to any MCP-compatible client (Claude Desktop, Claude Code,
Cursor, etc.):

  generate_video   — Full 9-step pipeline: topic + brand → MP4
  preview_script   — Generate + TTS + transcribe (no render; fast iteration)
  list_brands      — Return brand configs from brands.json
  list_renders     — List completed MP4 renders with metadata

Run:
  python3.11 mcp_server.py          # stdio transport (Claude Desktop / Code)
  python3.11 mcp_server.py --sse    # SSE transport  (HTTP clients)
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).parent
load_dotenv(ROOT / "config" / ".env")

sys.path.insert(0, str(ROOT))

mcp = FastMCP(
    "ContentEngine",
    instructions=(
        "ContentEngine produces brand-specific short-form vertical videos (1080×1920). "
        "Use generate_video to produce an MP4, preview_script to iterate on copy, "
        "list_brands to see available brands, and list_renders to review outputs."
    ),
)


# ── Tool 1: generate_video ─────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Run the full ContentEngine pipeline: topic + brand → broadcast-quality "
        "1080×1920 MP4. Steps: script → TTS → transcribe → B-roll → render. "
        "Returns output path, duration, and step timings. "
        "Brands: 'w-real-estate' or 'alpha-insurance'."
    )
)
def generate_video(topic: str, brand_id: str) -> dict:
    """
    Produce a 1080×1920 MP4 video from a topic string.

    Args:
        topic:    Subject of the video (e.g. 'Why Mississippi homeowners need
                  umbrella insurance').
        brand_id: 'w-real-estate' or 'alpha-insurance'.

    Returns:
        Dict with output_path, file_size_mb, duration_seconds, tts_stub, and
        step_times.
    """
    from analyzer.generate_video import run_pipeline

    result = run_pipeline(topic=topic, brand_id=brand_id)
    return {
        "success":             True,
        "output_path":         result["output_path"],
        "file_size_mb":        result["file_size_mb"],
        "duration_seconds":    result["duration_seconds"],
        "word_count":          result["word_count"],
        "broll_clips_found":   result["broll_clips_found"],
        "tts_stub":            result["tts_stub"],
        "total_time_seconds":  result["total_time_seconds"],
        "step_times":          result["step_times"],
        "script_preview":      result["script_preview"],
        "pending_notes": (
            ["⚠️ ElevenLabs voice clone not configured — using silent stub audio. "
             "Add ELEVENLABS_AMANDA_VOICE_ID to config/.env for real TTS."]
            if result["tts_stub"] else []
        ),
    }


# ── Tool 2: preview_script ─────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Generate a video script and word timestamps without rendering. "
        "Fast feedback loop for copy iteration. Returns spoken_text, word_count, "
        "segments breakdown, B-roll queries, and estimated duration."
    )
)
def preview_script(topic: str, brand_id: str) -> dict:
    """
    Generate script → TTS → transcribe but skip B-roll fetch and render.

    Useful for reviewing copy before committing to a full render.

    Args:
        topic:    Video topic.
        brand_id: 'w-real-estate' or 'alpha-insurance'.

    Returns:
        Dict with spoken_text, word_count, duration_seconds, words (timestamps),
        and broll_queries.
    """
    from analyzer.generate_video import load_brand, generate_script, derive_broll_queries
    from analyzer import tts, subtitle_sync

    brand = load_brand(brand_id)
    script_data = generate_script(topic, brand_id, brand)
    spoken_text = script_data["spoken_text"]

    tts_result = tts.synthesize(spoken_text, brand_id)
    subtitle_result = subtitle_sync.transcribe(tts_result["audio_path"], brand_id)
    broll_queries = derive_broll_queries(script_data, brand_id)

    return {
        "spoken_text":       spoken_text,
        "word_count":        script_data.get("word_count", len(spoken_text.split())),
        "duration_seconds":  tts_result["duration_seconds"],
        "tts_stub":          tts_result.get("stub", False),
        "segments":          script_data.get("segments", {}),
        "broll_queries":     broll_queries,
        "word_timestamps":   subtitle_result["words"],
        "pending_notes": (
            ["⚠️ ElevenLabs voice clone not configured — using silent stub audio."]
            if tts_result.get("stub") else []
        ),
    }


# ── Tool 3: list_brands ────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "List available brands with their Phase 2 configuration: theme, colors, "
        "fonts, phone, and composition path. Use before generate_video to confirm "
        "valid brand_id values."
    )
)
def list_brands() -> dict:
    """Return Phase 2 brand summaries from brands.json."""
    brands_file = ROOT / "config" / "brands.json"
    with open(brands_file, encoding="utf-8") as f:
        all_brands = json.load(f)

    result = {}
    for brand_id, brand in all_brands.items():
        p2 = brand.get("phase2", {})
        voice_env = p2.get("voice_id_env", "ELEVENLABS_AMANDA_VOICE_ID")
        voice_ready = bool(os.getenv(voice_env, "").strip())

        result[brand_id] = {
            "name":         p2.get("name", brand_id),
            "theme":        p2.get("theme_name", ""),
            "phone":        p2.get("phone", ""),
            "colors":       p2.get("colors", {}),
            "fonts":        p2.get("fonts", {}),
            "composition":  p2.get("composition", ""),
            "dimensions":   p2.get("dimensions", {}),
            "fps":          p2.get("fps", 30),
            "voice_ready":  voice_ready,
            "cta_default":  p2.get("cta_default", ""),
        }

    return {
        "brands": result,
        "valid_brand_ids": list(result.keys()),
    }


# ── Tool 4: list_renders ───────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "List completed MP4 renders in the renders/ directory, optionally filtered "
        "by brand_id. Returns file paths, sizes, and creation timestamps sorted "
        "newest first."
    )
)
def list_renders(brand_id: str = "") -> dict:
    """
    List rendered MP4 files.

    Args:
        brand_id: Optional filter ('w-real-estate' or 'alpha-insurance').
                  Pass empty string or omit to list all renders.

    Returns:
        Dict with renders list and total count.
    """
    renders_dir = ROOT / "renders"
    renders_dir.mkdir(exist_ok=True)

    files = sorted(renders_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)

    renders = []
    for f in files:
        if brand_id and not f.name.startswith(brand_id):
            continue
        stat = f.stat()
        renders.append({
            "filename":       f.name,
            "path":           str(f),
            "size_mb":        round(stat.st_size / 1_048_576, 2),
            "created":        datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "brand":          f.name.split("_")[0] + "-" + f.name.split("_")[1]
                              if f.name.count("_") >= 2 else "unknown",
        })

    return {
        "renders": renders,
        "count":   len(renders),
        "renders_dir": str(renders_dir),
    }


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    use_sse = "--sse" in sys.argv

    if use_sse:
        # HTTP/SSE transport for web clients
        port = int(os.getenv("MCP_PORT", "8000"))
        print(f"ContentEngine MCP server starting (SSE) on port {port}")
        mcp.run(transport="sse")
    else:
        # stdio transport — standard for Claude Desktop / Claude Code
        mcp.run(transport="stdio")
