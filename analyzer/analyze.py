"""
analyze.py — Content analysis pipeline
Combines transcript + OCR + scene data and sends to Claude for structured analysis.
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
import anthropic

ROOT = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"
SCRIPTS_DIR = ROOT / "scripts"

# claude-sonnet-4-5 — specified model for all Anthropic calls
CLAUDE_MODEL = "claude-sonnet-4-5"

# Approximate token costs (claude-sonnet-4-5 as of 2026)
INPUT_COST_PER_1K = 0.003
OUTPUT_COST_PER_1K = 0.015

load_dotenv(ROOT / "config" / ".env")


def get_logger(video_id: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOGS_DIR / f"analyze-{timestamp}.log"
    logger = logging.getLogger(f"analyze.{video_id}")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Copy config/.env.template to config/.env and add your key."
        )
    return anthropic.Anthropic(api_key=api_key)


def estimate_token_cost(input_tokens: int, output_tokens: int) -> float:
    cost = (input_tokens / 1000 * INPUT_COST_PER_1K) + (output_tokens / 1000 * OUTPUT_COST_PER_1K)
    return round(cost, 6)


def build_analysis_prompt(transcript: dict, ocr_data: dict, extract_meta: dict) -> str:
    transcript_text = transcript.get("text", "")
    duration = extract_meta.get("duration_seconds", 0)
    scene_changes = extract_meta.get("scene_changes", [])
    scene_count = len(scene_changes)
    frame_count = extract_meta.get("frame_count", 0)

    ocr_entries = ocr_data.get("text_entries", [])
    ocr_summary = "\n".join(
        f"  [{e['timestamp_seconds']:.1f}s] {e['text'][:120]}"
        for e in ocr_entries[:30]
    )

    cuts_per_second = round(scene_count / duration, 2) if duration > 0 else 0

    prompt = f"""You are a content strategist analyzing a short-form social media video (likely from Instagram or TikTok) to extract viral patterns and production intelligence.

VIDEO DATA:
- Duration: {duration:.1f} seconds
- Scene changes detected: {scene_count}
- Cuts per second: {cuts_per_second}
- Frames extracted: {frame_count}

FULL TRANSCRIPT:
{transcript_text}

ON-SCREEN TEXT (OCR from keyframes):
{ocr_summary if ocr_summary else "(no on-screen text detected)"}

SCENE CHANGE TIMESTAMPS:
{json.dumps([s['timestamp_seconds'] for s in scene_changes[:20]], indent=2)}

Analyze this video and return a JSON object with EXACTLY these keys:

{{
  "hook_structure": {{
    "first_3_seconds_transcript": "<exact words spoken in first ~3 seconds>",
    "visual_hook": "<describe the visual opening — what is shown immediately>",
    "pattern_interrupt": "<what makes this unusual or attention-grabbing>",
    "hook_type": "<one of: question, bold-claim, controversy, transformation, fear, curiosity-gap, direct-address>"
  }},
  "pacing": {{
    "cuts_per_second": {cuts_per_second},
    "scene_change_count": {scene_count},
    "average_scene_duration_seconds": {round(duration / scene_count, 2) if scene_count > 0 else duration},
    "pacing_style": "<one of: rapid-cut, moderate, slow-burn, single-take>",
    "pacing_notes": "<brief description of pacing rhythm and energy>"
  }},
  "content_structure": {{
    "segments": [
      {{
        "label": "<hook|problem|agitation|solution|proof|cta>",
        "start_seconds": 0,
        "end_seconds": 0,
        "summary": "<what happens in this segment>"
      }}
    ],
    "has_clear_problem_solution": true,
    "has_clear_cta": true
  }},
  "cta": {{
    "placement_seconds": 0,
    "exact_words": "<CTA text if audible or visible>",
    "cta_type": "<one of: follow, comment, dm, link-in-bio, call, visit, share, save>",
    "urgency_device": "<any urgency language used — or null>"
  }},
  "psychological_hooks": {{
    "emotional_triggers": ["<list of emotions targeted: fear, fomo, aspiration, trust, anger, etc.>"],
    "persuasion_techniques": ["<social proof, authority, scarcity, reciprocity, etc.>"],
    "identity_language": "<any 'if you are X' or 'people like you' framing>",
    "pain_points_addressed": ["<specific problems mentioned or implied>"]
  }},
  "messaging_patterns": {{
    "repeated_phrases": ["<any phrase said or shown more than once>"],
    "power_words": ["<high-impact vocabulary used>"],
    "key_claim": "<the single most important claim or promise made>",
    "credibility_signals": ["<anything establishing authority or trust>"]
  }},
  "caption_text_strategy": {{
    "overlay_text_used": {"true" if ocr_entries else "false"},
    "text_timing": "<when text appears relative to speech>",
    "text_style": "<matches speech | reveals next point | adds commentary | standalone>",
    "caption_hook": "<first line of caption if visible, or inferred from transcript>"
  }},
  "production_notes": {{
    "estimated_platform": "<instagram-reels | tiktok | facebook | youtube-shorts>",
    "video_style": "<talking-head | b-roll-voiceover | screen-record | mixed>",
    "audio_type": "<direct-to-camera | voiceover | music-only>",
    "production_quality": "<low | medium | high>",
    "standout_technique": "<the single most replicable technique from this video>"
  }}
}}

Return ONLY the JSON object. No preamble, no explanation, no markdown code fences."""

    return prompt


def analyze(extract_meta_path: str | Path, transcript_path: str | Path, ocr_path: str | Path) -> dict:
    """
    Main entry point.
    Loads all data, sends to Claude, saves structured analysis JSON.
    """
    extract_meta_path = Path(extract_meta_path)
    transcript_path = Path(transcript_path)
    ocr_path = Path(ocr_path)

    for p in [extract_meta_path, transcript_path, ocr_path]:
        if not p.exists():
            raise FileNotFoundError(f"Required file not found: {p}")

    with open(extract_meta_path, encoding="utf-8") as f:
        extract_meta = json.load(f)
    with open(transcript_path, encoding="utf-8") as f:
        transcript = json.load(f)
    with open(ocr_path, encoding="utf-8") as f:
        ocr_data = json.load(f)

    video_id = extract_meta["video_id"]
    logger = get_logger(video_id)
    logger.info(f"=== Analysis Pipeline ===")
    logger.info(f"Video ID: {video_id}")
    logger.info(f"Model: {CLAUDE_MODEL}")

    client = get_anthropic_client()
    prompt = build_analysis_prompt(transcript, ocr_data, extract_meta)

    logger.info("Sending to Claude API for analysis...")
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        raise

    raw_content = response.content[0].text.strip()
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = estimate_token_cost(input_tokens, output_tokens)

    logger.info(f"API response received. Tokens: {input_tokens} in / {output_tokens} out")
    logger.info(f"Estimated cost: ${cost:.6f}")

    # Strip markdown fences if Claude wrapped the JSON
    if raw_content.startswith("```"):
        lines = raw_content.split("\n")
        raw_content = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    try:
        analysis = json.loads(raw_content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        logger.error(f"Raw response: {raw_content[:500]}")
        raise ValueError(f"Claude returned invalid JSON: {e}")

    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_filename = f"analysis-{video_id}-{timestamp}.json"
    out_path = SCRIPTS_DIR / out_filename

    output = {
        "video_id": video_id,
        "analyzed_at": datetime.now().isoformat(),
        "model": CLAUDE_MODEL,
        "api_usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": cost,
        },
        "analysis": analysis,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"Analysis saved → {out_path}")
    logger.info("=== Analysis complete ===")

    return output


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python analyzer/analyze.py <extract_meta_json> <transcript_json> <ocr_json>")
        sys.exit(1)
    result = analyze(sys.argv[1], sys.argv[2], sys.argv[3])
    print(json.dumps(result["analysis"]["hook_structure"], indent=2))
    print(f"\nCost: ${result['api_usage']['estimated_cost_usd']:.6f}")
