"""A*STAR Bioinformatics Institute (BII) scraper.

Index:
    https://www.a-star.edu.sg/bii/people

BII renders each PI as a "lightbox" popup on a single page — there are no
separate profile URLs. The DOM pattern is:

    <div class="lightbox-off">
        <div class="inner-banner sf_colsIn">          # card (image + name)
            <a class="card"> ... <img ... > ... </a>
        </div>
        <div class="container">                        # modal body
            <div class="lightbox__title"><h2>NAME</h2></div>
            <div class="lightbox__content__details">
                NAME\nTitle\nEmail: ...\nResearch Group: ...\n<bio...>
            </div>
        </div>
    </div>

We pull name+photo+bio from these boxes directly. profile_url points back to
the listing page since there is no individual URL.
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
INDEX_URL = f"{BASE}/bii/people"

_EMAIL_RE = re.compile(r"([\w.+-]+@[\w.-]+\.\w+)")


def _reformat_astar_name(name: str) -> str:
    """Same casing rule as other A*STAR scrapers (family name often CAPS)."""
    parts = name.split()
    fixed = []
    for p in parts:
        if p.isupper() and len(p) > 1:
            fixed.append("-".join(w.capitalize() for w in p.split("-")))
        else:
            fixed.append(p)
    return " ".join(fixed)


def _parse_box(box) -> Faculty | None:
    title_el = box.find(class_="lightbox__title")
    content_el = box.find(class_="lightbox__content__details")
    if not title_el or not content_el:
        return None
    h2 = title_el.find("h2")
    if not h2:
        return None
    raw_name = clean_text(h2.get_text(" ", strip=True).replace("\xa0", " "))
    raw_name = re.sub(r"\([^)]*\)", "", raw_name).strip()
    if not raw_name:
        return None
    name = _reformat_astar_name(raw_name)

    # Inside the content the header card lives in a <table>; the bio is in
    # following <p> tags. Parse those separately.
    table = content_el.find("table")
    header_td = None
    if table:
        tds = table.find_all("td")
        if len(tds) >= 2:
            header_td = tds[1]

    title_line = ""
    research_group = ""
    lab_url = ""
    research_url = ""
    if header_td:
        # Replace <br> with explicit newlines so each field is its own line.
        for br in header_td.find_all("br"):
            br.replace_with("\n")
        raw = header_td.get_text("\n")
        lines = [clean_text(ln) for ln in raw.split("\n") if clean_text(ln)]
        # The leading 1-2 lines repeat the name (h2 may have given-name first
        # while the header lists family-name first, possibly with "(Head)" or
        # similar decoration). Treat the name as a multiset of letters and
        # drop lines from the top while they're still entirely contained in
        # that multiset.
        from collections import Counter
        name_bag = Counter(re.sub(r"[^a-z]", "", raw_name.lower()))
        consumed = 0
        for ln in lines[:3]:
            # Strip parenthetical decoration like "(Head)" before comparing.
            ln_clean = re.sub(r"\([^)]*\)", "", ln)
            ln_bag = Counter(re.sub(r"[^a-z]", "", ln_clean.lower()))
            if not ln_bag:
                continue
            # Subtract; if any letter goes negative, this line isn't part of
            # the name.
            if all(name_bag.get(c, 0) >= n for c, n in ln_bag.items()):
                name_bag.subtract(ln_bag)
                consumed += 1
                if sum(name_bag.values()) == 0:
                    break
            else:
                break
        lines = lines[consumed:]
        # Labels can be "Email: foo" or "Email:\nfoo" (when the value is in
        # an <a> tag — get_text + br→newline puts it on the next line).
        # Track the active label and consume the following line if needed.
        title_parts: list[str] = []
        pending_label: str | None = None
        SKIP_LABELS = ("lab website", "research gate", "researchgate", "google scholar", "orcid", "linkedin")
        for ln in lines:
            low = ln.lower().rstrip(":").strip()
            value = ln.split(":", 1)[1].strip() if ":" in ln else ""
            if pending_label:
                # Treat this line as the value for the previous label.
                if pending_label == "research group":
                    research_group = ln
                pending_label = None
                continue
            if low == "email" or low.startswith("email"):
                pending_label = "email" if not value else None
                continue
            if low == "research group" or low.startswith("research group"):
                if value:
                    research_group = value
                else:
                    pending_label = "research group"
                continue
            if any(low.startswith(s) for s in SKIP_LABELS):
                pending_label = None if value else low.split(":")[0]
                continue
            title_parts.append(ln)
        title_line = ", ".join(title_parts)
        # Pull the research-group profile link if present.
        for a in header_td.find_all("a", href=True):
            txt = clean_text(a.get_text(" ", strip=True))
            href = a["href"]
            if txt and txt == research_group:
                research_url = urljoin(BASE, href)
            if "lab website" in (a.find_previous(string=True) or "").lower():
                pass  # noqa: keep simple
        # Lab Website link (preceded by text "Lab Website:")
        for sib_text in header_td.stripped_strings:
            pass
        for a in header_td.find_all("a", href=True):
            prev = a.previous_sibling
            label = ""
            while prev is not None and not isinstance(prev, str):
                prev = prev.previous_sibling
            if isinstance(prev, str):
                label = prev.lower()
            if "lab website" in label and not lab_url:
                lab_url = a["href"]

    # Bio: concatenation of <p> children inside content_el (not in the header).
    bio_parts: list[str] = []
    for p in content_el.find_all("p"):
        if table and p in table.descendants:
            continue
        t = clean_text(p.get_text(" ", strip=True))
        if t:
            bio_parts.append(t)
    summary = " ".join(bio_parts)[:4000].strip()

    # Photo: prefer a thumbnail from inside the header td; fall back to any
    # img in the surrounding box (the card thumbnail).
    photo = ""
    img = (header_td.find("img") if header_td else None) or box.find("img")
    if img and img.get("src"):
        photo = urljoin(BASE, img["src"])

    short_title = title_line.split(",")[0].strip() if title_line else ""
    roles: list[str] = []
    if title_line and title_line != short_title:
        roles.append(title_line)
    if research_group:
        roles.append(f"Research Group: {research_group}")

    areas = split_keywords(research_group) if research_group else []

    return Faculty(
        id=slugify("astar", "bii", name),
        name=name,
        institution="A*STAR",
        department="Bioinformatics Institute (BII)",
        title=short_title,
        roles=roles,
        research_areas=areas,
        summary=summary,
        email="",
        profile_url=research_url or INDEX_URL,
        lab_url=lab_url,
        photo_url=photo,
    )


def scrape() -> list[Faculty]:
    html = get(INDEX_URL)
    soup = BeautifulSoup(html, "lxml")
    boxes = soup.find_all("div", class_="lightbox-off")
    out: list[Faculty] = []
    seen: set[str] = set()
    for b in boxes:
        rec = _parse_box(b)
        if rec is None or rec["id"] in seen:
            continue
        seen.add(rec["id"])
        out.append(rec)
    print(f"[astar_bii] {len(out)} PIs")
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    records = scrape()
    (out_dir / "astar_bii.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[astar_bii] wrote {len(records)} records")


if __name__ == "__main__":
    main()
