"""NTU College of Computing and Data Science (CCDS).

Pulls the main Faculty list plus Cross Appointments. Adjunct/Visiting are
deferred to merge.py's standard secondary-appointment dedup.
"""

from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

from scrapers._http import get
from scrapers._ntu_table import parse_card
from schema import Faculty


BASE = "https://www.ntu.edu.sg"
PAGES = [
    f"{BASE}/computing/our-people/faculty",
    f"{BASE}/computing/our-people/cross-appointments",
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
        for card in soup.select("div.img-card--academic"):
            rec = parse_card(
                card,
                base=BASE,
                institution="NTU",
                department="College of Computing and Data Science (CCDS)",
                id_prefix=("ntu", "ccds"),
                fallback_profile=url,
            )
            if rec is None or rec["id"] in seen:
                continue
            seen.add(rec["id"])
            out.append(rec)
            n += 1
        print(f"[ntu_ccds] {url.rsplit('/',1)[-1]}: {n}")
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    records = scrape()
    (out_dir / "ntu_ccds.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[ntu_ccds] wrote {len(records)} records")


if __name__ == "__main__":
    main()
