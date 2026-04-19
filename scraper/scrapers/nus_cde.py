"""NUS College of Design and Engineering (CDE) — 7 STEM departments.

All CDE departments run the same "websparks-people" WordPress plugin
which renders 12 cards per page with standard numbered pagination via
`?paged=N`. Each card uses the `ws-people-content` class with a
consistent internal structure (content-image, content-name, content-title,
content-designation, content-department). We fetch page 1, read the
last-page number from `.ws-listing-pagination .last-paging`, then iterate
`paged=2..N` — same card parser for everything.

Different depts use different URL paths to filter "tenure-track"
(primary) faculty. The listing[] entry per dept captures that.

Following the Duke-NUS / NUS-Sci rule we keep only Assistant / Associate
/ Full Professor ranks (no Adjunct / Visiting / Emeritus / Honorary /
Educator / Practice-track / Joint-appointment secondary faculty).

Usage:
    python -m scrapers.nus_cde            # full scrape
    python -m scrapers.nus_cde --reparse  # re-parse cached HTML only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup

from schema import Faculty, clean_text, slugify


ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "out"
CACHE_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)


DEPARTMENTS: list[dict] = [
    {"slug": "bme",  "name": "Department of Biomedical Engineering",
     "listing": "https://cde.nus.edu.sg/bme/about-us/people/academic-staff/?category=academic-3"},
    {"slug": "chbe", "name": "Department of Chemical and Biomolecular Engineering",
     "listing": "https://cde.nus.edu.sg/chbe/about-us/people/?category=tenure-track"},
    {"slug": "cee",  "name": "Department of Civil and Environmental Engineering",
     "listing": "https://cde.nus.edu.sg/cee/about-us/people/faculty-staff/"},
    {"slug": "ece",  "name": "Department of Electrical and Computer Engineering",
     "listing": "https://cde.nus.edu.sg/ece/about-us/people/academic-staff/"},
    {"slug": "isem", "name": "Department of Industrial Systems Engineering and Management",
     "listing": "https://cde.nus.edu.sg/isem/faculty-members/"},
    {"slug": "mse",  "name": "Department of Materials Science and Engineering",
     "listing": "https://cde.nus.edu.sg/mse/about-us/people/academic-staff/"},
    {"slug": "me",   "name": "Department of Mechanical Engineering",
     "listing": "https://cde.nus.edu.sg/me/about-us/people/academic-staff/"},
]


# --------------------------------------------------------------------------- #
# cache helpers
# --------------------------------------------------------------------------- #

def _cache_key(url: str, prefix: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"{prefix}_{h}.html"


def _load_cached(url: str, prefix: str) -> str | None:
    p = _cache_key(url, prefix)
    if p.exists() and p.stat().st_size > 5_000:
        return p.read_text(encoding="utf-8", errors="ignore")
    return None


def _save_cached(url: str, prefix: str, html: str) -> None:
    _cache_key(url, prefix).write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Playwright fetch
# --------------------------------------------------------------------------- #

def _fetch_pages(dept: dict, max_pages: int = 20) -> list[str]:
    """Fetch page 1, determine total pages, fetch 2..N.
    Returns list of HTML strings (one per page). Uses disk cache per page."""
    base = dept["listing"]
    pages: list[str] = []

    # Try page 1 from cache first.
    html = _load_cached(base, f"cde_{dept['slug']}")
    if html:
        pages.append(html)
        total = _total_pages(html)
    else:
        html, total = _fetch_playwright_pages(base, dept, max_pages)
        pages.extend(html)
        return pages

    # Fetch remaining pages from cache or web.
    missing = [p for p in range(2, total + 1)
               if not _load_cached(_paged_url(base, p), f"cde_{dept['slug']}")]
    if missing:
        extra, _ = _fetch_playwright_pages(base, dept, max_pages, start_page=2)
        for i, h in enumerate(extra, start=2):
            pages.append(h)
    else:
        for p in range(2, total + 1):
            cached = _load_cached(_paged_url(base, p), f"cde_{dept['slug']}")
            if cached:
                pages.append(cached)
    return pages


def _paged_url(base: str, page: int) -> str:
    if page <= 1:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}paged={page}"


def _total_pages(html: str) -> int:
    """Scan .ws-listing-pagination for the last page number. The numbered
    links only show a window (e.g. 1..4), so prefer the `last-paging` href
    (`?paged=N`) which points to the real final page."""
    s = BeautifulSoup(html, "html.parser")
    nums: list[int] = []
    last = s.select_one(".ws-listing-pagination a.last-paging")
    if last and last.get("href"):
        m = re.search(r"paged=(\d+)", last["href"])
        if m:
            nums.append(int(m.group(1)))
    for a in s.select(".ws-listing-pagination a, .ws-listing-pagination span"):
        txt = a.get_text(strip=True)
        if txt.isdigit():
            nums.append(int(txt))
    return max(nums) if nums else 1


def _fetch_playwright_pages(base: str, dept: dict, max_pages: int,
                             start_page: int = 1) -> tuple[list[str], int]:
    from playwright.sync_api import sync_playwright
    pages_html: list[str] = []
    total = 1
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        cur = start_page
        while cur <= max_pages:
            u = _paged_url(base, cur)
            html = ""
            for attempt in range(3):
                try:
                    page.goto(u, wait_until="networkidle", timeout=60_000)
                    page.wait_for_timeout(1_500)
                    html = page.content()
                    if len(html) > 20_000:
                        _save_cached(u, f"cde_{dept['slug']}", html)
                        break
                except Exception as e:
                    print(f"  ! {dept['slug']} p{cur} attempt {attempt+1}: {e}")
                time.sleep(1 + attempt)
            if not html:
                break
            pages_html.append(html)
            if cur == start_page:
                total = _total_pages(html)
                print(f"  [{dept['slug']}] total pages: {total}")
            if cur >= total:
                break
            cur += 1
        b.close()
    return pages_html, total


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

_KEEP_RANKS = {
    "professor": "Professor",
    "associate professor": "Associate Professor",
    "assistant professor": "Assistant Professor",
    "presidential young professor": "Assistant Professor",
}

# Substrings in title/designation that mark a record as non-primary.
_SKIP_TITLE_TOKENS = (
    "adjunct", "visiting", "emeritus", "honorary", "educator track",
    "practice track", "teaching", "courtesy", "joint appointment",
    "professor of practice",
)


def _parse_page(html: str, dept: dict) -> list[dict]:
    s = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for card in s.find_all(class_="ws-people-content"):
        # name
        name_el = card.select_one(".content-name h3, .content-name h2, .content-name h4")
        if not name_el:
            continue
        raw_name = clean_text(name_el.get_text(" "))
        # strip honorifics
        name = re.sub(
            r"^(?:Prof\.?|Dr\.?|A/Prof\.?|Asst\s+Prof\.?|Assistant\s+Prof\.?|Associate\s+Prof\.?)\s+",
            "", raw_name, flags=re.I,
        ).strip()
        if not name:
            continue

        # rank: content-title h5
        rank_el = card.select_one(".content-title h5, .content-title h4, .content-title h3")
        rank_text = clean_text(rank_el.get_text(" ")) if rank_el else ""
        rank = _match_cde_rank(rank_text)
        if not rank:
            continue

        # skip if designation contains secondary-appointment markers
        des_el = card.select_one(".content-designation")
        designation = clean_text(des_el.get_text(" ")) if des_el else ""
        if any(tok in designation.lower() for tok in _SKIP_TITLE_TOKENS):
            continue
        if any(tok in rank_text.lower() for tok in _SKIP_TITLE_TOKENS):
            continue

        # profile URL
        prof_a = card.select_one(".content-name a, .content-image a")
        profile_url = prof_a.get("href", "") if prof_a else ""

        # photo
        img = card.find("img")
        photo = img.get("src") if img and img.get("src") else ""

        # dept-level extra
        dept_el = card.select_one(".content-department")
        dept_line = clean_text(dept_el.get_text(" ")) if dept_el else ""

        roles = [x for x in (designation, dept_line) if x]

        out.append({
            "name": name,
            "title": rank_text or rank,
            "rank": rank,
            "roles": roles,
            "profile_url": profile_url,
            "photo_url": photo,
        })
    return out


def _match_cde_rank(text: str) -> str | None:
    t = text.lower()
    if not t:
        return None
    if any(tok in t for tok in _SKIP_TITLE_TOKENS):
        return None
    for key, canon in _KEEP_RANKS.items():
        if key in t:
            return canon
    return None


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

def _to_faculty(dept: dict, rec: dict) -> Faculty:
    out: Faculty = {
        "id": slugify("nus", "cde", dept["slug"], rec["name"]),
        "name": rec["name"],
        "institution": "NUS",
        "department": f"College of Design and Engineering — {dept['name']}",
        "profile_url": rec["profile_url"],
    }
    if rec.get("title"):
        out["title"] = rec["title"]
    if rec.get("roles"):
        out["roles"] = rec["roles"]
    if rec.get("photo_url"):
        out["photo_url"] = rec["photo_url"]
    return out


def scrape(reparse: bool = False) -> list[Faculty]:
    records: list[Faculty] = []
    for dept in DEPARTMENTS:
        if reparse:
            # Reparse: pull page 1 from cache, infer total, pull 2..N from cache.
            base = dept["listing"]
            p1 = _load_cached(base, f"cde_{dept['slug']}")
            if not p1:
                print(f"[{dept['slug']}] no cache for page 1")
                continue
            pages = [p1]
            total = _total_pages(p1)
            for p in range(2, total + 1):
                h = _load_cached(_paged_url(base, p), f"cde_{dept['slug']}")
                if h:
                    pages.append(h)
        else:
            pages = _fetch_pages(dept)

        dept_records: list[dict] = []
        for html in pages:
            dept_records.extend(_parse_page(html, dept))
        # Dedup by profile_url within dept
        seen = set()
        unique: list[dict] = []
        for r in dept_records:
            key = r.get("profile_url") or r.get("name")
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)
        print(f"[{dept['slug']}] {len(unique)} faculty ({len(pages)} pages)")
        records.extend(_to_faculty(dept, r) for r in unique)
    return records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparse", action="store_true")
    args = ap.parse_args()
    records = scrape(reparse=args.reparse)
    out_path = OUT_DIR / "nus_cde.json"
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    with_photo = sum(1 for r in records if r.get("photo_url"))
    print(f"\nWrote {len(records)} records to {out_path}")
    print(f"  with photo: {with_photo}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
