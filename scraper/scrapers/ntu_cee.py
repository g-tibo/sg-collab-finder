"""NTU School of Civil and Environmental Engineering (CEE)."""

from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

from scrapers._http import get
from scrapers._ntu_table import parse_card
from schema import Faculty


BASE = "https://www.ntu.edu.sg"
URL = f"{BASE}/cee/about-us/our-people/faculty"


def scrape() -> list[Faculty]:
    html = get(URL)
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    out: list[Faculty] = []
    seen: set[str] = set()
    for card in soup.select("div.img-card--academic"):
        rec = parse_card(
            card,
            base=BASE,
            institution="NTU",
            department="School of Civil and Environmental Engineering (CEE)",
            id_prefix=("ntu", "cee"),
            fallback_profile=URL,
        )
        if rec is None or rec["id"] in seen:
            continue
        seen.add(rec["id"])
        out.append(rec)
    print(f"[ntu_cee] {len(out)} faculty")
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "out"
    out_dir.mkdir(exist_ok=True)
    records = scrape()
    (out_dir / "ntu_cee.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[ntu_cee] wrote {len(records)} records")


if __name__ == "__main__":
    main()
