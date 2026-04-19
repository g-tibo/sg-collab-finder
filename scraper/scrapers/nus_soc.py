"""NUS School of Computing — Computer Science + Information Systems & Data Analytics.

The `/about/faculty/` page renders a Vue/Alpine app and embeds the full
faculty roster as a JavaScript object literal:

    staff_list_allf: [
      { division: "...", name: "...", appt: ["Associate Professor", ...],
        appointment: ["Associate Professor, Department of ...", ...],
        image: "https://.../photo/uid.jpg",
        bio: "https://www.comp.nus.edu.sg/cs/people/uid",
        deptList: "Computer Science" | "Department of Information Systems and Data Analysis",
        ... }, ...
    ]

The block isn't strict JSON (unquoted keys, single-quoted values, trailing
commas), so we locate it by bracket-matching and extract per-record fields
with regex — cheaper and more robust than shelling out to node.

Only primary professorial ranks kept (Assistant / Associate / Full). Adjunct,
Visiting, Courtesy, Honorary, Emeritus, Lecturer, Practice-/Educator-track
are excluded.

Usage:
    python -m scrapers.nus_soc            # full scrape
    python -m scrapers.nus_soc --reparse  # re-parse cached HTML only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from schema import Faculty, clean_text, slugify


BASE = "https://www.comp.nus.edu.sg"
LISTING = f"{BASE}/about/faculty/"

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "out"
CACHE_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)


_DEPT_MAP = {
    "Computer Science": "Department of Computer Science",
    "Department of Information Systems and Data Analysis":
        "Department of Information Systems and Data Analysis",
}

_KEEP_RANKS = {
    "professor": "Professor",
    "associate professor": "Associate Professor",
    "assistant professor": "Assistant Professor",
    "nus presidential young professor": "Assistant Professor",
    "sung kah kay assistant professor": "Assistant Professor",
    "distinguished professor": "Professor",
    "provost's chair professor": "Professor",
    "dean's chair associate professor": "Associate Professor",
    "kithct chair professor": "Professor",
    "tan sri runme shaw senior professor": "Professor",
}

_SKIP_TOKENS = (
    "adjunct", "visiting", "emeritus", "honorary", "courtesy",
    "practice track", "educator track", "part-time", "lecturer",
    "professorial fellow",
)


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #

def _cache_path() -> Path:
    h = hashlib.sha256(LISTING.encode()).hexdigest()[:24]
    return CACHE_DIR / f"soc_{h}.html"


def _load_cached() -> str | None:
    p = _cache_path()
    if p.exists() and p.stat().st_size > 50_000:
        return p.read_text(encoding="utf-8", errors="ignore")
    return None


def _save_cached(html: str) -> None:
    _cache_path().write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #

def _fetch() -> str:
    cached = _load_cached()
    if cached:
        return cached
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_context().new_page()
        for attempt in range(3):
            try:
                pg.goto(LISTING, wait_until="domcontentloaded", timeout=60_000)
                pg.wait_for_timeout(4_000)
                html = pg.content()
                if "staff_list_allf" in html and len(html) > 500_000:
                    _save_cached(html)
                    b.close()
                    return html
            except Exception as e:
                print(f"  ! attempt {attempt+1}: {e}")
            time.sleep(2 + attempt)
        b.close()
    raise RuntimeError("failed to fetch SoC faculty listing")


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

def _extract_allf_block(html: str) -> str:
    i = html.find("staff_list_allf:")
    if i < 0:
        raise RuntimeError("staff_list_allf marker not found")
    j = i + len("staff_list_allf:")
    while j < len(html) and html[j] in " \n\t":
        j += 1
    if html[j] != "[":
        raise RuntimeError("expected [ after staff_list_allf")
    depth = 0
    k = j
    while k < len(html):
        c = html[k]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return html[j : k + 1]
        k += 1
    raise RuntimeError("unterminated staff_list_allf array")


def _split_records(block: str) -> list[str]:
    """Split the allf array into individual record substrings by brace-match."""
    out: list[str] = []
    depth = 0
    start = None
    for idx, c in enumerate(block):
        if c == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(block[start : idx + 1])
                start = None
    return out


_NAME_RE = re.compile(r'name:\s*"([^"]*)"')
_IMAGE_RE = re.compile(r"image:\s*['\"]([^'\"]*)['\"]")
_BIO_RE = re.compile(r"bio:\s*['\"]([^'\"]*)['\"]")
_DEPT_RE = re.compile(r'deptList:\s*"([^"]*)"')
_APPT_RE = re.compile(r"appt:\s*\[(.*?)\]", re.S)
_APPOINTMENT_RE = re.compile(r"appointment:\s*\[(.*?)\]", re.S)
_STR_RE = re.compile(r'"([^"]+)"')


def _parse_record(rec: str) -> dict | None:
    name_m = _NAME_RE.search(rec)
    if not name_m:
        return None
    name = clean_text(name_m.group(1))
    if not name:
        return None

    dept_raw = (m.group(1) if (m := _DEPT_RE.search(rec)) else "").strip()
    dept = _DEPT_MAP.get(dept_raw)
    if not dept:
        return None  # skip records outside CS / ISA (shouldn't happen in allf)

    appt_block = _APPT_RE.search(rec)
    appts = _STR_RE.findall(appt_block.group(1)) if appt_block else []
    rank = _match_rank(appts)
    if not rank:
        return None

    appointment_block = _APPOINTMENT_RE.search(rec)
    appointment_strs = (
        _STR_RE.findall(appointment_block.group(1)) if appointment_block else []
    )

    image = (m.group(1) if (m := _IMAGE_RE.search(rec)) else "").strip()
    bio = (m.group(1) if (m := _BIO_RE.search(rec)) else "").strip()

    # Roles: dedup appointments in original order, skip bare rank duplicates.
    roles: list[str] = []
    seen = set()
    for s in appointment_strs:
        s2 = clean_text(s)
        if s2 and s2 not in seen:
            seen.add(s2)
            roles.append(s2)

    return {
        "name": _normalize_name(name),
        "dept": dept,
        "rank": rank,
        "roles": roles,
        "profile_url": bio,
        "photo_url": image,
    }


def _match_rank(appts: list[str]) -> str | None:
    """Return canonical rank if any appt is a primary professorial title.
    A record is rejected if ALL appt entries are non-primary (admin-only),
    but an Assistant Dean who is also an Assoc Prof keeps Assoc Prof."""
    # Match longest keys first so "assistant professor" wins over "professor".
    ordered = sorted(_KEEP_RANKS.items(), key=lambda kv: -len(kv[0]))
    hit: str | None = None
    for a in appts:
        t = a.lower().strip()
        if not t:
            continue
        if any(tok in t for tok in _SKIP_TOKENS):
            continue
        for key, canon in ordered:
            if key in t:
                if hit is None or _rank_order(canon) > _rank_order(hit):
                    hit = canon
                break
    return hit


def _rank_order(r: str) -> int:
    return {"Professor": 3, "Associate Professor": 2, "Assistant Professor": 1}.get(r, 0)


def _normalize_name(raw: str) -> str:
    """Names arrive like "Tulika MITRA" or "Stéphane BRESSAN". Title-case
    the all-caps surname while leaving mixed-case tokens alone."""
    parts = raw.split()
    out = []
    for p in parts:
        # If >60% of letters are uppercase and it has >=2 letters, title-case it.
        letters = [c for c in p if c.isalpha()]
        if letters:
            upper = sum(1 for c in letters if c.isupper())
            if upper / len(letters) > 0.6 and len(letters) > 1:
                p = p.title()
        out.append(p)
    return " ".join(out)


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

def _to_faculty(rec: dict) -> Faculty:
    out: Faculty = {
        "id": slugify("nus", "soc", rec["name"]),
        "name": rec["name"],
        "institution": "NUS",
        "department": f"School of Computing — {rec['dept']}",
        "profile_url": rec["profile_url"],
    }
    if rec["rank"]:
        out["title"] = rec["rank"]
    if rec["roles"]:
        out["roles"] = rec["roles"]
    if rec["photo_url"]:
        out["photo_url"] = rec["photo_url"]
    return out


def scrape(reparse: bool = False) -> list[Faculty]:
    html = _load_cached() if reparse else _fetch()
    if not html:
        print("no cache; run without --reparse first")
        return []
    block = _extract_allf_block(html)
    records = _split_records(block)
    print(f"found {len(records)} raw records in staff_list_allf")
    parsed: list[dict] = []
    for rec in records:
        p = _parse_record(rec)
        if p:
            parsed.append(p)
    # Dedup by name+dept
    seen = set()
    unique: list[dict] = []
    for r in parsed:
        k = (r["name"], r["dept"])
        if k in seen:
            continue
        seen.add(k)
        unique.append(r)
    cs = sum(1 for r in unique if "Computer Science" in r["dept"])
    isa = sum(1 for r in unique if "Information Systems" in r["dept"])
    print(f"kept {len(unique)} (CS {cs}, ISA {isa})")
    return [_to_faculty(r) for r in unique]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparse", action="store_true")
    args = ap.parse_args()
    records = scrape(reparse=args.reparse)
    out_path = OUT_DIR / "nus_soc.json"
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    with_photo = sum(1 for r in records if r.get("photo_url"))
    print(f"\nWrote {len(records)} records to {out_path}")
    print(f"  with photo: {with_photo}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
