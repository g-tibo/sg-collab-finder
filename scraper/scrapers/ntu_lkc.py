"""NTU Lee Kong Chian School of Medicine (LKCMedicine).

The faculty A-Z directory renders each person as a 3-column `<tr>`:
    <td><a>Prof / Dr / Assoc Prof NAME</a></td>
    <td>Title line 1<br>Title line 2<br>...</td>
    <td>email</td>

No research interests on the listing page — we keep the multi-line title
block as `roles` so matching still picks up thematic leads (e.g. "Vertical
Theme Lead (Pathology)", "Provost's Chair in Metabolic Disorder").
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers._http import get
from scrapers._ntu_table import _reformat_name
from schema import Faculty, clean_text, slugify


BASE = "https://www.ntu.edu.sg"
URL = f"{BASE}/medicine/our-people/faculty"

_TITLE_PREFIX = re.compile(
    r"^(prof\.?|dr\.?|a/?p|asst\.? prof\.?|assoc\.? prof\.?|ms\.?|mr\.?|mrs\.?)\s+",
    re.I,
)


def _parse_tr(tr) -> Faculty | None:
    tds = tr.find_all("td", recursive=False)
    if len(tds) != 3:
        return None
    name_td, role_td, _ = tds
    link = name_td.find("a")
    if not link:
        return None
    raw = clean_text(link.get_text(" ", strip=True).replace("\u200b", ""))
    raw = _TITLE_PREFIX.sub("", raw)
    if not raw or len(raw.split()) < 2:
        return None
    name = _reformat_name(raw)

    profile_url = link.get("href") or URL
    if profile_url and not profile_url.startswith("http"):
        profile_url = urljoin(BASE, profile_url)

    # Role cell: split on <br> and <div> into lines.
    work = BeautifulSoup(str(role_td), "lxml")
    for br in work.find_all("br"):
        br.replace_with("\n")
    for div in work.find_all("div"):
        div.insert_before("\n")
        div.insert_after("\n")
    lines = [
        clean_text(ln).replace("\u200b", "")
        for ln in work.get_text("\n").split("\n")
        if clean_text(ln)
    ]
    title_line = lines[0] if lines else ""
    short_title = title_line.split(",")[0].strip()
    roles = lines[1:] if len(lines) > 1 else []

    return {
        "id": slugify("ntu", "lkc", name),
        "name": name,
        "institution": "NTU",
        "department": "Lee Kong Chian School of Medicine (LKCMedicine)",
        "title": short_title,
        "roles": roles,
        "research_areas": [],
        "summary": "",
        "email": "",
        "profile_url": profile_url,
        "photo_url": "",
    }


def scrape() -> list[Faculty]:
    html = get(URL)
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    out: list[Faculty] = []
    seen: set[str] = set()
    for tr in soup.find_all("tr"):
        rec = _parse_tr(tr)
        if rec is None or rec["id"] in seen:
            continue
        seen.add(rec["id"])
        out.append(rec)
    print(f"[ntu_lkc] {len(out)} faculty")
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    records = scrape()
    (out_dir / "ntu_lkc.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[ntu_lkc] wrote {len(records)} records")


if __name__ == "__main__":
    main()
