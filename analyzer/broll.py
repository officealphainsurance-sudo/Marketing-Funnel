"""
broll.py - Unified B-Roll Orchestrator
Tries Kling AI first (premium quality), falls back to Pexels (free) automatically.

Usage:
    python analyzer/broll.py <generated_script.json> <brand>

Environment variables (in D:\\ContentEngine\\.env):
    KLING_ACCESS_KEY=your_access_key
    KLING_SECRET_KEY=your_secret_key
    PEXELS_API_KEY=your_pexels_key
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

ROOT      = Path(__file__).parent.parent
LOGS_DIR  = ROOT / "logs"
BROLL_DIR = ROOT / "broll"

VALID_BRANDS = ["w-real-estate", "alpha-insurance"]


def get_logger(video_id: str, brand: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file  = LOGS_DIR / f"broll-orchestrator-{brand}-{timestamp}.log"
    logger    = logging.getLogger(f"broll.orchestrator.{brand}.{video_id}")
    logger.setLevel(logging.DEBUG)
    fh  = logging.FileHandler(log_file, encoding="utf-8")
    ch  = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def has_kling_credits(logger: logging.Logger) -> bool:
    """
    Check Kling credentials exist and credits are available.
    Uses GET /v1/videos/text2video (task list) — read-only, zero credit cost.
    """
    access_key = os.environ.get("KLING_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("KLING_SECRET_KEY", "").strip()

    if not access_key or not secret_key:
        logger.info("Kling credentials not found — skipping Kling")
        return False

    try:
        import time
        import requests
        import jwt

        now = int(time.time())
        payload = {
            "iss": access_key,
            "exp": now + 1800,
            "nbf": now - 5,
        }
        token = jwt.encode(payload, secret_key, algorithm="HS256",
                           headers={"alg": "HS256", "typ": "JWT"})
        if not isinstance(token, str):
            token = token.decode("utf-8")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # GET task list — read-only endpoint, costs zero credits
        resp = requests.get(
            "https://api.klingai.com/v1/videos/text2video",
            headers=headers,
            params={"pageNum": 1, "pageSize": 1},
            timeout=15,
        )
        data = resp.json()
        code = data.get("code", -1)

        if code == 0:
            logger.info("Kling credentials valid — proceeding with Kling AI")
            return True
        elif code == 1102:
            logger.warning("Kling: Account balance not enough — falling back to Pexels")
            return False
        elif code in (1001, 1002, 1003):
            logger.warning(f"Kling auth error (code {code}) — check API keys")
            return False
        else:
            logger.warning(f"Kling probe code {code}: {data.get('message')} — falling back to Pexels")
            return False

    except Exception as e:
        logger.warning(f"Kling probe failed: {e} — falling back to Pexels")
        return False


def generate_broll(script_path: str | Path, brand: str) -> dict:
    """
    Main entry point.
    1. Probe Kling for credit availability
    2. If credits available → run kling_broll.py
    3. If no credits / Kling fails → run pexels_broll.py
    4. Return unified manifest
    """
    if brand not in VALID_BRANDS:
        raise ValueError(f"Brand must be one of: {VALID_BRANDS}")

    script_path = Path(script_path).resolve()
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    # Get video_id for logger
    with open(script_path, encoding="utf-8") as f:
        script_data = json.load(f)
    content  = script_data.get("content", script_data)
    video_id = content.get("video_id", "unknown")

    logger = get_logger(video_id, brand)
    logger.info("=== B-Roll Orchestrator ===")
    logger.info(f"Brand: {brand} | Video ID: {video_id}")
    logger.info("Probing Kling AI credit balance...")

    # --- Try Kling first ---
    if has_kling_credits(logger):
        logger.info("Kling credits available — using Kling AI")
        try:
            # Import and run kling_broll
            sys.path.insert(0, str(ROOT / "analyzer"))
            from kling_broll import generate_broll as kling_generate

            manifest = kling_generate(script_path, brand)

            # Check if all clips succeeded
            if manifest["succeeded"] == manifest["total"]:
                logger.info(f"Kling complete: {manifest['succeeded']}/{manifest['total']} clips")
                manifest["source"] = "kling"
                return manifest

            # Partial success — fall back to Pexels for failed clips
            failed_count = len(manifest.get("failed", []))
            logger.warning(
                f"Kling partial: {manifest['succeeded']} succeeded, "
                f"{failed_count} failed — filling gaps with Pexels"
            )
            # Run Pexels for the failed clips only
            manifest = _fill_gaps_with_pexels(
                script_path, brand, manifest, logger
            )
            return manifest

        except Exception as e:
            logger.error(f"Kling failed entirely: {e}")
            logger.info("Falling back to Pexels for all clips...")

    # --- Fall back to Pexels ---
    logger.info("Using Pexels (free fallback)")
    try:
        from pexels_broll import generate_broll_pexels

        manifest = generate_broll_pexels(script_path, brand)
        manifest["source"] = "pexels"
        logger.info(f"Pexels complete: {manifest['succeeded']}/{manifest['total']} clips")
        return manifest

    except Exception as e:
        logger.error(f"Pexels also failed: {e}")
        raise RuntimeError(
            f"Both Kling and Pexels failed. Last error: {e}"
        )


def _fill_gaps_with_pexels(
    script_path: Path,
    brand: str,
    kling_manifest: dict,
    logger: logging.Logger,
) -> dict:
    """
    For clips that Kling failed to generate, fetch from Pexels instead.
    Merges results into a single manifest.
    """
    from pexels_broll import generate_broll_pexels

    failed_labels = {f["label"] for f in kling_manifest.get("failed", [])}
    if not failed_labels:
        return kling_manifest

    logger.info(f"Fetching {len(failed_labels)} gap clips from Pexels: {failed_labels}")

    # Run full Pexels pass — it will download all clips
    pexels_manifest = generate_broll_pexels(script_path, brand)

    # Merge: Kling clips take priority, Pexels fills gaps
    merged_clips = {**pexels_manifest["clips"], **kling_manifest["clips"]}

    merged = {
        **kling_manifest,
        "clips":     merged_clips,
        "source":    "kling+pexels",
        "succeeded": len(merged_clips),
        "failed":    [
            f for f in kling_manifest.get("failed", [])
            if f["label"] not in pexels_manifest["clips"]
        ],
    }

    logger.info(f"Merged: {merged['succeeded']} total clips ({merged['source']})")
    return merged


# --- CLI ---------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analyzer/broll.py <script.json> <brand>")
        print(f"  brand: {VALID_BRANDS}")
        print()
        print("Tries Kling AI first (premium), falls back to Pexels (free) automatically.")
        sys.exit(1)

    result = generate_broll(sys.argv[1], sys.argv[2])

    source = result.get("source", "unknown")
    print(f"\nB-Roll complete [{source}]: {result['succeeded']}/{result['total']} clips")
    for label, path in result["clips"].items():
        print(f"  {label}: {path}")
    if result.get("failed"):
        print(f"\nFailed: {len(result['failed'])} clips")
        for f in result["failed"]:
            print(f"  - {f['label']}: {f['error']}")
