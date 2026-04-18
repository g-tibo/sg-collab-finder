"""A*STAR Institute of Molecular and Cell Biology (IMCB) scraper.

Indexes:
    https://www.a-star.edu.sg/imcb/people/core-investigators
    https://www.a-star.edu.sg/imcb/people/joint-investigators
    https://www.a-star.edu.sg/imcb/people/adjunct-investigators

Each card is:
    <a class="card" name="card_layout">
        <div class="card__image"><img .../></div>
        <div class="card__title">
            <div><div><strong>Name</strong><br />Lab or research area<br /></div></div>
            <div name="cardconfig" cardcconfig_navigateurl="<profile url>"></div>
        </div>
    </a>

Detail pages are Sitefinity-rendered and have: name, lab-name, degree,
email, summary, RESEARCH block, awards, publications.
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
INDEXES = [
    ("Core Investigator", f"{BASE}/imcb/people/core-investigators"),
    ("Joint Investigator", f"{BASE}/imcb/people/joint-investigators"),
    ("Adjunct Investigator", f"{BASE}/imcb/people/adjunct-investigators"),
]


# --------------------------------------------------------------------------- #

def _cards_from_index(url: str, default_title: str) -> list[tuple[str, str, str, str]]:
    """Return list of (display_name, lab_area, profile_url, photo_url)."""
    html = get(url)
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, str, str, str]] = []

    for card in soup.find_all("a", attrs={"class": lambda c: c and "card" in c.split()}):
        title_div = card.select_one(".card__title")
        img = card.select_one(".card__image img")
        cfg = card.find("div", attrs={"name": "cardconfig"})
        if not title_div:
            continue
        strong = title_div.find("strong")
        display_name = clean_text(strong.get_text(" ", strip=True)) if strong else ""
        if not display_name:
            continue
        # Everything inside the inner div that isn't the <strong> is the lab/area line.
        inner = title_div.find(lambda t: t.name == "div" and t.find("strong"))
        lab_area = ""
        if inner:
            strong_text = strong.get_text(" ", strip=True) if strong else ""
            full = clean_text(inner.get_text(" ", strip=True))
            lab_area = clean_text(full.replace(strong_text, "", 1))
        # profile URL: prefer cardconfig; else fall back to the card's href or
        # to the index page (joint/adjunct lists don't deep-link to profiles).
        profile = (cfg.get("cardcconfig_navigateurl", "") if cfg else "") or card.get("href", "") or url
        photo = urljoin(BASE, img.get("src", "")) if img and img.get("src") else ""
        out.append((_reformat_astar_name(display_name), lab_area, profile, photo))
    return out


def _reformat_astar_name(name: str) -> str:
    """A*STAR list cards put family name in ALL CAPS. Re-title-case for display.

    'Sherry AW' -> 'Sherry Aw', 'Qi-Jing LI' -> 'Qi-Jing Li',
    'Jonathan Yuin-Han LOH' -> 'Jonathan Yuin-Han Loh'.
    """
    parts = name.split()
    fixed = []
    for p in parts:
        if p.isupper() and len(p) > 1:
            # title-case but keep hyphenated parts
            fixed.append("-".join(w.capitalize() for w in p.split("-")))
        else:
            fixed.append(p)
    return " ".join(fixed)


# --------------------------------------------------------------------------- #

SECTION_HEADS = ("SUMMARY", "AWARDS & GRANTS", "RESEARCH", "PUBLICATIONS")


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    """Given the visible text of a profile page, split it into sections keyed
    by uppercase section heading. Everything before the first known heading is
    discarded (it's navigation)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for ln in lines:
        if ln.strip().upper() in SECTION_HEADS:
            current = ln.strip().upper()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(ln)
    return sections


def _parse_detail(name: str, lab_area: str, url: str, photo: str, role_title: str, html: str) -> Faculty:
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    text = soup.get_text("\n", strip=True)
    lines = [clean_text(ln) for ln in text.split("\n") if clean_text(ln)]
    sections = _split_sections(lines)

    # Find "email:" line anywhere in visible text
    email = ""
    for i, ln in enumerate(lines):
        if ln.rstrip(":").lower() == "email" and i + 1 < len(lines):
            cand = lines[i + 1]
            if "@" in cand:
                email = cand
                break
    if not email:
        m = re.search(r"([\w.+-]+@[\w.-]+\.\w+)", text)
        if m:
            email = m.group(1)

    # Lab URL
    lab_url = ""
    for i, ln in enumerate(lines):
        if ln.lower().startswith("lab page") and i + 1 < len(lines):
            cand = lines[i + 1]
            if cand.startswith("http"):
                lab_url = cand
                break
    if not lab_url:
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if any(k in h.lower() for k in ("lab.", "lab/", ".lab", "-lab", "lab-")) and "a-star.edu.sg" not in h:
                if a.get_text(" ", strip=True).lower() == "lab page" or "lab page" in str(a.previous_sibling or "").lower():
                    lab_url = h
                    break

    # Scholar / ORCID
    scholar_url = ""
    orcid = ""
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if "scholar.google" in h and not scholar_url:
            scholar_url = h
        if "orcid.org" in h and not orcid:
            orcid = h

    # Summary: first 2 sentences of SUMMARY + first line of RESEARCH (lab name).
    summary_lines = sections.get("SUMMARY", [])[:4]
    research_lines = sections.get("RESEARCH", [])[:3]
    summary = " ".join(summary_lines).strip()
    if research_lines:
        summary = (summary + "\n\n" + " ".join(research_lines)).strip()

    # Research areas: we don't have an explicit list here, so derive from the
    # lab-area line on the index card (e.g. "RNA biology and therapeutics").
    research_areas = split_keywords(lab_area) if lab_area else []

    return Faculty(
        id=slugify("astar", "imcb", name),
        name=name,
        institution="A*STAR",
        department="Institute of Molecular and Cell Biology (IMCB)",
        title=role_title,
        roles=[lab_area] if lab_area else [],
        research_areas=research_areas,
        summary=summary,
        email=email,
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
    for role_title, index_url in INDEXES:
        cards = _cards_from_index(index_url, role_title)
        print(f"[astar_imcb] {role_title}: {len(cards)} cards")
        for display_name, lab_area, profile, photo in cards:
            rec_id = slugify("astar", "imcb", display_name)
            if rec_id in seen_ids:
                continue
            seen_ids.add(rec_id)
            # Only fetch detail for Core Investigators (others often don't deep-link).
            is_deep = profile.startswith("http") and "/imcb/people/" in profile and not profile.endswith(
                ("core-investigators", "joint-investigators", "adjunct-investigators")
            )
            if role_title == "Core Investigator" and is_deep:
                try:
                    html = get(profile)
                    out.append(_parse_detail(display_name, lab_area, profile, photo, role_title, html))
                    continue
                except Exception as e:
                    print(f"  skip detail {display_name} @ {profile}: {e}")
            # Fallback: card-only record.
            out.append(Faculty(
                id=rec_id,
                name=display_name,
                institution="A*STAR",
                department="Institute of Molecular and Cell Biology (IMCB)",
                title=role_title,
                roles=[lab_area] if lab_area else [],
                research_areas=split_keywords(lab_area) if lab_area else [],
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
    (out_dir / "astar_imcb.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[astar_imcb] wrote {len(records)} records")


if __name__ == "__main__":
    main()
