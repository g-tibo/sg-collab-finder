"""NTU School of Biological Sciences — faculty scraper.

Entry point: https://www.ntu.edu.sg/sbs/about-us/our-people
Each faculty member has a lab page at /sbs/Research/lab-pages/<slug>.

The lab pages are server-rendered Sitefinity output. We extract:
    name, title, roles, email, research_areas, summary, lab_url,
    scholar_url, orcid, photo_url.

Run with:
    python -m scrapers.ntu_sbs
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers._http import get
from schema import Faculty, clean_text, slugify, split_keywords


BASE = "https://www.ntu.edu.sg"
INDEX = f"{BASE}/sbs/about-us/our-people"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _decode_cfemail(hex_str: str) -> str:
    """Decode Cloudflare-obfuscated emails (data-cfemail=\"...\")."""
    key = int(hex_str[:2], 16)
    return "".join(chr(int(hex_str[i : i + 2], 16) ^ key) for i in range(2, len(hex_str), 2))


def _extract_email(soup: BeautifulSoup) -> str:
    tag = soup.find(attrs={"data-cfemail": True})
    if tag:
        try:
            return _decode_cfemail(tag["data-cfemail"])
        except Exception:
            pass
    # Fallback: occasionally pages expose a raw mailto:
    m = re.search(r"mailto:([\w.+-]+@[\w.-]+\.\w+)", str(soup))
    return m.group(1) if m else ""


def _reformat_name(last_first: str) -> str:
    """'Thibault, Guillaume' -> 'Guillaume Thibault'. Leaves single-part names alone."""
    s = clean_text(last_first)
    if "," in s:
        last, first = [p.strip() for p in s.split(",", 1)]
        return f"{first} {last}"
    return s


# --------------------------------------------------------------------------- #
# index page
# --------------------------------------------------------------------------- #

def list_faculty() -> list[tuple[str, str]]:
    """Return list of (display_name, profile_url)."""
    html = get(INDEX)
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/sbs/Research/lab-pages/" not in href:
            continue
        name = clean_text(a.get_text(" ", strip=True))
        if not name or name.lower() == "close":
            continue
        url = urljoin(BASE, href)
        if url in seen:
            continue
        seen.add(url)
        out.append((_reformat_name(name), url))
    return out


# --------------------------------------------------------------------------- #
# detail page
# --------------------------------------------------------------------------- #

# The lab pages use Sitefinity "rte" (rich-text editor) blocks. Content appears
# as a flat sequence of <div class="rte"><div><... /></div></div>.
def _rte_blocks(soup: BeautifulSoup) -> list[BeautifulSoup]:
    return soup.select("div.rte")


def _parse_detail(name: str, url: str, html: str) -> Faculty:
    soup = BeautifulSoup(html, "lxml")

    # --- Title + roles --------------------------------------------------- #
    # Structure (text order): rank line, then one or more role lines.
    # We look inside the first few rte blocks for lines that look like titles.
    title = ""
    roles: list[str] = []
    blocks = _rte_blocks(soup)
    for b in blocks[:6]:
        for line in b.get_text("\n", strip=True).split("\n"):
            line = clean_text(line)
            if not line:
                continue
            if not title and re.search(
                r"\b(Professor|Associate Professor|Assistant Professor|Senior Lecturer|"
                r"Lecturer|Chair Professor|Distinguished Professor|Emeritus|Provost|"
                r"President|Principal(?!\s+Investigator)|NRF Fellow)\b",
                line,
                re.I,
            ) and len(line) < 140:
                title = line
            elif title and any(k in line for k in ("Dean", "Director", "Head", "Chair", "Coordinator", "President")):
                roles.append(line)

    # --- Email, lab url, scholar, orcid --------------------------------- #
    email = _extract_email(soup)
    lab_url = ""
    scholar_url = ""
    orcid = ""
    dr_ntu = ""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(" ", strip=True).lower()
        if "scholar.google" in href:
            scholar_url = href
        elif "orcid.org" in href:
            orcid = href
        elif "dr.ntu.edu.sg" in href:
            dr_ntu = href
        elif text == "personal lab webpage" or "Personal Lab Webpage" in str(a.previous_sibling or ""):
            lab_url = href
        elif re.search(r"(thibaultlab|lab\.|\.lab\.)", href, re.I) and not lab_url:
            # weak heuristic; only fill if blank
            lab_url = href
    # The page often has a labeled "Personal Lab Webpage:" followed by a link.
    if not lab_url:
        m = re.search(r"Personal Lab Webpage:\s*</[^>]+>\s*(?:<[^>]+>)*\s*<a[^>]+href=\"([^\"]+)\"", html, re.I)
        if m:
            lab_url = m.group(1)

    # --- Research areas (keywords) + summary ---------------------------- #
    research_areas: list[str] = []
    ra_idx = -1
    for i, b in enumerate(blocks):
        txt = clean_text(b.get_text(" ", strip=True))
        if re.fullmatch(r"Research Areas?", txt, re.I) and i + 1 < len(blocks):
            research_areas = split_keywords(clean_text(blocks[i + 1].get_text(" ", strip=True)))
            ra_idx = i
            break

    # Summary = narrative paragraph rte blocks that appear BEFORE "Research Areas"
    # and don't contain contact/metadata labels. We require real sentences (multi
    # sentence, contains "." + length >= 120).
    summary_parts: list[str] = []
    METADATA_MARKERS = (
        "Email", "Personal Lab", "Digital Repository", "Google Scholar",
        "NCBI", "ORCID", "LinkedIn", "Lab page:",
    )
    scan_range = blocks[:ra_idx] if ra_idx >= 0 else blocks
    for b in scan_range:
        t = clean_text(b.get_text(" ", strip=True))
        if len(t) < 120:
            continue
        if any(m in t for m in METADATA_MARKERS):
            continue
        if t.count(".") < 2:  # not paragraph-like
            continue
        summary_parts.append(t)
    summary = "\n\n".join(summary_parts[:4])

    # --- Photo ---------------------------------------------------------- #
    # SBS stores PI headshots under /faculty/<year>-faculty-photos/. Lab member
    # photos live under /researcher/<lab>-lab/...-lab-members-photos/. We match
    # the PI folder first, then fall back to the first non-lab-member image.
    photo_url = ""
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "/faculty/" in src and "faculty-photos" in src:
            # Strip the Sitefinity signed query string (MaxWidth/Signature/etc).
            # The bare URL serves the full-size PNG and doesn't expire.
            photo_url = urljoin(BASE, src.split("?", 1)[0])
            break

    return Faculty(
        id=slugify("ntu", "sbs", name),
        name=name,
        institution="NTU",
        department="School of Biological Sciences",
        title=title,
        roles=roles,
        research_areas=research_areas,
        summary=summary,
        email=email,
        profile_url=url,
        lab_url=lab_url,
        scholar_url=scholar_url,
        orcid=orcid,
        photo_url=photo_url,
    )


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def scrape() -> list[Faculty]:
    people = list_faculty()
    print(f"[ntu_sbs] found {len(people)} faculty on index")
    out: list[Faculty] = []
    for name, url in people:
        try:
            html = get(url)
            rec = _parse_detail(name, url, html)
            out.append(rec)
        except Exception as e:
            print(f"  skip {name} @ {url}: {e}")
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    records = scrape()
    (out_dir / "ntu_sbs.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[ntu_sbs] wrote {len(records)} records")


if __name__ == "__main__":
    main()
