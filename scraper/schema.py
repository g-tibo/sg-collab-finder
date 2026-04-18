"""Shared schema + helpers for faculty records.

Every scraper returns a list of dicts matching this shape. All fields except
`id`, `name`, and `institution` are optional — missing data is better than
wrong data.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TypedDict, NotRequired


class Faculty(TypedDict):
    id: str                                   # stable slug, e.g. "ntu-sbs-thibault-guillaume"
    name: str                                  # display name, e.g. "Guillaume Thibault"
    institution: str                           # top-level, e.g. "NTU", "NUS", "A*STAR"
    department: NotRequired[str]               # school / dept / RI
    title: NotRequired[str]                    # rank, e.g. "Associate Professor"
    roles: NotRequired[list[str]]              # extra roles (e.g. "Associate Dean, ...")
    research_areas: NotRequired[list[str]]     # short keywords
    summary: NotRequired[str]                  # 1-3 paragraphs
    email: NotRequired[str]
    profile_url: str                           # canonical institutional profile
    lab_url: NotRequired[str]                  # personal lab/group site
    scholar_url: NotRequired[str]
    orcid: NotRequired[str]
    photo_url: NotRequired[str]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def slugify(*parts: str) -> str:
    s = "-".join(p for p in parts if p)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ").replace("\u202f", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def split_keywords(s: str) -> list[str]:
    """'ER Stress, UPR; Lipid Homeostasis' -> ['ER Stress', 'UPR', 'Lipid Homeostasis']"""
    if not s:
        return []
    parts = re.split(r"[;,\u2022/|]|\s{2,}", s)
    return [clean_text(p) for p in parts if clean_text(p)]
