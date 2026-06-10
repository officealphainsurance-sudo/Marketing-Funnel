#!/usr/bin/env python3.11
# Adapted from MoneyPrinterTurbo (MIT) github.com/harry0703/MoneyPrinterTurbo
"""
broll_v2.py — B-roll fetcher: Pexels → Pixabay fallback chain.

Chain: Pexels (key 1) → Pexels (key 2, on 429) → Pixabay.
No Kling. No PyJWT. Portrait orientation only.

Given a clip manifest (from audio_sync.build_manifest), downloads one
video file per clip slot and returns the manifest enriched with local paths.
"""

import os
import re
import time
import logging
import hashlib
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / "config" / ".env")

BROLL_DIR = ROOT / "temp" / "broll"
BROLL_DIR.mkdir(parents=True, exist_ok=True)

PEXELS_SEARCH_URL  = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"

REQUEST_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120

# Material quality bar — adapted from MoneyPrinterTurbo's preprocess_video()
# minimum-resolution check. Clips below this are unusable on a 1080x1920
# composite (visible upscale blur), so they're filtered before duration
# selection rather than downloaded and discarded.
MIN_CLIP_WIDTH = 480
MIN_CLIP_HEIGHT = 480

logger = logging.getLogger(__name__)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)
logger.setLevel(logging.INFO)


# ── Pexels ────────────────────────────────────────────────────────────────────

def _pexels_keys() -> list[str]:
    """Return available Pexels API keys (primary + optional secondary)."""
    keys = []
    for env in ("PEXELS_API_KEY", "PEXELS_API_KEY_2"):
        k = os.getenv(env, "").strip()
        if k:
            keys.append(k)
    return keys


def _pexels_best_file(video: dict) -> dict | None:
    """Pick the best portrait video_file from a Pexels video object."""
    files = video.get("video_files", [])
    portrait = [f for f in files if f.get("width", 0) <= f.get("height", 1)]
    if not portrait:
        # Accept any file rather than skip the clip entirely
        portrait = files
    if not portrait:
        return None
    # Prefer hd > sd; within same quality prefer higher resolution
    order = {"hd": 2, "sd": 1}
    portrait.sort(key=lambda f: (order.get(f.get("quality", ""), 0), f.get("height", 0)), reverse=True)
    return portrait[0]


def search_pexels(query: str, target_duration: float) -> dict | None:
    """
    Search Pexels for a portrait video matching the query.

    Rotates to the second API key on 429. Returns a result dict with
    {url, duration, source, width, height} or None on failure.
    """
    keys = _pexels_keys()
    if not keys:
        logger.warning("  Pexels: no API keys configured — skipping")
        return None

    params = {
        "query": query,
        "orientation": "portrait",
        "size": "medium",
        "per_page": 5,
    }

    for i, key in enumerate(keys):
        try:
            resp = requests.get(
                PEXELS_SEARCH_URL,
                headers={"Authorization": key},
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            logger.warning(f"  Pexels key {i+1} request error: {e}")
            continue

        if resp.status_code == 429:
            logger.warning(f"  Pexels key {i+1} rate-limited — {'trying key 2' if i == 0 and len(keys) > 1 else 'giving up'}")
            if i == 0 and len(keys) > 1:
                continue
            return None

        if resp.status_code != 200:
            logger.warning(f"  Pexels {resp.status_code} for '{query}'")
            return None

        videos = resp.json().get("videos", [])
        if not videos:
            logger.debug(f"  Pexels: no results for '{query}'")
            return None

        # Filter to videos whose best file clears the resolution bar before
        # duration selection — a high-res clip slightly off-target beats a
        # blurry clip that's a perfect duration match.
        candidates = []
        for video in videos:
            file_obj = _pexels_best_file(video)
            if file_obj and _meets_quality_bar(
                file_obj.get("width"), file_obj.get("height"), video.get("duration", 0)
            ):
                candidates.append(video)
        if not candidates:
            logger.debug(f"  Pexels: no results ≥ {MIN_CLIP_WIDTH}x{MIN_CLIP_HEIGHT} for '{query}'")
            return None

        # Pick video whose duration is closest to target (prefer ≥ target)
        best = _pick_best_duration(candidates, target_duration, duration_key="duration")
        if not best:
            return None

        file_obj = _pexels_best_file(best)
        if not file_obj:
            return None

        return {
            "url": file_obj["link"],
            "duration": best.get("duration", target_duration),
            "source": "pexels",
            "width": file_obj.get("width"),
            "height": file_obj.get("height"),
            "video_id": best.get("id"),
        }

    return None


# ── Pixabay ───────────────────────────────────────────────────────────────────

def search_pixabay(query: str, target_duration: float) -> dict | None:
    """
    Search Pixabay for a vertical video matching the query.

    Returns {url, duration, source, width, height} or None.
    """
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        logger.warning("  Pixabay: PIXABAY_API_KEY not configured — skipping")
        return None

    params = {
        "key": api_key,
        "q": query,
        "video_type": "all",
        "orientation": "vertical",
        "per_page": 5,
        "safesearch": "true",
    }

    try:
        resp = requests.get(PIXABAY_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        logger.warning(f"  Pixabay request error: {e}")
        return None

    if resp.status_code == 429:
        logger.warning("  Pixabay rate-limited")
        return None

    if resp.status_code != 200:
        logger.warning(f"  Pixabay {resp.status_code} for '{query}'")
        return None

    hits = resp.json().get("hits", [])
    if not hits:
        logger.debug(f"  Pixabay: no results for '{query}'")
        return None

    # A hit qualifies if any of its quality variants clears the resolution bar.
    candidates = [
        hit for hit in hits
        if any(
            _meets_quality_bar(v.get("width"), v.get("height"), hit.get("duration", 0))
            for v in hit.get("videos", {}).values()
        )
    ]
    if not candidates:
        logger.debug(f"  Pixabay: no results ≥ {MIN_CLIP_WIDTH}x{MIN_CLIP_HEIGHT} for '{query}'")
        return None

    best = _pick_best_duration(candidates, target_duration, duration_key="duration")
    if not best:
        return None

    # Prefer medium quality for reasonable file size, but skip variants
    # below the resolution bar in favor of the next-best quality tier.
    videos = best.get("videos", {})
    for quality in ("medium", "small", "large", "tiny"):
        vid = videos.get(quality)
        if vid and vid.get("url") and _meets_quality_bar(
            vid.get("width"), vid.get("height"), best.get("duration", 0)
        ):
            return {
                "url": vid["url"],
                "duration": best.get("duration", target_duration),
                "source": "pixabay",
                "width": vid.get("width"),
                "height": vid.get("height"),
                "video_id": best.get("id"),
            }

    return None


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _meets_quality_bar(width: int, height: int, duration: float) -> bool:
    """
    Reject material below the minimum usable resolution or with no duration.

    Adapted from MoneyPrinterTurbo's preprocess_video() material filter
    (480x480 minimum). Search results are checked here, before download,
    so low-res hits never reach _pick_best_duration or consume bandwidth.
    """
    if duration <= 0:
        return False
    if not width or not height:
        # Some API responses omit dimensions — don't reject on missing data,
        # only on confirmed sub-480 resolution.
        return True
    return width >= MIN_CLIP_WIDTH and height >= MIN_CLIP_HEIGHT


def _pick_best_duration(items: list[dict], target: float, duration_key: str) -> dict | None:
    """Return item whose duration is closest to target, preferring ≥ target."""
    if not items:
        return None
    # Separate items into those ≥ target and those < target
    ge = [v for v in items if v.get(duration_key, 0) >= target]
    lt = [v for v in items if v.get(duration_key, 0) < target]
    pool = ge if ge else lt
    return min(pool, key=lambda v: abs(v.get(duration_key, 0) - target))


def _clip_filename(brand: str, role: str, query: str, source: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower())[:30].strip("-")
    h = hashlib.md5(query.encode()).hexdigest()[:6]
    return f"broll_{brand}_{role}_{slug}_{h}_{source}.mp4"


def _download_clip(url: str, dest: Path) -> bool:
    """Stream-download a video file to dest. Returns True on success."""
    if dest.exists() and dest.stat().st_size > 10_000:
        logger.info(f"  Cache hit: {dest.name}")
        return True
    try:
        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
        logger.info(f"  Downloaded: {dest.name} ({dest.stat().st_size / 1024:.0f}KB)")
        return True
    except Exception as e:
        logger.warning(f"  Download failed {dest.name}: {e}")
        if dest.exists():
            dest.unlink()
        return False


# ── Main entry point ───────────────────────────────────────────────────────────

def fetch_broll(manifest: dict, brand: str) -> dict:
    """
    Download B-roll clips for every slot in a clip manifest.

    For each clip in manifest["clips"]:
      1. Try Pexels (with key rotation)
      2. Fall back to Pixabay
      3. Record local path (or None if both fail)

    Returns the manifest enriched with "local_path" and "broll_source" per clip.
    """
    enriched_clips = []
    missing = []

    for clip in manifest.get("clips", []):
        role = clip["role"]
        target = clip["duration"]
        queries = clip.get("queries", [])

        local_path = None
        source = None

        for query in queries:
            logger.info(f"  [{role}] Searching: '{query}' (~{target:.1f}s)")

            result = search_pexels(query, target)
            if result:
                logger.info(f"    Pexels match: {result['duration']}s id={result['video_id']}")
            else:
                result = search_pixabay(query, target)
                if result:
                    logger.info(f"    Pixabay match: {result['duration']}s id={result['video_id']}")

            if result:
                fname = _clip_filename(brand, role, query, result["source"])
                dest = BROLL_DIR / fname
                if _download_clip(result["url"], dest):
                    local_path = str(dest)
                    source = result["source"]
                    break
            else:
                logger.warning(f"    No result for '{query}' — trying next query")

        if local_path:
            logger.info(f"  [{role}] ✓ {Path(local_path).name}")
        else:
            logger.warning(f"  [{role}] ✗ No clip found for any query: {queries}")
            missing.append(role)

        enriched_clips.append({**clip, "local_path": local_path, "broll_source": source})

    result_manifest = {
        **manifest,
        "clips": enriched_clips,
        "missing_roles": missing,
        "fetch_complete": len(missing) == 0,
    }

    logger.info(
        f"  B-roll fetch: {len(enriched_clips) - len(missing)}/{len(enriched_clips)} clips found"
        + (f" | missing: {missing}" if missing else "")
    )
    return result_manifest


if __name__ == "__main__":
    import json

    # Smoke test — validates API connectivity without downloading full clips
    print("\nRunning broll_v2 smoke test")

    pexels_keys = _pexels_keys()
    pixabay_key = os.getenv("PIXABAY_API_KEY", "").strip()

    if not pexels_keys and not pixabay_key:
        print("⚠️  No API keys configured (PEXELS_API_KEY / PIXABAY_API_KEY not set)")
        print("   Add keys to config/.env to enable B-roll fetching")
        raise SystemExit(0)

    query = "Mississippi family home"
    target = 5.0

    if pexels_keys:
        print(f"Testing Pexels: '{query}' ~{target}s")
        result = search_pexels(query, target)
        if result:
            print(f"  ✓ Pexels: {result['source']} | {result['duration']}s | {result['width']}x{result['height']}")
        else:
            print("  ✗ Pexels: no result (check key or quota)")

    if pixabay_key:
        print(f"Testing Pixabay: '{query}' ~{target}s")
        result = search_pixabay(query, target)
        if result:
            print(f"  ✓ Pixabay: {result['source']} | {result['duration']}s | {result['width']}x{result['height']}")
        else:
            print("  ✗ Pixabay: no result (check key or quota)")

    print("\n✓ broll_v2 smoke test complete (structure validated — download skipped)")
    print("  ⚠️  PENDING: Add PEXELS_API_KEY / PIXABAY_API_KEY to config/.env for live fetch")
