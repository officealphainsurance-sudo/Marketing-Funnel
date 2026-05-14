"""
kling_broll.py — Kling AI B-Roll Generator (Phase 2.5)
Takes b_roll_cues from generate.py script output → generates MP4 clips via Kling API
Clips saved to D:\ContentEngine\broll\ for use as scene backgrounds in render.py

Usage:
    python analyzer/kling_broll.py <generated_script.json> <brand>

Environment variables required (in D:\ContentEngine\.env):
    KLING_ACCESS_KEY=your_access_key_here
    KLING_SECRET_KEY=your_secret_key_here

Official Kling API: https://api.klingai.com
Auth: JWT (HS256) with access_key + secret_key
"""

import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from datetime import datetime

# PyJWT — install with: pip install PyJWT
try:
    import jwt
except ImportError:
    print("ERROR: PyJWT not installed. Run: pip install PyJWT")
    sys.exit(1)

# python-dotenv — install with: pip install python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # .env loading optional — can use system env vars

# ─── Config ──────────────────────────────────────────────────────────────────

ROOT         = Path(__file__).parent.parent
BROLL_DIR    = ROOT / "broll"
LOGS_DIR     = ROOT / "logs"

KLING_API_BASE  = "https://api.klingai.com"
KLING_MODEL     = "kling-v1-6"       # Best quality on free tier
KLING_MODE      = "std"              # std = standard quality (free tier)
KLING_DURATION  = "5"                # 5 seconds per clip (matches scene length)
KLING_ASPECT    = "9:16"             # Vertical video for Reels/TikTok

POLL_INTERVAL   = 10                 # Seconds between status checks
MAX_WAIT        = 300                # Max 5 minutes per clip

VALID_BRANDS    = ["w-real-estate", "alpha-insurance"]

# ─── Brand-specific prompt modifiers ─────────────────────────────────────────

BRAND_STYLE = {
    "w-real-estate": (
        "cinematic, luxury real estate, Mississippi, warm golden lighting, "
        "professional quality, 4K, smooth camera movement"
    ),
    "alpha-insurance": (
        "professional, trustworthy, Mississippi community, warm lighting, "
        "everyday life, families, local neighborhood, professional quality"
    ),
}

BRAND_NEGATIVE = (
    "text, watermark, logo, blurry, low quality, cartoon, animation, "
    "distorted, ugly, bad anatomy, duplicate"
)

# ─── JWT Auth ─────────────────────────────────────────────────────────────────

def generate_jwt_token(access_key: str, secret_key: str) -> str:
    """
    Generate JWT token for Kling API authentication.
    Token expires in 30 minutes, valid 5 seconds from now.
    """
    now = int(time.time())
    payload = {
        "iss": access_key,
        "exp": now + 1800,   # 30 minute expiry
        "nbf": now - 5,      # Valid 5 seconds ago (clock skew buffer)
    }
    token = jwt.encode(
        payload,
        secret_key,
        algorithm="HS256",
        headers={"alg": "HS256", "typ": "JWT"},
    )
    return token if isinstance(token, str) else token.decode("utf-8")


def get_auth_headers(access_key: str, secret_key: str) -> dict:
    token = generate_jwt_token(access_key, secret_key)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# ─── API calls ────────────────────────────────────────────────────────────────

def submit_text_to_video(
    prompt: str,
    access_key: str,
    secret_key: str,
    brand: str,
) -> str:
    """Submit a text-to-video task to Kling. Returns task_id."""
    url = f"{KLING_API_BASE}/v1/videos/text2video"
    headers = get_auth_headers(access_key, secret_key)

    # Enrich prompt with brand style
    style_suffix = BRAND_STYLE.get(brand, "")
    full_prompt = f"{prompt}, {style_suffix}"

    payload = {
        "model_name":       KLING_MODEL,
        "prompt":           full_prompt[:2500],   # API max 2500 chars
        "negative_prompt":  BRAND_NEGATIVE,
        "cfg_scale":        0.5,
        "mode":             KLING_MODE,
        "aspect_ratio":     KLING_ASPECT,
        "duration":         KLING_DURATION,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(
            f"Kling submit failed [{response.status_code}]: {response.text}"
        )

    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(
            f"Kling API error: {data.get('message', 'Unknown error')}"
        )

    task_id = data["data"]["task_id"]
    return task_id


def poll_task_status(
    task_id: str,
    access_key: str,
    secret_key: str,
    logger: logging.Logger,
) -> str:
    """
    Poll Kling task until complete. Returns video URL.
    Polls every POLL_INTERVAL seconds, times out at MAX_WAIT seconds.
    """
    url = f"{KLING_API_BASE}/v1/videos/text2video/{task_id}"
    start = time.time()

    while True:
        elapsed = time.time() - start
        if elapsed > MAX_WAIT:
            raise TimeoutError(
                f"Kling task {task_id} timed out after {MAX_WAIT}s"
            )

        headers = get_auth_headers(access_key, secret_key)
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code != 200:
            logger.warning(
                f"Poll error [{response.status_code}]: {response.text}"
            )
            time.sleep(POLL_INTERVAL)
            continue

        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"Kling poll error: {data.get('message', 'Unknown')}"
            )

        task_data   = data["data"]
        task_status = task_data.get("task_status", "")

        logger.info(
            f"Task {task_id} status: {task_status} "
            f"({elapsed:.0f}s elapsed)"
        )

        if task_status == "succeed":
            videos = task_data.get("task_result", {}).get("videos", [])
            if not videos:
                raise RuntimeError("Task succeeded but no videos in result")
            return videos[0]["url"]

        elif task_status == "failed":
            reason = task_data.get("task_status_msg", "Unknown reason")
            raise RuntimeError(f"Kling task failed: {reason}")

        # Still processing — wait and poll again
        time.sleep(POLL_INTERVAL)


def download_clip(url: str, output_path: Path, logger: logging.Logger) -> None:
    """Download generated video clip from Kling CDN URL."""
    logger.info(f"Downloading clip → {output_path.name}")

    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    size_mb = output_path.stat().st_size / 1024 / 1024
    logger.info(f"✓ Downloaded: {size_mb:.2f} MB")


# ─── Main ─────────────────────────────────────────────────────────────────────

def generate_broll(script_path: str | Path, brand: str) -> dict:
    """
    Main entry point.
    Reads generated script JSON → submits each b_roll_cue to Kling API
    → polls for completion → downloads clips to broll/<video_id>/

    Returns dict with list of generated clip paths mapped to segment labels.
    """
    if brand not in VALID_BRANDS:
        raise ValueError(f"Brand must be one of: {VALID_BRANDS}")

    # Load credentials
    access_key = os.environ.get("KLING_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("KLING_SECRET_KEY", "").strip()

    if not access_key or not secret_key:
        raise RuntimeError(
            "Kling credentials not found.\n"
            "Add to D:\\ContentEngine\\.env:\n"
            "  KLING_ACCESS_KEY=your_access_key\n"
            "  KLING_SECRET_KEY=your_secret_key"
        )

    # Load script
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

    # Setup logger
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file  = LOGS_DIR / f"broll-{brand}-{timestamp}.log"
    logger    = logging.getLogger(f"broll.{brand}.{video_id}")
    logger.setLevel(logging.DEBUG)
    fh  = logging.FileHandler(log_file, encoding="utf-8")
    ch  = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"=== Kling B-Roll Generator ===")
    logger.info(f"Brand: {brand} | Video ID: {video_id}")
    logger.info(f"Cues to generate: {len(cues)}")

    # Output dir: broll/<video_id>/
    broll_dir = BROLL_DIR / video_id
    broll_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    failed  = []

    for idx, cue in enumerate(cues):
        # Handle actual b_roll_cues format: {"seconds": 0, "cue": "...", "duration_seconds": 3}
        if isinstance(cue, dict):
            prompt  = cue.get("cue", cue.get("prompt", str(cue)))
            seconds = cue.get("seconds", idx * 5)
            label   = cue.get("label", f"scene-{seconds}s")
        else:
            prompt  = str(cue)
            label   = f"scene-{idx}"

        logger.info(f"[{idx+1}/{len(cues)}] Generating: {label}")
        logger.info(f"  Prompt: {prompt}")

        clip_path = broll_dir / f"{label}-{idx:02d}.mp4"

        # Skip if already generated (resume support)
        if clip_path.exists() and clip_path.stat().st_size > 10_000:
            logger.info(f"  ✓ Already exists, skipping")
            results[label] = str(clip_path.relative_to(ROOT))
            continue

        try:
            # Submit to Kling
            task_id = submit_text_to_video(prompt, access_key, secret_key, brand)
            logger.info(f"  Task ID: {task_id}")

            # Poll until done
            video_url = poll_task_status(task_id, access_key, secret_key, logger)
            logger.info(f"  Video URL: {video_url}")

            # Download clip
            download_clip(video_url, clip_path, logger)
            results[label] = str(clip_path.relative_to(ROOT))

        except Exception as e:
            logger.error(f"  ✗ Failed: {e}")
            failed.append({"label": label, "prompt": prompt, "error": str(e)})
            continue

    # Save results manifest
    manifest = {
        "video_id":   video_id,
        "brand":      brand,
        "timestamp":  timestamp,
        "clips":      results,
        "failed":     failed,
        "total":      len(cues),
        "succeeded":  len(results),
    }
    manifest_path = broll_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"=== B-Roll Complete ===")
    logger.info(f"Generated: {len(results)}/{len(cues)} clips")
    if failed:
        logger.warning(f"Failed: {len(failed)} clips")
        for f_item in failed:
            logger.warning(f"  - {f_item['label']}: {f_item['error']}")

    return manifest


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analyzer/kling_broll.py <script.json> <brand>")
        print(f"  brand: {VALID_BRANDS}")
        sys.exit(1)

    result = generate_broll(sys.argv[1], sys.argv[2])
    print(f"\n✓ B-Roll complete: {result['succeeded']}/{result['total']} clips")
    for label, path in result["clips"].items():
        print(f"  {label}: {path}")
    if result["failed"]:
        print(f"\n✗ Failed: {len(result['failed'])} clips")
