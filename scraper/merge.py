"""Combine per-institution JSON into web/public/faculty.json."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "out"
TARGET = ROOT.parent / "web" / "public" / "faculty.json"
OVERRIDES = ROOT / "overrides.json"

SOURCES = [
    "ntu_sbs.json",
    "ntu_spms.json",
    "ntu_cceb.json",
    "ntu_ase.json",
    "ntu_cee.json",
    "ntu_eee.json",
    "ntu_mae.json",
    "ntu_mse.json",
    "ntu_ccds.json",
    "ntu_lkc.json",
    "astar_imcb.json",
    "astar_gis.json",
    "astar_bii.json",
    "astar_sign.json",
    "nus_dbs.json",
    "nus_yll.json",
    "dukenus.json",
    "nus_sci.json",
    "nus_cde.json",
    "nus_soc.json",
]


def _norm_name(name: str) -> str:
    """Case/accent/punctuation-insensitive key for cross-institution matching."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    # Drop parenthesized content (e.g. Chinese names in "Luke Ong (...)").
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-zA-Z\s]", " ", s).lower()
    # Sort tokens so "Kanaga Sabapathy" == "Sabapathy, Kanaga" after reorder.
    tokens = [t for t in s.split() if t]
    return " ".join(sorted(tokens))


# Titles that disqualify a record outright — holders typically don't run
# independent research groups, so they don't belong on a collab-finder.
# Covers Adjunct/Visiting/Honorary/Emeritus/Affiliated appointments plus
# teaching-track (Lecturer/Instructor) and industry titles like "Flagship
# Pioneering" that appear when a VC/entrepreneur has an honorary link.
_EXCLUDE_TITLE_RE = re.compile(
    r"\b("
    r"Adjunct|Visiting|Honorary|Emeritus|Affiliated|"
    r"Lecturer|Instructor|"
    r"Flagship\s+Pioneering"
    r")\b",
    re.I,
)

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


def _merge_subset_keys(by_key: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Merge groups where one key's tokens are a subset of another's. Catches
    "Alain Filloux" vs "Alain Ange Marie Filloux" as the same person. Requires
    both sides to have >=2 tokens so single-token keys don't collide."""
    keys = sorted(by_key.keys(), key=lambda k: len(k.split()))
    merged: dict[str, list[dict]] = {}
    for k in keys:
        toks = set(k.split())
        if len(toks) < 2:
            merged[k] = list(by_key[k])
            continue
        target = None
        for existing in merged:
            etoks = set(existing.split())
            if len(etoks) < 2:
                continue
            if toks.issubset(etoks) or etoks.issubset(toks):
                target = existing
                break
        if target is None:
            merged[k] = list(by_key[k])
        else:
            merged[target].extend(by_key[k])
    return merged


def _dedup(records: list[dict]) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """Collapse records by normalized name. Returns (kept, dropped) where
    `dropped` is a list of (name, institution, reason) for logging."""
    by_key: dict[str, list[dict]] = {}
    for r in records:
        by_key.setdefault(_norm_name(r.get("name", "")), []).append(r)
    by_key = _merge_subset_keys(by_key)
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

    # Apply manual overrides keyed by record id. These let us enrich profiles
    # the scrapers can't fully capture (richer summaries, curated keyword
    # lists, corrections). Overrides are a shallow merge per record.
    if OVERRIDES.exists():
        patches = json.loads(OVERRIDES.read_text(encoding="utf-8"))
        applied = 0
        for rec in all_records:
            patch = patches.get(rec.get("id"))
            if patch:
                rec.update(patch)
                applied += 1
        if applied:
            print(f"  applied {applied}/{len(patches)} overrides from overrides.json")

    # Drop non-research titles (adjunct, visiting, lecturer, etc.) outright.
    before = len(all_records)
    excluded: list[tuple[str, str, str]] = []
    kept: list[dict] = []
    for r in all_records:
        title = r.get("title", "") or ""
        if _EXCLUDE_TITLE_RE.search(title):
            excluded.append((r.get("name", ""), r.get("institution", ""), title))
        else:
            kept.append(r)
    all_records = kept
    if excluded:
        print(f"  excluded {len(excluded)} non-research titles (of {before}):")
        by_title: dict[str, int] = {}
        for _, _, t in excluded:
            by_title[t] = by_title.get(t, 0) + 1
        for t, n in sorted(by_title.items(), key=lambda kv: -kv[1]):
            safe = t.encode("ascii", "replace").decode("ascii")
            print(f"    {n:3d} {safe}")

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
