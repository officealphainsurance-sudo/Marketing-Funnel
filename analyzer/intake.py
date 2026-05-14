"""
intake.py v2.1 — URL-based video intake with platform detection and performance metadata
Replaces manual MP4 dropping. Supports YouTube (full auto) and Instagram/TikTok (semi-auto).

CHANGELOG v2.1:
- FIXED: Instagram regex now correctly extracts handle vs. capturing reel ID
- FIXED: yt-dlp output template prevents .mp4.mp4 double-extension bug
- FIXED: Manual view entry now handles "47.5K" / "1.2M" style inputs

Usage:
    python analyzer/intake.py --url "https://youtube.com/watch?v=xxxxx" --brand w-real-estate
    python analyzer/intake.py --url "https://www.tiktok.com/@handle/video/xxxxx" --brand alpha-insurance
"""

import os
import sys
import json
import argparse
import re
import subprocess
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
VIDEOS_DIR = ROOT / "competitor-videos"

load_dotenv(ROOT / "config" / ".env")

VALID_BRANDS = ["w-real-estate", "alpha-insurance"]
RESERVED_PATH_SEGMENTS = {"reel", "reels", "p", "explore", "tv", "stories", "shorts"}


def detect_platform(url: str) -> str:
    url = url.lower()
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    elif "tiktok.com" in url:
        return "tiktok"
    elif "instagram.com" in url:
        return "instagram"
    elif "facebook.com" in url or "fb.watch" in url:
        return "facebook"
    else:
        return "unknown"


def extract_youtube_id(url: str) -> str | None:
    patterns = [
        r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:embed/)([A-Za-z0-9_-]{11})",
        r"(?:shorts/)([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_handle_from_url(url: str, platform: str) -> str:
    """
    FIX v2.1: Instagram regex correctly extracts handle vs. capturing reel/p path segment.
    """
    try:
        if platform == "tiktok":
            match = re.search(r"tiktok\.com/@([^/]+)", url)
            return match.group(1) if match else "unknown"

        elif platform == "instagram":
            # Format A: instagram.com/{handle}/reel/{id}/
            match = re.search(r"instagram\.com/([^/]+)/(?:reel|reels|p|tv)/", url)
            if match and match.group(1).lower() not in RESERVED_PATH_SEGMENTS:
                return match.group(1)
            # Format B: instagram.com/{handle}/
            match = re.search(r"instagram\.com/([^/?]+)/?", url)
            if match:
                seg = match.group(1).lower()
                if seg not in RESERVED_PATH_SEGMENTS:
                    return seg
            return "unknown"

        elif platform == "youtube":
            match = re.search(r"(?:@|channel/|user/|c/)([^/?&]+)", url)
            return match.group(1).lstrip("@") if match else "unknown"

        elif platform == "facebook":
            match = re.search(r"facebook\.com/([^/?]+)", url)
            if match and match.group(1) not in {"watch", "reel", "video"}:
                return match.group(1)

    except Exception:
        pass
    return "unknown"


def fetch_youtube_metadata(video_id: str) -> dict:
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        print("  ⚠  YOUTUBE_API_KEY not set in config/.env")
        print("     Falling back to manual metadata entry.")
        return {}

    try:
        import urllib.request
        import urllib.parse

        params = urllib.parse.urlencode({
            "part": "statistics,snippet",
            "id": video_id,
            "key": api_key,
        })
        api_url = f"https://www.googleapis.com/youtube/v3/videos?{params}"

        with urllib.request.urlopen(api_url, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        items = data.get("items", [])
        if not items:
            return {}

        item = items[0]
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})

        return {
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt", ""),
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
        }

    except Exception as e:
        print(f"  ⚠  YouTube API fetch failed: {e}")
        return {}


def download_video(url: str, output_path: Path) -> bool:
    """
    FIX v2.1: Uses %(ext)s template instead of hardcoded .mp4 to prevent
    .mp4.mp4 double-extension bug.
    """
    try:
        # Pass output WITHOUT extension; let yt-dlp add the merged format extension
        output_template = str(output_path.parent / f"{output_path.stem}.%(ext)s")

        cmd = [
            "yt-dlp",
            "--format", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--output", output_template,
            "--no-playlist",
            "--no-mtime",
            "--progress",
            url,
        ]
        print(f"  Downloading via yt-dlp...")
        result = subprocess.run(cmd, capture_output=False, text=True)
        if result.returncode != 0:
            print(f"  ✗ yt-dlp failed with exit code {result.returncode}")
            return False

        if output_path.exists():
            return True

        # Fallback: yt-dlp may produce mkv/webm if mp4 merge fails
        for alt_ext in (".mkv", ".webm"):
            alt = output_path.with_suffix(alt_ext)
            if alt.exists():
                print(f"  ℹ  Got {alt_ext} — renaming to .mp4")
                alt.rename(output_path)
                return True

        print(f"  ✗ Downloaded file not found at expected path: {output_path}")
        return False

    except FileNotFoundError:
        print("  ✗ yt-dlp not found. Install with: pip install yt-dlp")
        return False
    except Exception as e:
        print(f"  ✗ Download failed: {e}")
        return False


def parse_view_count(raw: str) -> int:
    """
    FIX v2.1: Handles 47000, 47,000, 47K, 47.5K, 1.2M formats.
    """
    raw = raw.strip().replace(",", "").upper()
    if not raw:
        raise ValueError("empty input")

    multiplier = 1
    if raw.endswith("M"):
        multiplier = 1_000_000
        raw = raw[:-1]
    elif raw.endswith("K"):
        multiplier = 1_000
        raw = raw[:-1]

    return int(float(raw) * multiplier)


def prompt_manual_metadata(platform: str, handle: str) -> dict:
    print(f"\n  📊 Manual metadata entry required for {platform}")
    print(f"     (YouTube is fully automatic — other platforms require this step)")
    print(f"     Accepts: 47000, 47,000, 47K, 47.5K, 1.2M\n")

    while True:
        try:
            views_str = input("  Enter view count for this video: ").strip()
            views = parse_view_count(views_str)
            break
        except (ValueError, AttributeError):
            print("  Invalid input. Examples: 47000, 47.5K, 1.2M")

    title = input("  Brief description (optional, press Enter to skip): ").strip()

    return {
        "views": views,
        "likes": 0,
        "comments": 0,
        "title": title,
        "channel": handle,
        "published_at": datetime.now().strftime("%Y-%m-%d"),
    }


def build_filename(platform: str, handle: str, description: str) -> str:
    date_str = datetime.now().strftime("%Y-%m-%d")
    desc_clean = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")[:40]
    if not desc_clean:
        desc_clean = "video"
    handle_clean = re.sub(r"[^a-z0-9]+", "", handle.lower())[:20]
    return f"{platform}-{handle_clean}-{date_str}-{desc_clean}"


def write_companion_json(json_path, platform, handle, brand, url, metadata, filename_stem):
    companion = {
        "filename": filename_stem,
        "platform": platform,
        "handle": handle,
        "url": url,
        "brand_target": brand,
        "intake_date": datetime.now().isoformat(),
        "performance": {
            "views": metadata.get("views", 0),
            "likes": metadata.get("likes", 0),
            "comments": metadata.get("comments", 0),
            "title": metadata.get("title", ""),
            "channel": metadata.get("channel", handle),
            "published_at": metadata.get("published_at", ""),
        },
        "pipeline_status": {
            "downloaded": True,
            "analyzed": False,
            "scored": False,
            "synthesized": False,
            "generated": False,
        }
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(companion, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Companion metadata saved → {json_path.name}")


def intake(url: str, brand: str, description: str = "") -> dict:
    if brand not in VALID_BRANDS:
        raise ValueError(f"Brand must be one of: {VALID_BRANDS}")

    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    platform = detect_platform(url)
    handle = extract_handle_from_url(url, platform)

    print(f"\n{'='*55}")
    print(f"  ContentEngine — Intake v2.1")
    print(f"  Platform: {platform} | Handle: {handle} | Brand: {brand}")
    print(f"{'='*55}\n")

    if not description:
        description = input("  Brief description for filename (e.g. seller-mistakes): ").strip()
        if not description:
            description = "video"

    filename_stem = build_filename(platform, handle, description)
    video_path = VIDEOS_DIR / f"{filename_stem}.mp4"
    companion_path = VIDEOS_DIR / f"{filename_stem}.json"

    print(f"  Target file: {video_path.name}")
    if video_path.exists():
        print(f"  ℹ  Video already exists, skipping download.")
    else:
        if not download_video(url, video_path):
            raise RuntimeError(f"Video download failed for URL: {url}")
        print(f"  ✓ Download complete → {video_path.name}")

    print(f"\n  Fetching performance metadata...")

    if platform == "youtube":
        yt_id = extract_youtube_id(url)
        if yt_id:
            metadata = fetch_youtube_metadata(yt_id)
            if metadata:
                print(f"  ✓ YouTube API: {metadata['views']:,} views | {metadata['likes']:,} likes")
                print(f"     Title: {metadata.get('title', '')[:60]}")
            else:
                metadata = prompt_manual_metadata(platform, handle)
        else:
            metadata = prompt_manual_metadata(platform, handle)
    else:
        metadata = prompt_manual_metadata(platform, handle)

    write_companion_json(companion_path, platform, handle, brand, url, metadata, filename_stem)

    print(f"\n{'='*55}")
    print(f"  ✓ Intake complete")
    print(f"  Video:    competitor-videos/{video_path.name}")
    print(f"  Metadata: competitor-videos/{companion_path.name}")
    print(f"  Views:    {metadata.get('views', 0):,}")
    print(f"\n  Ready to run pipeline:")
    print(f"  python analyzer/run.py --video \"competitor-videos/{video_path.name}\" --brand {brand}")
    print(f"{'='*55}\n")

    return {
        "video_path": str(video_path.relative_to(ROOT)),
        "companion_path": str(companion_path.relative_to(ROOT)),
        "filename_stem": filename_stem,
        "platform": platform,
        "handle": handle,
        "brand": brand,
        "views": metadata.get("views", 0),
    }


def main():
    parser = argparse.ArgumentParser(description="ContentEngine Intake v2.1")
    parser.add_argument("--url", required=True)
    parser.add_argument("--brand", required=True, choices=VALID_BRANDS)
    parser.add_argument("--description", default="")
    args = parser.parse_args()
    intake(args.url, args.brand, args.description)


if __name__ == "__main__":
    main()
