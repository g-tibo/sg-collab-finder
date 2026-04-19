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

# YLL department configuration. Each entry lists one or more listing URLs
# because some departments split faculty across sub-pages (e.g. Nursing by rank,
# Physiology by track, Psych Med by role). Profile URLs are discovered by
# taking the first <a> in each .sol-item card, so we don't need a per-dept
# href filter — we just trust that anchor points to an individual profile.
#
# Legacy-static subsites (anaesthesia, ant, meddnr, medi, mbio, obgyn, medoph,
# os, paed, ent, medsur) use bespoke pre-WordPress HTML — left for later.
DEPARTMENTS: list[dict] = [
    # "sol-item" layout: Sitefinity-style cards with link to a per-faculty page.
    {
        "slug": "bch", "layout": "sol-item",
        "name": "Department of Biochemistry",
        "listings": ["/bch/faculty_category/academic-faculty/"],
    },
    # "fl-photo" layout: Beaver Builder rows where an image module and a rich-
    # text module sit in the same fl-col. Profile URL is on the photo/name anchor.
    {
        "slug": "patho", "layout": "fl-photo",
        "name": "Department of Pathology",
        "listings": ["/patho/our-people/academic-staff/"],
    },
    # "uabb-infobox" layout: Ultimate Addons for Beaver Builder. Each card has
    # its own in-page modal with the full bio; no separate profile URL.
    {
        "slug": "medphc", "layout": "uabb-infobox",
        "name": "Department of Pharmacology",
        "listings": ["/medphc/about-us/academic-staff/"],
    },
    # "faculty-list-profile" layout: custom theme class. Name in h4, title and
    # email inline, profile URL on the h4 anchor.
    {
        "slug": "nursing", "layout": "faculty-list-profile",
        "name": "Alice Lee Centre for Nursing Studies",
        "listings": [
            "/nursing/our-people/our-faculty/leadership-teams-directors/",
            "/nursing/our-people/our-faculty/professors-associate-professors/",
            "/nursing/our-people/our-faculty/assistant-professors/",
            "/nursing/our-people/our-faculty/teaching-faculty/",
        ],
    },
    # "anchor-card" layout: bare <a><img><h3>Name</h3><p>Title</p></a>.
    {
        "slug": "phys", "layout": "anchor-card",
        "name": "Department of Physiology",
        "listings": ["/phys/about-us/academic-staff/"],
    },
]


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


def _make_record(dept_slug: str, dept_name: str, *, name: str, title_lines: list[str],
                 email: str, profile_url: str, photo_url: str) -> dict:
    title = title_lines[0] if title_lines else ""
    short_title = title.split(",")[0].strip()
    roles = title_lines[1:] if len(title_lines) > 1 else []
    return {
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
    }


def _absolutize(url: str) -> str:
    if not url:
        return ""
    return url if url.startswith("http") else BASE + url


def _br_lines(node) -> list[str]:
    """Split a BS4 node's text on <br>, returning cleaned non-empty lines."""
    work = BeautifulSoup(str(node), "lxml")
    for br in work.find_all("br"):
        br.replace_with("\n")
    return [clean_text(ln) for ln in work.get_text("\n").split("\n") if clean_text(ln)]


def _parse_listing_sol_item(dept_slug: str, dept_name: str, html: str) -> list[dict]:
    """Sitefinity-style `div.col-md-3.sol-item` cards (bch)."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    seen: set[str] = set()
    for card in soup.select("div.col-md-3.sol-item"):
        link = card.find("a", href=True)
        if not link:
            continue
        profile_url = link.get("href", "")
        # Skip anchors that just point to /{slug}/ or external sites — we want
        # profile-page links, which are deeper than the dept root.
        if f"/{dept_slug}/" not in profile_url:
            continue
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
            ps = info.find_all("p")
            if ps:
                title_lines = _br_lines(ps[0])
            for p in ps:
                a = p.find("a", href=re.compile(r"^mailto:"))
                if a:
                    email = clean_text(a.get_text(" ", strip=True))
                    break

        photo_url = ""
        img = card.find("img")
        if img and img.get("src"):
            photo_url = _absolutize(img["src"])

        if not name:
            continue
        out.append(_make_record(
            dept_slug, dept_name, name=name, title_lines=title_lines,
            email=email, profile_url=profile_url, photo_url=photo_url,
        ))
    return out


def _parse_listing_fl_photo(dept_slug: str, dept_name: str, html: str) -> list[dict]:
    """Beaver Builder: paired photo + rich-text modules per fl-col (patho)."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    seen: set[str] = set()
    for col in soup.select("div.fl-col"):
        photo = col.select_one("div.fl-photo")
        rt = col.select_one("div.fl-rich-text")
        if not photo or not rt:
            continue
        # First anchor with a non-empty href in the rich-text is the profile URL.
        profile_url = ""
        for a in rt.find_all("a", href=True):
            if a["href"].strip() and not a["href"].startswith("#"):
                profile_url = a["href"]
                break
        if not profile_url or f"/{dept_slug}/" not in profile_url:
            continue
        profile_url = _absolutize(profile_url)
        if profile_url in seen:
            continue
        seen.add(profile_url)

        p = rt.find("p")
        lines = _br_lines(p) if p else []
        if not lines:
            continue
        name = clean_text(lines[0])
        title_lines = lines[1:]

        photo_url = ""
        img = photo.find("img")
        if img and img.get("src"):
            photo_url = _absolutize(img["src"])

        out.append(_make_record(
            dept_slug, dept_name, name=name, title_lines=title_lines,
            email="", profile_url=profile_url, photo_url=photo_url,
        ))
    return out


def _parse_listing_uabb_infobox(dept_slug: str, dept_name: str, html: str) -> list[dict]:
    """Ultimate Addons infobox cards with on-page modals (medphc).

    No separate profile URL — research content lives in a `#modal-<id>` div
    elsewhere in the same HTML, linked via `data-modal` on a trigger <a>.
    We synthesize profile_url as BASE + listing + '#<data-modal>' so enrichment
    can rehydrate the modal from the same cached listing HTML."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    seen: set[str] = set()
    listing_url = f"{BASE}/{dept_slug}/about-us/academic-staff/"
    for card in soup.select("div.uabb-infobox"):
        name_el = card.select_one("p.uabb-infobox-title-prefix")
        if not name_el:
            continue
        name = clean_text(name_el.get_text(" ", strip=True))
        if not name:
            continue
        title_el = card.select_one("p.uabb-infobox-title")
        title_lines = [clean_text(title_el.get_text(" ", strip=True))] if title_el else []

        email = ""
        mail = card.select_one(".uabb-infobox-text a[href^='mailto:']")
        if mail:
            email = clean_text(mail.get_text(" ", strip=True))

        photo_url = ""
        img = card.select_one("img.uabb-photo-img, .uabb-image img")
        if img and img.get("src"):
            photo_url = _absolutize(img["src"])

        trigger = card.select_one("a.uabb-modal-action[data-modal]")
        modal_id = trigger["data-modal"] if trigger else ""
        profile_url = f"{listing_url}#{modal_id}" if modal_id else listing_url
        if profile_url in seen:
            continue
        seen.add(profile_url)

        out.append(_make_record(
            dept_slug, dept_name, name=name, title_lines=title_lines,
            email=email, profile_url=profile_url, photo_url=photo_url,
        ))
    return out


def _parse_listing_faculty_list_profile(dept_slug: str, dept_name: str, html: str) -> list[dict]:
    """Custom theme: div.faculty-list-profile cards (nursing)."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    seen: set[str] = set()
    for card in soup.select("div.faculty-list-profile"):
        detail = card.select_one(".faculty-list-profile-detail")
        if not detail:
            continue
        h = detail.find("h4")
        if not h:
            continue
        name = clean_text(h.get_text(" ", strip=True))
        if not name:
            continue
        link = h.find_parent("a", href=True) or detail.find("a", href=True)
        profile_url = ""
        if link and link.get("href"):
            profile_url = _absolutize(link["href"])
        if not profile_url or f"/{dept_slug}/" not in profile_url:
            continue
        if profile_url in seen:
            continue
        seen.add(profile_url)

        p = detail.find("p")
        title_lines = _br_lines(p) if p else []

        email = ""
        mail = detail.find("a", href=re.compile(r"^mailto:"))
        if mail:
            email = clean_text(mail.get_text(" ", strip=True))

        photo_url = ""
        thumb = card.select_one(".faculty-list-profile-thumbnail img")
        if thumb and thumb.get("src"):
            photo_url = _absolutize(thumb["src"])

        out.append(_make_record(
            dept_slug, dept_name, name=name, title_lines=title_lines,
            email=email, profile_url=profile_url, photo_url=photo_url,
        ))
    return out


def _parse_listing_anchor_card(dept_slug: str, dept_name: str, html: str) -> list[dict]:
    """Simple <a href=profile><img><h3>Name</h3><p>Title</p></a> cards (phys)."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    seen: set[str] = set()
    # Anchors that wrap both an img and an h3 are almost certainly faculty cards.
    for a in soup.find_all("a", href=True):
        h = a.find("h3")
        if not h:
            continue
        if not a.find("img"):
            continue
        profile_url = a["href"].strip()
        if not profile_url or f"/{dept_slug}/" not in profile_url:
            continue
        profile_url = _absolutize(profile_url)
        if profile_url in seen:
            continue
        seen.add(profile_url)

        name = clean_text(h.get_text(" ", strip=True))
        if not name:
            continue
        p = a.find("p")
        title_lines = _br_lines(p) if p else []

        photo_url = ""
        img = a.find("img")
        if img and img.get("src"):
            photo_url = _absolutize(img["src"])

        out.append(_make_record(
            dept_slug, dept_name, name=name, title_lines=title_lines,
            email="", profile_url=profile_url, photo_url=photo_url,
        ))
    return out


_LAYOUT_PARSERS = {
    "sol-item": _parse_listing_sol_item,
    "fl-photo": _parse_listing_fl_photo,
    "uabb-infobox": _parse_listing_uabb_infobox,
    "faculty-list-profile": _parse_listing_faculty_list_profile,
    "anchor-card": _parse_listing_anchor_card,
}


def _parse_listing(dept_slug: str, dept_name: str, html: str, layout: str) -> list[dict]:
    fn = _LAYOUT_PARSERS.get(layout)
    if not fn:
        print(f"[nus_yll] unknown layout {layout!r} for {dept_slug}")
        return []
    return fn(dept_slug, dept_name, html)


# Headings that mark where the research section starts / stops.
_RESEARCH_HEADING_RE = re.compile(
    r"^(?:"
    r"(?:Main\s+|Major\s+|Current\s+)?Research\s+Interests?"
    r"|Research\s+Areas?(?:\s+of\s+Interest)?"
    r"|Research\s+Focus|Research\s+Description|Research"
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


def _enrich_from_modal(rec: dict, listing_html: str, modal_id: str) -> None:
    """Pull Research Interests out of an UABB modal embedded in listing HTML."""
    if not modal_id:
        return
    soup = BeautifulSoup(listing_html, "lxml")
    modal = soup.find(id=modal_id)
    if not modal:
        return
    for s in modal(["script", "style", "noscript"]):
        s.decompose()

    # Find "Research Interests" heading (h2/h3/h4/strong/p) then collect
    # following paragraphs and list items until the next top-level heading.
    paras: list[str] = []
    subs: list[str] = []
    headings = modal.find_all(["h1", "h2", "h3", "h4", "strong", "b"])
    for h in headings:
        htxt = clean_text(h.get_text(" ", strip=True))
        if not _RESEARCH_HEADING_RE.match(htxt):
            continue
        # Walk siblings of the heading's enclosing paragraph/container.
        start = h if h.name in ("h1", "h2", "h3", "h4") else h.parent
        for sib in start.find_all_next():
            if sib.name in ("h1", "h2", "h3", "h4"):
                sib_text = clean_text(sib.get_text(" ", strip=True))
                if _STOP_HEADING_RE.match(sib_text):
                    break
            elif sib.name in ("p", "li"):
                t = clean_text(sib.get_text(" ", strip=True))
                if t:
                    paras.append(t)
            if len(paras) > 12:
                break
        break

    if paras:
        rec["summary"] = "\n\n".join(paras[:4])[:2000]
    # Bullet-list fallback for "* A. * B." flattened text.
    if paras and not subs:
        first = paras[0]
        if first.count("* ") >= 2 or first.count("• ") >= 2:
            parts = re.split(r"\s*[*•]\s+", first)
            items = [clean_text(p).rstrip(".") for p in parts if clean_text(p)]
            items = [i for i in items if 3 <= len(i) <= 120]
            if len(items) >= 2:
                subs = items[:8]
    # If collected paras were short list items, use them as research_areas.
    if not subs and paras:
        short = [p.rstrip(".") for p in paras if 3 <= len(p) <= 120]
        if len(short) >= 2:
            subs = short[:8]
    if subs:
        rec["research_areas"] = subs


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

        # Track per-dept warmup so we only hit each listing once.
        warmed: set[str] = set()

        def dept_prefix(u: str) -> str:
            # e.g. "/phys/" from https://medicine.nus.edu.sg/phys/about-us/...
            m = re.match(r"https?://[^/]+/([^/]+)/", u)
            return m.group(1) if m else ""

        for i, url in enumerate(todo, 1):
            html = ""
            # Per-dept warmup: if this is our first profile fetch for a given
            # subsite, hit that subsite's listing first so Incapsula gives us
            # a scoped session cookie. Without this, phys profiles get stuck
            # in a challenge loop even though the listing fetched fine.
            slug = dept_prefix(url)
            if slug and slug not in warmed:
                warmed.add(slug)
                # Use the listing we already know about: /<slug>/ root.
                warm_url = f"{BASE}/{slug}/"
                try:
                    page.goto(warm_url, wait_until="load", timeout=45_000)
                    page.wait_for_timeout(3_000)
                except Exception:
                    pass
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
    listing_urls: list[tuple[str, str, str, str]] = []  # (slug, dept_name, url, layout)
    for dept in DEPARTMENTS:
        for path in dept["listings"]:
            listing_urls.append((dept["slug"], dept["name"], BASE + path, dept["layout"]))

    # Stage 1: listing pages.
    if not reparse_only:
        _fetch_playwright([u for _, _, u, _ in listing_urls], headless=headless)

    all_records: list[dict] = []
    by_dept: dict[str, int] = {}
    # For uabb-infobox depts, remember the listing HTML so we can pull modal
    # content during enrichment (profile_url is an in-page fragment).
    modal_source_html: dict[str, str] = {}
    for slug, name, url, layout in listing_urls:
        html = _read_cached(url)
        if not html:
            print(f"[nus_yll] listing not cached for {slug} {url} — skipping")
            continue
        recs = _parse_listing(slug, name, html, layout)
        by_dept[slug] = by_dept.get(slug, 0) + len(recs)
        all_records.extend(recs)
        if layout == "uabb-infobox":
            modal_source_html[url] = html
    for slug, n in by_dept.items():
        print(f"[nus_yll] {slug}: {n} faculty")

    # De-dup by profile URL (someone may be joint across departments).
    by_url: dict[str, dict] = {}
    for r in all_records:
        by_url.setdefault(r["profile_url"], r)
    all_records = list(by_url.values())
    print(f"[nus_yll] {len(all_records)} unique faculty after URL dedup")

    # Stage 2: profile pages. Skip uabb-infobox records (modal content is in
    # the already-cached listing HTML, not a separate URL).
    profile_urls = [
        r["profile_url"] for r in all_records if "#" not in r["profile_url"]
    ]
    if not reparse_only:
        _fetch_playwright(profile_urls, headless=headless)

    enriched = 0
    for r in all_records:
        url = r["profile_url"]
        if "#" in url:
            listing_url, _, modal_id = url.partition("#")
            src = modal_source_html.get(listing_url)
            if src:
                _enrich_from_modal(r, src, modal_id)
        else:
            html = _read_cached(url)
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
