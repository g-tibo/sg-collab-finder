"""Shared parser for NTU "Sitefinity table" faculty pages.

Pages from SPMS, CCEB, ASE, and friends render each faculty as a `<tr>` with
two cells: an image on the left, a free-text block on the right whose first
`<strong>` is the name and whose `<br>`-separated lines carry title, role,
PhD, Profile/Website links, Email, Phone, Office, and Research Interests.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from schema import Faculty, clean_text, slugify, split_keywords


_LABEL_RE = re.compile(r"^\s*(email|phone|office|fax|tel)\s*:\s*", re.I)
_PHD_RE = re.compile(r"^(ph\.?d|d\.?phil|dr\.?\s*rer|m\.?d)\b", re.I)
_RESEARCH_RE = re.compile(r"^research interests?\s*:\s*", re.I)


def _name_from_strong(td: Tag) -> str:
    """The first non-empty <strong> with reasonable length is the display name."""
    for st in td.find_all("strong"):
        t = clean_text(st.get_text(" ", strip=True))
        if t and len(t) < 80 and not _LABEL_RE.match(t) and "research" not in t.lower():
            return t
    return ""


def _reformat_name(name: str) -> str:
    """Convert "BRUNO, Annalisa" / "BEI Xiaohui" to title-cased "Bruno, Annalisa".

    Family-name token in NTU listings is usually ALL CAPS. Capitalize hyphenated
    parts so "MAURER-STROH" -> "Maurer-Stroh".
    """
    parts = name.split()
    fixed = []
    for p in parts:
        if p.isupper() and len(p) > 1:
            stripped = p.rstrip(",")
            tail = "," if stripped != p else ""
            fixed.append("-".join(w.capitalize() for w in stripped.split("-")) + tail)
        else:
            fixed.append(p)
    return " ".join(fixed)


def parse_row(
    td: Tag,
    *,
    base: str,
    institution: str,
    department: str,
    id_prefix: tuple[str, ...],
    fallback_profile: str,
    photo_td: Tag | None = None,
) -> Faculty | None:
    """Parse the info `<td>` of a faculty table row.

    `photo_td` (left cell) is searched for the headshot if provided; otherwise
    we look inside `td` itself.
    """
    raw_name = _name_from_strong(td)
    if not raw_name:
        return None
    raw_name = re.sub(r"\([^)]*\)", "", raw_name).strip(" ,")
    if not raw_name or len(raw_name.split()) < 2:
        return None
    name = _reformat_name(raw_name)

    # Replace <br> with newline so each field is its own line; then walk lines.
    work = BeautifulSoup(str(td), "lxml")
    for br in work.find_all("br"):
        br.replace_with("\n")
    text = work.get_text("\n")
    lines = [clean_text(ln) for ln in text.split("\n") if clean_text(ln)]

    # Drop the leading name line (and any duplicate strong-only lines like
    # "Professor", "Chair" that appear before the first content). Use a
    # heuristic: skip while the line equals the raw_name or is a substring
    # of the raw_name letters.
    title_line = ""
    extra_roles: list[str] = []
    research_interests = ""
    skip_first_name = True
    seen_strong: list[str] = []
    for ln in lines:
        low = ln.lower()
        if skip_first_name and ln.replace(",", "").strip().lower() == raw_name.replace(",", "").strip().lower():
            skip_first_name = False
            continue
        skip_first_name = False
        if ln in ("|", ":", "-"):
            continue
        if _LABEL_RE.match(ln):
            continue  # email/phone/office/fax — we strip these
        if low in ("profile", "website", "read more", "read more...", "profile website"):
            continue
        if _PHD_RE.match(ln):
            continue
        m = _RESEARCH_RE.match(ln)
        if m:
            research_interests = ln[m.end():].strip()
            continue
        # Office line without label (rare)
        if re.match(r"^[NS]\d", ln) or re.match(r"^SPMS-", ln) or re.match(r"^CCEB-", ln):
            continue
        if low.startswith("research team"):
            continue
        # Otherwise it's title / role text
        if not title_line:
            title_line = ln
        else:
            extra_roles.append(ln)
        seen_strong.append(ln)

    short_title = title_line.split(",")[0].strip() if title_line else ""

    # Profile + Website + photo come from the original td, not the cleaned copy.
    profile_url = ""
    lab_url = ""
    for a in td.find_all("a", href=True):
        h = a["href"]
        label = clean_text(a.get_text(" ", strip=True)).lower()
        if "cdn-cgi/l/email" in h:
            continue
        if "dr.ntu.edu.sg" in h and not profile_url:
            profile_url = h
        elif label == "profile" and not profile_url:
            profile_url = urljoin(base, h)
        elif label == "website" and not lab_url:
            lab_url = h if h.startswith("http") else urljoin(base, h)
        elif "research team" in (a.find_previous(string=True) or "").lower() and not lab_url:
            lab_url = h if h.startswith("http") else urljoin(base, h)
    if not profile_url:
        profile_url = fallback_profile

    photo = ""
    img = (photo_td.find("img") if photo_td else None) or td.find("img")
    if img and img.get("src"):
        photo = urljoin(base, img["src"])

    summary_bits: list[str] = []
    if research_interests:
        summary_bits.append("Research interests: " + research_interests)
    summary = " ".join(summary_bits)[:4000]

    research_areas = split_keywords(research_interests)[:8] if research_interests else []

    rec: Faculty = {
        "id": slugify(*id_prefix, name),
        "name": name,
        "institution": institution,
        "department": department,
        "title": short_title,
        "roles": extra_roles,
        "research_areas": research_areas,
        "summary": summary,
        "email": "",
        "profile_url": profile_url,
        "photo_url": photo,
    }
    if lab_url:
        rec["lab_url"] = lab_url
    return rec


def iter_col_rows(soup: BeautifulSoup):
    """Yield (left_col, info_col) for Bootstrap row layouts (col-md-3 + col-md-9).

    Used by some NTU CoE pages (e.g. MAE) where each faculty is rendered as a
    two-column row instead of a `<tr>`.
    """
    for col in soup.select("div.col-md-9.col-sm-12"):
        if not col.find("strong"):
            continue
        text = col.get_text(" ", strip=True).lower()
        if "email" not in text and "profile" not in text:
            continue
        # Sibling col-md-3 holds the photo.
        parent = col.parent
        left = parent.select_one("div.col-md-3.col-sm-12") if parent else None
        yield left, col


def parse_card(card: Tag, *, base: str, institution: str, department: str,
               id_prefix: tuple[str, ...], fallback_profile: str) -> Faculty | None:
    """Parse an `img-card--academic` block (CEE, MSE)."""
    title_a = card.select_one(".img-card__title a")
    if not title_a:
        return None
    raw = clean_text(title_a.get_text(" ", strip=True))
    if not raw:
        return None
    raw = re.sub(r"^(prof\.?|dr\.?|a/?p|asst\.? prof\.?|assoc\.? prof\.?)\s+", "", raw, flags=re.I)
    if not raw or len(raw.split()) < 2:
        return None
    name = _reformat_name(raw)
    profile_url = title_a.get("href") or fallback_profile
    if profile_url and not profile_url.startswith("http"):
        profile_url = urljoin(base, profile_url)

    img = card.select_one(".img-card__img img")
    photo = urljoin(base, img["src"]) if img and img.get("src") else ""

    summary_text = ""
    appointments = ""
    keywords_text = ""
    for desc in card.select(".img-card__desc"):
        label_el = desc.find("strong")
        label = clean_text(label_el.get_text(" ", strip=True)).lower().rstrip(":") if label_el else ""
        # Strip the label out of the desc text.
        body = clean_text(desc.get_text(" ", strip=True))
        if label:
            body = re.sub(rf"^{re.escape(label_el.get_text())}\s*:?\s*", "", body, flags=re.I)
        if "appointment" in label:
            appointments = body
        elif "keyword" in label or "interest" in label:
            interests = desc.select_one(".interests")
            keywords_text = clean_text(interests.get_text(" ", strip=True)) if interests else body
        elif not summary_text:
            summary_text = body

    title_line = appointments.split(",")[0].strip() if appointments else ""
    roles = [appointments] if appointments and appointments != title_line else []
    research_areas = split_keywords(keywords_text)[:8] if keywords_text else []
    summary_parts = []
    if summary_text:
        summary_parts.append(summary_text)
    if keywords_text:
        summary_parts.append("Research interests: " + keywords_text)
    summary = " ".join(summary_parts)[:4000]

    return {
        "id": slugify(*id_prefix, name),
        "name": name,
        "institution": institution,
        "department": department,
        "title": title_line,
        "roles": roles,
        "research_areas": research_areas,
        "summary": summary,
        "email": "",
        "profile_url": profile_url,
        "photo_url": photo,
    }


def parse_profile_row(row: Tag, *, base: str, institution: str, department: str,
                      id_prefix: tuple[str, ...], fallback_profile: str) -> Faculty | None:
    """Parse a `div.profile-row` block (EEE)."""
    name_el = row.select_one(".profile-row-name .name-text") or row.select_one(".profile-row-name a")
    if not name_el:
        return None
    raw = clean_text(name_el.get_text(" ", strip=True))
    raw = re.sub(r"^(prof\.?|dr\.?|a/?p|asst\.? prof\.?|assoc\.? prof\.?)\s+", "", raw, flags=re.I)
    if not raw or len(raw.split()) < 2:
        return None
    name = _reformat_name(raw)
    a = row.select_one(".profile-row-name a")
    profile_url = (a.get("href") if a else "") or fallback_profile
    if profile_url and not profile_url.startswith("http"):
        profile_url = urljoin(base, profile_url)

    img = row.select_one(".profile-row-image-wrap img")
    photo = urljoin(base, img["src"]) if img and img.get("src") else ""

    designation = row.select_one(".profile-row-designation")
    title_line = clean_text(designation.get_text(" ", strip=True)) if designation else ""
    short_title = title_line.split(",")[0].strip()
    roles = [title_line] if title_line and title_line != short_title else []

    # The last <p> in profile-row-org that isn't an office or email is keywords.
    keywords_text = ""
    for p in row.select(".profile-row-org p"):
        if "office" in (p.get("class") or []):
            continue
        if p.find("a", href=lambda h: h and "email-protection" in h):
            continue
        t = clean_text(p.get_text(" ", strip=True))
        if t and not keywords_text:
            keywords_text = t
    research_areas = split_keywords(keywords_text)[:8] if keywords_text else []
    summary = ("Research interests: " + keywords_text)[:4000] if keywords_text else ""

    return {
        "id": slugify(*id_prefix, name),
        "name": name,
        "institution": institution,
        "department": department,
        "title": short_title,
        "roles": roles,
        "research_areas": research_areas,
        "summary": summary,
        "email": "",
        "profile_url": profile_url,
        "photo_url": photo,
    }


def iter_rows(soup: BeautifulSoup):
    """Yield (left_td, info_td) for each faculty row in the page.

    A faculty row is a `<tr>` with exactly two `<td>` children where the right
    cell contains at least one `<strong>` (the name).
    """
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 2:
            continue
        right = tds[1]
        if not right.find("strong"):
            continue
        # Skip header/section rows by requiring at least one Profile/Website
        # link OR an "Email:" label inside the right cell.
        text = right.get_text(" ", strip=True).lower()
        if "email" not in text and "profile" not in text:
            continue
        yield tds[0], right
