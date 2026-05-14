"""
synthesize.py v2.1 — Agent brain aggregation
Reads all scored JSONs for a brand, aggregates patterns weighted by view performance,
updates data/agent-brain.json with evolved pattern weights.

CHANGELOG v2.1:
- FIXED: copy.deepcopy() instead of shallow .copy() on BRAIN_TEMPLATE
- FIXED: Brain weight is now mean(view_multiplier) of videos where each hook
  appeared. Decoupled from composite_score to prevent compounding multiplication.
- FIXED: Atomic write (temp file + rename) prevents brain corruption on crash.
- FIXED: Deduplication by video_id — re-runs of same video no longer double-count.
- FIXED: Removed dead `structures` defaultdict.
- FIXED: Emotional triggers now tracked from trigger_records (separate field
  from score.py output) — uses raw trigger names, not hook taxonomy.

Usage (standalone):
    python analyzer/synthesize.py --brand w-real-estate
"""

import sys
import json
import copy
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = ROOT / "scripts"
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
BRAIN_PATH = DATA_DIR / "agent-brain.json"

VALID_BRANDS = ["w-real-estate", "alpha-insurance"]


def get_logger() -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("synthesize")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        ch = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger


# ─── Brain Initialization ─────────────────────────────────────────────────────

BRAIN_TEMPLATE = {
    "w-real-estate": {
        "hook_patterns": {},
        "top_emotional_triggers": {},
        "top_pain_points": {},
        "top_standout_techniques": [],
        "top_key_claims": [],
        "videos_analyzed": 0,
        "last_updated": "",
    },
    "alpha-insurance": {
        "hook_patterns": {},
        "top_emotional_triggers": {},
        "top_pain_points": {},
        "top_standout_techniques": [],
        "top_key_claims": [],
        "videos_analyzed": 0,
        "last_updated": "",
    },
    "meta": {
        "total_videos_analyzed": 0,
        "brain_version": "2.1",
        "created_at": "",
        "last_updated": "",
    }
}


def load_brain() -> dict:
    """FIX v2.1: Uses copy.deepcopy() to prevent BRAIN_TEMPLATE mutation across runs."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if BRAIN_PATH.exists():
        try:
            with open(BRAIN_PATH, encoding="utf-8") as f:
                brain = json.load(f)
            # Migrate older brains that lack required fields
            for brand in VALID_BRANDS:
                if brand not in brain:
                    brain[brand] = copy.deepcopy(BRAIN_TEMPLATE[brand])
                else:
                    for k, v in BRAIN_TEMPLATE[brand].items():
                        if k not in brain[brand]:
                            brain[brand][k] = copy.deepcopy(v)
            if "meta" not in brain:
                brain["meta"] = copy.deepcopy(BRAIN_TEMPLATE["meta"])
            return brain
        except Exception:
            pass

    brain = copy.deepcopy(BRAIN_TEMPLATE)
    brain["meta"]["created_at"] = datetime.now().isoformat()
    save_brain(brain)
    return brain


def save_brain(brain: dict) -> None:
    """FIX v2.1: Atomic write using temp file + rename to prevent corruption."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    brain["meta"]["last_updated"] = datetime.now().isoformat()

    temp_path = BRAIN_PATH.with_suffix(".json.tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(brain, f, indent=2, ensure_ascii=False)
    temp_path.replace(BRAIN_PATH)  # atomic on POSIX, near-atomic on Windows


# ─── Score File Loading ───────────────────────────────────────────────────────

def load_all_scored_files(brand: str) -> list[dict]:
    """
    FIX v2.1: Deduplicates by video_id. If the same video has been scored
    multiple times (debug re-runs), only the most recent score is used.
    """
    # Sort newest first (timestamp suffix in filename guarantees lexical order)
    scored_files = sorted(SCRIPTS_DIR.glob(f"scored-{brand}-*.json"), reverse=True)

    seen_video_ids = set()
    results = []
    for sf in scored_files:
        try:
            with open(sf, encoding="utf-8") as f:
                data = json.load(f)
            vid = data.get("video_id")
            if vid and vid not in seen_video_ids:
                seen_video_ids.add(vid)
                results.append(data)
        except Exception:
            pass
    return results


# ─── Pattern Aggregation ──────────────────────────────────────────────────────

def aggregate_patterns(scored_data: list[dict]) -> dict:
    """
    FIX v2.1: Brain weight is now mean(view_multiplier) of videos where each
    hook appeared — NOT the composite_score. This prevents compounding
    multiplication. A hook that appears in high-view videos accumulates
    a high brain_weight directly from that performance signal.

    FIX v2.1: Emotional triggers tracked from trigger_records using raw
    trigger names, not hook taxonomy.
    """
    hook_view_mults = defaultdict(list)         # hook_type → [view_mult, view_mult, ...]
    trigger_view_mults = defaultdict(list)      # trigger → [view_mult, view_mult, ...]
    pain_points = defaultdict(int)              # pain_point → count
    standout_techniques = []
    key_claims = []

    for entry in scored_data:
        view_mult = entry.get("performance_context", {}).get("view_multiplier", 1.0)

        # Primary hook — track view_mult of source video
        primary = entry.get("primary_hook_score", {})
        hook_type = primary.get("hook_type")
        if hook_type and hook_type != "unknown":
            hook_view_mults[hook_type].append(view_mult)

        # Emotional triggers — pulled from trigger_records (v2.1) or fallback
        triggers = entry.get("emotional_trigger_records", [])
        if triggers:
            for tr in triggers:
                t = tr.get("trigger", "")
                if t:
                    trigger_view_mults[t].append(tr.get("source_view_multiplier", view_mult))
        else:
            # Backwards compat: older scored files used emotional_trigger_scores
            for ts in entry.get("emotional_trigger_scores", []):
                t = ts.get("hook_type", "")
                if t:
                    trigger_view_mults[t].append(view_mult)

        # Pain points
        for pp in entry.get("pain_points", []):
            pp_clean = pp.strip()
            if pp_clean:
                pain_points[pp_clean] += 1

        # Standout techniques
        st = entry.get("standout_technique", "")
        if st:
            standout_techniques.append({"technique": st, "view_multiplier": view_mult})

        # Key claims
        kc = entry.get("key_claim", "")
        if kc:
            key_claims.append({"claim": kc, "view_multiplier": view_mult})

    # Build hook pattern summary — brain_weight = mean view_multiplier
    hook_pattern_summary = {}
    for hook_type, view_mults in hook_view_mults.items():
        avg_view_mult = round(sum(view_mults) / len(view_mults), 4)
        hook_pattern_summary[hook_type] = {
            "weight": avg_view_mult,
            "frequency": len(view_mults),
            "avg_view_multiplier": avg_view_mult,
            "last_seen": datetime.now().isoformat(),
        }

    # Trigger summary — same logic
    trigger_summary = {}
    for trigger, view_mults in trigger_view_mults.items():
        avg_view_mult = round(sum(view_mults) / len(view_mults), 4)
        trigger_summary[trigger] = {
            "weight": avg_view_mult,
            "frequency": len(view_mults),
            "avg_view_multiplier": avg_view_mult,
        }

    top_pain = dict(sorted(pain_points.items(), key=lambda x: x[1], reverse=True)[:10])
    top_techniques = sorted(standout_techniques, key=lambda x: x["view_multiplier"], reverse=True)[:5]
    top_claims = sorted(key_claims, key=lambda x: x["view_multiplier"], reverse=True)[:5]

    return {
        "hook_patterns": hook_pattern_summary,
        "top_emotional_triggers": trigger_summary,
        "top_pain_points": top_pain,
        "top_standout_techniques": top_techniques,
        "top_key_claims": top_claims,
    }


def update_brain(brain: dict, brand: str, new_aggregation: dict, video_count: int) -> dict:
    """
    FIX v2.1: Direct overwrite is now correct because aggregate_patterns already
    does the cumulative averaging across all scored videos. No double-averaging
    via learning rate (which was redundant in v2.0).
    """
    brand_brain = brain.get(brand, copy.deepcopy(BRAIN_TEMPLATE[brand]))
    brand_brain["hook_patterns"] = new_aggregation["hook_patterns"]
    brand_brain["top_emotional_triggers"] = new_aggregation["top_emotional_triggers"]
    brand_brain["top_pain_points"] = new_aggregation["top_pain_points"]
    brand_brain["top_standout_techniques"] = new_aggregation.get("top_standout_techniques", [])
    brand_brain["top_key_claims"] = new_aggregation.get("top_key_claims", [])
    brand_brain["videos_analyzed"] = video_count
    brand_brain["last_updated"] = datetime.now().isoformat()

    brain[brand] = brand_brain
    brain["meta"]["total_videos_analyzed"] = sum(
        brain.get(b, {}).get("videos_analyzed", 0) for b in VALID_BRANDS
    )
    return brain


def build_brain_context(brain: dict, brand: str) -> dict:
    brand_brain = brain.get(brand, {})
    videos_analyzed = brand_brain.get("videos_analyzed", 0)

    if videos_analyzed == 0:
        return {
            "has_learned_patterns": False,
            "videos_analyzed": 0,
            "message": "Brain has no data yet — generating from current video only.",
        }

    hook_patterns = brand_brain.get("hook_patterns", {})
    top_hooks = sorted(hook_patterns.items(), key=lambda x: x[1].get("weight", 0), reverse=True)[:3]

    triggers = brand_brain.get("top_emotional_triggers", {})
    top_triggers = sorted(triggers.items(), key=lambda x: x[1].get("weight", 0), reverse=True)[:3]

    pain_points = list(brand_brain.get("top_pain_points", {}).keys())[:5]
    techniques = [t["technique"] for t in brand_brain.get("top_standout_techniques", [])[:3]]

    return {
        "has_learned_patterns": True,
        "videos_analyzed": videos_analyzed,
        "top_performing_hook_types": [
            {"hook_type": k, "weight": v.get("weight", 1.0), "frequency": v.get("frequency", 0)}
            for k, v in top_hooks
        ],
        "top_emotional_triggers": [k for k, v in top_triggers],
        "most_resonant_pain_points": pain_points,
        "proven_standout_techniques": techniques,
        "top_key_claims": [c["claim"] for c in brand_brain.get("top_key_claims", [])[:3]],
        "instruction": (
            f"The brain has analyzed {videos_analyzed} videos for {brand}. "
            f"Prioritize hook types: {[k for k, v in top_hooks]}. "
            f"Lean into emotional triggers: {[k for k, v in top_triggers]}. "
            f"Address these pain points: {pain_points[:3]}."
        ),
    }


def synthesize(brand: str) -> dict:
    if brand not in VALID_BRANDS:
        raise ValueError(f"Brand must be one of: {VALID_BRANDS}")

    logger = get_logger()
    logger.info(f"=== Synthesize Pipeline v2.1 ===")
    logger.info(f"Brand: {brand}")

    brain = load_brain()
    scored_data = load_all_scored_files(brand)
    video_count = len(scored_data)
    logger.info(f"Unique scored videos found: {video_count}")

    if video_count == 0:
        logger.info("No scored data yet — brain unchanged.")
        return {"brain_context": build_brain_context(brain, brand), "brain_updated": False}

    aggregation = aggregate_patterns(scored_data)
    logger.info(f"Hook patterns aggregated: {list(aggregation['hook_patterns'].keys())}")

    brain = update_brain(brain, brand, aggregation, video_count)
    save_brain(brain)
    logger.info(f"Brain updated → {BRAIN_PATH}")

    brain_context = build_brain_context(brain, brand)
    top_hooks = [h['hook_type'] for h in brain_context.get('top_performing_hook_types', [])]
    logger.info(f"Brain context built — {video_count} videos | Top hooks: {top_hooks}")
    logger.info("=== Synthesize complete ===")

    return {
        "brain_context": brain_context,
        "brain_updated": True,
        "videos_synthesized": video_count,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ContentEngine Synthesize v2.1")
    parser.add_argument("--brand", required=True, choices=VALID_BRANDS)
    args = parser.parse_args()

    result = synthesize(args.brand)
    ctx = result["brain_context"]
    print(f"\nBrain updated: {result['brain_updated']}")
    print(f"Videos analyzed: {ctx.get('videos_analyzed', 0)}")
    if ctx.get("has_learned_patterns"):
        print(f"Top hook types: {[h['hook_type'] for h in ctx.get('top_performing_hook_types', [])]}")
        print(f"Top triggers: {ctx.get('top_emotional_triggers', [])}")


if __name__ == "__main__":
    main()
