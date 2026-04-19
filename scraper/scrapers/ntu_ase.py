"""NTU Asian School of the Environment (ASE) scraper.

The /ase/research/faculty-directory page is JS-rendered and empty in static
HTML. We scrape /ase/aboutus/staff-directory instead — same Sitefinity table
pattern as SPMS/CCEB, but without an outer <tbody>'s recursive=False
guarantee, so we accept rows whose <td>s are direct children.
"""

from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

from scrapers._http import get
from scrapers._ntu_table import iter_rows, parse_row
from schema import Faculty


BASE = "https://www.ntu.edu.sg"
INDEX = f"{BASE}/ase/aboutus/staff-directory"
PAGES = [
    f"{INDEX}/management-team",
    f"{INDEX}/faculty",
]


def scrape() -> list[Faculty]:
    out: list[Faculty] = []
    seen: set[str] = set()
    for url in PAGES:
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
                department="Asian School of the Environment (ASE)",
                id_prefix=("ntu", "ase"),
                fallback_profile=url,
                photo_td=left,
            )
            if rec is None or rec["id"] in seen:
                continue
            seen.add(rec["id"])
            out.append(rec)
            n += 1
        print(f"[ntu_ase] {url.rsplit('/',1)[-1]}: {n}")
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    records = scrape()
    (out_dir / "ntu_ase.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[ntu_ase] wrote {len(records)} records")


if __name__ == "__main__":
    main()
