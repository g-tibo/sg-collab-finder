"""Combine per-institution JSON into web/public/faculty.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "out"
TARGET = ROOT.parent / "web" / "public" / "faculty.json"

SOURCES = [
    "ntu_sbs.json",
    "astar_imcb.json",
    "nus_dbs.json",
]


def main() -> None:
    all_records: list[dict] = []
    for src in SOURCES:
        p = OUT_DIR / src
        if not p.exists():
            print(f"  missing {src} — run the matching scraper first")
            continue
        records = json.loads(p.read_text(encoding="utf-8"))
        print(f"  {src}: {len(records)} records")
        all_records.extend(records)

    # Stable sort by institution then name for predictable diffs.
    all_records.sort(key=lambda r: (r.get("institution", ""), r.get("name", "")))

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(all_records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"wrote {len(all_records)} -> {TARGET}")


if __name__ == "__main__":
    main()
