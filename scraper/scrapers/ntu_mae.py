"""NTU School of Mechanical and Aerospace Engineering (MAE).

Note: the MAE site has the navigation labels swapped — the URL slug
"administrative-staff" actually points to the Faculty listing.
"""

from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

from scrapers._http import get
from scrapers._ntu_table import iter_col_rows, parse_row
from schema import Faculty


BASE = "https://www.ntu.edu.sg"
URL = f"{BASE}/mae/about-us/our-people/administrative-staff"


def scrape() -> list[Faculty]:
    html = get(URL)
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    out: list[Faculty] = []
    seen: set[str] = set()
    for left, right in iter_col_rows(soup):
        rec = parse_row(
            right,
            base=BASE,
            institution="NTU",
            department="School of Mechanical and Aerospace Engineering (MAE)",
            id_prefix=("ntu", "mae"),
            fallback_profile=URL,
            photo_td=left,
        )
        if rec is None or rec["id"] in seen:
            continue
        seen.add(rec["id"])
        out.append(rec)
    print(f"[ntu_mae] {len(out)} faculty")
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    records = scrape()
    (out_dir / "ntu_mae.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[ntu_mae] wrote {len(records)} records")


if __name__ == "__main__":
    main()
