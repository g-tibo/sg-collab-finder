"""NTU Lee Kong Chian School of Medicine (LKCMedicine).

The faculty A-Z directory renders each person as a 3-column `<tr>`:
    <td><a>Prof / Dr / Assoc Prof NAME</a></td>
    <td>Title line 1<br>Title line 2<br>...</td>
    <td>email</td>

No research interests or photos on the listing page. For entries whose
profile link points to DR-NTU we follow through and grab the og:image
headshot from the profile page (disk-cached).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from scrapers._http import get
from scrapers._ntu_table import _reformat_name
from schema import Faculty, clean_text, slugify


BASE = "https://www.ntu.edu.sg"
URL = f"{BASE}/medicine/our-people/faculty"

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
_CRIS_ID_RE = re.compile(r"/cris/rp/(rp\d+)", re.I)
_DISCOVER_URL = "https://dr.ntu.edu.sg/server/api/discover/search/objects?query={}"


def _photo_from_og(url: str) -> str:
    """New-style DR-NTU `/entities/person/<slug>` URLs embed og:image."""
    try:
        html = get(url)
    except Exception:
        return ""
    m = _OG_IMAGE_RE.search(html)
    if not m:
        return ""
    photo = m.group(1)
    if not photo or "default" in photo.lower() or "logo" in photo.lower():
        return ""
    return photo


def _photo_from_cris(rp_id: str) -> str:
    """Old-style `/cris/rp/<rp_id>` URLs are SPAs; follow the DSpace REST API
    to find the person's thumbnail bitstream."""
    try:
        data = json.loads(get(_DISCOVER_URL.format(rp_id)))
        objs = data.get("_embedded", {}).get("searchResult", {}).get("_embedded", {}).get("objects", [])
    except Exception:
        return ""
    for wrapper in objs:
        obj = wrapper.get("_embedded", {}).get("indexableObject", {})
        if obj.get("entityType") != "Person":
            continue
        thumb_href = obj.get("_links", {}).get("thumbnail", {}).get("href")
        if not thumb_href:
            continue
        try:
            thumb = json.loads(get(thumb_href))
        except requests.HTTPError:
            # No thumbnail bitstream (404); skip this person.
            return ""
        except Exception:
            return ""
        return thumb.get("_links", {}).get("content", {}).get("href", "") or ""
    return ""


def _dr_ntu_photo(profile_url: str) -> str:
    if "dr.ntu.edu.sg" not in profile_url:
        return ""
    m = _CRIS_ID_RE.search(profile_url)
    if m:
        return _photo_from_cris(m.group(1))
    return _photo_from_og(profile_url)


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
    print(f"[ntu_lkc] {len(out)} faculty, fetching DR-NTU photos...")

    with_photo = 0
    for rec in out:
        photo = _dr_ntu_photo(rec.get("profile_url", ""))
        if photo:
            rec["photo_url"] = photo
            with_photo += 1
    print(f"[ntu_lkc] attached {with_photo}/{len(out)} photos from DR-NTU")
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
