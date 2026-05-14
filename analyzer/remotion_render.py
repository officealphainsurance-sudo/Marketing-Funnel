import json
import shutil
import subprocess
import logging
from pathlib import Path
from datetime import datetime

ROOT       = Path(__file__).parent.parent
VIDEOS_DIR = ROOT / "videos"
TEMP_DIR   = ROOT / "temp"
PUBLIC_DIR = ROOT / "public"
BROLL_DIR  = ROOT / "broll"
ASSETS_DIR = ROOT / "assets"


def _extract_segment(segments, label):
    for seg in segments:
        if seg.get("label") == label:
            return seg.get("spoken_text", "")
    return ""


def _setup_public(video_id, brand, logger):
    pub_broll  = PUBLIC_DIR / "broll"
    pub_assets = PUBLIC_DIR / "assets"
    pub_broll.mkdir(parents=True, exist_ok=True)
    pub_assets.mkdir(parents=True, exist_ok=True)

    broll_folder = BROLL_DIR / video_id
    scene_map = {
        "hook":     ["scene-0s-00.mp4",  "pexels-scene-0s-00.mp4"],
        "problem":  ["scene-3s-01.mp4",  "pexels-scene-3s-01.mp4"],
        "solution": ["scene-8s-02.mp4",  "pexels-scene-8s-02.mp4"],
        "cta":      ["scene-16s-03.mp4", "pexels-scene-16s-03.mp4"],
    }

    broll_props = {}
    if broll_folder.exists():
        for scene, candidates in scene_map.items():
            for candidate in candidates:
                src = broll_folder / candidate
                if src.exists():
                    dest_name = f"{video_id}-{scene}-kf.mp4"
                    dest = pub_broll / dest_name
                    import subprocess
                    subprocess.run([
                        "ffmpeg", "-i", str(src),
                        "-vf", "scale=1080:1920,fps=30",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                        "-g", "1", "-y", str(dest)
                    ], capture_output=True)
                    broll_props[scene] = f"broll/{dest_name}"
                    logger.info(f"  B-roll [{scene}]: {candidate}")
                    break
            else:
                logger.warning(f"  B-roll [{scene}]: NOT FOUND")
    else:
        logger.warning(f"  B-roll folder not found: {broll_folder}")

    logo_src  = ASSETS_DIR / brand / "logo.png"
    logo_prop = None
    if logo_src.exists():
        dest_name = f"{brand}-logo.png"
        shutil.copy2(logo_src, pub_assets / dest_name)
        logo_prop = f"assets/{dest_name}"
        logger.info(f"  Logo: {logo_src.name}")
    else:
        logger.warning(f"  Logo not found at {logo_src}")

    return broll_props, logo_prop


def render_remotion(script_path, brand, logger=None):
    if logger is None:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s [%(levelname)s] %(message)s")
        logger = logging.getLogger("remotion_render")

    script_path = Path(script_path).resolve()
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    with open(script_path, encoding="utf-8") as f:
        script_data = json.load(f)

    content     = script_data.get("content", script_data)
    video_id    = content.get("video_id", "unknown")
    full_script = content.get("full_script", {})
    segments    = full_script.get("segments", [])

    if not segments:
        raise ValueError("Script has no segments - cannot render")

    hook_text     = _extract_segment(segments, "hook")
    problem_text  = _extract_segment(segments, "problem")
    solution_text = _extract_segment(segments, "solution")
    cta_text      = _extract_segment(segments, "cta")

    logger.info(f"  Hook:     {hook_text[:70]}")
    logger.info(f"  Problem:  {problem_text[:70]}")
    logger.info(f"  Solution: {solution_text[:70]}")
    logger.info(f"  CTA:      {cta_text[:70]}")

    logger.info("  Setting up public assets...")
    broll_props, logo_prop = _setup_public(video_id, brand, logger)

    props = {
        "hookText":      hook_text,
        "problemText":   problem_text,
        "solutionText":  solution_text,
        "ctaText":       cta_text,
        "brandKey":      brand,
        "brollHook":     broll_props.get("hook",     ""),
        "brollProblem":  broll_props.get("problem",  ""),
        "brollSolution": broll_props.get("solution", ""),
        "brollCta":      broll_props.get("cta",      ""),
        "logoPath":      logo_prop or "",
    }

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    props_path = TEMP_DIR / f"remotion-props-{video_id}.json"
    with open(props_path, "w", encoding="utf-8") as f:
        json.dump(props, f, indent=2)

    logger.info(f"  Props written: {props_path}")
    logger.info(f"  logoPath  = {logo_prop}")
    logger.info(f"  brollHook = {broll_props.get('hook', 'MISSING')}")

    timestamp   = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = VIDEOS_DIR / f"{brand}-{video_id}-{timestamp}-remotion.mp4"

    logger.info(f"Output: {output_path.name}")
    logger.info("Remotion rendering - ~60-120 seconds...")

    cmd = [
        "npx", "remotion", "render",
        "remotion-test/index.jsx",
        "AuthorityReel",
        str(output_path),
        "--props", str(props_path),
        "--public-dir", r"D:/ContentEngine/public",
    ]

    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        timeout=300,
        shell=True,
    )

    if result.returncode != 0:
        raise RuntimeError("Remotion render failed - check output above")

    if not output_path.exists():
        raise RuntimeError(f"Output not created: {output_path}")

    size_mb = output_path.stat().st_size / 1024 / 1024
    logger.info(f"Render complete: {output_path.name} ({size_mb:.2f} MB)")

    return {
        "video_path":    str(output_path.relative_to(ROOT)),
        "video_size_mb": size_mb,
        "brand":         brand,
        "video_id":      video_id,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Render Remotion video from script JSON")
    parser.add_argument("script", help="Path to generated script JSON")
    parser.add_argument("brand",  help="w-real-estate or alpha-insurance")
    args = parser.parse_args()

    result = render_remotion(args.script, args.brand)
    print(f"\nVideo: {result['video_path']}")
    print(f"Size:  {result['video_size_mb']:.2f} MB")