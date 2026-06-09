#!/usr/bin/env python3.11
"""
generate_video.py — Phase 2 pipeline orchestrator.

topic + brand → broadcast-quality 1080×1920 MP4

9-step pipeline:
  1  Load brand config
  2  Generate video script from topic (Claude API)
  3  TTS → audio file
  4  Transcribe → word timestamps
  5  Derive B-roll search queries from script
  6  Build clip manifest (15/25/30/30% time split)
  7  Fetch B-roll clips (Pexels → Pixabay)
  8  Compose HyperFrames render variables
  9  Render composition → MP4

Phase 1 pipeline (run.py / generate.py) is untouched.
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / "config" / ".env")

from analyzer import tts, subtitle_sync, audio_sync, broll_v2, hyperframes_render

BRANDS_FILE = ROOT / "config" / "brands.json"
RENDERS_DIR = ROOT / "renders"
RENDERS_DIR.mkdir(parents=True, exist_ok=True)

CLAUDE_MODEL = "claude-sonnet-4-6"
VALID_BRANDS = ["w-real-estate", "alpha-insurance"]

logger = logging.getLogger(__name__)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)
logger.setLevel(logging.INFO)


# ── Step 1 helpers ─────────────────────────────────────────────────────────────

def load_brand(brand_id: str) -> dict:
    if brand_id not in VALID_BRANDS:
        raise ValueError(f"Brand must be one of {VALID_BRANDS}, got '{brand_id}'")
    with open(BRANDS_FILE, encoding="utf-8") as f:
        return json.load(f)[brand_id]


# ── Step 2: Script generation ──────────────────────────────────────────────────

def _build_script_prompt(topic: str, brand: dict, brand_id: str) -> str:
    p2 = brand["phase2"]
    name     = p2["name"]
    phone    = p2["phone"]
    tone     = p2.get("tone", "professional")
    cta      = p2["cta_default"]
    pillars  = brand.get("content_pillars", [])
    service  = brand.get("service_area", "Mississippi")

    compliance = ""
    if brand_id == "w-real-estate":
        compliance = (
            "\nCOMPLIANCE (Mississippi Rule 3.3): The CTA segment MUST include "
            f"'W Real Estate, LLC' and '{phone}' verbatim."
        )

    return f"""Write a short-form vertical video script for {name}.

TOPIC: {topic}
BRAND VOICE: {tone}
SERVICE AREA: {service}
CONTENT PILLARS: {', '.join(pillars) if pillars else 'education, trust, authority'}
{compliance}

The script will be recorded as a voiceover (20–30 seconds at 2.8 words/second).
Target word count: 56–84 words.

Segment structure:
  hook    (0–3s)   — attention-grabbing opening line
  setup   (3–8s)   — problem or context
  payload (8–18s)  — value, solution, insight
  cta     (18–20s) — call to action ending with: "{cta}"

Return ONLY a JSON object — no markdown fences, no extra text:
{{
  "spoken_text": "<full script as one continuous spoken paragraph>",
  "word_count": <integer>,
  "segments": {{
    "hook":    "<hook segment text>",
    "setup":   "<setup segment text>",
    "payload": "<payload segment text>",
    "cta":     "<cta segment text>"
  }},
  "broll_queries": [
    "<query 1 — 3-5 word stock video search term>",
    "<query 2>",
    "<query 3>",
    "<query 4>"
  ]
}}"""


def generate_script(topic: str, brand_id: str, brand: dict) -> dict:
    """Call Claude to generate a 20-30s video script from a topic."""
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Add it to config/.env."
        )

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_script_prompt(topic, brand, brand_id)

    logger.info(f"  Script: calling Claude ({CLAUDE_MODEL}) for topic: {topic[:60]}")
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = resp.content[0].text.strip()
    # Strip markdown fences if Claude adds them anyway
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned non-JSON script: {e}\n---\n{raw[:400]}")

    if "spoken_text" not in data:
        raise ValueError(f"Claude response missing 'spoken_text': {data}")

    logger.info(
        f"  Script: {data.get('word_count', '?')} words | "
        f"tokens: {resp.usage.input_tokens}in/{resp.usage.output_tokens}out"
    )
    return data


# ── Step 5: B-roll queries ─────────────────────────────────────────────────────

def derive_broll_queries(script_data: dict, brand_id: str) -> list[str]:
    """
    Extract B-roll search queries from the generated script.

    Priority order:
      1. script_data["broll_queries"]  — Claude-suggested in script response
      2. Brand-specific defaults
    """
    queries = script_data.get("broll_queries", [])

    defaults = {
        "w-real-estate": [
            "luxury home Mississippi exterior",
            "real estate agent house keys",
            "Mississippi neighborhood homes",
            "house sold sign yard",
        ],
        "alpha-insurance": [
            "Mississippi family home protection",
            "insurance documents signing",
            "car keys auto insurance",
            "family home safety",
        ],
    }

    # Pad to at least 4 from defaults if needed
    seen = {q.lower() for q in queries}
    for d in defaults.get(brand_id, []):
        if d.lower() not in seen:
            queries.append(d)
            seen.add(d.lower())
        if len(queries) >= 6:
            break

    return queries[:6]


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(
    topic: str,
    brand_id: str,
    output_path: str | None = None,
    fps: int = 30,
    quality: str = "standard",
) -> dict:
    """
    Run the full 9-step Phase 2 video production pipeline.

    Args:
        topic:       Video topic (free text).
        brand_id:    "w-real-estate" or "alpha-insurance".
        output_path: Absolute path for the output MP4. Auto-generated if None.
        fps:         Frame rate (default 30).
        quality:     HyperFrames quality preset.

    Returns:
        Full result dict including output_path, metadata, and step timings.
    """
    t_start = time.time()
    logger.info(f"\n{'='*60}")
    logger.info(f"ContentEngine Phase 2 pipeline")
    logger.info(f"  Brand:  {brand_id}")
    logger.info(f"  Topic:  {topic}")
    logger.info(f"{'='*60}")

    step_times: dict[str, float] = {}

    def timed(label: str, fn, *args, **kwargs):
        t0 = time.time()
        logger.info(f"\n[{label}]")
        result = fn(*args, **kwargs)
        step_times[label] = round(time.time() - t0, 2)
        logger.info(f"  ✓ {label} done ({step_times[label]}s)")
        return result

    # ── Step 1: Brand config ───────────────────────────────────────────────
    brand = timed("1_brand_config", load_brand, brand_id)
    p2 = brand["phase2"]

    # ── Step 2: Script generation ──────────────────────────────────────────
    script_data = timed("2_script_gen", generate_script, topic, brand_id, brand)
    spoken_text = script_data["spoken_text"]

    # ── Step 3: TTS ───────────────────────────────────────────────────────
    tts_result = timed("3_tts", tts.synthesize, spoken_text, brand_id)
    audio_path = tts_result["audio_path"]
    duration   = tts_result["duration_seconds"]

    # ── Step 4: Transcribe ────────────────────────────────────────────────
    subtitle_result = timed("4_transcribe", subtitle_sync.transcribe, audio_path, brand_id)
    words = subtitle_result["words"]

    # ── Step 5: B-roll queries ────────────────────────────────────────────
    broll_queries = timed("5_broll_queries", derive_broll_queries, script_data, brand_id)
    logger.info(f"  Queries: {broll_queries}")

    # ── Step 6: Clip manifest ─────────────────────────────────────────────
    manifest = timed("6_manifest", audio_sync.build_manifest, duration, broll_queries, brand_id)

    # ── Step 7: Fetch B-roll ──────────────────────────────────────────────
    enriched = timed("7_broll_fetch", broll_v2.fetch_broll, manifest, brand_id)
    clips_found = [c for c in enriched["clips"] if c.get("local_path")]
    broll_path = clips_found[0]["local_path"] if clips_found else ""
    if not broll_path:
        logger.warning("  No B-roll clips fetched — video will render without B-roll")

    # ── Step 8: Compose render variables ──────────────────────────────────
    logger.info("\n[8_compose_vars]")
    variables = {
        "brand":      brand_id,
        "brand_name": p2["name"],
        "phone":      p2["phone"],
        "cta_text":   p2["cta_default"],
        "duration":   duration,
        "words":      json.dumps(words),   # stringified — composition parses via JSON.parse
        "broll_path": broll_path,
        "audio_path": str(audio_path),
    }
    logger.info(
        f"  Variables: duration={duration:.1f}s words={len(words)} "
        f"broll={'yes' if broll_path else 'none'}"
    )
    step_times["8_compose_vars"] = 0.0

    # ── Step 9: Render ────────────────────────────────────────────────────
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower())[:40].strip("-")
        output_path = str(RENDERS_DIR / f"{brand_id}_{slug}_{ts}.mp4")

    render_result = timed(
        "9_render",
        hyperframes_render.render,
        p2["composition"],
        variables,
        output_path,
        fps,
        quality,
    )

    total = round(time.time() - t_start, 1)
    logger.info(f"\n{'='*60}")
    logger.info(f"Pipeline complete in {total}s → {render_result['output_path']}")
    logger.info(f"{'='*60}\n")

    return {
        "brand":               brand_id,
        "topic":               topic,
        "output_path":         render_result["output_path"],
        "file_size_mb":        render_result["file_size_mb"],
        "duration_seconds":    duration,
        "word_count":          subtitle_result["word_count"],
        "broll_clips_found":   len(clips_found),
        "tts_stub":            tts_result.get("stub", False),
        "render_time_seconds": render_result["render_time_seconds"],
        "total_time_seconds":  total,
        "step_times":          step_times,
        "script_preview":      spoken_text[:120] + "…" if len(spoken_text) > 120 else spoken_text,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python3.11 analyzer/generate_video.py <topic> <brand_id>\n"
            f"  brand_id: {VALID_BRANDS}\n\n"
            'Example: python3.11 analyzer/generate_video.py '
            '"Why Mississippi families need better home insurance" alpha-insurance'
        )
        sys.exit(1)

    topic_arg = sys.argv[1]
    brand_arg = sys.argv[2]

    result = run_pipeline(topic_arg, brand_arg)

    print(f"\n{'='*50}")
    print(f"OUTPUT:     {result['output_path']}")
    print(f"SIZE:       {result['file_size_mb']}MB")
    print(f"DURATION:   {result['duration_seconds']:.1f}s")
    print(f"B-ROLL:     {result['broll_clips_found']} clips")
    print(f"TTS STUB:   {result['tts_stub']}")
    print(f"TOTAL TIME: {result['total_time_seconds']}s")
    if result['tts_stub']:
        print("\n⚠️  PENDING: ElevenLabs voice clone not yet configured")
        print("   Add ELEVENLABS_AMANDA_VOICE_ID to config/.env for real TTS")
