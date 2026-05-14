"""
pexels_broll.py - Pexels API B-Roll Generator (Free Fallback)
Takes b_roll_cues from generate.py output -> searches Pexels for matching stock video
Clips saved to D:\\ContentEngine\\broll\\ for use as scene backgrounds in render.py

Usage:
    python analyzer/pexels_broll.py <generated_script.json> <brand>

Environment variables required (in D:\\ContentEngine\\.env):
    PEXELS_API_KEY=your_pexels_api_key_here

Free tier: 200 requests/hour, 20,000/month. Zero cost.
"""

import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from datetime import datetime

# python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# --- Config ------------------------------------------------------------------

ROOT       = Path(__file__).parent.parent
BROLL_DIR  = ROOT / "broll"
LOGS_DIR   = ROOT / "logs"

PEXELS_API_BASE = "https://api.pexels.com/videos"

# Vertical video preferred (9:16) — Pexels doesn't filter by orientation
# but we pick the best matching file from results
TARGET_WIDTH  = 1080
TARGET_HEIGHT = 1920

VALID_BRANDS = ["w-real-estate", "alpha-insurance"]

# Brand-specific search keyword boosters appended to each cue's keywords
BRAND_KEYWORDS = {
    "w-real-estate": ["luxury home", "real estate", "house", "property", "neighborhood"],
    "alpha-insurance": ["family", "community", "neighborhood", "home", "people"],
}

# Fallback search terms if cue extraction yields no results
BRAND_FALLBACK = {
    "w-real-estate": [
        "luxury house exterior",
        "modern home interior",
        "real estate neighborhood",
        "house keys",
        "beautiful home",
    ],
    "alpha-insurance": [
        "happy family home",
        "neighborhood street",
        "car driving",
        "family outdoors",
        "community",
    ],
}


# --- Keyword Extraction ------------------------------------------------------

def extract_keywords(cue_text: str, brand: str) -> list[str]:
    """
    Extract 2-4 search keywords from a b-roll cue description.
    Strips cinematic directions and keeps content nouns.
    """
    # Words to strip (camera directions, quality descriptors)
    stop_words = {
        "slow", "pan", "quick", "montage", "overlay", "close", "up", "close-up",
        "closeup", "return", "fade", "fades", "text", "elegant", "professional",
        "clean", "setting", "cinematic", "detail", "details", "shot", "camera",
        "transition", "transitions", "stock", "expression", "brokerage", "name",
        "phone", "number", "font", "across", "into", "with", "the", "and", "or",
        "of", "a", "an", "in", "at", "to", "for", "on", "from", "by", "as",
        "this", "that", "these", "those", "its", "is", "are", "was", "be",
    }

    words = cue_text.lower().replace(",", " ").replace(";", " ").replace("'", "").split()
    keywords = [w for w in words if w not in stop_words and len(w) > 3]

    # Keep first 4 meaningful words
    keywords = keywords[:4]

    # Add one brand keyword for relevance
    brand_kw = BRAND_KEYWORDS.get(brand, [])
    if brand_kw and brand_kw[0] not in " ".join(keywords):
        keywords.append(brand_kw[0])

    return keywords


# --- Pexels API --------------------------------------------------------------

def search_pexels_videos(
    query: str,
    api_key: str,
    per_page: int = 10,
) -> list[dict]:
    """Search Pexels for videos matching the query. Returns list of video results."""
    url = f"{PEXELS_API_BASE}/search"
    headers = {"Authorization": api_key}
    params = {
        "query":    query,
        "per_page": per_page,
        "orientation": "portrait",  # Prefer vertical/portrait videos
        "size": "medium",           # medium = 1920p or lower
    }

    response = requests.get(url, headers=headers, params=params, timeout=15)

    if response.status_code == 401:
        raise RuntimeError("Pexels API key invalid — check PEXELS_API_KEY in .env")
    if response.status_code == 429:
        raise RuntimeError("Pexels rate limit hit (200/hour). Wait 1 hour.")
    if response.status_code != 200:
        raise RuntimeError(f"Pexels search failed [{response.status_code}]: {response.text}")

    data = response.json()
    return data.get("videos", [])


def pick_best_video_file(video: dict) -> dict | None:
    """
    From a Pexels video result, pick the best video file.
    Priority: portrait HD > portrait SD > landscape HD > any
    """
    files = video.get("video_files", [])
    if not files:
        return None

    # Sort by: portrait first, then by resolution (higher = better)
    def score(f):
        w = f.get("width", 0)
        h = f.get("height", 0)
        is_portrait = h > w
        resolution = w * h
        return (is_portrait, resolution)

    files_sorted = sorted(files, key=score, reverse=True)
    return files_sorted[0]


def find_best_clip(
    cue_text: str,
    brand: str,
    api_key: str,
    logger: logging.Logger,
) -> tuple[str, str] | None:
    """
    Search Pexels for a clip matching the cue.
    Returns (download_url, video_title) or None if nothing found.

    Strategy:
    1. Try full extracted keywords
    2. Try reduced keywords (first 2)
    3. Try brand fallback terms
    """
    keywords = extract_keywords(cue_text, brand)
    fallbacks = BRAND_FALLBACK.get(brand, ["house", "home", "family"])

    search_attempts = [
        " ".join(keywords),
        " ".join(keywords[:2]) if len(keywords) > 2 else None,
    ] + fallbacks[:3]

    # Remove None and deduplicate
    search_attempts = list(dict.fromkeys(q for q in search_attempts if q))

    for query in search_attempts:
        logger.info(f"  Searching Pexels: '{query}'")
        try:
            videos = search_pexels_videos(query, api_key)
            if not videos:
                logger.info(f"  No results for '{query}', trying next...")
                continue

            # Pick first video with a usable file
            for video in videos:
                best_file = pick_best_video_file(video)
                if best_file and best_file.get("link"):
                    title = video.get("url", "").split("/")[-2].replace("-", " ")
                    logger.info(
                        f"  Found: '{title}' "
                        f"({best_file.get('width')}x{best_file.get('height')})"
                    )
                    return best_file["link"], title

        except RuntimeError as e:
            # Rate limit or auth error — re-raise immediately
            if "rate limit" in str(e).lower() or "invalid" in str(e).lower():
                raise
            logger.warning(f"  Search error: {e}")
            continue

    return None


def download_clip(
    url: str,
    output_path: Path,
    logger: logging.Logger,
) -> None:
    """Download a Pexels video clip."""
    logger.info(f"  Downloading → {output_path.name}")
    response = requests.get(url, stream=True, timeout=120)
    response.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=65536):
            f.write(chunk)

    size_mb = output_path.stat().st_size / 1024 / 1024
    logger.info(f"  Downloaded: {size_mb:.2f} MB")


# --- Main --------------------------------------------------------------------

def generate_broll_pexels(script_path: str | Path, brand: str) -> dict:
    """
    Main entry point.
    Reads generated script JSON -> searches Pexels for each b_roll_cue
    -> downloads best matching clip to broll/<video_id>/

    Returns manifest dict with clip paths per scene label.
    """
    if brand not in VALID_BRANDS:
        raise ValueError(f"Brand must be one of: {VALID_BRANDS}")

    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Pexels API key not found.\n"
            "Add to D:\\ContentEngine\\.env:\n"
            "  PEXELS_API_KEY=your_key_here"
        )

    script_path = Path(script_path).resolve()
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    with open(script_path, encoding="utf-8") as f:
        script_data = json.load(f)

    content  = script_data.get("content", script_data)
    video_id = content.get("video_id", "unknown")
    cues     = content.get("b_roll_cues", [])

    if not cues:
        raise ValueError("Script has no b_roll_cues — run generate.py first")

    # Logger
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file  = LOGS_DIR / f"pexels-{brand}-{timestamp}.log"
    logger    = logging.getLogger(f"pexels.{brand}.{video_id}")
    logger.setLevel(logging.DEBUG)
    fh  = logging.FileHandler(log_file, encoding="utf-8")
    ch  = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info("=== Pexels B-Roll Generator ===")
    logger.info(f"Brand: {brand} | Video ID: {video_id}")
    logger.info(f"Cues to process: {len(cues)}")

    broll_dir = BROLL_DIR / video_id
    broll_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    failed  = []

    for idx, cue in enumerate(cues):
        # Parse cue format: {"seconds": 0, "cue": "...", "duration_seconds": 3}
        if isinstance(cue, dict):
            cue_text = cue.get("cue", cue.get("prompt", str(cue)))
            seconds  = cue.get("seconds", idx * 5)
            label    = cue.get("label", f"scene-{seconds}s")
        else:
            cue_text = str(cue)
            label    = f"scene-{idx}"

        logger.info(f"[{idx+1}/{len(cues)}] {label}: {cue_text[:80]}...")

        clip_path = broll_dir / f"pexels-{label}-{idx:02d}.mp4"

        # Resume support — skip if already downloaded
        if clip_path.exists() and clip_path.stat().st_size > 100_000:
            logger.info(f"  Already exists, skipping")
            results[label] = str(clip_path.relative_to(ROOT))
            continue

        try:
            result = find_best_clip(cue_text, brand, api_key, logger)
            if not result:
                raise RuntimeError(f"No Pexels results found for any search query")

            download_url, title = result
            download_clip(download_url, clip_path, logger)
            results[label] = str(clip_path.relative_to(ROOT))
            logger.info(f"  Saved: {clip_path.relative_to(ROOT)}")

            # Small delay to respect rate limits
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"  Failed: {e}")
            failed.append({"label": label, "cue": cue_text, "error": str(e)})
            continue

    # Save manifest
    manifest = {
        "video_id":  video_id,
        "brand":     brand,
        "source":    "pexels",
        "timestamp": timestamp,
        "clips":     results,
        "failed":    failed,
        "total":     len(cues),
        "succeeded": len(results),
    }
    manifest_path = broll_dir / "pexels_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info("=== Pexels B-Roll Complete ===")
    logger.info(f"Generated: {len(results)}/{len(cues)} clips")
    if failed:
        logger.warning(f"Failed: {len(failed)} clips")

    return manifest


# --- CLI ---------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analyzer/pexels_broll.py <script.json> <brand>")
        print(f"  brand: {VALID_BRANDS}")
        sys.exit(1)

    result = generate_broll_pexels(sys.argv[1], sys.argv[2])
    print(f"\n Pexels B-Roll: {result['succeeded']}/{result['total']} clips")
    for label, path in result["clips"].items():
        print(f"  {label}: {path}")
    if result["failed"]:
        print(f"\n Failed: {len(result['failed'])} clips")
        for f in result["failed"]:
            print(f"  - {f['label']}: {f['error']}")
