"""
ocr.py — Frame OCR pipeline
Runs Tesseract OCR on extracted keyframes, deduplicates similar text.
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

from PIL import Image

ROOT = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"

TESSERACT_INSTALL_URL = "https://github.com/UB-Mannheim/tesseract/wiki"


def check_tesseract() -> None:
    """Verify Tesseract is installed and accessible. Exit with clear message if not."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception as e:
        print("\n" + "=" * 60)
        print("ERROR: Tesseract OCR is not installed or not on your PATH.")
        print("")
        print("Windows Install Instructions:")
        print(f"  {TESSERACT_INSTALL_URL}")
        print("")
        print("After installing, ensure Tesseract is added to your PATH,")
        print("or set the path in ocr.py:")
        print("  pytesseract.pytesseract.tesseract_cmd = r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'")
        print("=" * 60 + "\n")
        sys.exit(1)


def get_logger(video_id: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOGS_DIR / f"ocr-{timestamp}.log"
    logger = logging.getLogger(f"ocr.{video_id}")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def deduplicate_text(entries: list[dict], threshold: float = 0.85) -> list[dict]:
    """
    Remove near-duplicate OCR text entries across frames.
    Keeps the first occurrence of each unique text block.
    """
    unique = []
    for entry in entries:
        text = entry.get("text", "").strip()
        if not text:
            continue
        is_dup = any(similarity(text, u["text"]) >= threshold for u in unique)
        if not is_dup:
            unique.append(entry)
    return unique


def ocr_frame(frame_path: Path, frame_index: int, logger: logging.Logger) -> dict | None:
    """Run OCR on a single frame image."""
    import pytesseract

    # Uncomment and set path if Tesseract is not on PATH:
    # pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    try:
        img = Image.open(frame_path)
        # Convert to RGB if needed (handles RGBA PNGs, etc.)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        text = pytesseract.image_to_string(img, config="--psm 3").strip()

        if not text:
            return None

        # Infer approximate timestamp from frame index (0.5 fps = 2s intervals)
        timestamp_seconds = frame_index * 2.0

        return {
            "frame": frame_path.name,
            "frame_index": frame_index,
            "timestamp_seconds": timestamp_seconds,
            "text": text,
        }
    except Exception as e:
        logger.warning(f"OCR failed on {frame_path.name}: {e}")
        return None


def run_ocr(frames_dir: str | Path, video_id: str) -> dict:
    """
    Main entry point.
    Returns structured OCR results with deduplication applied.
    """
    frames_dir = Path(frames_dir).resolve()
    if not frames_dir.exists():
        raise FileNotFoundError(f"Frames directory not found: {frames_dir}")

    check_tesseract()

    logger = get_logger(video_id)
    logger.info(f"=== OCR Pipeline ===")
    logger.info(f"Frames dir: {frames_dir}")
    logger.info(f"Video ID: {video_id}")

    frame_files = sorted(frames_dir.glob("frame_*.jpg"))
    logger.info(f"Processing {len(frame_files)} frames...")

    raw_results = []
    for i, frame_path in enumerate(frame_files):
        result = ocr_frame(frame_path, i, logger)
        if result:
            raw_results.append(result)
            logger.debug(f"Frame {i}: {result['text'][:60]!r}")

    logger.info(f"OCR found text in {len(raw_results)}/{len(frame_files)} frames")

    deduped = deduplicate_text(raw_results)
    logger.info(f"After deduplication: {len(deduped)} unique text blocks")

    output = {
        "video_id": video_id,
        "frames_processed": len(frame_files),
        "frames_with_text": len(raw_results),
        "unique_text_blocks": len(deduped),
        "text_entries": deduped,
        "ocr_run_at": datetime.now().isoformat(),
    }

    out_path = LOGS_DIR / f"ocr-{video_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"OCR results saved → {out_path}")
    logger.info("=== OCR complete ===")

    return output


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analyzer/ocr.py <frames_dir> <video_id>")
        sys.exit(1)
    result = run_ocr(sys.argv[1], sys.argv[2])
    for entry in result["text_entries"]:
        print(f"[{entry['timestamp_seconds']:.1f}s] {entry['text'][:80]}")
