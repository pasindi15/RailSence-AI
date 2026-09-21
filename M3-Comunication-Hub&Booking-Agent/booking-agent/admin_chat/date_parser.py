"""
admin_chat/date_parser.py
-------------------------
Deterministic date parsing and ISO normalization for railway queries.
Operates within the configured project timezone (Asia/Colombo UTC+05:30).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    COLOMBO_TZ = ZoneInfo("Asia/Colombo")
except Exception:
    COLOMBO_TZ = timezone(timedelta(hours=5, minutes=30))


MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def get_current_colombo_date() -> date:
    """Return today's date in Asia/Colombo timezone."""
    return datetime.now(COLOMBO_TZ).date()


def parse_query_date(text: str) -> tuple[date | None, str | None]:
    """
    Deterministically extract and convert a date from natural language query.

    Returns
    -------
    tuple[date | None, str | None]:
        (parsed_date, normalized_iso_string) or (None, None)
    """
    if not text:
        return None, None

    normalized = text.lower()
    today = get_current_colombo_date()

    # 1. Relative keywords
    if re.search(r"\btoday\b", normalized):
        return today, today.isoformat()

    if re.search(r"\btomorrow\b", normalized):
        d = today + timedelta(days=1)
        return d, d.isoformat()

    if re.search(r"\byesterday\b", normalized):
        d = today - timedelta(days=1)
        return d, d.isoformat()

    if re.search(r"\bnext week\b", normalized):
        d = today + timedelta(days=7)
        return d, d.isoformat()

    # 2. ISO format YYYY-MM-DD
    iso_match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if iso_match:
        try:
            d = date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
            return d, d.isoformat()
        except ValueError:
            pass

    # 3. DD/MM/YYYY or DD-MM-YYYY
    dmy_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if dmy_match:
        try:
            d = date(int(dmy_match.group(3)), int(dmy_match.group(2)), int(dmy_match.group(1)))
            return d, d.isoformat()
        except ValueError:
            pass

    # 4. "September 25", "Sep 25", "September 25th", "September 25, 2026"
    month_regex = "|".join(MONTH_MAP.keys())
    m1 = re.search(rf"\b({month_regex})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{{4}}))?\b", normalized)
    if m1:
        month_str = m1.group(1)
        day = int(m1.group(2))
        year = int(m1.group(3)) if m1.group(3) else today.year
        month = MONTH_MAP[month_str]
        try:
            d = date(year, month, day)
            return d, d.isoformat()
        except ValueError:
            pass

    # 5. "25 September", "25th September", "25 Sep 2026"
    m2 = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_regex})(?:\s*,?\s*(\d{{4}}))?\b", normalized)
    if m2:
        day = int(m2.group(1))
        month_str = m2.group(2)
        year = int(m2.group(3)) if m2.group(3) else today.year
        month = MONTH_MAP[month_str]
        try:
            d = date(year, month, day)
            return d, d.isoformat()
        except ValueError:
            pass

    return None, None
