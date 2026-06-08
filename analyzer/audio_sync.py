#!/usr/bin/env python3.11
"""
audio_sync.py — Clip manifest generator.

Splits TTS audio duration into 4 time-locked segments and assigns
B-roll search queries to each slot. The manifest drives broll_v2.py
so every clip download is pre-positioned on the timeline.

Segment proportions (from build spec):
  hook    15%
  setup   25%
  payload 30%
  cta     30%
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / "config" / ".env")

TEMP_DIR = ROOT / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

SEGMENT_RATIOS = [
    ("hook",    0.15),
    ("setup",   0.25),
    ("payload", 0.30),
    ("cta",     0.30),
]

logger = logging.getLogger(__name__)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)
logger.setLevel(logging.INFO)


def _distribute_queries(queries: list[str], n_slots: int) -> list[list[str]]:
    """Round-robin distribute queries across n_slots.

    If fewer queries than slots, last slot(s) inherit the nearest prior query
    so every slot always has at least one search term.
    """
    if not queries:
        return [[] for _ in range(n_slots)]

    slots: list[list[str]] = [[] for _ in range(n_slots)]
    for i, q in enumerate(queries):
        slots[i % n_slots].append(q)

    # Back-fill empty slots with the last non-empty slot's first query
    last_query = queries[-1]
    for slot in slots:
        if not slot:
            slot.append(last_query)

    return slots


def build_manifest(
    duration_seconds: float,
    broll_queries: list[str],
    brand: str,
) -> dict:
    """
    Build a clip manifest from TTS duration and B-roll search queries.

    Args:
        duration_seconds: Total audio duration (from tts.synthesize).
        broll_queries: Ordered list of search queries (from generate.py).
        brand: Brand ID string (e.g. "alpha-insurance").

    Returns:
        Manifest dict with clips list and metadata.
        Also writes temp/manifest_{brand}_{timestamp}.json.
    """
    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be > 0, got {duration_seconds}")

    query_slots = _distribute_queries(broll_queries, len(SEGMENT_RATIOS))

    clips = []
    cursor = 0.0
    for (role, ratio), queries in zip(SEGMENT_RATIOS, query_slots):
        seg_duration = round(duration_seconds * ratio, 3)
        end = round(cursor + seg_duration, 3)
        clips.append({
            "role": role,
            "start": round(cursor, 3),
            "end": end,
            "duration": seg_duration,
            "queries": queries,
        })
        cursor = end

    # Snap final end to exact duration to avoid float drift
    clips[-1]["end"] = round(duration_seconds, 3)
    clips[-1]["duration"] = round(clips[-1]["end"] - clips[-1]["start"], 3)

    manifest = {
        "brand": brand,
        "total_duration": round(duration_seconds, 3),
        "clips": clips,
        "query_count": len(broll_queries),
    }

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = TEMP_DIR / f"manifest_{brand}_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info(
        f"  Manifest: {len(clips)} clips | {duration_seconds:.1f}s total | "
        f"{len(broll_queries)} queries | → {out_path.name}"
    )
    for clip in clips:
        logger.info(
            f"    [{clip['role']:7s}] {clip['start']:.2f}s–{clip['end']:.2f}s "
            f"({clip['duration']:.2f}s) | queries: {clip['queries']}"
        )

    return manifest


if __name__ == "__main__":
    # Self-test against the most recent TTS stub output
    tts_files = sorted(
        TEMP_DIR.glob("tts_*.mp3"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not tts_files:
        print("No TTS file in temp/ — run analyzer/tts.py first")
        raise SystemExit(1)

    import re
    from mutagen.mp3 import MP3

    audio_file = tts_files[0]
    duration = MP3(str(audio_file)).info.length
    brand = "alpha-insurance"

    test_queries = [
        "Mississippi insurance family protection",
        "home insurance coverage documents",
        "auto insurance car keys",
        "life insurance family consultation",
        "insurance agent office Mississippi",
    ]

    print(f"\nRunning audio_sync self-test")
    print(f"Audio: {audio_file.name} ({duration:.1f}s)")
    print(f"Queries: {test_queries}")

    manifest = build_manifest(duration, test_queries, brand)

    # Validate structure
    assert manifest["brand"] == brand
    assert len(manifest["clips"]) == 4
    assert abs(manifest["total_duration"] - duration) < 0.01

    total_clip_time = sum(c["duration"] for c in manifest["clips"])
    assert abs(total_clip_time - duration) < 0.01, (
        f"Clip durations don't sum to total: {total_clip_time:.3f} vs {duration:.3f}"
    )

    roles = [c["role"] for c in manifest["clips"]]
    assert roles == ["hook", "setup", "payload", "cta"], f"Wrong roles: {roles}"

    for clip in manifest["clips"]:
        assert clip["queries"], f"Clip '{clip['role']}' has no queries"
        assert clip["duration"] > 0, f"Clip '{clip['role']}' has zero duration"
        assert clip["end"] > clip["start"], f"Clip '{clip['role']}' end <= start"

    # Check ratios are approximately correct
    for clip, (_, ratio) in zip(manifest["clips"], SEGMENT_RATIOS):
        expected = duration * ratio
        assert abs(clip["duration"] - expected) < 0.01, (
            f"Ratio off for {clip['role']}: got {clip['duration']:.3f}s, "
            f"expected ~{expected:.3f}s"
        )

    print(f"\n✓ audio_sync self-test passed")
    print(f"  Total duration: {manifest['total_duration']:.1f}s")
    for c in manifest["clips"]:
        print(
            f"  [{c['role']:7s}] {c['start']:.2f}s–{c['end']:.2f}s "
            f"({c['duration']:.2f}s) | {c['queries']}"
        )
