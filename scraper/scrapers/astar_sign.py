"""A*STAR Singapore Immunology Network (SIgN) scraper.

Index:
    https://www.a-star.edu.sg/sign/people

Index cards are column divs containing an <a> wrapping <img>+<br>+name. Each
links to /sign/people/principal-investigators/<slug> (or .../joint-...).

Detail pages have an <h1> name and <h2> sections: Biography, Research Focus,
Adjunct Positions, Lab Members, Publications.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers._http import get
from schema import Faculty, clean_text, slugify, split_keywords


BASE = "https://www.a-star.edu.sg"
INDEX_URL = f"{BASE}/sign/people"


def _reformat_astar_name(name: str) -> str:
    parts = name.split()
    fixed = []
    for p in parts:
        if p.isupper() and len(p) > 1:
            fixed.append("-".join(w.capitalize() for w in p.split("-")))
        else:
            fixed.append(p)
    return " ".join(fixed)


def _cards_from_index(url: str) -> list[tuple[str, str, str]]:
    """Return (display_name, profile_url, photo_url) for each card."""
    html = get(url)
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for col in soup.select("div.sf_colsIn.col-lg-3.col-md-6"):
        link = col.find("a", href=lambda h: h and "/sign/people/principal-investigators" in h)
        if not link:
            continue
        href = urljoin(BASE, link["href"])
        if href in seen:
            continue
        seen.add(href)
        # Name: text inside the <a> excluding the <img> alt. Replace <br> with
        # a space so we get "FirstLast" not glued together.
        for br in link.find_all("br"):
            br.replace_with(" ")
        # The <img> get_text contributes nothing; only stripped-strings matter.
        name_raw = clean_text(link.get_text(" ", strip=True))
        if not name_raw:
            img = link.find("img")
            name_raw = clean_text(img.get("alt", "")) if img else ""
        if not name_raw:
            continue
        img = link.find("img")
        photo = urljoin(BASE, img.get("src", "")) if img and img.get("src") else ""
        out.append((_reformat_astar_name(name_raw), href, photo))
    return out


def _collect_section(main, head_pattern: str) -> str:
    """Return the joined text of all elements under the first <h2> matching."""
    h = None
    for cand in main.find_all(["h2", "h3"]):
        t = clean_text(cand.get_text(" ", strip=True)).lower()
        if re.match(head_pattern, t):
            h = cand
            break
    if h is None:
        return ""
    container = h.parent
    if container is None:
        return ""
    full = container.get_text(" ", strip=True)
    head_text = h.get_text(" ", strip=True)
    if head_text in full:
        full = full.split(head_text, 1)[1]
    # Stop at the next h2/h3 sibling within the same container.
    for nxt in h.find_next_siblings(["h2", "h3"]):
        nxt_text = nxt.get_text(" ", strip=True)
        if nxt_text and nxt_text in full:
            full = full.split(nxt_text, 1)[0]
            break
    return clean_text(full)


def _parse_detail(name: str, url: str, photo: str, html: str) -> Faculty:
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    main = soup.select_one("section.page-content__inner") or soup

    biography = _collect_section(main, r"^biography\b")
    research_focus = _collect_section(main, r"^research focus\b")

    # Pull research-focus bullets directly from <li>/<p> elements when the
    # section uses a list — gives us cleaner keywords than splitting prose.
    focus_items: list[str] = []
    for cand in main.find_all(["h2", "h3"]):
        if re.match(r"^research focus\b", clean_text(cand.get_text(" ", strip=True)).lower()):
            for sib in cand.find_all_next():
                if sib.name in ("h2", "h3"):
                    break
                if sib.name in ("li", "p") and not sib.find(["li", "p"]):
                    t = clean_text(sib.get_text(" ", strip=True)).rstrip(".")
                    if t and 3 < len(t) < 120:
                        focus_items.append(t)
            break

    summary_parts: list[str] = []
    if biography:
        summary_parts.append(biography)
    if research_focus:
        summary_parts.append("Research focus: " + research_focus)
    summary = " ".join(summary_parts)[:4000].strip()

    # Research areas: prefer <li>/<p> items; otherwise fall back to splitting
    # the prose on sentence boundaries.
    areas: list[str] = list(focus_items)
    if not areas and research_focus:
        for p in re.split(r"\s{2,}|(?:\.\s+)|\n", research_focus):
            p = clean_text(p).rstrip(".")
            if p and 3 < len(p) < 120:
                areas.append(p)
    seen = set()
    research_areas = [a for a in areas if not (a.lower() in seen or seen.add(a.lower()))][:8]

    # Title: use h1 plus the first short phrase that follows it (usually the
    # academic rank or "Principal Investigator").
    short_title = ""
    h1 = main.find("h1")
    if h1:
        for sib in h1.find_all_next():
            if sib.name == "h2":
                break
            if sib.name in ("p", "div") and not sib.find(["h2", "h3"]):
                t = clean_text(sib.get_text(" ", strip=True))
                if t and "@" not in t and len(t) < 100:
                    short_title = t
                    break

    return Faculty(
        id=slugify("astar", "sign", name),
        name=name,
        institution="A*STAR",
        department="Singapore Immunology Network (SIgN)",
        title=short_title,
        roles=[],
        research_areas=research_areas,
        summary=summary,
        email="",
        profile_url=url,
        photo_url=photo,
    )


def scrape() -> list[Faculty]:
    cards = _cards_from_index(INDEX_URL)
    print(f"[astar_sign] {len(cards)} cards")
    out: list[Faculty] = []
    seen_ids: set[str] = set()
    for name, url, photo in cards:
        rec_id = slugify("astar", "sign", name)
        if rec_id in seen_ids:
            continue
        seen_ids.add(rec_id)
        try:
            html = get(url)
            out.append(_parse_detail(name, url, photo, html))
        except Exception as e:
            print(f"  skip detail {name}: {e}")
            out.append(Faculty(
                id=rec_id,
                name=name,
                institution="A*STAR",
                department="Singapore Immunology Network (SIgN)",
                title="",
                roles=[],
                research_areas=[],
                summary="",
                email="",
                profile_url=url,
                photo_url=photo,
            ))
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    records = scrape()
    (out_dir / "astar_sign.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[astar_sign] wrote {len(records)} records")


if __name__ == "__main__":
    main()
