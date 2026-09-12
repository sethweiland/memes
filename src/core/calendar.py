"""
Read-only calendar module for Home.

Not a sixth primitive. The contract is a snapshot:

    { updated_at, timezone, events: [{ id, title, start, end, all_day, location, url }] }

S3: ``ops/calendar/snapshot.json``
Local fallback: ``data/calendar/snapshot.json``

If ``CALENDAR_ICS_URL`` is set, fetch that feed, parse VEVENTs into the same
shape, and cache the result as the snapshot. Credentials never go in tenant
YAML. There is no Google OAuth in this app.

Home (America/New_York unless the snapshot says otherwise; zone is not printed):

- This week: now through Sunday, grouped by day
- On the horizon: Monday after this Sunday through ~3 months, grouped by date

Events outside those windows are kept in the snapshot and hidden on Home.
Do not invent events.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrulestr

from src.core.s3_store import BucketLayout, S3Store, get_s3_store
from src.core.tenant import load_tenant


logger = logging.getLogger(__name__)

LOCAL_PATH = Path("data/calendar/snapshot.json")
DEFAULT_TZ = "America/New_York"
ICS_CACHE_SECONDS = 15 * 60
ICS_MAX_BYTES = 1_000_000
ICS_TIMEOUT_SECONDS = 10
EMPTY_SNAPSHOT_MESSAGE = "No calendar snapshot yet."
_UNSET = object()
_STREET_WORD = re.compile(
    r"\b(st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|"
    r"ct|court|pl|place|way|pkwy|parkway|hwy|highway|apt|apartment|"
    r"suite|ste|unit|fl|floor|bldg|building)\.?\b",
    re.I,
)
_HOUSE_NUM = re.compile(r"(?:^|[\s,])\d+[A-Za-z]?\s+\S+")
_CITY_STATE = re.compile(
    r"\b([A-Za-z][A-Za-z .'-]+),\s*[A-Z]{2}(?:\s+\d{5}(?:-\d{4})?)?\b"
)
_IANA_ZONE = re.compile(r"^[A-Za-z]+/[A-Za-z_+\-]+$")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _blank(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_timezone(name: Optional[str]) -> ZoneInfo:
    cleaned = (name or "").strip() or DEFAULT_TZ
    try:
        return ZoneInfo(cleaned)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TZ)


def _parse_iso_datetime(value: Any, tz: ZoneInfo) -> Optional[datetime]:
    text = _blank(value)
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        day = date.fromisoformat(text)
        return datetime(day.year, day.month, day.day, tzinfo=tz)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def normalize_event(raw: Any, *, default_tz: Optional[str] = None) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    title = _blank(raw.get("title"))
    if not title:
        return None
    tz = resolve_timezone(default_tz)
    all_day = bool(raw.get("all_day"))
    start = _parse_iso_datetime(raw.get("start"), tz)
    if start is None:
        return None
    end = _parse_iso_datetime(raw.get("end"), tz)
    if end is None:
        end = start + (timedelta(days=1) if all_day else timedelta(0))
    if end < start:
        end = start
    event_id = _blank(raw.get("id")) or f"{title}:{start.isoformat()}"
    return {
        "id": event_id,
        "title": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "all_day": all_day,
        "location": _blank(raw.get("location")),
        "url": _blank(raw.get("url")),
    }


def normalize_snapshot(data: Any, *, default_tz: Optional[str] = None) -> Optional[dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    tz_name = _blank(data.get("timezone")) or default_tz or DEFAULT_TZ
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_events = data.get("events")
    if raw_events is None:
        raw_events = []
    if not isinstance(raw_events, list):
        return None
    for raw in raw_events:
        event = normalize_event(raw, default_tz=tz_name)
        if not event or event["id"] in seen:
            continue
        seen.add(event["id"])
        events.append(event)
    events.sort(key=lambda item: (item["start"], item["title"].casefold()))
    return {
        "updated_at": _blank(data.get("updated_at")),
        "timezone": tz_name,
        "events": events,
    }


def empty_snapshot(*, timezone_name: Optional[str] = None) -> dict[str, Any]:
    return {
        "updated_at": None,
        "timezone": timezone_name or DEFAULT_TZ,
        "events": [],
    }


def _hydrate(event: dict[str, Any], tz: ZoneInfo) -> Optional[dict[str, Any]]:
    start = _parse_iso_datetime(event.get("start"), tz)
    end = _parse_iso_datetime(event.get("end"), tz)
    if start is None:
        return None
    if end is None:
        end = start + (timedelta(days=1) if event.get("all_day") else timedelta(0))
    hydrated = dict(event)
    hydrated["_start"] = start
    hydrated["_end"] = end
    return hydrated


def this_week_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    now = now.astimezone(tz)
    days_until_sunday = (6 - now.weekday()) % 7
    sunday = now.date() + timedelta(days=days_until_sunday)
    week_end = datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59, 999999, tzinfo=tz)
    return now, week_end


def horizon_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Horizon starts the Monday after this week's Sunday, not 14 days out."""
    now = now.astimezone(tz)
    _week_start, week_end = this_week_bounds(now, tz)
    next_day = week_end.date() + timedelta(days=1)
    horizon_start = datetime(next_day.year, next_day.month, next_day.day, tzinfo=tz)
    return horizon_start, now + relativedelta(months=3)


def _in_this_week(event: dict[str, Any], now: datetime, week_end: datetime) -> bool:
    start: datetime = event["_start"]
    end: datetime = event["_end"]
    if event.get("all_day"):
        window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        window_start = now
    return start <= week_end and end >= window_start


def _in_horizon(event: dict[str, Any], horizon_start: datetime, horizon_end: datetime) -> bool:
    start: datetime = event["_start"]
    if event.get("all_day"):
        return horizon_start.date() <= start.date() <= horizon_end.date()
    return horizon_start <= start <= horizon_end


def _day_label(value: datetime | date) -> str:
    if isinstance(value, datetime):
        return f"{value.strftime('%a %b')} {value.day}"
    return f"{value.strftime('%a %b')} {value.day}"


def _week_day_heading(value: date, *, include_month: bool) -> str:
    weekday = value.strftime("%a")
    if include_month:
        return f"{weekday} {value.strftime('%b')} {value.day}"
    return f"{weekday} {value.day}"


def _each_date(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


def _time_label(value: datetime) -> str:
    hour = value.hour % 12 or 12
    suffix = "AM" if value.hour < 12 else "PM"
    if value.minute == 0:
        return f"{hour} {suffix}"
    return f"{hour}:{value.minute:02d} {suffix}"


def _format_event_when(event: dict[str, Any], tz: ZoneInfo) -> str:
    """Time only — day lives on the section header, never the zone name."""
    start: datetime = event["_start"].astimezone(tz)
    end: datetime = event["_end"].astimezone(tz)
    if event.get("all_day"):
        last = (end - timedelta(microseconds=1)).date() if end.date() > start.date() else start.date()
        if last <= start.date():
            return "All day"
        return f"through {_day_label(last)}"
    start_t = _time_label(start)
    if start.date() == end.date() and end > start:
        end_t = _time_label(end)
        if start_t[-2:] == end_t[-2:] and start_t.endswith(("AM", "PM")):
            return f"{start_t[:-3]}–{end_t}"
        return f"{start_t}–{end_t}"
    if end.date() > start.date() and end > start:
        return f"{start_t} – {_day_label(end)}"
    return start_t


def _norm_place(value: str) -> str:
    text = value.casefold()
    for src, dst in (("→", "->"), ("⟶", "->"), ("–", "-"), ("—", "-"), ("\u00a0", " ")):
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_street_address(text: str) -> bool:
    if _STREET_WORD.search(text) and _HOUSE_NUM.search(text):
        return True
    first = re.split(r"[\n,]", text, 1)[0].strip()
    return bool(re.match(r"^\d+\s+.+", first) and ("," in text or "\n" in text))


def present_location(title: str, location: Optional[str]) -> Optional[str]:
    """Venue or city for Home. Hide title repeats and apartment street dumps."""
    loc = _blank(location)
    if not loc:
        return None
    loc = loc.replace("\r\n", "\n").strip()
    if _IANA_ZONE.fullmatch(loc):
        return None
    normalized_loc = _norm_place(loc)
    normalized_title = _norm_place(title)
    if normalized_loc == normalized_title:
        return None
    if len(normalized_loc) >= 4 and normalized_loc in normalized_title:
        return None
    if not _looks_like_street_address(loc):
        return loc
    parts = [part.strip() for part in re.split(r"[\n,]", loc) if part.strip()]
    first = parts[0] if parts else ""
    if first and not re.match(r"^\d+\s+", first) and not _STREET_WORD.search(first):
        return first
    match = _CITY_STATE.search(loc)
    if match:
        return match.group(1).strip()
    for part in reversed(parts):
        if re.fullmatch(r"\d{5}(?:-\d{4})?", part):
            continue
        if re.fullmatch(r"[A-Z]{2}", part):
            continue
        if re.fullmatch(r"(?:apt|apartment|suite|ste|unit|fl|floor)\s*\S+", part, re.I):
            continue
        if _STREET_WORD.search(part) or re.match(r"^\d+\s+", part):
            continue
        return part
    return None


def _present_event(event: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    title = event["title"]
    return {
        "id": event["id"],
        "title": title,
        "start": event["start"],
        "end": event["end"],
        "all_day": bool(event.get("all_day")),
        "location": present_location(title, event.get("location")),
        "url": event.get("url"),
        "when_label": _format_event_when(event, tz),
    }


def _placement_date(event: dict[str, Any], tz: ZoneInfo, floor: Optional[date] = None) -> date:
    start = event["_start"].astimezone(tz).date()
    if floor and start < floor:
        return floor
    return start


def _group_week_days(
    hydrated: list[dict[str, Any]],
    clock: datetime,
    week_end: datetime,
    tz: ZoneInfo,
) -> list[dict[str, Any]]:
    today = clock.astimezone(tz).date()
    last = week_end.astimezone(tz).date()
    include_month = today.month != last.month or today.year != last.year
    buckets: dict[date, list[dict[str, Any]]] = {day: [] for day in _each_date(today, last)}
    for event in hydrated:
        day = _placement_date(event, tz, today)
        if day not in buckets:
            day = today if day < today else last
        buckets[day].append(_present_event(event, tz))
    return [
        {
            "date": day.isoformat(),
            "label": _week_day_heading(day, include_month=include_month),
            "is_today": day == today,
            "events": buckets[day],
        }
        for day in _each_date(today, last)
    ]


def _group_horizon_days(hydrated: list[dict[str, Any]], tz: ZoneInfo) -> list[dict[str, Any]]:
    buckets: dict[date, list[dict[str, Any]]] = {}
    for event in hydrated:
        day = _placement_date(event, tz)
        buckets.setdefault(day, []).append(_present_event(event, tz))
    return [
        {
            "date": day.isoformat(),
            "label": _day_label(day),
            "events": buckets[day],
        }
        for day in sorted(buckets)
    ]


def split_home_events(
    snapshot: Optional[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    timezone_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Split a snapshot into This week vs On the horizon.

    Does not invent events. Items outside the two windows are omitted.
    """
    tz = resolve_timezone(
        timezone_name
        or (snapshot or {}).get("timezone")
        or DEFAULT_TZ
    )
    clock = (now or datetime.now(tz)).astimezone(tz)
    _week_start, week_end = this_week_bounds(clock, tz)
    horizon_start, horizon_end = horizon_bounds(clock, tz)
    has_snapshot = snapshot is not None
    events = list((snapshot or {}).get("events") or []) if has_snapshot else []

    this_week_hydrated: list[dict[str, Any]] = []
    horizon_hydrated: list[dict[str, Any]] = []
    for raw in events:
        hydrated = _hydrate(raw, tz)
        if hydrated is None:
            continue
        if _in_this_week(hydrated, clock, week_end):
            this_week_hydrated.append(hydrated)
        elif _in_horizon(hydrated, horizon_start, horizon_end):
            horizon_hydrated.append(hydrated)

    this_week = [_present_event(event, tz) for event in this_week_hydrated]
    horizon = [_present_event(event, tz) for event in horizon_hydrated]
    return {
        "has_snapshot": has_snapshot,
        "updated_at": (snapshot or {}).get("updated_at") if has_snapshot else None,
        "timezone": tz.key,
        "this_week": this_week,
        "horizon": horizon,
        "this_week_days": _group_week_days(this_week_hydrated, clock, week_end, tz)
        if has_snapshot
        else [],
        "horizon_days": _group_horizon_days(horizon_hydrated, tz) if has_snapshot else [],
        "this_week_label": "",
        "horizon_label": "",
        "empty_message": None if has_snapshot else EMPTY_SNAPSHOT_MESSAGE,
    }


def _ics_unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _unfold_ics(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
            continue
        lines.append(raw)
    return lines


def _split_ics_prop(line: str) -> tuple[str, dict[str, str], str]:
    if ":" not in line:
        return "", {}, ""
    head, value = line.split(":", 1)
    parts = head.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for item in parts[1:]:
        if "=" not in item:
            continue
        key, val = item.split("=", 1)
        params[key.upper()] = val
    return name, params, value


def _parse_ics_dt(value: str, params: dict[str, str], default_tz: ZoneInfo) -> tuple[Optional[datetime], bool]:
    raw = (value or "").strip()
    if not raw:
        return None, False
    tzid = params.get("TZID")
    try:
        tz = ZoneInfo(tzid) if tzid else default_tz
    except ZoneInfoNotFoundError:
        tz = default_tz
    value_date = params.get("VALUE", "").upper() == "DATE" or (
        len(raw) == 8 and raw.isdigit()
    )
    try:
        if value_date:
            day = datetime.strptime(raw[:8], "%Y%m%d").date()
            return datetime(day.year, day.month, day.day, tzinfo=tz), True
        if raw.endswith("Z"):
            stamp = raw[:-1]
            fmt = "%Y%m%dT%H%M%S" if len(stamp) >= 15 else "%Y%m%dT%H%M"
            parsed = datetime.strptime(stamp[:15] if len(stamp) >= 15 else stamp, fmt)
            return parsed.replace(tzinfo=timezone.utc), False
        fmt = "%Y%m%dT%H%M%S" if len(raw) >= 15 else "%Y%m%dT%H%M"
        parsed = datetime.strptime(raw[:15] if len(raw) >= 15 else raw, fmt)
        return parsed.replace(tzinfo=tz), False
    except ValueError:
        return None, False


def _parse_ics_duration(value: str) -> Optional[timedelta]:
    match = re.fullmatch(
        r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
        (value or "").strip(),
    )
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def _parse_exdates(value: str, params: dict[str, str], default_tz: ZoneInfo) -> list[datetime]:
    out: list[datetime] = []
    for chunk in (value or "").split(","):
        parsed, _all_day = _parse_ics_dt(chunk, params, default_tz)
        if parsed is not None:
            out.append(parsed)
    return out


def parse_ics(
    text: str,
    *,
    timezone_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Parse VEVENTs into the snapshot shape. No invented titles."""
    tz = resolve_timezone(timezone_name)
    clock = (now or datetime.now(tz)).astimezone(tz)
    window_start = clock.replace(hour=0, minute=0, second=0, microsecond=0)
    window_end = clock + relativedelta(months=3)
    events: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        block = current
        current = None
        if str(block.get("STATUS") or "").upper() == "CANCELLED":
            return
        title = _blank(_ics_unescape(str(block.get("SUMMARY") or "")))
        if not title:
            return
        start, all_day = block.get("_start") or (None, False)
        if start is None:
            return
        end = block.get("_end")
        duration = block.get("_duration")
        if end is None and duration is not None:
            end = start + duration
        if end is None:
            end = start + (timedelta(days=1) if all_day else timedelta(0))
        uid = _blank(block.get("UID")) or title
        location = _blank(_ics_unescape(str(block.get("LOCATION") or "")))
        url = _blank(block.get("URL"))
        rrule = _blank(block.get("RRULE"))
        exdates: list[datetime] = list(block.get("_exdates") or [])
        occurrences: list[datetime]
        if rrule:
            try:
                rule = rrulestr(f"RRULE:{rrule}", dtstart=start)
                occurrences = list(rule.between(window_start, window_end, inc=True))
            except (ValueError, TypeError) as exc:
                logger.warning("Skipping unreadable RRULE: %s", exc)
                occurrences = [start] if window_start <= start <= window_end else []
        else:
            occurrences = [start]
        length = end - start
        exset = {item.astimezone(timezone.utc).replace(microsecond=0) for item in exdates}
        for occ in occurrences:
            key = occ.astimezone(timezone.utc).replace(microsecond=0)
            if key in exset:
                continue
            occ_end = occ + length
            event_id = uid if not rrule else f"{uid}:{occ.isoformat()}"
            events.append(
                {
                    "id": event_id,
                    "title": title,
                    "start": occ.isoformat(),
                    "end": occ_end.isoformat(),
                    "all_day": all_day,
                    "location": location,
                    "url": url,
                }
            )

    for line in _unfold_ics(text):
        name, params, value = _split_ics_prop(line)
        if name == "BEGIN" and value.strip().upper() == "VEVENT":
            current = {"_exdates": []}
            continue
        if name == "END" and value.strip().upper() == "VEVENT":
            flush()
            continue
        if current is None or not name:
            continue
        if name == "DTSTART":
            current["_start"] = _parse_ics_dt(value, params, tz)
        elif name == "DTEND":
            parsed, _all_day = _parse_ics_dt(value, params, tz)
            current["_end"] = parsed
        elif name == "DURATION":
            current["_duration"] = _parse_ics_duration(value)
        elif name == "EXDATE":
            current["_exdates"].extend(_parse_exdates(value, params, tz))
        else:
            current[name] = value

    flush()
    snapshot = normalize_snapshot(
        {"updated_at": utc_now(), "timezone": tz.key, "events": events},
        default_tz=tz.key,
    )
    return snapshot or empty_snapshot(timezone_name=tz.key)


def calendar_ics_url(explicit: Optional[str] = None) -> Optional[str]:
    if explicit is not None:
        return _blank(explicit)
    return _blank(os.environ.get("CALENDAR_ICS_URL"))


def fetch_ics(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("CALENDAR_ICS_URL must be http or https")
    request = Request(url, headers={"User-Agent": "life-ops-calendar/1.0"})
    with urlopen(request, timeout=ICS_TIMEOUT_SECONDS) as response:
        body = response.read(ICS_MAX_BYTES + 1)
    if len(body) > ICS_MAX_BYTES:
        raise ValueError("ICS feed is larger than 1MB")
    return body.decode("utf-8", errors="replace")


def _snapshot_age_seconds(snapshot: Optional[dict[str, Any]], now: datetime) -> Optional[float]:
    if not snapshot or not snapshot.get("updated_at"):
        return None
    updated = _parse_iso_datetime(snapshot.get("updated_at"), now.tzinfo or timezone.utc)
    if updated is None:
        return None
    return (now.astimezone(updated.tzinfo) - updated).total_seconds()


class CalendarStore:
    """
    Snapshot reader with optional ICS refresh.

    Writes only happen when an ICS fetch succeeds (cache). Agents may also
    write ``ops/calendar/snapshot.json`` directly.
    """

    def __init__(
        self,
        store: Optional[S3Store] = None,
        local_path: Optional[Path] = None,
        timezone_name: Optional[str] = None,
        ics_url: Any = _UNSET,
        now: Optional[datetime] = None,
    ):
        self.store = store or S3Store()
        self.local_path = local_path or LOCAL_PATH
        self._timezone_name = timezone_name
        self._ics_url = calendar_ics_url() if ics_url is _UNSET else _blank(ics_url)
        self._now = now

    def timezone_name(self) -> str:
        if self._timezone_name:
            return self._timezone_name
        try:
            return load_tenant().timezone or DEFAULT_TZ
        except Exception:
            return DEFAULT_TZ

    def s3_key(self) -> str:
        key = BucketLayout.calendar_snapshot_key()
        BucketLayout.require_ops_key(key)
        if key.startswith(BucketLayout.PUBLIC_PREFIX):
            raise ValueError("Calendar snapshot must never be written under public/")
        return key

    def save(self, data: dict[str, Any]) -> bool:
        normalized = normalize_snapshot(data, default_tz=self.timezone_name())
        if normalized is None:
            raise ValueError("Calendar snapshot must be {updated_at, timezone, events}")
        if not normalized.get("updated_at"):
            normalized["updated_at"] = utc_now()
        json_bytes = json.dumps(normalized, indent=2, ensure_ascii=False).encode("utf-8")
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_bytes(json_bytes)
        if not self.store.configured:
            return False
        try:
            self.store.put_object(
                self.s3_key(),
                json_bytes,
                kind="private_ops",
                content_type="application/json",
            )
            return True
        except Exception as exc:
            logger.warning("Failed to save calendar snapshot to S3: %s", exc)
            return False

    def _load_local(self) -> Optional[dict[str, Any]]:
        if not self.local_path.exists():
            return None
        try:
            data = json.loads(self.local_path.read_text(encoding="utf-8"))
            return normalize_snapshot(data, default_tz=self.timezone_name())
        except Exception as exc:
            logger.error("Failed to load local calendar snapshot: %s", exc)
            return None

    def load_snapshot(self) -> Optional[dict[str, Any]]:
        if self.store.configured:
            try:
                result = self.store.get_json(self.s3_key())
                if result:
                    data, _etag = result
                    normalized = normalize_snapshot(data, default_tz=self.timezone_name())
                    if normalized is not None:
                        return normalized
            except Exception as exc:
                logger.warning("Failed to load calendar snapshot from S3: %s", exc)
        return self._load_local()

    def refresh_from_ics(
        self,
        *,
        now: Optional[datetime] = None,
        ics_text: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        url = self._ics_url
        if not url and ics_text is None:
            return None
        tz_name = self.timezone_name()
        clock = now or datetime.now(resolve_timezone(tz_name))
        text = ics_text if ics_text is not None else fetch_ics(url or "")
        snapshot = parse_ics(text, timezone_name=tz_name, now=clock)
        self.save(snapshot)
        return snapshot

    def load(self, *, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
        existing = self.load_snapshot()
        if not self._ics_url:
            return existing
        tz = resolve_timezone(self.timezone_name())
        clock = (now or datetime.now(tz)).astimezone(tz)
        age = _snapshot_age_seconds(existing, clock)
        if existing is not None and age is not None and 0 <= age < ICS_CACHE_SECONDS:
            return existing
        try:
            return self.refresh_from_ics(now=clock)
        except Exception as exc:
            logger.warning("Calendar ICS fetch failed; using last snapshot: %s", exc)
            return existing

    def home_lists(self, *, now: Optional[datetime] = None) -> dict[str, Any]:
        clock = now or self._now
        snapshot = self.load(now=clock)
        return split_home_events(
            snapshot,
            now=clock,
            timezone_name=self.timezone_name(),
        )


_calendar: Optional[CalendarStore] = None


def get_calendar() -> CalendarStore:
    global _calendar
    if _calendar is None:
        _calendar = CalendarStore(store=get_s3_store())
    return _calendar


def reset_calendar(calendar: Optional[CalendarStore] = None) -> None:
    """Clear or replace the process-wide calendar store (tests)."""
    global _calendar
    _calendar = calendar
