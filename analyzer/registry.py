"""
registry.py — Competitor source registry manager

Usage:
    python analyzer/registry.py --add --brand w-real-estate --platform instagram --handle "@example" --type "luxury-realtor" --notes "strong hook style"
    python analyzer/registry.py --list --brand w-real-estate
    python analyzer/registry.py --remove --brand w-real-estate --handle "@example"
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
REGISTRY_FILE = ROOT / "config" / "competitor-sources.json"

VALID_BRANDS = ["w-real-estate", "alpha-insurance"]
REGISTRY_KEYS = {
    "w-real-estate": "w-real-estate-competitors",
    "alpha-insurance": "alpha-insurance-competitors",
}


def load_registry() -> dict:
    if not REGISTRY_FILE.exists():
        return {
            "w-real-estate-competitors": [],
            "alpha-insurance-competitors": [],
        }
    with open(REGISTRY_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_registry(data: dict) -> None:
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_entry(brand: str, platform: str, handle: str, entry_type: str, notes: str) -> None:
    if brand not in VALID_BRANDS:
        print(f"Error: brand must be one of {VALID_BRANDS}")
        sys.exit(1)

    registry = load_registry()
    key = REGISTRY_KEYS[brand]
    entries = registry.get(key, [])

    # Check for duplicate handle
    existing = [e for e in entries if e.get("handle", "").lower() == handle.lower()
                and e.get("platform", "").lower() == platform.lower()]
    if existing:
        print(f"Entry already exists for {handle} on {platform} under {brand}. Use --remove first to update.")
        sys.exit(1)

    new_entry = {
        "platform": platform,
        "handle": handle,
        "type": entry_type,
        "notes": notes,
        "date_added": datetime.now().strftime("%Y-%m-%d"),
    }
    entries.append(new_entry)
    registry[key] = entries
    save_registry(registry)

    print(f"✓ Added: [{brand}] {handle} on {platform} ({entry_type})")
    if notes:
        print(f"  Notes: {notes}")


def list_entries(brand: str) -> None:
    if brand not in VALID_BRANDS:
        print(f"Error: brand must be one of {VALID_BRANDS}")
        sys.exit(1)

    registry = load_registry()
    key = REGISTRY_KEYS[brand]
    entries = registry.get(key, [])

    print(f"\nCompetitor sources for: {brand}")
    print("─" * 60)
    if not entries:
        print("  (no entries yet)")
    else:
        for i, e in enumerate(entries, 1):
            print(f"  {i}. {e.get('handle')} | {e.get('platform')} | {e.get('type')}")
            print(f"     Added: {e.get('date_added')} | Notes: {e.get('notes', '')}")
    print(f"─" * 60)
    print(f"  Total: {len(entries)} source(s)\n")


def remove_entry(brand: str, handle: str) -> None:
    if brand not in VALID_BRANDS:
        print(f"Error: brand must be one of {VALID_BRANDS}")
        sys.exit(1)

    registry = load_registry()
    key = REGISTRY_KEYS[brand]
    entries = registry.get(key, [])
    before = len(entries)

    entries = [e for e in entries if e.get("handle", "").lower() != handle.lower()]
    removed = before - len(entries)

    if removed == 0:
        print(f"No entry found for handle '{handle}' under brand '{brand}'.")
        sys.exit(1)

    registry[key] = entries
    save_registry(registry)
    print(f"✓ Removed {removed} entry/entries for {handle} from {brand}.")


def main():
    parser = argparse.ArgumentParser(description="ContentEngine competitor registry manager")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--add", action="store_true", help="Add a competitor source")
    group.add_argument("--list", action="store_true", help="List competitor sources for a brand")
    group.add_argument("--remove", action="store_true", help="Remove a competitor source")

    parser.add_argument("--brand", required=True, choices=VALID_BRANDS)
    parser.add_argument("--platform", help="Platform: instagram, tiktok, facebook, youtube")
    parser.add_argument("--handle", help="Account handle e.g. @example")
    parser.add_argument("--type", dest="entry_type", default="", help="Type e.g. luxury-realtor, insurance-local")
    parser.add_argument("--notes", default="", help="Notes about this source")

    args = parser.parse_args()

    if args.add:
        if not args.platform or not args.handle:
            print("--add requires --platform and --handle")
            sys.exit(1)
        add_entry(args.brand, args.platform, args.handle, args.entry_type, args.notes)

    elif args.list:
        list_entries(args.brand)

    elif args.remove:
        if not args.handle:
            print("--remove requires --handle")
            sys.exit(1)
        remove_entry(args.brand, args.handle)


if __name__ == "__main__":
    main()
