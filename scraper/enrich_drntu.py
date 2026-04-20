"""Enrich faculty records with research interests + biography from DR-NTU.

DR-NTU (dr.ntu.edu.sg) runs DSpace-CRIS and exposes each NTU researcher at
a predictable slug:

    https://dr.ntu.edu.sg/entities/person/<Last-First-Middle>

The page renders a "Keywords" block followed by "Biography" — both are
plain text. We fetch via Playwright (page is JS-rendered), cache the HTML,
and copy keywords into `research_areas` + biography into `summary` for any
record that's missing either field.

Usage:
    python enrich_drntu.py ntu_cceb.json
    python enrich_drntu.py ntu_cceb.json ntu_sbs.json ...
    python enrich_drntu.py --reparse ntu_cceb.json   # cache-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "out"
CACHE_DIR.mkdir(exist_ok=True)

BASE = "https://dr.ntu.edu.sg/entities/person/"

# Section headings that terminate the Biography text. We stop scanning at
# whichever comes first.
_STOP_HEADINGS = (
    "Research Interests", "Current Grants", "Teaching", "News", "Contact Us",
    "Publications", "Fellowships & Other Recognition", "Fellowships",
)


def _cache_key(slug: str) -> Path:
    h = hashlib.sha256(slug.encode()).hexdigest()[:24]
    return CACHE_DIR / f"drntu_{h}.html"


def _load_cached(slug: str, min_size: int = 50_000) -> str | None:
    p = _cache_key(slug)
    if p.exists() and p.stat().st_size > min_size:
        return p.read_text(encoding="utf-8", errors="ignore")
    return None


def _save_cached(slug: str, html: str) -> None:
    _cache_key(slug).write_text(html, encoding="utf-8")


def _name_to_slug(name: str) -> str:
    """`Bansal Mukta` -> `Bansal-Mukta`, `Chew Sing Yian` -> `Chew-Sing-Yian`.
    Strips accents, parenthesized content, commas, and dots."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"\([^)]*\)", " ", s)      # drop Chinese chars / aliases
    s = re.sub(r"[,.]", " ", s)            # drop commas, dots (e.g. "Chan Park B., Mary")
    s = re.sub(r"\s+", " ", s).strip()
    parts = [p for p in s.split(" ") if p]
    return "-".join(parts)


def _extract(html: str) -> tuple[list[str], str]:
    """Return (keywords, biography) from a DR-NTU entities page."""
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    text = soup.get_text("\n", strip=True)

    keywords: list[str] = []
    m = re.search(r"\bKeywords\b\s*\n(.+?)(?:\n(?:Biography|Research Interests|Current Grants|Teaching|News|Contact Us|Publications)\b)",
                  text, re.S)
    if m:
        for line in m.group(1).split("\n"):
            line = line.strip()
            if line and len(line) < 120:
                keywords.append(line)

    bio = ""
    b = re.search(r"\bBiography\b\s*\n(.+?)(?=\n(?:" + "|".join(_STOP_HEADINGS) + r")\b)",
                  text, re.S)
    if b:
        bio = re.sub(r"\s+", " ", b.group(1)).strip()

    return keywords, bio


def _try_slug(slug: str, page) -> str | None:
    """Fetch `BASE + slug`. Returns HTML if the profile resolved (200 + has
    Keywords/Biography chrome), else None."""
    cached = _load_cached(slug)
    if cached is not None:
        return cached
    url = BASE + slug
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=40_000)
        if resp and resp.status == 404:
            return None
        page.wait_for_timeout(1_500)
        html = page.content()
        # DSpace 404s still render chrome — detect by absence of data.
        if "Keywords" not in html and "Biography" not in html:
            return None
        _save_cached(slug, html)
        return html
    except Exception as e:
        print(f"  ! {slug}: {e}")
        return None


def _search_slug(name: str, page) -> str | None:
    """Fallback: DR-NTU full-site search, return first /entities/person/<id>."""
    from urllib.parse import quote
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    ascii_name = re.sub(r"[(),.]", " ", ascii_name)
    # Drop single-letter tokens (middle initials like "T." or "B."); they
    # over-constrain DR-NTU's search and return zero hits.
    toks = [t for t in ascii_name.split() if len(t) > 1]
    q = "+".join(toks)
    if not q:
        return None
    try:
        page.goto(f"https://dr.ntu.edu.sg/search?query={quote(q, safe='+')}",
                  wait_until="domcontentloaded", timeout=40_000)
        page.wait_for_timeout(2_500)
        html = page.content()
    except Exception as e:
        print(f"  ! search {name}: {e}")
        return None
    ids = re.findall(r"/entities/person/([A-Za-z0-9\-]+)", html)
    # Deduplicate in order; pick the first.
    seen: list[str] = []
    for x in ids:
        if x not in seen:
            seen.append(x)
    return seen[0] if seen else None


def _fetch(name: str, page) -> str | None:
    """Try: (1) name-as-is slug, (2) reversed-token slug, (3) search fallback."""
    slug = _name_to_slug(name)
    html = _try_slug(slug, page)
    if html:
        return html
    toks = slug.split("-")
    if len(toks) >= 2:
        rev = "-".join(reversed(toks))
        html = _try_slug(rev, page)
        if html:
            return html
    # Search fallback returns a UUID-style slug.
    found = _search_slug(name, page)
    if found and found not in (slug, "-".join(reversed(toks)) if len(toks) >= 2 else ""):
        html = _try_slug(found, page)
        if html:
            return html
    return None


def _needs_enrichment(rec: dict) -> bool:
    return not rec.get("summary") or not rec.get("research_areas")


def enrich_file(path: Path, reparse: bool = False) -> None:
    records = json.loads(path.read_text(encoding="utf-8"))
    targets = [r for r in records if _needs_enrichment(r)]
    print(f"{path.name}: {len(targets)}/{len(records)} need enrichment")
    if not targets:
        return

    from playwright.sync_api import sync_playwright
    updated = 0
    missed: list[str] = []
    if reparse:
        page = None
        for rec in targets:
            slug = _name_to_slug(rec["name"])
            html = _load_cached(slug)
            if not html:
                missed.append(rec["name"])
                continue
            kw, bio = _extract(html)
            touched = False
            if kw and not rec.get("research_areas"):
                rec["research_areas"] = kw
                touched = True
            if bio and not rec.get("summary"):
                rec["summary"] = bio
                touched = True
            if touched:
                updated += 1
    else:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            page = b.new_context().new_page()
            for i, rec in enumerate(targets, 1):
                html = _fetch(rec["name"], page)
                if not html:
                    missed.append(rec["name"])
                    continue
                kw, bio = _extract(html)
                if not kw and not bio:
                    missed.append(rec["name"])
                    continue
                touched = False
                if kw and not rec.get("research_areas"):
                    rec["research_areas"] = kw
                    touched = True
                if bio and not rec.get("summary"):
                    rec["summary"] = bio
                    touched = True
                if touched:
                    updated += 1
                if i % 10 == 0:
                    print(f"  [{i}/{len(targets)}] updated {updated}")
            b.close()

    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  updated {updated}/{len(targets)}; missed {len(missed)}")
    for name in missed:
        print(f"    - {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="JSON filenames under scraper/out/")
    ap.add_argument("--reparse", action="store_true")
    args = ap.parse_args()
    for f in args.files:
        p = OUT_DIR / f
        if not p.exists():
            print(f"missing: {p}")
            continue
        enrich_file(p, reparse=args.reparse)


if __name__ == "__main__":
    main()
