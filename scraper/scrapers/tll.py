"""Temasek Life Sciences Laboratory — principal investigators.

TLL's four research-group pages
(tll.org.sg/research/research-groups/{cell-biology,developmental-biology,
genome-and-ecological-biology,molecular-pathogenesis}/) each link to PI
profiles at /people/<slug>/. Each profile page has an Affiliations list
with lines like "Principal Investigator", "Senior Principal Investigator",
"Deputy Chairman", plus secondary NUS/NTU adjunct appointments.

TLL PIs are primary-research faculty running their own labs — the adjunct
title that appears in their affiliations refers to their teaching role at
NUS/NTU, not their TLL position. So we label them by their TLL role
(Principal Investigator / Senior Principal Investigator) and keep all PIs.

Usage:
    python -m scrapers.tll            # full scrape
    python -m scrapers.tll --reparse  # re-parse cached HTML only
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


BASE = "https://www.tll.org.sg"
GROUP_URLS = [
    f"{BASE}/research/research-groups/cell-biology/",
    f"{BASE}/research/research-groups/developmental-biology/",
    f"{BASE}/research/research-groups/genome-and-ecological-biology/",
    f"{BASE}/research/research-groups/molecular-pathogenesis/",
]

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "out"
CACHE_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

_GROUP_LABEL = {
    "cell-biology": "Cell Biology",
    "developmental-biology": "Developmental Biology",
    "genome-and-ecological-biology": "Genome and Ecological Biology",
    "molecular-pathogenesis": "Molecular Pathogenesis",
}

_PI_TITLES = (
    "Senior Principal Investigator",
    "Principal Investigator",
    "Deputy Chairman",
    "Chairman",
)


def _cache_key(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"tll_{h}.html"


def _load_cached(url: str, min_size: int = 20_000) -> str | None:
    p = _cache_key(url)
    if p.exists() and p.stat().st_size > min_size:
        return p.read_text(encoding="utf-8", errors="ignore")
    return None


def _save_cached(url: str, html: str) -> None:
    _cache_key(url).write_text(html, encoding="utf-8")


def _fetch(url: str, page) -> str:
    cached = _load_cached(url)
    if cached:
        return cached
    for attempt in range(3):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(1_500)
            html = page.content()
            if len(html) > 20_000:
                _save_cached(url, html)
                return html
        except Exception as e:
            print(f"  ! {url} attempt {attempt+1}: {e}")
        time.sleep(1 + attempt)
    return ""


def _collect_pi_urls(group_html: str) -> list[str]:
    urls = set(re.findall(r'href="(https://www\.tll\.org\.sg/people/[^"]+)"', group_html))
    return sorted(u.rstrip("/") + "/" for u in urls)


def _infer_group(url: str, html_by_group: dict[str, str]) -> str:
    for slug, gh in html_by_group.items():
        if url.rstrip("/") + "/" in gh:
            return _GROUP_LABEL.get(slug, slug)
    return ""


def _parse_profile(html: str, url: str, group: str) -> dict | None:
    s = BeautifulSoup(html, "html.parser")
    h1 = s.find("h1")
    name = clean_text(h1.get_text(" ")) if h1 else ""
    if not name:
        return None

    body_text = s.get_text("\n", strip=True)

    # Pick the most senior TLL title appearing on the page.
    title = ""
    for t in _PI_TITLES:
        if t in body_text:
            title = t
            break
    if not title:
        # Not a PI (e.g. retired chairman without active title) — skip.
        return None

    # Photo: first /uploads/ image that isn't a logo.
    photo = ""
    for img in s.find_all("img"):
        src = img.get("src", "")
        if src and "/uploads/" in src and "logo" not in src.lower():
            photo = src
            break

    # Summary: combine Question / Approach / Bio sections if present.
    summary_parts: list[str] = []
    for heading in ("Question", "Approach", "Bio"):
        m = re.search(
            rf"\n{heading}\n(.+?)(?=\n(?:Question|Approach|Bio|Impact|Affiliations|"
            rf"Collaborations|Research Areas|Contact|Group Publications)\b)",
            body_text,
            re.S,
        )
        if m:
            chunk = clean_text(m.group(1))
            if chunk:
                summary_parts.append(chunk)
    summary = "\n\n".join(summary_parts)

    return {
        "name": name,
        "title": title,
        "group": group,
        "profile_url": url,
        "photo_url": photo,
        "summary": summary,
    }


def _to_faculty(rec: dict) -> Faculty:
    out: Faculty = {
        "id": slugify("tll", rec["name"]),
        "name": rec["name"],
        "institution": "TLL",
        "department": f"Temasek Life Sciences Laboratory — {rec['group']}"
        if rec.get("group") else "Temasek Life Sciences Laboratory",
        "profile_url": rec["profile_url"],
        "title": rec["title"],
    }
    if rec.get("photo_url"):
        out["photo_url"] = rec["photo_url"]
    if rec.get("summary"):
        out["summary"] = rec["summary"]
    return out


def scrape(reparse: bool = False) -> list[Faculty]:
    from playwright.sync_api import sync_playwright

    html_by_group: dict[str, str] = {}
    pi_urls: set[str] = set()

    if reparse:
        for gu in GROUP_URLS:
            slug = gu.rstrip("/").split("/")[-1]
            gh = _load_cached(gu) or ""
            if not gh:
                print(f"  missing cache for {slug}")
                continue
            html_by_group[slug] = gh
            pi_urls.update(_collect_pi_urls(gh))
        out: list[Faculty] = []
        for u in sorted(pi_urls):
            html = _load_cached(u) or ""
            if not html:
                continue
            group = _infer_group(u, html_by_group)
            rec = _parse_profile(html, u, group)
            if rec:
                out.append(_to_faculty(rec))
        print(f"[reparse] {len(out)} PIs")
        return out

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_context().new_page()
        for gu in GROUP_URLS:
            slug = gu.rstrip("/").split("/")[-1]
            gh = _fetch(gu, page)
            if gh:
                html_by_group[slug] = gh
                pi_urls.update(_collect_pi_urls(gh))
        print(f"found {len(pi_urls)} unique PI URLs")
        out: list[Faculty] = []
        for i, u in enumerate(sorted(pi_urls), 1):
            html = _fetch(u, page)
            if not html:
                continue
            group = _infer_group(u, html_by_group)
            rec = _parse_profile(html, u, group)
            if rec:
                out.append(_to_faculty(rec))
            if i % 10 == 0:
                print(f"  [{i}/{len(pi_urls)}] kept {len(out)}")
        b.close()
    print(f"kept {len(out)} / {len(pi_urls)}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparse", action="store_true")
    args = ap.parse_args()
    records = scrape(reparse=args.reparse)
    out_path = OUT_DIR / "tll.json"
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    with_photo = sum(1 for r in records if r.get("photo_url"))
    with_summary = sum(1 for r in records if r.get("summary"))
    print(f"\nWrote {len(records)} records to {out_path}")
    print(f"  with photo: {with_photo}  with summary: {with_summary}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
