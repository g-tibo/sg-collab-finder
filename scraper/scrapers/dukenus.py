"""Duke-NUS Medical School — full faculty directory.

www.duke-nus.edu.sg sits behind Imperva/Incapsula, so plain requests get a
challenge shell. The directory is a Telerik ASP.NET WebForms app, but it
exposes an internal JSON API for pagination:

    GET /directory/GetAllPemRevamp2024/{search}/{category}/{page}/{sort}
        -> { TotalPage, PemStaffInfoModels: [ {Full_Name, Url, Email,
             Position_Title, Lab_Section_Team, Employment_Status,
             ToDisplay, CategoryList, Photo (base64), ...}, ... ] }

Directly curling this endpoint returns Incapsula HTML. Calling it from
inside Playwright via page.evaluate(async () => fetch(...)) bypasses the
challenge (the browser holds the session cookie).

The list API returns rich metadata but leaves Bio/Research as null for
many staff. So stage 2 fetches each staff's profile page and extracts the
Bio block, which is delimited by <!-- BIO -->...<!-- END BIO -->.

Photos in the JSON are base64 data URIs (bloated); we drop them and let
the UI fall back to institution logo.

Usage:
    python -m scrapers.dukenus            # full scrape
    python -m scrapers.dukenus --reparse  # re-parse cached HTML only
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup

from schema import Faculty, clean_text, slugify


BASE = "https://www.duke-nus.edu.sg"
DIRECTORY_URL = f"{BASE}/directory"

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "out"
CACHE_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

# Photos are delivered as base64 data URIs in the list JSON — we decode
# them to individual JPEGs under web/public/photos/dukenus/ so the JSON
# stays small and the browser can cache the images.
PHOTOS_DIR = ROOT.parent / "web" / "public" / "photos" / "dukenus"

INDEX_PATH = CACHE_DIR / "dukenus_index.json"


# --------------------------------------------------------------------------- #
# cache helpers
# --------------------------------------------------------------------------- #

def _cache_key(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"dukenus_{h}.html"


def _load_cached(url: str) -> str | None:
    p = _cache_key(url)
    if p.exists() and p.stat().st_size > 5_000:
        return p.read_text(encoding="utf-8", errors="ignore")
    return None


def _save_cached(url: str, html: str) -> None:
    _cache_key(url).write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------- #
# stage 1: list API
# --------------------------------------------------------------------------- #

def _fetch_all_staff(page) -> list[dict]:
    """Page through the JSON API, collect all PemStaffInfoModels."""
    all_items: list[dict] = []
    total_pages = None
    pg = 1
    while True:
        data = page.evaluate(
            f"""async () => {{
              const r = await fetch('/directory/GetAllPemRevamp2024/null/null/{pg}/aToz', {{
                headers: {{'X-Requested-With': 'XMLHttpRequest'}}
              }});
              if (r.status !== 200) return {{ err: r.status }};
              const ct = r.headers.get('content-type') || '';
              if (!ct.includes('json')) return {{ err: 'not json' }};
              return await r.json();
            }}"""
        )
        if "err" in data:
            print(f"  page {pg}: retry ({data['err']})")
            time.sleep(2)
            continue
        items = data.get("PemStaffInfoModels", [])
        all_items.extend(items)
        total_pages = data.get("TotalPage", 0)
        print(f"  page {pg}/{total_pages}: +{len(items)} (total {len(all_items)})")
        if pg >= total_pages:
            break
        pg += 1
    return all_items


# --------------------------------------------------------------------------- #
# stage 2: profile HTML -> Bio / Research
# --------------------------------------------------------------------------- #

_BIO_RE = re.compile(r"<!--\s*BIO\s*-->(.*?)<!--\s*END\s+BIO\s*-->", re.S | re.I)
_RESEARCH_RE = re.compile(
    r"<!--\s*RESEARCH(?:\s+[A-Z\s]*)?\s*-->(.*?)<!--\s*END\s+RESEARCH[^>]*-->",
    re.S | re.I,
)


def _extract_section(html: str, pattern: re.Pattern) -> str:
    m = pattern.search(html)
    if not m:
        return ""
    inner = m.group(1)
    # Strip the leading <h2 class="main-title">...</h2> heading.
    inner = re.sub(r'<h2[^>]*class="main-title"[^>]*>.*?</h2>', "", inner, count=1, flags=re.S | re.I)
    soup = BeautifulSoup(inner, "html.parser")
    return clean_text(soup.get_text(" ", strip=True))


def _extract_bio(html: str) -> str:
    return _extract_section(html, _BIO_RE)


def _extract_research(html: str) -> str:
    return _extract_section(html, _RESEARCH_RE)


# --------------------------------------------------------------------------- #
# mapping
# --------------------------------------------------------------------------- #

def _should_include(rec: dict) -> bool:
    """Keep only primary Duke-NUS faculty.

    Excludes:
    - Inactive / hidden records.
    - Adjunct titles (per-user request).
    - SingHealth Duke-NUS Academic Clinical Programme faculty — these are
      SingHealth hospital clinicians (SGH/NUH/KKH/etc.) with affiliate
      ACP appointments, not based at the Duke-NUS campus.
    """
    if not rec.get("ToDisplay"):
        return False
    if rec.get("Employment_Status") != "Active":
        return False
    pos = (rec.get("Position_Title") or "").strip()
    # Only professorial ranks (Assistant/Associate/Full, plus Clinical/
    # Emeritus/Visiting variants). Excludes research fellows, research
    # assistants, research scientists, and adjunct titles.
    if not pos.endswith("Professor") or "Adjunct" in pos:
        return False
    team = (rec.get("Lab_Section_Team") or "").strip()
    if not team or team.startswith("SingHealth Duke-NUS"):
        return False
    return True


_DATA_URI_RE = re.compile(r"^data:image/(\w+);base64,(.+)$", re.S)


def _save_photo(data_uri: str, faculty_id: str) -> str | None:
    """Decode base64 data URI, downsize to <=400px long side, save as JPEG.
    Returns the public path or None for empty/invalid input."""
    if not data_uri:
        return None
    m = _DATA_URI_RE.match(data_uri.strip())
    if not m:
        return None
    try:
        blob = base64.b64decode(m.group(2), validate=False)
    except Exception:
        return None
    if len(blob) < 2_000:
        return None
    from io import BytesIO
    from PIL import Image
    try:
        im = Image.open(BytesIO(blob))
        im.load()
    except Exception:
        return None
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    long = max(w, h)
    if long > 400:
        scale = 400 / long
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{faculty_id}.jpg"
    im.save(PHOTOS_DIR / fname, "JPEG", quality=82, optimize=True)
    return f"/photos/dukenus/{fname}"


def _profile_url(slug: str) -> str:
    slug = (slug or "").lstrip("/")
    if not slug:
        return ""
    if slug.startswith("http"):
        return slug
    return f"{BASE}/directory/detail/{slug}"


def _to_record(rec: dict, bio: str, research: str) -> Faculty:
    name = clean_text(rec.get("Full_Name") or rec.get("DisplayName") or "")
    title = clean_text(rec.get("Position_Title") or "")
    dept = clean_text(rec.get("Lab_Section_Team") or "")
    email = clean_text(rec.get("Email") or "")
    prof_url = _profile_url(rec.get("Url") or "")

    summary_parts = [s for s in (bio, research) if s]
    summary = "\n\n".join(summary_parts)

    fid = slugify("dukenus", name)
    out: Faculty = {
        "id": fid,
        "name": name,
        # Duke-NUS is an NUS graduate medical school (see nus.edu.sg/education),
        # so we group it under the NUS institution and keep the Duke-NUS name
        # in the department prefix for clarity.
        "institution": "NUS",
        "profile_url": prof_url,
    }
    if dept:
        out["department"] = f"Duke-NUS Medical School — {dept}"
    if title:
        out["title"] = title
    if email and "@" in email:
        out["email"] = email
    if summary:
        out["summary"] = summary
    photo = _save_photo(rec.get("Photo") or rec.get("ProfilePictureUrl") or "", fid)
    if photo:
        out["photo_url"] = photo
    return out


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

def _fetch_profile_html(page, url: str) -> str:
    cached = _load_cached(url)
    if cached:
        return cached
    for attempt in range(3):
        try:
            page.goto(url, wait_until="load", timeout=45_000)
            page.wait_for_timeout(800)
            html = page.content()
            if len(html) > 20_000:
                _save_cached(url, html)
                return html
        except Exception as e:
            print(f"    ! {url} attempt {attempt+1}: {e}")
        time.sleep(1 + attempt)
    return ""


def scrape(reparse: bool = False) -> list[Faculty]:
    # Load or fetch the index (stage 1).
    if reparse and INDEX_PATH.exists():
        staff_list = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        print(f"[reparse] loaded {len(staff_list)} from cached index")
    else:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            print("Warming up Duke-NUS directory...")
            page.goto(DIRECTORY_URL, wait_until="load", timeout=60_000)
            page.wait_for_timeout(3_000)
            print("Fetching staff index...")
            staff_list = _fetch_all_staff(page)
            INDEX_PATH.write_text(json.dumps(staff_list, indent=1), encoding="utf-8")
            print(f"Saved {len(staff_list)} staff to index.")

            # Stage 2: profile pages for faculty-worthy records.
            eligible = [s for s in staff_list if _should_include(s)]
            print(f"Fetching {len(eligible)} profile pages...")
            records: list[Faculty] = []
            for i, rec in enumerate(eligible, 1):
                url = _profile_url(rec.get("Url") or "")
                if not url:
                    continue
                html = _fetch_profile_html(page, url)
                bio = _extract_bio(html) if html else ""
                research = _extract_research(html) if html else ""
                records.append(_to_record(rec, bio, research))
                if i % 25 == 0:
                    print(f"  [{i}/{len(eligible)}] {rec['Full_Name']}")
            browser.close()
            return records

    # Reparse path: use cached HTML only.
    eligible = [s for s in staff_list if _should_include(s)]
    records: list[Faculty] = []
    for rec in eligible:
        url = _profile_url(rec.get("Url") or "")
        html = _load_cached(url) or ""
        bio = _extract_bio(html) if html else ""
        research = _extract_research(html) if html else ""
        records.append(_to_record(rec, bio, research))
    return records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparse", action="store_true")
    args = ap.parse_args()

    records = scrape(reparse=args.reparse)
    out_path = OUT_DIR / "dukenus.json"
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    with_summary = sum(1 for r in records if r.get("summary"))
    print(f"\nWrote {len(records)} records to {out_path}")
    print(f"  with summary: {with_summary}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
