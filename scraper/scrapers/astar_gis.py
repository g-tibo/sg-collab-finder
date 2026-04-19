"""A*STAR Genome Institute of Singapore (GIS) scraper.

Index:
    https://www.a-star.edu.sg/gis/our-people

Cards here are NOT the same Sitefinity "card" component used by IMCB. They're
column divs (``div.sf_colsIn.col-lg-3.col-md-6``) each containing an image and
a paragraph of text with embedded profile link. The first <a> in each card is
a broken template placeholder pointing at Jian Jun Liu — the real link is the
<a> whose inner text matches the faculty name.

Detail pages are Sitefinity: <h1> name, <h2> RESEARCH, <h2> Selected
Publications. Title/roles/email/phone appear as a text block just above the
RESEARCH heading.
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
INDEX_URL = f"{BASE}/gis/our-people"


# --------------------------------------------------------------------------- #

def _cards_from_index(url: str) -> list[tuple[str, str, str, str]]:
    """Return list of (display_name, title_line, profile_url, photo_url)."""
    html = get(url)
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    cols = soup.select("div.sf_colsIn.col-lg-3.col-md-6")
    for col in cols:
        img = col.find("img", src=lambda s: s and "librariesprovider11" in s and "default-album" not in s)
        # The real profile link is the <a> with non-empty text (i.e. not the
        # placeholder whose only child is a <br>). Its inner text is the name.
        link = None
        for a in col.find_all("a", href=lambda h: h and "/faculty-staff/members/" in h):
            txt = clean_text(a.get_text(" ", strip=True))
            if txt:
                link = a
                break
        if not link:
            continue
        display_name = clean_text(link.get_text(" ", strip=True))
        profile = urljoin(BASE, link["href"])
        if profile in seen:
            continue
        seen.add(profile)

        # Title: the paragraph text with the name stripped out.
        para = link.find_parent("p")
        raw = clean_text(para.get_text(" ", strip=True)) if para else ""
        title_line = clean_text(raw.replace(display_name, "", 1))

        photo = urljoin(BASE, img.get("src", "")) if img and img.get("src") else ""
        out.append((_reformat_astar_name(display_name), title_line, profile, photo))
    return out


def _reformat_astar_name(name: str) -> str:
    """Same rule as IMCB: family-name token is ALL CAPS on the card."""
    parts = name.split()
    fixed = []
    for p in parts:
        if p.isupper() and len(p) > 1:
            fixed.append("-".join(w.capitalize() for w in p.split("-")))
        else:
            fixed.append(p)
    return " ".join(fixed)


# --------------------------------------------------------------------------- #

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_PHONE_RE = re.compile(r"\b\d{7,}\b")


def _parse_detail(name: str, title_line: str, url: str, photo: str, html: str) -> Faculty:
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()

    # The profile body lives inside a main content section — not inside the
    # side nav. Scope our h1/h2 search there to avoid matching "Research" in
    # a navigation menu.
    main = soup.select_one("section.page-content__inner") or soup
    h1 = main.find("h1")

    # Role / lab block: text between <h1> and the next <h2> inside the same
    # content section. Contains the title(s), programme, lab name (after ">"),
    # email, and phone.
    role_text = ""
    if h1:
        parts: list[str] = []
        for elem in h1.find_all_next():
            if elem.name == "h2":
                break
            # Only grab direct paragraphs/divs that contain free text, not nav.
            if elem.name == "p":
                t = clean_text(elem.get_text(" ", strip=True))
                if t and t not in parts:
                    parts.append(t)
        role_text = " ".join(parts)

    # Strip email and phone out of the role text before parsing roles.
    role_clean = _EMAIL_RE.sub("", role_text)
    role_clean = _PHONE_RE.sub("", role_clean).strip()

    # Lab name: text after the last ">" on the role line.
    lab_name = ""
    if ">" in role_clean:
        lab_name = role_clean.rsplit(">", 1)[-1].strip(" ,.")
        role_clean = role_clean.rsplit(">", 1)[0].strip()

    # Short title: first comma-separated phrase from the combined title_line
    # (index card) and role_clean (detail page). The card value is usually
    # the concise headline ("Executive Director"); detail adds the lab role.
    short_title = (title_line or role_clean).split(",")[0].split(">")[0].strip()

    roles: list[str] = []
    if role_clean and role_clean != short_title:
        roles.append(role_clean)
    if lab_name:
        roles.append(lab_name)

    # Research summary: find the "Research" h2 inside the main section. Collect
    # all following siblings (including <h3> subheadings that label the lab)
    # until the next <h2>.
    summary_parts: list[str] = []
    research_h2 = None
    for h in main.find_all("h2"):
        t = clean_text(h.get_text(" ", strip=True)).lower()
        if t.startswith("research") and "publication" not in t:
            research_h2 = h
            break
    if research_h2:
        # Profiles render the research block inconsistently: some use <p>
        # children, others stuff plaintext with <br> between <b> tags, others
        # nest the h2 and its body inside a single wrapper div. Grabbing text
        # from the h2's parent — then trimming anything that belongs to
        # following <h2> siblings (Publications, etc.) — covers all of these.
        container = research_h2.parent
        if container is not None:
            full = container.get_text(" ", strip=True)
            # Cut off once we hit the next h2 inside the same container.
            for nxt in research_h2.find_next_siblings("h2"):
                nxt_text = nxt.get_text(" ", strip=True)
                if nxt_text and nxt_text in full:
                    full = full.split(nxt_text, 1)[0]
                    break
            # Drop the leading "RESEARCH" heading itself.
            full = re.sub(r"^\s*RESEARCH\b[\s:]*", "", full, flags=re.I)
            full = re.sub(r"\bResearch Summary\b[\s:]*", "", full, flags=re.I)
            summary_parts.append(clean_text(full))
    summary = " ".join(summary_parts)[:4000].strip()

    # External links: lab site, Scholar, ORCID.
    lab_url = ""
    scholar_url = ""
    orcid = ""
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if "scholar.google" in h and not scholar_url:
            scholar_url = h
        elif "orcid.org" in h and not orcid:
            orcid = h
        elif not lab_url and "a-star.edu.sg" not in h and h.startswith("http"):
            label = clean_text(a.get_text(" ", strip=True)).lower()
            if "lab" in label and ("website" in label or "page" in label or label == "lab"):
                lab_url = h

    # Research areas: derive from lab name + programme.
    areas: list[str] = []
    if lab_name:
        areas.extend(split_keywords(lab_name.replace("Laboratory of ", "")))
    if role_clean and role_clean != short_title:
        # Programme ("RNA & DNA Technologies") is usually the last phrase of
        # role_clean after removing the leading role titles.
        programme = role_clean.split(",")[-1].strip()
        if programme and programme != short_title and len(programme) < 80:
            areas.extend(split_keywords(programme))
    # Dedupe while preserving order.
    seen = set()
    research_areas = [a for a in areas if not (a.lower() in seen or seen.add(a.lower()))]

    return Faculty(
        id=slugify("astar", "gis", name),
        name=name,
        institution="A*STAR",
        department="Genome Institute of Singapore (GIS)",
        title=short_title,
        roles=roles,
        research_areas=research_areas,
        summary=summary,
        email="",
        profile_url=url,
        lab_url=lab_url,
        scholar_url=scholar_url,
        orcid=orcid,
        photo_url=photo,
    )


# --------------------------------------------------------------------------- #

def scrape() -> list[Faculty]:
    out: list[Faculty] = []
    seen_ids: set[str] = set()
    cards = _cards_from_index(INDEX_URL)
    print(f"[astar_gis] {len(cards)} cards")
    for display_name, title_line, profile, photo in cards:
        rec_id = slugify("astar", "gis", display_name)
        if rec_id in seen_ids:
            continue
        seen_ids.add(rec_id)
        try:
            html = get(profile)
            out.append(_parse_detail(display_name, title_line, profile, photo, html))
        except Exception as e:
            print(f"  skip detail {display_name} @ {profile}: {e}")
            out.append(Faculty(
                id=rec_id,
                name=display_name,
                institution="A*STAR",
                department="Genome Institute of Singapore (GIS)",
                title=title_line.split(",")[0].strip() if title_line else "",
                roles=[title_line] if title_line else [],
                research_areas=[],
                summary="",
                email="",
                profile_url=profile,
                photo_url=photo,
            ))
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    records = scrape()
    (out_dir / "astar_gis.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[astar_gis] wrote {len(records)} records")


if __name__ == "__main__":
    main()
