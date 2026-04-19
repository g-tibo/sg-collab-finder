"""NUS Faculty of Dentistry — full academic staff directory.

The "Our People" page (dentistry.nus.edu.sg/faculty/our-people/) is a
WordPress/Elementor listing that groups staff into Faculty Board, Deanery,
Discipline, Postgrad, etc. Each card is an `<a href>` wrapping a
`.hr-item` with a short-form rank (Prof / A/P / Dr) — unreliable for our
primary-rank filter because "Dr" doesn't disambiguate Senior Lecturer
from Assistant Professor.

So we collect unique `/faculty/staff/<slug>/` URLs and fetch each profile
for the real "Appointment Status" block, which contains lines like
"Associate Professor, NUS Faculty of Dentistry". We pick the first
academic-rank line and feed it through the shared rank filter.

Usage:
    python -m scrapers.nus_dent            # full scrape
    python -m scrapers.nus_dent --reparse  # re-parse cached HTML only
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


BASE = "https://www.dentistry.nus.edu.sg"
LISTING = f"{BASE}/faculty/our-people/"

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "out"
CACHE_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

_KEEP_RANKS = {
    "assistant professor": "Assistant Professor",
    "associate professor": "Associate Professor",
    "professor": "Professor",
}
_SKIP_TOKENS = (
    "adjunct", "visiting", "emeritus", "honorary", "senior lecturer",
    "lecturer", "instructor",
)


def _cache_key(url: str, prefix: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"{prefix}_{h}.html"


def _load_cached(url: str, prefix: str, min_size: int = 20_000) -> str | None:
    p = _cache_key(url, prefix)
    if p.exists() and p.stat().st_size > min_size:
        return p.read_text(encoding="utf-8", errors="ignore")
    return None


def _save_cached(url: str, prefix: str, html: str) -> None:
    _cache_key(url, prefix).write_text(html, encoding="utf-8")


def _fetch(url: str, prefix: str, page=None) -> str:
    cached = _load_cached(url, prefix)
    if cached:
        return cached
    close = False
    if page is None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        b = pw.chromium.launch(headless=True)
        page = b.new_context().new_page()
        close = True
    try:
        for attempt in range(3):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1_500)
                html = page.content()
                if len(html) > 20_000:
                    _save_cached(url, prefix, html)
                    return html
            except Exception as e:
                print(f"  ! {url} attempt {attempt+1}: {e}")
            time.sleep(1 + attempt)
        return ""
    finally:
        if close:
            b.close()
            pw.stop()


def _collect_profile_urls(listing_html: str) -> list[str]:
    urls = set(re.findall(r'href="(https://www\.dentistry\.nus\.edu\.sg/faculty/staff/[^"]+)"',
                          listing_html))
    return sorted(u.rstrip("/") + "/" for u in urls)


_DESIG_SEP = re.compile(r"\s*,\s*")


def _parse_profile(html: str, url: str) -> dict | None:
    """Return {name, rank, title, roles, photo_url} or None if excluded."""
    s = BeautifulSoup(html, "html.parser")
    # Profile pages don't render an h1 — the staff name lives in <title>
    # as "Full Name - HR".
    raw_title = clean_text(s.title.string) if s.title else ""
    name = re.sub(r"\s*[-|]\s*HR\s*$", "", raw_title).strip()
    if not name:
        return None

    # Appointment Status block is a plain-text accordion body. Flatten
    # the whole body text and scan for the section.
    body_text = s.get_text("\n", strip=True)
    i = body_text.find("Appointment Status")
    if i < 0:
        return None
    # Stop at the next section heading. Common next headings on these
    # profiles: Research Group, Research Interests, Appointments and
    # Membership, Qualifications, Other Interests, Publications.
    stop = re.search(
        r"\n(Research Group|Research Interests|Appointments and Membership|"
        r"Qualifications|Other Interests|Publications|Teaching)",
        body_text[i:], re.I,
    )
    block = body_text[i : i + (stop.start() if stop else 2000)]
    lines = [ln.strip() for ln in block.split("\n")[1:] if ln.strip()]

    rank: str | None = None
    rank_line: str = ""
    for ln in lines:
        low = ln.lower()
        # Skip rows carrying a non-research title (Senior Lecturer,
        # Instructor, Adjunct, ...) even if "Professor" also appears.
        if any(tok in low for tok in _SKIP_TOKENS):
            continue
        for key, canon in sorted(_KEEP_RANKS.items(), key=lambda kv: -len(kv[0])):
            if key in low:
                rank = canon
                rank_line = ln
                break
        if rank:
            break
    if not rank:
        return None

    # roles: keep all Appointment Status lines as context.
    roles = [ln for ln in lines if ln]

    # photo: the first <img> after the h1, skipping logos.
    photo = ""
    for img in s.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:"):
            continue
        if "logo" in src.lower() or "icon" in src.lower():
            continue
        if "/uploads/" in src:
            photo = src
            break

    return {
        "name": _normalize_name(name),
        "rank": rank,
        "title": rank_line,
        "roles": roles,
        "profile_url": url,
        "photo_url": photo,
    }


def _normalize_name(raw: str) -> str:
    parts = raw.split()
    out: list[str] = []
    for p in parts:
        letters = [c for c in p if c.isalpha()]
        if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.6 and len(letters) > 1:
            p = p.title()
        out.append(p)
    return " ".join(out)


def _to_faculty(rec: dict) -> Faculty:
    out: Faculty = {
        "id": slugify("nus", "dent", rec["name"]),
        "name": rec["name"],
        "institution": "NUS",
        "department": "Faculty of Dentistry",
        "profile_url": rec["profile_url"],
        "title": rec["rank"],
    }
    if rec["roles"]:
        out["roles"] = rec["roles"]
    if rec["photo_url"]:
        out["photo_url"] = rec["photo_url"]
    return out


def scrape(reparse: bool = False) -> list[Faculty]:
    from playwright.sync_api import sync_playwright
    if reparse:
        listing_html = _load_cached(LISTING, "dent") or ""
        if not listing_html:
            print("no cached listing; run without --reparse first")
            return []
        urls = _collect_profile_urls(listing_html)
        out: list[Faculty] = []
        for u in urls:
            html = _load_cached(u, "dent") or ""
            if not html:
                continue
            rec = _parse_profile(html, u)
            if rec:
                out.append(_to_faculty(rec))
        print(f"[reparse] {len(out)} faculty from {len(urls)} profile URLs")
        return out

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_context().new_page()
        print("fetching listing...")
        listing_html = _fetch(LISTING, "dent", page)
        urls = _collect_profile_urls(listing_html)
        print(f"found {len(urls)} unique profile URLs")
        out: list[Faculty] = []
        for i, u in enumerate(urls, 1):
            html = _fetch(u, "dent", page)
            if not html:
                continue
            rec = _parse_profile(html, u)
            if rec:
                out.append(_to_faculty(rec))
            if i % 20 == 0:
                print(f"  [{i}/{len(urls)}] kept {len(out)}")
        b.close()
    print(f"kept {len(out)} / {len(urls)}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparse", action="store_true")
    args = ap.parse_args()
    records = scrape(reparse=args.reparse)
    out_path = OUT_DIR / "nus_dent.json"
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    with_photo = sum(1 for r in records if r.get("photo_url"))
    print(f"\nWrote {len(records)} records to {out_path}")
    print(f"  with photo: {with_photo}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
