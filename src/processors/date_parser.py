"""Date parsing and UTC normalization utility for pipeline intelligence entities."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Optional, Union

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

import dateutil.parser


def parse_to_utc(raw_date: Union[str, int, float, None]) -> Optional[datetime]:
    """Parse various date formats (RFC 2822, ISO 8601, UNIX epoch) into timezone-aware UTC datetime.

    Returns None if parsing fails, string is empty, or input is invalid.
    """
    if raw_date is None or raw_date == "":
        return None

    # Handle UNIX epoch timestamps (int or float)
    if isinstance(raw_date, (int, float)):
        try:
            # If timestamp is in milliseconds (> 1e11), convert to seconds
            ts = raw_date / 1000.0 if raw_date > 1e11 else float(raw_date)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    if isinstance(raw_date, str):
        raw_str = raw_date.strip()
        if not raw_str:
            return None

        # Check if string contains only digits (epoch timestamp as string)
        if raw_str.isdigit():
            try:
                ts = int(raw_str)
                ts = ts / 1000.0 if ts > 1e11 else float(ts)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                pass

        try:
            dt = dateutil.parser.parse(raw_str)
            if dt.tzinfo is None:
                # If naive, assume UTC
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except (ValueError, TypeError, OverflowError):
            return None

    return None


def parse_to_utc_iso(raw_date: Union[str, int, float, None]) -> Optional[str]:
    """Parse a date into standard ISO-8601 UTC string (e.g. '2026-11-22T04:05:12Z')."""
    dt = parse_to_utc(raw_date)
    if dt:
        return dt.isoformat()
    return None


def is_within_last_24_hours(
    dt: Union[datetime, str, int, float, None],
    reference_time: Optional[datetime] = None,
    future_tolerance_minutes: int = 60,
) -> bool:
    """Check if the given datetime is strictly within the last 24 hours of reference_time (default now UTC)."""
    if not dt:
        return False

    if isinstance(dt, (str, int, float)):
        parsed_dt = parse_to_utc(dt)
        if not parsed_dt:
            return False
        dt = parsed_dt

    ref = reference_time or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    oldest_allowed = ref - timedelta(hours=24)
    newest_allowed = ref + timedelta(minutes=future_tolerance_minutes)

    return oldest_allowed <= dt <= newest_allowed
