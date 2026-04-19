"""NTU School of Physical and Mathematical Sciences (SPMS) scraper.

Two listing pages — Physics, Maths — both Sitefinity table rows.
"""

from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

from scrapers._http import get
from scrapers._ntu_table import iter_rows, parse_row
from schema import Faculty


BASE = "https://www.ntu.edu.sg"

PAGES = [
    ("Division of Physics and Applied Physics", f"{BASE}/spms/people"),
    ("Division of Mathematical Sciences", f"{BASE}/spms/about-us/mathematics/people"),
]


def scrape() -> list[Faculty]:
    out: list[Faculty] = []
    seen: set[str] = set()
    for dept, url in PAGES:
        html = get(url)
        soup = BeautifulSoup(html, "lxml")
        for s in soup(["script", "style", "noscript"]):
            s.decompose()
        n = 0
        for left, right in iter_rows(soup):
            rec = parse_row(
                right,
                base=BASE,
                institution="NTU",
                department=f"School of Physical and Mathematical Sciences ({dept})",
                id_prefix=("ntu", "spms", "phys" if "Physics" in dept else "math"),
                fallback_profile=url,
                photo_td=left,
            )
            if rec is None or rec["id"] in seen:
                continue
            seen.add(rec["id"])
            out.append(rec)
            n += 1
        print(f"[ntu_spms] {dept}: {n} faculty")
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    records = scrape()
    (out_dir / "ntu_spms.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[ntu_spms] wrote {len(records)} records")


if __name__ == "__main__":
    main()
