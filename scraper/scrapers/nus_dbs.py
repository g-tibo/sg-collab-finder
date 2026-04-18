"""NUS Department of Biological Sciences scraper.

NUS sites sit behind Imperva/Incapsula bot protection, which blocks plain
`requests` (you get a 2xx with a challenge iframe instead of real HTML). There
are two supported modes for this scraper:

1. Lite mode (default): uses a hand-curated faculty index embedded below. This
   produces records with name + title + profile URL only — no research detail.
   Suitable for getting the app running without a browser dependency.

2. Full mode: uses Playwright to render each profile page through a real
   Chromium, which passes the Incapsula challenge. Enable with
   `python -m scrapers.nus_dbs --full`. Requires `pip install playwright &&
   playwright install chromium`.

Refresh strategy: the lite index below is a snapshot. To refresh it without
Playwright, open https://www.dbs.nus.edu.sg/staff/faculty/ in your browser and
paste the updated list into `NUS_DBS_INDEX` below.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from schema import Faculty, clean_text, slugify, split_keywords


# --------------------------------------------------------------------------- #
# Hand-curated index (snapshot from https://www.dbs.nus.edu.sg/staff/faculty/).
# Organised approximately by rank. Keep as (name, title, profile_url).
# --------------------------------------------------------------------------- #

NUS_DBS_INDEX: list[tuple[str, str, str]] = [
    # --- Professors ---
    ("Yu Hao", "Provost's Chair Professor", "https://www.dbs.nus.edu.sg/staffs/yu-hao/"),
    ("Rong Li", "Distinguished Professor", "https://www.dbs.nus.edu.sg/staffs/rong-li/"),
    ("Antonia Monteiro", "Professor", "https://www.dbs.nus.edu.sg/staffs/antonia-monteiro/"),
    ("J. Sivaraman", "Professor", "https://www.dbs.nus.edu.sg/staffs/j-sivaraman/"),
    ("Koh Lian Pin", "Professor", "https://www.nus.edu.sg/cncs/koh-lian-pin/"),
    ("Lok Shee Mei", "Professor", "https://www.dbs.nus.edu.sg/staffs/lok-shee-mei/"),
    ("Peter Ng Kee Lin", "Professor", "https://www.dbs.nus.edu.sg/staffs/peter-ng-kee-lin/"),
    ("Prakash Kumar", "Professor", "https://www.dbs.nus.edu.sg/staffs/prakash-kumar/"),
    ("Stephen Brian Pointing", "Professor", "https://www.dbs.nus.edu.sg/staffs/stephen-brian-pointing/"),
    ("Thorsten Wohland", "Professor", "https://www.dbs.nus.edu.sg/staffs/thorsten-wohland/"),
    ("Yang Daiwen", "Professor", "https://www.dbs.nus.edu.sg/staffs/yang-daiwen/"),
    ("Greg Tucker-Kellogg", "Professor in Practice", "https://www.dbs.nus.edu.sg/staffs/greg-tucker-kellogg/"),
    ("Veerasekaran S/O P Arumugam", "Professor in Practice", "https://www.dbs.nus.edu.sg/staffs/veerasekaran-s-o-p-arumugam/"),
    # --- Associate Professors ---
    ("L. Roman Carrasco", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/l-roman-carrasco/"),
    ("Low Boon Chuan", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/low-boon-chuan/"),
    ("Mok Yu-Keung Henry", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/mok-yu-keung-henry/"),
    ("Lam Siew Hong", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/lam-siew-hong/"),
    ("Lau On Sun", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/lau-on-sun/"),
    ("Chan Woon Khiong", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/chan-woon-khiong/"),
    ("Chew Fook Tim", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/chew-fook-tim/"),
    ("Christoph Winkler", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/christoph-winkler/"),
    ("Cynthia He", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/cynthia-he/"),
    ("Danwei Huang", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/danwei-huang/"),
    ("Darren Yeo Chong Jinn", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/darren-yeo-chong-jinn/"),
    ("Frank Rheindt", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/frank-rheindt/"),
    ("Ge Ruowen", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/ge-ruowen/"),
    ("Liou Yih-Cherng", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/liou-yih-cherng/"),
    ("Loh Ne-Te Duane", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/loh-ne-te-duane/"),
    ("Pan Shen Quan", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/pan-shen-quan/"),
    ("Ryan A. Chisholm", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/ryan-a-chisholm/"),
    ("Sanjay Swarup", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/sanjay-swarup/"),
    ("Todd, Peter Alan", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/todd-peter-alan/"),
    ("Utkur Mirsaidov", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/utkur-mirsaidov/"),
    ("Yusuke Toyama", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/yusuke-toyama/"),
    ("Philip Johns", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/philip-johns/"),
    ("Seow Teck Keong", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/seow-teck-keong/"),
    ("Wu Jinlu", "Associate Professor", "https://www.dbs.nus.edu.sg/staffs/wu-jinlu/"),
    ("Lin Qingsong", "Principal Research Fellow", "https://www.dbs.nus.edu.sg/staffs/lin-qingsong/"),
    # --- Assistant Professors ---
    ("Benjamin Wainwright", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/benjamin-wainwright/"),
    ("Chii Jou (Joe) Chan", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/chii-jou-chan/"),
    ("Eunice Jingmei Tan", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/eunice-jingmei-tan/"),
    ("Hao Tang", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/hao-tang/"),
    ("Hu Chunyi", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/hu-chunyi/"),
    ("Jiao Chunlei", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/jiao-chunlei/"),
    ("Lim Jun Ying", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/lim-jun-ying/"),
    ("Lin Jieshun", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/lin-jieshun/"),
    ("Lin Zhewang", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/lin-zhewang/"),
    ("Long Yuchen", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/long-yuchen/"),
    ("Luo Min", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/luo-min/"),
    ("Nalini Puniamoorthy", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/nalini-puniamoorthy/"),
    ("Phua Siew Cheng", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/phua-siew-cheng/"),
    ("Tan Yong Zi", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/tan-yong-zi/"),
    ("Wei Jiangbo", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/wei-jiangbo/"),
    ("Xue Shifeng", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/xue-shifeng/"),
    ("Ying Chang", "Assistant Professor", "https://www.dbs.nus.edu.sg/staffs/ying-chang/"),
    ("Zeehan Jaafar", "Senior Lecturer", "https://www.dbs.nus.edu.sg/staffs/zeehan-jaafar/"),
]


# --------------------------------------------------------------------------- #

def _lite_record(name: str, title: str, url: str) -> Faculty:
    return Faculty(
        id=slugify("nus", "dbs", name),
        name=clean_text(name).title() if name.isupper() else clean_text(name),
        institution="NUS",
        department="Department of Biological Sciences",
        title=title,
        profile_url=url,
    )


def scrape_lite() -> list[Faculty]:
    return [_lite_record(n, t, u) for n, t, u in NUS_DBS_INDEX]


# --------------------------------------------------------------------------- #
# Full mode — Playwright-based enrichment. Lazy import so the lite path has
# no dependency on Playwright.
# --------------------------------------------------------------------------- #

PROFILE_CSS_FIELDS = {
    "research_interests": [
        "section#research-interests",
        ".research-interests",
        "h2:has-text('Research Interests') + *",
    ],
    "biography": [
        "section#biography",
        ".biography",
        "h2:has-text('Biography') + *",
    ],
}


def _cache_file_for(url: str) -> Path:
    import hashlib
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    d = Path(__file__).resolve().parents[1] / "cache"
    d.mkdir(exist_ok=True)
    return d / f"nus_{h}.html"


def scrape_full(*, reparse_only: bool = False) -> list[Faculty]:
    """Full scrape. Writes rendered HTML to scraper/cache/ so you can tweak the
    parser and rerun with --reparse without hitting the network again.
    """
    records: list[Faculty] = []
    if reparse_only:
        # No network, no browser. Read whatever HTML we have on disk.
        for i, (name, title, url) in enumerate(NUS_DBS_INDEX, 1):
            f = _cache_file_for(url)
            if not f.exists():
                print(f"  [{i:2}/{len(NUS_DBS_INDEX)}] no cache for {name} — skipping (run without --reparse first)")
                records.append(_lite_record(name, title, url))
                continue
            html = f.read_text(encoding="utf-8", errors="replace")
            rec = _parse_nus_profile(name, title, url, html)
            records.append(rec)
            print(
                f"  [{i:2}/{len(NUS_DBS_INDEX)}] {name}: "
                f"{len(rec.get('research_areas', []))} areas, "
                f"{len(rec.get('summary', ''))} chars, "
                f"photo={'y' if rec.get('photo_url') else 'n'}"
            )
        return records

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run:")
        print("  pip install playwright && playwright install chromium")
        sys.exit(1)

    import time
    # Headful (headless=False) is much less likely to trip Incapsula's bot
    # detection. Flip to True by setting HEADLESS=1 in the environment.
    headless_env = __import__("os").environ.get("HEADLESS", "0") == "1"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless_env)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-SG",
        )
        page = ctx.new_page()
        for i, (name, title, url) in enumerate(NUS_DBS_INDEX, 1):
            try:
                page.goto(url, wait_until="load", timeout=60_000)
                try:
                    page.wait_for_selector(
                        "text=/Research Interests?|Lab Information|Research Focus/i",
                        timeout=15_000,
                        state="attached",
                    )
                except Exception:
                    page.wait_for_timeout(3_000)
                html = page.content()
                _cache_file_for(url).write_text(html, encoding="utf-8")
                rec = _parse_nus_profile(name, title, url, html)
                records.append(rec)
                print(
                    f"  [{i:2}/{len(NUS_DBS_INDEX)}] {name}: "
                    f"{len(rec.get('research_areas', []))} areas, "
                    f"{len(rec.get('summary', ''))} chars, "
                    f"photo={'y' if rec.get('photo_url') else 'n'}"
                )
            except Exception as e:
                print(f"  [{i:2}/{len(NUS_DBS_INDEX)}] skip {name}: {e}")
                records.append(_lite_record(name, title, url))
            time.sleep(0.8)
        browser.close()
    return records


def _parse_nus_profile(name: str, title: str, url: str, html: str) -> Faculty:
    """Extract research interests, biography, email, photo from a rendered
    NUS profile page.

    NUS DBS uses a WordPress theme. Profile pages consistently have:
      - an <h3> "Research Interests" followed by paragraphs (with sub-<h4>s
        for specific focus areas that make great keyword tags)
      - a photo at /wp-content/uploads/sites/7/YYYY/MM/<file>.jpg
      - contact info text containing an email
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()

    # --- Research interests --------------------------------------------- #
    # NUS DBS profiles are inconsistent. Headings seen in the wild:
    #   "Research Interests", "Research Areas", "Research Focus", "Research",
    #   "Research Interests and Current Projects", "Major Research Interests",
    #   "Additional Research Interests", "Lab Information", "<Custom Lab Name>".
    # Strategy: (1) strict regex for the common wordings, (2) fall back to the
    # first non-meta heading after the page title if strict fails.
    RESEARCH_HEADING_RE = re.compile(
        r"^(?:"
        r"(?:Additional\s+|Major\s+|Main\s+)?Research\s+Interests?(?:\s+and\s+Current\s+Projects?)?"
        r"|Research\s+Areas?|Research\s+Focus|Research\s+Description|Research"
        r"|Lab(?:oratory)?\s+Information"
        r"|Research\s+and\s+Teaching"
        r")\s*:?\s*$",
        re.I,
    )
    # Headings that mark sections we want to STOP collecting at, and also
    # headings we should ignore entirely when picking a fallback section.
    STOP_HEADING_RE = re.compile(
        r"^(?:Publications?|Selected\s+Publications?|Recent\s+Publications?|Teaching"
        r"|Teaching\s+Areas?|Awards|Honours?|Grants?|Contact|Contact\s+Information"
        r"|Education|Training|Professional\s+Activities|Academic\s+Qualifications"
        r"|Qualifications|Editorial\s+Boards?|Memberships?|Supervisory\s+Roles"
        r"|Appointments?|Career|Biography|About)",
        re.I,
    )

    def _collect_from(h):
        """Collect research paragraphs + h4 sub-topics starting at heading h."""
        h_lvl = int(h.name[1])
        paras: list[str] = []
        subs: list[str] = []
        for sib in h.find_all_next():
            if sib.name in ("h1", "h2", "h3", "h4") and sib is not h:
                sib_text = clean_text(sib.get_text(" ", strip=True))
                if int(sib.name[1]) <= h_lvl:
                    break
                if STOP_HEADING_RE.match(sib_text):
                    break
            if sib.name == "h4":
                sub = clean_text(sib.get_text(" ", strip=True))
                sub = re.sub(r"^\(?\d+\)?[\.\s]+", "", sub).rstrip(":")
                if sub and len(sub) < 80:
                    subs.append(sub)
            elif sib.name in ("p", "li"):
                t = clean_text(sib.get_text(" ", strip=True))
                if t:
                    paras.append(t)
        return paras, subs

    research_paragraphs: list[str] = []
    research_subheads: list[str] = []

    # Pass 1: strict match.
    for h in soup.find_all(["h2", "h3", "h4"]):
        htxt = clean_text(h.get_text(" ", strip=True))
        if RESEARCH_HEADING_RE.match(htxt):
            research_paragraphs, research_subheads = _collect_from(h)
            break

    # Pass 2: fallback. Find the first h2/h3/h4 after the page title that
    # isn't in STOP_HEADING_RE. That's almost always the lab/research
    # description (e.g. "Agri-Environmental Systems Biology Group").
    if not research_paragraphs and not research_subheads:
        for h in soup.find_all(["h2", "h3"]):
            htxt = clean_text(h.get_text(" ", strip=True))
            # Skip the page-title-ish heading (ALL CAPS name), empty, role.
            if not htxt or htxt.isupper() or len(htxt) < 4:
                continue
            if STOP_HEADING_RE.match(htxt):
                continue
            # Skip pure-role headings like "Professor" / "Associate Professor".
            if re.fullmatch(r"(?:Associate |Assistant |Nanyang |Senior )*(?:Professor|Lecturer|Reader|Instructor|Research Fellow|Principal Research Fellow)(?:\s+in\s+Practice)?(?:\s+and\s+[A-Za-z' ]+)?", htxt, re.I):
                continue
            research_paragraphs, research_subheads = _collect_from(h)
            if research_paragraphs or research_subheads:
                break

    # --- Biography ------------------------------------------------------ #
    bio = ""
    for h in soup.find_all(["h2", "h3", "h4"]):
        htxt = clean_text(h.get_text(" ", strip=True))
        if re.fullmatch(r"(Biography|About|Short Bio)", htxt, re.I):
            h_level = int(h.name[1])
            parts: list[str] = []
            for sib in h.find_all_next():
                if sib.name in ("h1", "h2", "h3") and sib is not h:
                    if int(sib.name[1]) <= h_level:
                        break
                if sib.name in ("p", "li"):
                    parts.append(clean_text(sib.get_text(" ", strip=True)))
            bio = "\n".join(parts)
            break

    # --- Photo ---------------------------------------------------------- #
    # Every NUS DBS profile renders the site header which contains
    # `DBS-logo.png` — always the first /wp-content/ image on the page. Skip
    # anything that looks like a logo/banner/nav asset and take the first
    # remaining uploaded image (the faculty headshot).
    PHOTO_BLOCKLIST_RE = re.compile(
        r"(logo|banner|header|footer|icon|nav|placeholder|sprite|dbs-logo)",
        re.I,
    )
    photo_url = ""
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "/wp-content/uploads/" not in src:
            continue
        filename = src.rsplit("/", 1)[-1]
        if PHOTO_BLOCKLIST_RE.search(filename):
            continue
        photo_url = src if src.startswith("http") else f"https://www.dbs.nus.edu.sg{src}"
        break

    # --- Email ---------------------------------------------------------- #
    email = ""
    m = re.search(r"([\w.+-]+@(?:nus\.edu\.sg|u\.nus\.edu|dbs\.nus\.edu\.sg))", soup.get_text(" "))
    if m:
        email = m.group(1)

    summary = bio or "\n\n".join(research_paragraphs[:4])
    # Keyword tags: prefer the h4 sub-heads (specific research areas). Only
    # fall back to splitting the first paragraph on commas if the paragraph
    # looks like a list (short, no sentence punctuation) — otherwise we'd
    # mangle prose like "...from food proteins. This includes identifying,
    # isolating..." into phantom tags.
    research_areas = research_subheads[:8]
    if not research_areas and research_paragraphs:
        first = research_paragraphs[0]
        looks_like_list = (
            len(first) <= 200
            and first.count(".") <= 1
            and ("," in first or ";" in first)
        )
        if looks_like_list:
            research_areas = split_keywords(first)

    return Faculty(
        id=slugify("nus", "dbs", name),
        name=clean_text(name),
        institution="NUS",
        department="Department of Biological Sciences",
        title=title,
        research_areas=research_areas,
        summary=summary,
        email=email,
        profile_url=url,
        photo_url=photo_url,
    )


# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="Use Playwright for full scrape")
    ap.add_argument(
        "--reparse",
        action="store_true",
        help="Skip the network; re-parse already-cached HTML in scraper/cache/.",
    )
    args = ap.parse_args()

    if args.reparse:
        records = scrape_full(reparse_only=True)
    elif args.full:
        records = scrape_full()
    else:
        records = scrape_lite()

    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "nus_dbs.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[nus_dbs] wrote {len(records)} records ({'full' if args.full else 'lite'})")


if __name__ == "__main__":
    main()
