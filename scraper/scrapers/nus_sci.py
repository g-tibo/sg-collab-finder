"""NUS Faculty of Science — department scrapers.

NUS has 7 FoS departments:
  - Biological Sciences (DBS)          — separate scraper (nus_dbs.py)
  - Chemistry                           — chemistry.nus.edu.sg        [this file]
  - Food Science and Technology         — fst.nus.edu.sg              [TODO]
  - Mathematics                         — math.nus.edu.sg             [TODO]
  - Pharmacy & Pharmaceutical Sciences  — pharmacy.nus.edu.sg         [TODO]
  - Physics                             — physics.nus.edu.sg          [TODO]
  - Statistics and Data Science         — stat.nus.edu.sg             [TODO]

All departments are subdomains of nus.edu.sg running various WordPress
themes; a few sit behind Incapsula, so we use Playwright and cache HTML
to `scraper/cache/` with a per-dept prefix.

Per-department tabs differ. Following the Duke-NUS rule we keep only
primary professorial ranks (Professor / Associate Professor /
Assistant Professor) — no Adjunct, Visiting, Emeritus, Honorary, or
Educator/Teaching-track faculty.

Usage:
    python -m scrapers.nus_sci            # full scrape
    python -m scrapers.nus_sci --reparse  # re-parse cached HTML only
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


ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
OUT_DIR = ROOT / "out"
CACHE_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)


DEPARTMENTS: list[dict] = [
    # Chemistry: single "our-people" page with tabs; Faculty tab groups
    # Prof / Assoc Prof / Asst Prof under <h3>.
    {
        "slug": "chem", "name": "Department of Chemistry",
        "layout": "chem-c-list4",
        "listing": "https://chemistry.nus.edu.sg/our-people-2/",
    },
    # Math: div.people cards on /people/regular-faculty/ (no rank sections —
    # rank lives in p.designation on each card).
    {
        "slug": "math", "name": "Department of Mathematics",
        "layout": "math-people",
        "listing": "https://www.math.nus.edu.sg/people/regular-faculty/",
    },
    # Physics: anchor-wrapped cards on /staff/faculty/ with rank inside the
    # memberName text (e.g. "Jane Doe, Associate Professor"), grouped under
    # <h3> rank headers.
    {
        "slug": "phys", "name": "Department of Physics",
        "layout": "phys-memberbox",
        "listing": "https://www.physics.nus.edu.sg/staff/faculty/",
    },
    # Statistics & Data Science: type-faculty_member divs on
    # /our-people/faculty-members/ with h5 name, h6 rank+role, mailto.
    {
        "slug": "stat", "name": "Department of Statistics and Data Science",
        "layout": "stat-faculty-member",
        "listing": "https://www.stat.nus.edu.sg/our-people/faculty-members/",
    },
    # Pharmacy: tenure-track-faculty page. <h4> alternates between section
    # headers ("Professors" / "Associate Professors" / "Assistant Professors")
    # and per-person headings prefixed with Prof / A/Prof / Asst Prof.
    {
        "slug": "pharm", "name": "Department of Pharmacy and Pharmaceutical Sciences",
        "layout": "pharm-people-box",
        "listing": "https://pharmacy.nus.edu.sg/people/tenure-track-faculty/",
    },
    # Food Science & Technology: Elementor loop grid on /our-people/.
    # Category-faculty-members cards; name+rank in card text tail.
    {
        "slug": "fst", "name": "Department of Food Science and Technology",
        "layout": "fst-elementor-loop",
        "listing": "https://www.fst.nus.edu.sg/our-people/",
    },
]


# --------------------------------------------------------------------------- #
# cache helpers
# --------------------------------------------------------------------------- #

def _cache_key(url: str, prefix: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"{prefix}_{h}.html"


def _load_cached(url: str, prefix: str) -> str | None:
    p = _cache_key(url, prefix)
    if p.exists() and p.stat().st_size > 5_000:
        return p.read_text(encoding="utf-8", errors="ignore")
    return None


def _save_cached(url: str, prefix: str, html: str) -> None:
    _cache_key(url, prefix).write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Playwright fetch with per-dept warmup
# --------------------------------------------------------------------------- #

def _fetch_html(urls: list[tuple[str, str]]) -> dict[str, str]:
    """urls: list of (url, cache_prefix). Returns {url: html}."""
    # Pull everything we can from cache first.
    out: dict[str, str] = {}
    pending: list[tuple[str, str]] = []
    for url, prefix in urls:
        cached = _load_cached(url, prefix)
        if cached:
            out[url] = cached
        else:
            pending.append((url, prefix))
    if not pending:
        return out

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        warmed: set[str] = set()
        for url, prefix in pending:
            # Warm up the subsite root once (Incapsula scoping).
            host = re.match(r"https?://[^/]+", url).group(0)
            if host not in warmed:
                try:
                    page.goto(host + "/", wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(2_000)
                except Exception as e:
                    print(f"  ! warmup {host} failed: {e}")
                warmed.add(host)
            for attempt in range(3):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(1_500)
                    html = page.content()
                    if len(html) > 20_000:
                        _save_cached(url, prefix, html)
                        out[url] = html
                        break
                    print(f"  ! {url} attempt {attempt+1}: short HTML ({len(html)}B)")
                except Exception as e:
                    print(f"  ! {url} attempt {attempt+1}: {e}")
                time.sleep(1 + attempt)
        browser.close()
    return out


# --------------------------------------------------------------------------- #
# layout parsers
# --------------------------------------------------------------------------- #

_KEEP_RANKS = {"Professor", "Associate Professor", "Assistant Professor"}


def _parse_chem_c_list4(html: str, dept: dict) -> list[dict]:
    """Each faculty is a div.c-list4 with:
       <figure><img src=photo></figure>
       <h5><a href=profile>NAME</a></h5>
       <h6><b>Rank</b>[extra title lines]<br>(research keywords)</h6>
    Faculty are grouped by <h3> rank headings inside the main
    'Faculty' tab (div.tabs-content.active).
    """
    s = BeautifulSoup(html, "html.parser")
    # Restrict to the first (active) tab — "Faculty".
    tab = s.select_one("div.tabs-content.active") or s

    records: list[dict] = []
    # Walk: for each h3 rank header, find following c-list4 cards until
    # the next h3.
    current_rank: str | None = None
    for el in tab.find_all(["h3", "div"]):
        if el.name == "h3":
            rank = clean_text(el.get_text(" "))
            current_rank = rank if rank in _KEEP_RANKS else None
            continue
        if "c-list4" not in (el.get("class") or []):
            continue
        if not current_rank:
            continue

        h5 = el.find("h5")
        if not h5:
            continue
        a = h5.find("a")
        name_raw = clean_text((a or h5).get_text(" "))
        if not name_raw:
            continue
        name = _normalize_chem_name(name_raw)
        profile_url = a.get("href") if a and a.get("href") else ""

        img = el.find("img")
        photo = img.get("src") if img and img.get("src") else ""

        # h6 contains rank + extra titles + research keywords in (...)
        h6 = el.find("h6")
        title_lines: list[str] = []
        research: list[str] = []
        if h6:
            # Split on <br> using get_text with a sentinel newline.
            for br in h6.find_all("br"):
                br.replace_with("\n")
            for ln in h6.get_text("\n").split("\n"):
                ln = clean_text(ln)
                if not ln:
                    continue
                m = re.match(r"^\((.+)\)$", ln)
                if m:
                    research = [clean_text(x) for x in re.split(r"[,;]", m.group(1)) if clean_text(x)]
                else:
                    title_lines.append(ln)

        # Title = first line (rank). Keep additional lines as roles.
        title = title_lines[0] if title_lines else current_rank
        roles = title_lines[1:]

        records.append({
            "name": name,
            "title": title,
            "roles": roles,
            "research_areas": research,
            "profile_url": profile_url,
            "photo_url": photo,
        })
    return records


def _normalize_chem_name(raw: str) -> str:
    """Chemistry lists names as "ANG Wee Han" or "LI Fong Yau, Sam".
    Convert to title case while preserving recognizable comma-separated
    given names: "Ang Wee Han", "Li Fong Yau, Sam"."""
    if "," in raw:
        surname, rest = [p.strip() for p in raw.split(",", 1)]
        return f"{surname.title()}, {rest.title()}"
    return raw.title()


def _match_rank(text: str) -> str | None:
    """Return canonical rank string if `text` matches one of the three kept
    professorial ranks; else None. Accepts 'Full Professor', 'Distinguished
    Professor', 'Provost's Chair Professor' etc. as plain Professor."""
    t = clean_text(text)
    low = t.lower()
    if not low or any(x in low for x in ("adjunct", "visiting", "emeritus",
                                          "honorary", "retired", "educator",
                                          "practice", "teaching", "courtesy")):
        return None
    if "assistant professor" in low:
        return "Assistant Professor"
    if "associate professor" in low or "a/prof" in low or re.search(r"\basst\b", low):
        # crude fallback for "Asst Prof" only — handled above via "assistant"
        if "associate" in low:
            return "Associate Professor"
    if re.search(r"\bassociate professor\b", low):
        return "Associate Professor"
    if re.search(r"\bprofessor\b", low):
        return "Professor"
    return None


def _parse_math_people(html: str, dept: dict) -> list[dict]:
    """Math: <div class="people"> cards. Photo in figure[data-bg],
    name in <h5>, title+roles in <p class="designation">,
    research in '<p><b>Research:</b><span>...</span></p>'."""
    s = BeautifulSoup(html, "html.parser")
    records: list[dict] = []
    for card in s.find_all("div", class_="people"):
        h5 = card.find("h5")
        if not h5:
            continue
        name = _normalize_caps_name(clean_text(h5.get_text(" ")))
        if not name:
            continue

        desig = card.find("p", class_="designation")
        title_lines: list[str] = []
        if desig:
            for br in desig.find_all("br"):
                br.replace_with("\n")
            for ln in desig.get_text("\n").split("\n"):
                ln = clean_text(ln)
                if ln:
                    title_lines.append(ln)
        rank = _match_rank(title_lines[0]) if title_lines else None
        if not rank:
            continue
        title = title_lines[0]
        roles = title_lines[1:]

        fig = card.find("figure")
        photo = fig.get("data-bg") if fig and fig.get("data-bg") else ""

        email_a = card.find("a", href=re.compile(r"^mailto:"))
        email = email_a.get("href", "").replace("mailto:", "").strip() if email_a else ""

        research: list[str] = []
        for p in card.find_all("p"):
            b = p.find("b")
            if b and "research" in b.get_text(" ", strip=True).lower():
                sp = p.find("span")
                txt = clean_text((sp or p).get_text(" "))
                txt = re.sub(r"^Research:?\s*", "", txt, flags=re.I)
                if txt:
                    research = [clean_text(x) for x in re.split(r"[;]|, and ", txt) if clean_text(x)]
                break

        profile_url = ""
        disc = card.find("a", href=re.compile(r"discovery\.nus"))
        if disc:
            profile_url = disc.get("href", "")
        if not profile_url:
            profile_url = f"{dept['listing']}#{slugify(name)}"

        records.append({
            "name": name, "title": title, "roles": roles,
            "research_areas": research,
            "profile_url": profile_url,
            "photo_url": photo,
            "email": email,
        })
    return records


def _parse_phys_memberbox(html: str, dept: dict) -> list[dict]:
    """Physics: <h3> rank-section headers precede a series of
    <a><div.memberPicBox></div><div.memberInfoBox>...</div></a> cards.
    Only a subset of cards have ", Rank" in memberName; for the rest we
    take the rank from the enclosing <h3>. memberName may also carry
    "Courtesy Joint Appointment" / "Practice Track" — skip those."""
    _PHYS_SECTION = {
        "distinguished professors": "Professor",
        "professors": "Professor",
        "associate professors": "Associate Professor",
        "assistant professors": "Assistant Professor",
        "presidential young professors": "Assistant Professor",
    }
    s = BeautifulSoup(html, "html.parser")
    records: list[dict] = []
    current_rank: str | None = None
    # Walk h3s and memberInfoBoxes in document order.
    for el in s.find_all(["h3", "div"]):
        if el.name == "h3":
            sec = clean_text(el.get_text(" ")).lower()
            current_rank = _PHYS_SECTION.get(sec)
            continue
        if "memberInfoBox" not in (el.get("class") or []):
            continue
        if not current_rank:
            continue
        name_el = el.find(class_="memberName")
        if not name_el:
            continue
        raw = clean_text(name_el.get_text(" "))
        if not raw:
            continue
        low = raw.lower()
        if "courtesy joint" in low or "practice track" in low:
            continue

        # Name is everything before the first comma (if any); the rest is
        # extra title info.
        if "," in raw:
            name_part, tail = [x.strip() for x in raw.split(",", 1)]
            extra = [clean_text(x) for x in tail.split(",") if clean_text(x)]
        else:
            name_part, extra = raw, []
        # Strip any "Prof " prefix
        name_part = re.sub(r"^Prof\.?\s+", "", name_part, flags=re.I)
        name = _normalize_caps_name(name_part)
        if not name:
            continue

        wrap = el.find_parent("a")
        profile_url = wrap.get("href", "") if wrap and wrap.get("href") else ""
        img = (wrap or el).find("img")
        photo = img.get("src") if img and img.get("src") else ""

        text = el.get_text(" ", strip=True)
        em = re.search(r"Email:\s*([\w.+-]+@[\w.-]+)", text)
        email = em.group(1) if em else ""

        records.append({
            "name": name, "title": current_rank, "roles": extra,
            "research_areas": [],
            "profile_url": profile_url,
            "photo_url": photo,
            "email": email,
        })
    return records


def _parse_stat_faculty_member(html: str, dept: dict) -> list[dict]:
    """Statistics: div.type-faculty_member cards. h5 = name (with nested
    highlight span), h6 = 'Rank<br>Extra Role', mailto + 'Research Interests:'."""
    s = BeautifulSoup(html, "html.parser")
    records: list[dict] = []
    for card in s.find_all(class_="type-faculty_member"):
        h5 = card.find("h5")
        if not h5:
            continue
        name = _normalize_caps_name(clean_text(h5.get_text(" ")))
        if not name:
            continue

        h6 = card.find("h6")
        title_lines: list[str] = []
        if h6:
            for br in h6.find_all("br"):
                br.replace_with("\n")
            for ln in h6.get_text("\n").split("\n"):
                ln = clean_text(ln)
                if ln:
                    title_lines.append(ln)
        rank = _match_rank(title_lines[0]) if title_lines else None
        if not rank:
            continue

        img = card.find("img")
        photo = img.get("src") if img and img.get("src") else ""

        email_a = card.find("a", href=re.compile(r"^mailto:"))
        email = email_a.get("href", "").replace("mailto:", "").strip() if email_a else ""

        research: list[str] = []
        for p in card.find_all("p"):
            t = p.get_text(" ", strip=True)
            if "Research Interests" in t:
                tail = re.sub(r"^.*Research Interests:\s*", "", t)
                research = [clean_text(x) for x in re.split(r"[,;]", tail) if clean_text(x)]
                break

        # Profile URL: Stats doesn't have per-faculty pages; use the hash anchor.
        profile_url = f"{dept['listing']}#{slugify(name)}"
        portfolio = card.find("a", class_="full-link")
        if portfolio and portfolio.get("href"):
            profile_url = portfolio.get("href").strip()

        records.append({
            "name": name, "title": title_lines[0], "roles": title_lines[1:],
            "research_areas": research,
            "profile_url": profile_url,
            "photo_url": photo,
            "email": email,
        })
    return records


def _parse_pharm_people_box(html: str, dept: dict) -> list[dict]:
    """Pharmacy tenure-track: <h4> alternates between section heading
    ('Professors' / 'Associate Professors' / 'Assistant Professors') and
    per-person names prefixed with 'Prof' / 'A/Prof' / 'Asst Prof'.
    Cards are <li><a><div.people-box-picture><figure><img>...</a>."""
    s = BeautifulSoup(html, "html.parser")
    records: list[dict] = []
    # Each card is an <li> inside the people grid; the outer <a> has the
    # profile URL, img the photo, h4 the prefixed name, <p> the extra roles.
    current_rank: str | None = None
    _section_re = re.compile(r"^(Professors|Associate\s+Professors|Assistant\s+Professors)$", re.I)
    for el in s.find_all(["h4", "li"]):
        if el.name == "h4":
            txt = clean_text(el.get_text(" "))
            m = _section_re.match(txt)
            if m:
                current_rank = {
                    "professors": "Professor",
                    "associate professors": "Associate Professor",
                    "assistant professors": "Assistant Professor",
                }[m.group(1).lower()]
            continue
        if not current_rank:
            continue
        a = el.find("a", href=True)
        if not a:
            continue
        h4 = el.find("h4")
        if not h4:
            continue
        raw = clean_text(h4.get_text(" "))
        # strip rank prefix
        name_raw = re.sub(r"^(Prof\.?|Dr\.?|A/Prof\.?|Asst\s+Prof\.?)\s+", "", raw, flags=re.I)
        name = _normalize_caps_name(name_raw)

        img = a.find("img")
        photo = img.get("src") if img and img.get("src") else ""
        profile_url = a.get("href", "")

        roles: list[str] = []
        p = el.find("p")
        if p:
            for br in p.find_all("br"):
                br.replace_with("\n")
            for ln in p.get_text("\n").split("\n"):
                ln = clean_text(ln)
                if not ln or ln.lower().startswith(("office:", "tel:", "email:")):
                    continue
                roles.append(ln)

        records.append({
            "name": name, "title": current_rank, "roles": roles,
            "research_areas": [],
            "profile_url": profile_url,
            "photo_url": photo,
        })
    return records


def _parse_fst_elementor_loop(html: str, dept: dict) -> list[dict]:
    """FST: Elementor loop grid; each card has class 'category-faculty-members'.
    Card text tail contains: 'More Details <NAME> <Chinese/native> <RANK>
    <extra role>'. A button link goes to /our_people/faculty-members/<slug>/."""
    s = BeautifulSoup(html, "html.parser")
    records: list[dict] = []
    for card in s.find_all(class_="category-faculty-members"):
        # Profile URL (the "Read More" button)
        prof_a = None
        for a in card.find_all("a", href=True):
            if "/our_people/" in a.get("href", "") or "faculty-members" in a.get("href", ""):
                prof_a = a
                break
        profile_url = prof_a.get("href", "").rstrip("/") if prof_a else ""

        img = card.find("img")
        photo = img.get("src") if img and img.get("src") else ""

        # Card text: "More Details NAME CHINESE RANK ROLES..."
        raw = clean_text(card.get_text(" "))
        raw = re.sub(r"^.*?More Details\s*", "", raw, flags=re.I)
        # Try to find a rank keyword and split there
        # Need the earliest rank keyword that represents this person's rank.
        # Pattern: NAME [non-latin chars] RANK ROLE...
        rm = re.search(r"(Professor|Associate Professor|Assistant Professor|Distinguished Professor|Emeritus Professor|Adjunct|Visiting)", raw)
        if not rm:
            continue
        name_raw = raw[:rm.start()].strip()
        tail = raw[rm.start():].strip()
        # Strip trailing non-ascii after name (Chinese characters)
        name_ascii = re.sub(r"[^\x00-\x7f]", " ", name_raw)
        name_ascii = re.sub(r"\s+", " ", name_ascii).strip()
        if not name_ascii:
            continue

        # First rank word
        rank_m = re.match(r"(Associate Professor|Assistant Professor|Professor|Distinguished Professor|Emeritus Professor|Adjunct\s\w+|Visiting\s\w+)", tail)
        if not rank_m:
            continue
        rank_word = rank_m.group(1)
        rank = _match_rank(rank_word)
        if not rank:
            continue
        roles_tail = tail[rank_m.end():].strip()
        roles = [clean_text(roles_tail)] if roles_tail else []

        records.append({
            "name": _normalize_caps_name(name_ascii),
            "title": rank_word, "roles": roles,
            "research_areas": [],
            "profile_url": profile_url,
            "photo_url": photo,
        })
    return records


def _normalize_caps_name(raw: str) -> str:
    """Many NUS sites list names in SURNAME-CAPS format. Convert to
    Title Case while keeping comma-separated given-name clauses."""
    raw = clean_text(raw)
    if not raw:
        return ""
    # Only title-case if the string is mostly uppercase; otherwise leave as-is
    # (handles mixed-case names like 'Chan Hock Peng', 'Antonio Helio CASTRO-NETO').
    letters = [c for c in raw if c.isalpha()]
    if not letters:
        return raw
    upper_frac = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_frac < 0.4:
        return raw
    if "," in raw:
        surname, rest = [p.strip() for p in raw.split(",", 1)]
        return f"{surname.title()}, {rest.title()}"
    return raw.title()


_LAYOUT_PARSERS = {
    "chem-c-list4": _parse_chem_c_list4,
    "math-people": _parse_math_people,
    "phys-memberbox": _parse_phys_memberbox,
    "stat-faculty-member": _parse_stat_faculty_member,
    "pharm-people-box": _parse_pharm_people_box,
    "fst-elementor-loop": _parse_fst_elementor_loop,
}


# --------------------------------------------------------------------------- #
# Profile page enrichment: biography + research interests
# --------------------------------------------------------------------------- #

_RESEARCH_H_RE = re.compile(r"research\s+interest", re.I)
_ORCID_RE = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])")


def _enrich_from_profile(rec: dict, html: str) -> None:
    s = BeautifulSoup(html, "html.parser")
    # Research Interests: h4 heading followed by <p>s until next h-tag.
    for h in s.find_all(["h3", "h4"]):
        if _RESEARCH_H_RE.search(h.get_text(" ", strip=True)):
            paras: list[str] = []
            cur = h.find_next_sibling()
            while cur and cur.name not in ("h1", "h2", "h3", "h4"):
                if cur.name == "p":
                    t = clean_text(cur.get_text(" "))
                    if t:
                        paras.append(t)
                cur = cur.find_next_sibling()
            if paras:
                rec["summary"] = "\n\n".join(paras)
            break

    # ORCID anywhere in the page
    m = _ORCID_RE.search(html)
    if m:
        rec["orcid"] = m.group(1)


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

def _to_faculty(dept: dict, rec: dict) -> Faculty:
    out: Faculty = {
        "id": slugify("nus", dept["slug"], rec["name"]),
        "name": rec["name"],
        "institution": "NUS",
        "department": f"Faculty of Science — {dept['name']}",
        "profile_url": rec["profile_url"],
    }
    if rec.get("title"):
        out["title"] = rec["title"]
    if rec.get("roles"):
        out["roles"] = rec["roles"]
    if rec.get("research_areas"):
        out["research_areas"] = rec["research_areas"]
    if rec.get("summary"):
        out["summary"] = rec["summary"]
    if rec.get("photo_url"):
        out["photo_url"] = rec["photo_url"]
    if rec.get("orcid"):
        out["orcid"] = rec["orcid"]
    if rec.get("email") and "@" in rec["email"]:
        out["email"] = rec["email"]
    return out


def scrape(reparse: bool = False) -> list[Faculty]:
    # Stage 1: fetch all listing pages.
    listing_reqs = [(d["listing"], d["slug"]) for d in DEPARTMENTS]
    if reparse:
        listings = {u: _load_cached(u, p) or "" for u, p in listing_reqs}
    else:
        listings = _fetch_html(listing_reqs)

    # Parse listings -> per-dept records.
    all_records: list[tuple[dict, dict]] = []  # (dept, rec)
    for dept in DEPARTMENTS:
        html = listings.get(dept["listing"], "")
        if not html:
            print(f"[{dept['slug']}] no listing HTML")
            continue
        parser = _LAYOUT_PARSERS[dept["layout"]]
        recs = parser(html, dept)
        print(f"[{dept['slug']}] parsed {len(recs)} faculty from listing")
        for r in recs:
            all_records.append((dept, r))

    # Stage 2: enrich from profile pages. Only chem has well-structured
    # "Research Interests" h4 blocks worth scraping; the other depts either
    # embed research on the listing card or have profile pages with
    # inconsistent markup — skip them to avoid 200+ pointless fetches.
    _ENRICH_LAYOUTS = {"chem-c-list4"}
    profile_reqs = [
        (r["profile_url"], d["slug"])
        for d, r in all_records
        if r.get("profile_url") and r["profile_url"].startswith("http")
        and d["layout"] in _ENRICH_LAYOUTS
    ]
    if reparse:
        profiles = {u: _load_cached(u, p) or "" for u, p in profile_reqs}
    else:
        profiles = _fetch_html(profile_reqs)
    for dept, r in all_records:
        html = profiles.get(r.get("profile_url") or "", "")
        if html:
            _enrich_from_profile(r, html)

    return [_to_faculty(d, r) for d, r in all_records]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparse", action="store_true")
    args = ap.parse_args()

    records = scrape(reparse=args.reparse)
    out_path = OUT_DIR / "nus_sci.json"
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    with_summary = sum(1 for r in records if r.get("summary"))
    with_photo = sum(1 for r in records if r.get("photo_url"))
    print(f"\nWrote {len(records)} records to {out_path}")
    print(f"  with summary: {with_summary}")
    print(f"  with photo:   {with_photo}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
