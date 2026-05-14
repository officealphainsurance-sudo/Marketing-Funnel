"""
score.py v2.1 — HookGenie scoring layer
Reads analyze.py output + companion metadata JSON.
Scores hook patterns and tracks performance signal for synthesize.py.

CHANGELOG v2.1:
- FIXED: Companion JSON lookup now matches on platform-handle-date prefix
  (instead of full filename match which fails because video_id has hash suffix
  and companion JSON has description-only).
- FIXED: Composite score no longer includes view_multiplier — prevents
  compounding multiplication when scores feed back into brain_weight.
  view_multiplier is preserved in output for synthesize.py to use during
  weighted aggregation.
- FIXED: Emotional triggers no longer routed through HOOK_PATTERNS lookup.
  Triggers are now tracked separately with their own frequency tally.

Usage (standalone):
    python analyzer/score.py <analysis_json_path> <brand>
"""

import os
import sys
import json
import re
import logging
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"
SCRIPTS_DIR = ROOT / "scripts"
VIDEOS_DIR = ROOT / "competitor-videos"


# ─── Hook Pattern Definitions ─────────────────────────────────────────────────
# Brand-split, research-expandable. base_weight = intrinsic priority for this brand.
# brain_weight (computed from history in synthesize.py) layers on top.

HOOK_PATTERNS = {
    "w-real-estate": {
        "bold-claim": {"label": "Bold Claim", "base_weight": 1.0,
                       "description": "States a surprising or counterintuitive fact about real estate"},
        "question": {"label": "Question Open", "base_weight": 1.0,
                     "description": "Opens with a question the target audience is asking"},
        "myth-bust": {"label": "Myth Bust", "base_weight": 1.0,
                      "description": "Challenges a common misconception sellers/buyers hold"},
        "controversy": {"label": "Controversy", "base_weight": 1.0,
                        "description": "Strong position that creates engagement through disagreement"},
        "fear": {"label": "Fear / Loss Aversion", "base_weight": 1.0,
                 "description": "Highlights what the viewer risks losing by not taking action"},
        "curiosity-gap": {"label": "Curiosity Gap", "base_weight": 1.0,
                          "description": "Opens a loop the viewer must watch to close"},
        "transformation": {"label": "Transformation", "base_weight": 0.9,
                           "description": "Shows before/after or promise of change"},
        "direct-address": {"label": "Direct Address", "base_weight": 0.8,
                           "description": "Speaks directly to a specific identity or situation"},
    },
    "alpha-insurance": {
        "bold-claim": {"label": "Bold Claim", "base_weight": 1.0,
                       "description": "States a surprising fact about insurance costs or coverage"},
        "fear": {"label": "Cost Pain / Fear", "base_weight": 1.0,
                 "description": "Highlights financial risk of being underinsured or overcharged"},
        "question": {"label": "Question Open", "base_weight": 1.0,
                     "description": "Opens with a question Mississippi families are asking"},
        "myth-bust": {"label": "Myth Bust", "base_weight": 1.0,
                      "description": "Challenges a common misconception about insurance"},
        "controversy": {"label": "Controversy / Trust", "base_weight": 1.0,
                        "description": "Exposes what big insurance companies don't tell you"},
        "curiosity-gap": {"label": "Curiosity Gap", "base_weight": 1.0,
                          "description": "Opens a loop around hidden insurance facts"},
        "direct-address": {"label": "Direct Address", "base_weight": 0.9,
                           "description": "Speaks to MS families, homeowners, or drivers specifically"},
        "transformation": {"label": "Transformation", "base_weight": 0.8,
                           "description": "Shows financial relief after switching"},
    }
}

VIEW_TIERS = [
    (1_000_000, 5.0),
    (500_000, 4.0),
    (100_000, 3.0),
    (50_000, 2.5),
    (10_000, 2.0),
    (5_000, 1.5),
    (1_000, 1.2),
    (0, 1.0),
]


def get_logger(video_id: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"score.{video_id}")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        ch = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger


def get_view_multiplier(views: int) -> float:
    for threshold, multiplier in VIEW_TIERS:
        if views >= threshold:
            return multiplier
    return 1.0


def find_companion_json(video_id: str) -> dict:
    """
    FIX v2.1: Matches on platform-handle-date prefix instead of full filename.

    video_id format from extract.py:    platform-handle-YYYY-MM-DD-desc--HASH
    companion JSON from intake.py:      platform-handle-YYYY-MM-DD-desc

    These don't match exactly — descriptions can be truncated and a hash
    suffix is appended. So we extract the stable prefix (platform-handle-date)
    and find the most recently-modified companion JSON that matches.
    """
    if not VIDEOS_DIR.exists():
        return {}

    # Extract stable prefix: platform-handle-YYYY-MM-DD
    prefix_match = re.match(r"^([a-z]+)-([a-z0-9]+)-(\d{4}-\d{2}-\d{2})", video_id)
    if not prefix_match:
        return {}

    platform, handle, date = prefix_match.groups()
    prefix = f"{platform}-{handle}-{date}"

    # Find all companion JSONs with matching stable prefix
    candidates = [
        f for f in VIDEOS_DIR.glob("*.json")
        if f.stem.startswith(prefix)
    ]

    if not candidates:
        return {}

    # Prefer most recently modified (assumes user runs intake → run.py same session)
    candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    try:
        with open(candidates[0], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_pattern_meta(hook_type: str, brand: str) -> dict:
    """Returns base_weight, label, description for a hook type. Defaults if unknown."""
    patterns = HOOK_PATTERNS.get(brand, {})
    pattern = patterns.get(hook_type)
    if pattern is None:
        return {
            "base_weight": 0.7,
            "label": hook_type.replace("-", " ").title() if hook_type else "Unknown",
            "description": "Unknown pattern type",
        }
    return pattern


def score_hook(hook_type: str, brand: str, brain_weights: dict, view_multiplier: float) -> dict:
    """
    FIX v2.1: composite_score no longer includes view_multiplier.
    composite_score = base_weight × brain_weight  (recommendation strength)
    view_multiplier is preserved separately for synthesize.py to use during aggregation.
    """
    meta = get_pattern_meta(hook_type, brand)
    base_weight = meta["base_weight"]

    # brain_weight starts at 1.0 (neutral) and evolves via synthesize.py
    brain_weight = brain_weights.get(hook_type, {}).get("weight", 1.0)

    # Composite = recommendation strength only — does NOT include view_mult
    composite_score = round(base_weight * brain_weight, 4)

    return {
        "hook_type": hook_type,
        "label": meta["label"],
        "description": meta["description"],
        "base_weight": base_weight,
        "brain_weight": brain_weight,
        "source_view_multiplier": view_multiplier,
        "composite_score": composite_score,
    }


def load_brain_weights(brand: str) -> dict:
    brain_path = ROOT / "data" / "agent-brain.json"
    if not brain_path.exists():
        return {}
    try:
        with open(brain_path, encoding="utf-8") as f:
            brain = json.load(f)
        return brain.get(brand, {}).get("hook_patterns", {})
    except Exception:
        return {}


def score(analysis_path, brand: str) -> dict:
    if brand not in HOOK_PATTERNS:
        raise ValueError(f"Brand '{brand}' has no defined HOOK_PATTERNS")

    analysis_path = Path(analysis_path).resolve()
    if not analysis_path.exists():
        raise FileNotFoundError(f"Analysis file not found: {analysis_path}")

    with open(analysis_path, encoding="utf-8") as f:
        analysis_data = json.load(f)

    video_id = analysis_data.get("video_id", "unknown")
    analysis = analysis_data.get("analysis", {})
    logger = get_logger(video_id)

    logger.info(f"=== Score Pipeline v2.1 ===")
    logger.info(f"Video ID: {video_id} | Brand: {brand}")

    # Load companion metadata for view count
    companion = find_companion_json(video_id)
    if not companion:
        logger.warning(f"⚠  No companion JSON found for {video_id}. View_multiplier defaulting to 1.0x.")
        logger.warning(f"   Run intake.py for this video to enable performance weighting.")
    views = companion.get("performance", {}).get("views", 0)
    view_multiplier = get_view_multiplier(views)
    logger.info(f"Views: {views:,} | View Multiplier: {view_multiplier}x")

    brain_weights = load_brain_weights(brand)

    # Score primary hook (from current video analysis)
    hook_type = analysis.get("hook_structure", {}).get("hook_type", "unknown")
    primary_score = score_hook(hook_type, brand, brain_weights, view_multiplier)
    logger.info(f"Primary hook: {hook_type} | Composite: {primary_score['composite_score']} | View mult: {view_multiplier}x")

    # FIX v2.1: Emotional triggers tracked separately, NOT scored via HOOK_PATTERNS
    emotional_triggers = analysis.get("psychological_hooks", {}).get("emotional_triggers", [])
    trigger_records = [
        {
            "trigger": t,
            "source_view_multiplier": view_multiplier,
        }
        for t in emotional_triggers
    ]

    persuasion = analysis.get("psychological_hooks", {}).get("persuasion_techniques", [])

    # Rank all known hook patterns for this brand → top-3 recommendations to generate.py
    all_pattern_scores = [
        score_hook(pattern_key, brand, brain_weights, view_multiplier)
        for pattern_key in HOOK_PATTERNS[brand]
    ]
    all_pattern_scores.sort(key=lambda x: x["composite_score"], reverse=True)
    top_3_patterns = all_pattern_scores[:3]

    logger.info(f"Top-3 recommended patterns: {[p['hook_type'] for p in top_3_patterns]}")

    scored_output = {
        "video_id": video_id,
        "brand": brand,
        "scored_at": datetime.now().isoformat(),
        "scoring_version": "2.1",
        "performance_context": {
            "views": views,
            "view_multiplier": view_multiplier,
            "companion_file": companion.get("filename", "not found"),
            "companion_found": bool(companion),
            "platform": companion.get("platform", "unknown"),
            "handle": companion.get("handle", "unknown"),
        },
        "primary_hook_score": primary_score,
        "emotional_trigger_records": trigger_records,
        "persuasion_techniques": persuasion,
        "all_pattern_rankings": all_pattern_scores,
        "top_3_recommended_patterns": top_3_patterns,
        "key_claim": analysis.get("messaging_patterns", {}).get("key_claim", ""),
        "standout_technique": analysis.get("production_notes", {}).get("standout_technique", ""),
        "pain_points": analysis.get("psychological_hooks", {}).get("pain_points_addressed", []),
        "original_analysis_path": str(analysis_path),
    }

    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_filename = f"scored-{brand}-{video_id}-{timestamp}.json"
    out_path = SCRIPTS_DIR / out_filename

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scored_output, f, indent=2, ensure_ascii=False)

    logger.info(f"Scored output saved → {out_path}")
    logger.info("=== Score complete ===")

    return scored_output


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analyzer/score.py <analysis_json> <brand>")
        sys.exit(1)
    result = score(sys.argv[1], sys.argv[2])
    print(f"\nPrimary hook: {result['primary_hook_score']['hook_type']} | Score: {result['primary_hook_score']['composite_score']}")
    print(f"Top 3 patterns: {[p['hook_type'] for p in result['top_3_recommended_patterns']]}")
    print(f"Companion found: {result['performance_context']['companion_found']}")
