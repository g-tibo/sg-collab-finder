"""Small HTTP helper with a disk cache so scrapers are cheap to re-run."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

CACHE_DIR = Path(__file__).resolve().parents[1] / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"{h}.html"


def get(url: str, *, force: bool = False, sleep: float = 0.4) -> str:
    """GET with disk cache. Raises on non-200."""
    p = _cache_path(url)
    if p.exists() and not force:
        return p.read_text(encoding="utf-8", errors="replace")
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}, timeout=30)
    r.raise_for_status()
    p.write_text(r.text, encoding="utf-8")
    if sleep:
        time.sleep(sleep)
    return r.text
