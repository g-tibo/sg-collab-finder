"""Combine per-institution JSON into web/public/faculty.json."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "out"
TARGET = ROOT.parent / "web" / "public" / "faculty.json"

SOURCES = [
    "ntu_sbs.json",
    "astar_imcb.json",
    "nus_dbs.json",
]


def _norm_name(name: str) -> str:
    """Case/accent/punctuation-insensitive key for cross-institution matching."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z\s]", " ", s).lower()
    # Sort tokens so "Kanaga Sabapathy" == "Sabapathy, Kanaga" after reorder.
    tokens = [t for t in s.split() if t]
    return " ".join(sorted(tokens))


# Secondary-appointment title markers. Any record whose title matches is
# deprioritized when the same person also has a primary record elsewhere.
_SECONDARY_RE = re.compile(r"\b(Joint|Adjunct|Visiting|Affiliated|Honorary)\b", re.I)


def _is_primary(rec: dict) -> bool:
    return not _SECONDARY_RE.search(rec.get("title", "") or "")


def _priority(rec: dict) -> tuple:
    """Higher = better. Primary beats secondary; richer record beats thinner."""
    return (
        1 if _is_primary(rec) else 0,
        len(rec.get("summary", "") or ""),
        len(rec.get("research_areas", []) or []),
        1 if rec.get("photo_url") else 0,
    )


def _dedup(records: list[dict]) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """Collapse records by normalized name. Returns (kept, dropped) where
    `dropped` is a list of (name, institution, reason) for logging."""
    by_key: dict[str, list[dict]] = {}
    for r in records:
        by_key.setdefault(_norm_name(r.get("name", "")), []).append(r)
    kept: list[dict] = []
    dropped: list[tuple[str, str, str]] = []
    for key, group in by_key.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        group.sort(key=_priority, reverse=True)
        winner = group[0]
        kept.append(winner)
        for loser in group[1:]:
            dropped.append((
                loser.get("name", ""),
                f"{loser.get('institution','')} / {loser.get('department','')}",
                loser.get("title", "") or "(untitled)",
            ))
    return kept, dropped


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

    # Dedup cross-institution joint/adjunct appointments.
    all_records, dropped = _dedup(all_records)
    if dropped:
        print(f"  de-duplicated {len(dropped)} secondary appointment(s):")
        for name, where, title in dropped:
            print(f"    - {name} — {where} [{title}]")

    # Stable sort by institution then name for predictable diffs.
    all_records.sort(key=lambda r: (r.get("institution", ""), r.get("name", "")))

    # Strip faculty emails before publishing. The intent is to reduce
    # email-harvesting; the canonical institutional profile_url is still
    # linked from each card, so people can find the real address there.
    for r in all_records:
        r.pop("email", None)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(all_records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"wrote {len(all_records)} -> {TARGET}")


if __name__ == "__main__":
    main()
