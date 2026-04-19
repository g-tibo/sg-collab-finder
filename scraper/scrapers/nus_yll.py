"""NUS Yong Loo Lin School of Medicine (YLL) — 19 departments.

Like NUS DBS, medicine.nus.edu.sg sits behind Imperva/Incapsula bot
protection, so plain `requests` receives a 1KB challenge shell instead of
real HTML. We use Playwright (headful Chromium) to render every page and
cache the HTML to `scraper/cache/` so re-parses are free.

Two-stage scrape:

1. Department listing pages (19 URLs) -> faculty cards
   Each card is `div.col-md-3.sol-item` containing:
     <a href="/{dept}/faculty/<slug>/"><img .../></a>
     <div class="box-info">
       <h3>Name</h3>
       <p>Title line 1<br>Title line 2<br></p>
       <p>phone</p>
       <p><a href="mailto:...">email</a></p>

2. Individual profile pages -> Research Interest + biography text
   Each profile has a "### Research Interest" heading followed by paragraphs.

Usage:
    python -m scrapers.nus_yll            # full scrape (Playwright)
    python -m scrapers.nus_yll --reparse  # re-parse cached HTML only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup

from schema import Faculty, clean_text, slugify


BASE = "https://medicine.nus.edu.sg"

# Department slug -> full display name. YLL departments each use slightly
# different WordPress templates and listing URL paths, so we enable them
# incrementally as we verify the parser works end-to-end. See DEPARTMENTS_TODO
# below for the remaining ones.
DEPARTMENTS: list[tuple[str, str]] = [
    ("bch", "Department of Biochemistry"),
]

# Not yet wired up — each needs its own listing URL + parser verification:
#   nursing (Alice Lee Centre for Nursing Studies)
#   anaesthesia, ant, meddnr, medi, mbio, obgyn, medoph, os, ent, paed,
#   patho (uses /our-people/academic-staff/, circle-class cards),
#   medphc, phys, pcm, medsur.

LISTING_PATH = "/{slug}/faculty_category/academic-faculty/"


# --------------------------------------------------------------------------- #
# Cache helpers
# --------------------------------------------------------------------------- #

CACHE_DIR = Path(__file__).resolve().parents[1] / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _cache_file_for(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"yll_{h}.html"


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def _parse_listing(dept_slug: str, dept_name: str, html: str) -> list[dict]:
    """Parse a department listing page into stub records keyed by profile URL."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    seen: set[str] = set()
    for card in soup.select("div.col-md-3.sol-item"):
        link = card.find("a", href=re.compile(rf"/{dept_slug}/faculty/"))
        if not link:
            continue
        profile_url = link.get("href", "")
        if not profile_url.startswith("http"):
            profile_url = BASE + profile_url
        if profile_url in seen:
            continue
        seen.add(profile_url)

        info = card.select_one(".box-info")
        name = ""
        title_lines: list[str] = []
        email = ""
        if info:
            h = info.find("h3")
            if h:
                name = clean_text(h.get_text(" ", strip=True))
            # First <p> is title (may have <br>-separated lines).
            ps = info.find_all("p")
            if ps:
                work = BeautifulSoup(str(ps[0]), "lxml")
                for br in work.find_all("br"):
                    br.replace_with("\n")
                title_lines = [
                    clean_text(ln)
                    for ln in work.get_text("\n").split("\n")
                    if clean_text(ln)
                ]
            # Find email across all <p>s.
            for p in ps:
                a = p.find("a", href=re.compile(r"^mailto:"))
                if a:
                    email = clean_text(a.get_text(" ", strip=True))
                    break

        photo_url = ""
        img = card.find("img")
        if img and img.get("src"):
            photo_url = img["src"]
            if not photo_url.startswith("http"):
                photo_url = BASE + photo_url

        if not name:
            continue

        title = title_lines[0] if title_lines else ""
        # Short title: up to the first comma.
        short_title = title.split(",")[0].strip()
        roles = title_lines[1:] if len(title_lines) > 1 else []

        out.append({
            "id": slugify("nus", "yll", dept_slug, name),
            "name": name,
            "institution": "NUS",
            "department": f"Yong Loo Lin School of Medicine — {dept_name}",
            "title": short_title,
            "roles": roles,
            "research_areas": [],
            "summary": "",
            "email": email,
            "profile_url": profile_url,
            "photo_url": photo_url,
        })
    return out


# Headings that mark where the research section starts / stops.
_RESEARCH_HEADING_RE = re.compile(
    r"^(?:"
    r"(?:Main\s+|Major\s+|Current\s+)?Research\s+Interests?"
    r"|Research\s+Areas?|Research\s+Focus|Research\s+Description|Research"
    r")\s*:?\s*$",
    re.I,
)
_STOP_HEADING_RE = re.compile(
    r"^(?:Publications?|Selected\s+Publications?|Recent\s+Publications?|Teaching"
    r"|Awards|Honou?rs?|Grants?|Contact|Education|Training|Affiliations?"
    r"|Professional\s+Experience|Qualifications|Academic\s+Qualifications"
    r"|Appointments?|Career|Biography|About|Memberships?|Editorial)",
    re.I,
)


def _enrich_profile(rec: dict, html: str) -> None:
    """Extract research summary + areas from a profile page and merge into rec."""
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()

    paras: list[str] = []
    subs: list[str] = []
    for h in soup.find_all(["h2", "h3", "h4"]):
        htxt = clean_text(h.get_text(" ", strip=True))
        if not _RESEARCH_HEADING_RE.match(htxt):
            continue
        h_lvl = int(h.name[1])
        for sib in h.find_all_next():
            if sib.name in ("h1", "h2", "h3", "h4") and sib is not h:
                sib_text = clean_text(sib.get_text(" ", strip=True))
                if int(sib.name[1]) <= h_lvl:
                    break
                if _STOP_HEADING_RE.match(sib_text):
                    break
                if sib.name == "h4" and sib_text and len(sib_text) < 100:
                    subs.append(re.sub(r"^\(?\d+\)?[\.\s]+", "", sib_text).rstrip(":"))
            elif sib.name in ("p", "li"):
                t = clean_text(sib.get_text(" ", strip=True))
                if t:
                    paras.append(t)
        break

    if paras:
        rec["summary"] = "\n\n".join(paras[:4])[:2000]
    if subs:
        rec["research_areas"] = subs[:8]

    # Some YLL profiles format the Research Interest as a bulleted list that
    # lxml flattens into one paragraph: "* Topic A. * Topic B. * Topic C."
    # Split those on the bullet marker to recover research_areas.
    if not rec.get("research_areas") and paras:
        first = paras[0]
        if first.count("* ") >= 2 or first.count("• ") >= 2:
            parts = re.split(r"\s*[*•]\s+", first)
            items = [clean_text(p).rstrip(".") for p in parts if clean_text(p)]
            items = [i for i in items if 3 <= len(i) <= 120]
            if len(items) >= 2:
                rec["research_areas"] = items[:8]

    # Better photo: profile page may have a higher-res headshot.
    if not rec.get("photo_url"):
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "/wp-content/uploads/" not in src:
                continue
            fn = src.rsplit("/", 1)[-1].lower()
            if any(b in fn for b in ("logo", "banner", "header", "footer", "icon", "nav")):
                continue
            rec["photo_url"] = src if src.startswith("http") else BASE + src
            break


# --------------------------------------------------------------------------- #
# Playwright driver
# --------------------------------------------------------------------------- #


def _is_real_page(html: str) -> bool:
    """Heuristic: an Incapsula challenge shell is ~200-1000 bytes. A real YLL
    page is tens of KB. Treat anything under 5 KB as a failed fetch."""
    return len(html) > 5000


def _fetch_playwright(urls: list[str], *, headless: bool, max_attempts: int = 3) -> None:
    """Fetch each URL via Playwright and write to the shared disk cache.
    Skips URLs already cached with a real (non-challenge) page. Retries
    challenge-shell responses up to `max_attempts` times."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run:")
        print("  pip install playwright && playwright install chromium")
        sys.exit(1)

    def needs_fetch(u: str) -> bool:
        p = _cache_file_for(u)
        if not p.exists():
            return True
        try:
            return not _is_real_page(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return True

    todo = [u for u in urls if needs_fetch(u)]
    print(f"[nus_yll] {len(todo)}/{len(urls)} URLs to fetch ({len(urls)-len(todo)} cached)")
    if not todo:
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-SG",
        )
        page = ctx.new_page()
        # Warmup: hit the BCH listing first so Incapsula issues its session
        # cookie. Subsequent requests in this context reuse it and are much
        # less likely to be challenged.
        try:
            page.goto(f"{BASE}/bch/faculty_category/academic-faculty/",
                      wait_until="load", timeout=60_000)
            page.wait_for_timeout(3_000)
        except Exception as e:
            print(f"  warmup failed: {e}")

        for i, url in enumerate(todo, 1):
            html = ""
            for attempt in range(1, max_attempts + 1):
                try:
                    page.goto(url, wait_until="load", timeout=60_000)
                    # Give Incapsula time to clear the challenge iframe and
                    # Sitefinity time to render the page body.
                    page.wait_for_timeout(4_000)
                    try:
                        page.wait_for_selector(
                            "div.col-md-3.sol-item, h3, .box-info, article, main",
                            timeout=15_000,
                            state="attached",
                        )
                    except Exception:
                        pass
                    page.wait_for_timeout(1_500)
                    html = page.content()
                    if _is_real_page(html):
                        _cache_file_for(url).write_text(html, encoding="utf-8")
                        print(f"  [{i:3}/{len(todo)}] cached {url} ({len(html)//1024}KB)")
                        break
                    print(f"  [{i:3}/{len(todo)}] attempt {attempt} challenged ({len(html)}B) {url}")
                    page.wait_for_timeout(3_000)
                except Exception as e:
                    print(f"  [{i:3}/{len(todo)}] attempt {attempt} FAIL {url}: {e}")
                    page.wait_for_timeout(2_000)
            else:
                # All attempts exhausted. Keep whatever last body we saw so
                # we don't retry infinitely on a permanently blocked URL.
                _cache_file_for(url).write_text(html, encoding="utf-8")
            time.sleep(0.5)
        browser.close()


def _read_cached(url: str) -> str | None:
    f = _cache_file_for(url)
    if not f.exists():
        return None
    return f.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Main orchestration
# --------------------------------------------------------------------------- #


def scrape(*, reparse_only: bool = False, headless: bool = False) -> list[Faculty]:
    listing_urls = [BASE + LISTING_PATH.format(slug=slug) for slug, _ in DEPARTMENTS]

    # Stage 1: listing pages.
    if not reparse_only:
        _fetch_playwright(listing_urls, headless=headless)

    all_records: list[dict] = []
    for (slug, name), url in zip(DEPARTMENTS, listing_urls):
        html = _read_cached(url)
        if not html:
            print(f"[nus_yll] listing not cached for {slug} — skipping")
            continue
        recs = _parse_listing(slug, name, html)
        print(f"[nus_yll] {slug}: {len(recs)} faculty")
        all_records.extend(recs)

    # De-dup by profile URL (someone may be joint across departments).
    by_url: dict[str, dict] = {}
    for r in all_records:
        by_url.setdefault(r["profile_url"], r)
    all_records = list(by_url.values())
    print(f"[nus_yll] {len(all_records)} unique faculty after URL dedup")

    # Stage 2: profile pages.
    profile_urls = [r["profile_url"] for r in all_records]
    if not reparse_only:
        _fetch_playwright(profile_urls, headless=headless)

    enriched = 0
    for r in all_records:
        html = _read_cached(r["profile_url"])
        if not html:
            continue
        _enrich_profile(r, html)
        if r.get("summary") or r.get("research_areas"):
            enriched += 1
    print(f"[nus_yll] enriched {enriched}/{len(all_records)} with research text")

    return all_records  # type: ignore[return-value]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparse", action="store_true",
                    help="Skip network; re-parse cached HTML only")
    ap.add_argument("--headless", action="store_true",
                    help="Run Chromium headless (default: headful, more reliable vs Incapsula)")
    args = ap.parse_args()

    headless = args.headless or os.environ.get("HEADLESS", "0") == "1"
    records = scrape(reparse_only=args.reparse, headless=headless)

    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "nus_yll.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[nus_yll] wrote {len(records)} records")


if __name__ == "__main__":
    main()
