#!/usr/bin/env python3
"""
Refresh calendar broadcast providers from ESPN public API.

Usage:
    python scripts/refresh_broadcasts.py
    python scripts/refresh_broadcasts.py --date 2026-09-21
    python -m scripts.refresh_broadcasts --help

Queries ESPN scoreboard for events matching the calendar snapshot (or given date window).
Writes only confident matches to ops/calendar/broadcasts.json (S3 when configured, else local).
Never invents providers. Logs skipped events.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

# Allow running from repo root
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.core.calendar import (
    CalendarStore,
    LOCAL_BROADCASTS_PATH,
    empty_broadcasts,
    get_calendar,
    normalize_broadcasts,
    utc_now,
)
from src.core.s3_store import BucketLayout, get_s3_store

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

ESPN_TIMEOUT = 10
DEFAULT_TZ = "America/New_York"

# ESPN scoreboard API paths for supported sports/leagues
ESPN_ENDPOINTS = {
    "ncaa-football": "football/college-football",
    "premier-league": "soccer/eng.1",
    "champions-league": "soccer/uefa.champions",
    "carabao-cup": "soccer/eng.league_cup",
}


def fetch_espn_scoreboard(sport_path: str, date_str: str) -> Optional[dict[str, Any]]:
    """Fetch ESPN scoreboard for a specific date (YYYYMMDD format)."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard?dates={date_str}"
    try:
        request = Request(url, headers={"User-Agent": "life-ops-calendar/1.0"})
        with urlopen(request, timeout=ESPN_TIMEOUT) as response:
            body = response.read()
        return json.loads(body.decode("utf-8"))
    except Exception as exc:
        logger.warning("Failed to fetch ESPN %s for %s: %s", sport_path, date_str, exc)
        return None


def extract_broadcasts(event: dict[str, Any]) -> list[str]:
    """Extract US TV/streaming provider names from ESPN event. Never invent."""
    providers: list[str] = []
    seen: set[str] = set()
    
    competitions = event.get("competitions") or []
    for comp in competitions:
        if not isinstance(comp, dict):
            continue
        
        # Check broadcasts array
        broadcasts = comp.get("broadcasts") or []
        for bcast in broadcasts:
            if not isinstance(bcast, dict):
                continue
            names = bcast.get("names") or []
            for name in names:
                name_str = str(name).strip()
                if name_str and name_str.lower() not in seen:
                    providers.append(name_str)
                    seen.add(name_str.lower())
        
        # Check geoBroadcasts (typically more detailed)
        geo_broadcasts = comp.get("geoBroadcasts") or []
        for geo in geo_broadcasts:
            if not isinstance(geo, dict):
                continue
            media = geo.get("media") or {}
            if not isinstance(media, dict):
                continue
            short_name = str(media.get("shortName") or "").strip()
            if short_name and short_name.lower() not in seen:
                providers.append(short_name)
                seen.add(short_name.lower())
    
    return providers


def extract_team_ids(event: dict[str, Any]) -> list[str]:
    """Extract team IDs/names from ESPN event for matching."""
    team_ids: list[str] = []
    competitions = event.get("competitions") or []
    for comp in competitions:
        if not isinstance(comp, dict):
            continue
        competitors = comp.get("competitors") or []
        for competitor in competitors:
            if not isinstance(competitor, dict):
                continue
            team = competitor.get("team") or {}
            if not isinstance(team, dict):
                continue
            
            # Use display name, abbreviation, or name
            display = str(team.get("displayName") or "").strip()
            abbrev = str(team.get("abbreviation") or "").strip().lower()
            name = str(team.get("name") or "").strip()
            
            if display:
                team_ids.append(display)
            if abbrev and abbrev not in [t.lower() for t in team_ids]:
                team_ids.append(abbrev)
            if name and name not in team_ids:
                team_ids.append(name)
    
    return team_ids


def extract_title_needles(event: dict[str, Any]) -> list[str]:
    """Extract title keywords from ESPN event for matching."""
    needles: list[str] = []
    name = str(event.get("name") or "").strip()
    short_name = str(event.get("shortName") or "").strip()
    
    competitions = event.get("competitions") or []
    for comp in competitions:
        if not isinstance(comp, dict):
            continue
        competitors = comp.get("competitors") or []
        for competitor in competitors:
            if not isinstance(competitor, dict):
                continue
            team = competitor.get("team") or {}
            if not isinstance(team, dict):
                continue
            display = str(team.get("displayName") or "").strip()
            if display and display not in needles:
                needles.append(display)
    
    if name and name not in needles:
        needles.append(name)
    if short_name and short_name not in needles:
        needles.append(short_name)
    
    return needles[:2]  # Keep top 2 most distinctive needles


def refresh_broadcasts(
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    calendar_snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Refresh broadcast providers from ESPN for given date window or calendar snapshot.
    
    Returns normalized broadcasts.json structure with confident matches only.
    """
    tz = ZoneInfo(DEFAULT_TZ)
    
    if start_date is None:
        start_date = datetime.now(tz).date()
    if end_date is None:
        end_date = start_date + timedelta(days=7)
    
    logger.info("Refreshing broadcasts from %s to %s", start_date, end_date)
    
    entries: list[dict[str, Any]] = []
    current = start_date
    
    while current <= end_date:
        date_str = current.strftime("%Y%m%d")
        logger.info("Fetching ESPN data for %s", current)
        
        for league_id, sport_path in ESPN_ENDPOINTS.items():
            scoreboard = fetch_espn_scoreboard(sport_path, date_str)
            if not scoreboard:
                continue
            
            events = scoreboard.get("events") or []
            logger.info("  %s: found %d events", league_id, len(events))
            
            for event in events:
                if not isinstance(event, dict):
                    continue
                
                providers = extract_broadcasts(event)
                if not providers:
                    logger.debug("  Skipping event (no broadcasts): %s", event.get("name"))
                    continue
                
                team_ids = extract_team_ids(event)
                title_needles = extract_title_needles(event)
                
                entry = {
                    "date": current.isoformat(),
                    "teams": team_ids,
                    "title_contains": title_needles,
                    "providers": providers,
                    "source": f"espn-{league_id}",
                }
                entries.append(entry)
                logger.info(
                    "  Added: %s → %s",
                    " vs ".join(title_needles[:2]) if title_needles else event.get("name"),
                    ", ".join(providers),
                )
        
        current += timedelta(days=1)
    
    logger.info("Collected %d broadcast entries", len(entries))
    
    return {
        "updated_at": utc_now(),
        "timezone": DEFAULT_TZ,
        "entries": entries,
    }


def save_broadcasts(data: dict[str, Any]) -> bool:
    """Save broadcasts.json to S3 (when configured) and local fallback."""
    normalized = normalize_broadcasts(data)
    if normalized is None:
        logger.error("Failed to normalize broadcasts data")
        return False
    
    json_bytes = json.dumps(normalized, indent=2, ensure_ascii=False).encode("utf-8")
    
    # Always write local
    LOCAL_BROADCASTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_BROADCASTS_PATH.write_bytes(json_bytes)
    logger.info("Wrote broadcasts to %s", LOCAL_BROADCASTS_PATH)
    
    # Try S3 if configured
    store = get_s3_store()
    if store.configured:
        try:
            key = BucketLayout.calendar_broadcasts_key()
            BucketLayout.require_ops_key(key)
            store.put_object(
                key,
                json_bytes,
                kind="private_ops",
                content_type="application/json",
            )
            logger.info("Wrote broadcasts to S3: %s", key)
            return True
        except Exception as exc:
            logger.warning("Failed to write broadcasts to S3: %s", exc)
            return False
    else:
        logger.info("S3 not configured; local file only")
        return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh calendar broadcast providers from ESPN"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Start date (YYYY-MM-DD). Default: today",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to fetch. Default: 7",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and display data without writing",
    )
    args = parser.parse_args()
    
    if args.date:
        try:
            start = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error("Invalid date format. Use YYYY-MM-DD")
            return 1
    else:
        start = datetime.now(ZoneInfo(DEFAULT_TZ)).date()
    
    end = start + timedelta(days=args.days - 1)
    
    broadcasts = refresh_broadcasts(start_date=start, end_date=end)
    
    if args.dry_run:
        print(json.dumps(broadcasts, indent=2))
        logger.info("Dry run complete (not saved)")
        return 0
    
    if save_broadcasts(broadcasts):
        logger.info("Broadcast refresh complete")
        return 0
    else:
        logger.error("Failed to save broadcasts")
        return 1


if __name__ == "__main__":
    sys.exit(main())
