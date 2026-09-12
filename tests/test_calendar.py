"""Calendar snapshot / ICS — Home This week vs horizon. No invented events."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, Flask

import tests.bootstrap  # noqa: F401

from src.core.calendar import (
    EMPTY_SNAPSHOT_MESSAGE,
    CalendarStore,
    horizon_bounds,
    normalize_event,
    normalize_snapshot,
    parse_ics,
    present_location,
    reset_calendar,
    split_home_events,
)
from src.core.project_board import ProjectBoard, reset_project_board
from src.core.s3_store import BucketLayout
from src.core.tenant import load_tenant_from_path, reset_tenant
from tests.fakes import MemoryS3Store
from web.blueprints.home import bp as home_bp


_ROOT = Path(__file__).resolve().parents[1]
_WEB_ROOT = _ROOT / "web"
_SETH = Path(__file__).resolve().parent / "fixtures" / "seth_tenant.yaml"
ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=ET)

SNAPSHOT_EVENTS = [
    {
        "id": "past-standup",
        "title": "Past standup",
        "start": "2026-09-11T10:00:00-04:00",
        "end": "2026-09-11T10:30:00-04:00",
        "all_day": False,
    },
    {
        "id": "saturday-dinner",
        "title": "Saturday dinner",
        "start": "2026-09-12T18:00:00-04:00",
        "end": "2026-09-12T20:00:00-04:00",
        "all_day": False,
        "location": "Home",
    },
    {
        "id": "sunday-hike",
        "title": "Sunday hike",
        "start": "2026-09-13",
        "end": "2026-09-14",
        "all_day": True,
    },
    {
        "id": "next-friday",
        "title": "Next Friday gap",
        "start": "2026-09-18T09:00:00-04:00",
        "end": "2026-09-18T10:00:00-04:00",
        "all_day": False,
    },
    {
        "id": "october-trip",
        "title": "October trip",
        "start": "2026-10-05T09:00:00-04:00",
        "end": "2026-10-08T18:00:00-04:00",
        "all_day": False,
        "url": "https://example.com/trip",
    },
    {
        "id": "far-away",
        "title": "Far away",
        "start": "2027-03-01T12:00:00-05:00",
        "end": "2027-03-01T13:00:00-05:00",
        "all_day": False,
    },
]


def _nav_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(_WEB_ROOT / "templates"),
        static_folder=str(_WEB_ROOT / "static"),
    )
    app.secret_key = "test"
    for name, endpoint, path in (
        ("projects", "index", "/projects/"),
        ("spend", "index", "/spend/"),
        ("x_activity", "index", "/x/"),
        ("grok_bot", "index", "/grok-bot/"),
        ("dashboard", "index", "/memes/"),
        ("generate", "start", "/memes/generate/"),
        ("video", "start", "/memes/video/"),
        ("gallery", "index", "/memes/gallery/"),
        ("daily_candidates", "index", "/memes/gallery/daily-candidates/"),
        ("templates_review", "review_page", "/memes/templates/"),
        ("discovery", "dashboard", "/memes/discovery/"),
    ):
        stub = Blueprint(name, name)
        stub.add_url_rule(path, endpoint, lambda **_kwargs: "")
        app.register_blueprint(stub)
    app.register_blueprint(home_bp)
    return app


class NormalizeAndSplitTests(unittest.TestCase):
    def test_normalize_drops_events_without_title_or_start(self):
        self.assertIsNone(normalize_event({"id": "x", "start": "2026-09-12T12:00:00-04:00"}))
        self.assertIsNone(normalize_event({"title": "Nope"}))
        self.assertIsNone(normalize_snapshot(["not", "an", "object"]))

    def test_split_hides_invented_and_out_of_window_events(self):
        snapshot = normalize_snapshot(
            {
                "updated_at": "2026-09-12T00:00:00+00:00",
                "timezone": "America/New_York",
                "events": SNAPSHOT_EVENTS,
            }
        )
        lists = split_home_events(snapshot, now=NOW, timezone_name="America/New_York")
        week_titles = [event["title"] for event in lists["this_week"]]
        horizon_titles = [event["title"] for event in lists["horizon"]]
        self.assertEqual(week_titles, ["Saturday dinner", "Sunday hike"])
        self.assertEqual(horizon_titles, ["Next Friday gap", "October trip"])
        hidden = " ".join(week_titles + horizon_titles)
        self.assertNotIn("Past standup", hidden)
        self.assertNotIn("Far away", hidden)
        self.assertNotIn("Invented Birthday", hidden)
        self.assertNotIn("Team standup", hidden)

    def test_no_snapshot_is_empty_state_not_invented_events(self):
        lists = split_home_events(None, now=NOW, timezone_name="America/New_York")
        self.assertFalse(lists["has_snapshot"])
        self.assertEqual(lists["this_week"], [])
        self.assertEqual(lists["horizon"], [])
        self.assertEqual(lists["empty_message"], EMPTY_SNAPSHOT_MESSAGE)

    def test_empty_snapshot_has_no_invented_events(self):
        snapshot = normalize_snapshot(
            {"updated_at": "2026-09-12T00:00:00+00:00", "timezone": "America/New_York", "events": []}
        )
        lists = split_home_events(snapshot, now=NOW)
        self.assertTrue(lists["has_snapshot"])
        self.assertEqual(lists["this_week"], [])
        self.assertEqual(lists["horizon"], [])
        self.assertIsNone(lists["empty_message"])

    def test_horizon_starts_monday_after_this_week(self):
        start, _end = horizon_bounds(NOW, ET)
        self.assertEqual(start.date().isoformat(), "2026-09-14")
        self.assertEqual(start.weekday(), 0)
        sunday_end = datetime(2026, 9, 13, 23, 59, 59, tzinfo=ET)
        self.assertGreater(start, sunday_end)
        monday_now = datetime(2026, 9, 14, 9, 0, tzinfo=ET)
        monday_start, _monday_end = horizon_bounds(monday_now, ET)
        self.assertEqual(monday_start.date().isoformat(), "2026-09-21")

    def test_split_groups_remaining_week_days_and_horizon_dates(self):
        snapshot = normalize_snapshot(
            {
                "updated_at": "2026-09-12T00:00:00+00:00",
                "timezone": "America/New_York",
                "events": SNAPSHOT_EVENTS,
            }
        )
        lists = split_home_events(snapshot, now=NOW, timezone_name="America/New_York")
        self.assertEqual([day["label"] for day in lists["this_week_days"]], ["Sat 12", "Sun 13"])
        self.assertEqual([day["date"] for day in lists["this_week_days"]], ["2026-09-12", "2026-09-13"])
        self.assertTrue(lists["this_week_days"][0]["is_today"])
        self.assertFalse(lists["this_week_days"][1]["is_today"])
        self.assertEqual(
            [event["title"] for event in lists["this_week_days"][0]["events"]],
            ["Saturday dinner"],
        )
        self.assertEqual(lists["this_week_days"][0]["events"][0]["when_label"], "6–8 PM")
        self.assertEqual(
            [event["title"] for event in lists["this_week_days"][1]["events"]],
            ["Sunday hike"],
        )
        self.assertEqual(lists["this_week_days"][1]["events"][0]["when_label"], "All day")
        self.assertEqual(
            [(day["date"], day["label"]) for day in lists["horizon_days"]],
            [("2026-09-18", "Fri Sep 18"), ("2026-10-05", "Mon Oct 5")],
        )
        self.assertEqual(lists["horizon_days"][0]["events"][0]["when_label"], "9–10 AM")
        self.assertEqual(lists["horizon_days"][1]["events"][0]["when_label"], "9 AM – Thu Oct 8")
        self.assertEqual(lists["this_week_label"], "")
        self.assertEqual(lists["horizon_label"], "")

    def test_week_keeps_empty_days_so_the_week_is_readable(self):
        monday = datetime(2026, 9, 7, 12, 0, tzinfo=ET)
        snapshot = normalize_snapshot(
            {
                "updated_at": "2026-09-07T00:00:00+00:00",
                "timezone": "America/New_York",
                "events": SNAPSHOT_EVENTS,
            }
        )
        lists = split_home_events(snapshot, now=monday, timezone_name="America/New_York")
        labels = [day["label"] for day in lists["this_week_days"]]
        self.assertEqual(labels, ["Mon 7", "Tue 8", "Wed 9", "Thu 10", "Fri 11", "Sat 12", "Sun 13"])
        empty = [day["label"] for day in lists["this_week_days"] if not day["events"]]
        self.assertEqual(empty, ["Mon 7", "Tue 8", "Wed 9", "Thu 10"])
        friday = next(day for day in lists["this_week_days"] if day["date"] == "2026-09-11")
        self.assertEqual([event["title"] for event in friday["events"]], ["Past standup"])

    def test_present_location_quiets_streets_and_title_repeats(self):
        self.assertIsNone(present_location("EWR → BTV", "EWR → BTV"))
        self.assertIsNone(present_location("Flight EWR → BTV", "EWR -> BTV"))
        self.assertIsNone(present_location("Dentist", "America/New_York"))
        self.assertEqual(present_location("Saturday dinner", "Home"), "Home")
        self.assertEqual(
            present_location("Dentist", "123 Main St, Apt 4B, Brooklyn, NY 11201"),
            "Brooklyn",
        )
        self.assertEqual(
            present_location("Pizza", "Lucali, 456 5th Ave, New York, NY 10001"),
            "Lucali",
        )
        self.assertIsNone(present_location("Stay in", "123 Main Street, Apt 4B"))


class IcsParseTests(unittest.TestCase):
    def test_parse_ics_keeps_only_vevents(self):
        ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:dinner
DTSTART;TZID=America/New_York:20260912T180000
DTEND;TZID=America/New_York:20260912T200000
SUMMARY:Saturday dinner
LOCATION:Home
END:VEVENT
BEGIN:VEVENT
UID:trip
DTSTART;TZID=America/New_York:20261005T090000
DTEND;TZID=America/New_York:20261008T180000
SUMMARY:October trip
URL:https://example.com/trip
END:VEVENT
BEGIN:VEVENT
UID:cancelled
STATUS:CANCELLED
DTSTART:20260912T150000Z
SUMMARY:Cancelled thing
END:VEVENT
END:VCALENDAR
"""
        snapshot = parse_ics(ics, timezone_name="America/New_York", now=NOW)
        titles = [event["title"] for event in snapshot["events"]]
        self.assertIn("Saturday dinner", titles)
        self.assertIn("October trip", titles)
        self.assertNotIn("Cancelled thing", titles)
        self.assertNotIn("Invented Birthday", titles)


class CalendarStoreAndHomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.seth = load_tenant_from_path(_SETH)
        reset_tenant(self.seth)
        self.store = MemoryS3Store()
        self.calendar = CalendarStore(
            store=self.store,
            local_path=Path(self.tmp.name) / "snapshot.json",
            timezone_name="America/New_York",
            ics_url=None,
            now=NOW,
        )
        reset_calendar(self.calendar)
        self.board = ProjectBoard(
            store=MemoryS3Store(configured=False),
            local_path=Path(self.tmp.name) / "board.json",
            tenant=self.seth,
        )
        reset_project_board(self.board)
        self.client = _nav_app().test_client()

    def tearDown(self):
        reset_calendar()
        reset_project_board()
        reset_tenant()
        self.tmp.cleanup()

    def test_s3_key_stays_under_ops_calendar(self):
        key = self.calendar.s3_key()
        self.assertEqual(key, "ops/calendar/snapshot.json")
        BucketLayout.require_ops_key(key)
        self.assertFalse(key.startswith("public/"))

    def test_home_empty_state_without_snapshot(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("This week", html)
        self.assertIn("On the horizon", html)
        self.assertIn("No calendar snapshot yet.", html)
        self.assertNotIn("Saturday dinner", html)
        self.assertNotIn("Invented Birthday", html)
        self.assertNotIn("Team standup", html)
        self._assert_home_calendar_has_no_operator_chrome(html)

    def test_home_splits_this_week_and_horizon_from_snapshot(self):
        self.calendar.save(
            {
                "updated_at": "2026-09-12T00:00:00+00:00",
                "timezone": "America/New_York",
                "events": SNAPSHOT_EVENTS,
            }
        )
        html = self.client.get("/").get_data(as_text=True)
        week = html.split('data-calendar="this-week"')[1].split('data-calendar="horizon"')[0]
        horizon = html.split('data-calendar="horizon"')[1]
        self.assertIn("Saturday dinner", week)
        self.assertIn("Sunday hike", week)
        self.assertNotIn("October trip", week)
        self.assertIn("October trip", horizon)
        self.assertNotIn("Saturday dinner", horizon)
        self.assertNotIn("Past standup", html)
        self.assertIn("Next Friday gap", horizon)
        self.assertNotIn("Next Friday gap", week)
        self.assertNotIn("Far away", html)
        self.assertNotIn("Invented Birthday", html)
        self.assertIn("https://example.com/trip", html)
        self.assertIn('data-cal-day="2026-09-12"', week)
        self.assertIn("Sat 12", week)
        self.assertIn("Sun 13", week)
        self.assertIn("6–8 PM", week)
        self.assertNotIn("Sat Sep 12 ·", week)
        self.assertNotIn("Sun Sep 13 ·", week)
        self.assertIn('data-cal-day="2026-09-18"', horizon)
        self.assertIn("Fri Sep 18", horizon)
        self.assertIn("Mon Oct 5", horizon)
        self.assertNotIn("Fri Sep 18 ·", horizon)
        self._assert_home_calendar_has_no_operator_chrome(html)

    def test_home_calendar_html_hides_iana_and_noisy_locations(self):
        self.calendar.save(
            {
                "updated_at": "2026-09-12T00:00:00+00:00",
                "timezone": "America/New_York",
                "events": [
                    {
                        "id": "flight",
                        "title": "EWR → BTV",
                        "start": "2026-09-12T15:00:00-04:00",
                        "end": "2026-09-12T16:30:00-04:00",
                        "all_day": False,
                        "location": "EWR → BTV",
                    },
                    {
                        "id": "dentist",
                        "title": "Dentist",
                        "start": "2026-09-13T14:00:00-04:00",
                        "end": "2026-09-13T14:45:00-04:00",
                        "all_day": False,
                        "location": "123 Main St, Apt 4B, Brooklyn, NY 11201",
                    },
                    {
                        "id": "pizza",
                        "title": "Pizza",
                        "start": "2026-09-18T18:00:00-04:00",
                        "end": "2026-09-18T19:00:00-04:00",
                        "all_day": False,
                        "location": "Lucali, 456 5th Ave, New York, NY 10001",
                    },
                ],
            }
        )
        html = self.client.get("/").get_data(as_text=True)
        week = html.split('data-calendar="this-week"')[1].split('data-calendar="horizon"')[0]
        horizon = html.split('data-calendar="horizon"')[1]
        self._assert_home_calendar_has_no_operator_chrome(html)
        self.assertEqual(week.count("EWR → BTV"), 1)
        self.assertNotIn("123 Main St", html)
        self.assertNotIn("Apt 4B", html)
        self.assertIn("Brooklyn", week)
        self.assertIn("Lucali", horizon)
        self.assertNotIn("456 5th Ave", html)
        self.assertNotIn("ops/calendar/snapshot", html)
        self.assertNotIn("last-synced", html)
        self.assertNotIn("last synced", html)

    def test_ics_refresh_caches_snapshot(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:dinner
DTSTART;TZID=America/New_York:20260912T180000
DTEND;TZID=America/New_York:20260912T200000
SUMMARY:Saturday dinner
END:VEVENT
END:VCALENDAR
"""
        self.calendar._ics_url = "https://example.invalid/secret.ics"
        snapshot = self.calendar.refresh_from_ics(now=NOW, ics_text=ics)
        self.assertEqual([event["title"] for event in snapshot["events"]], ["Saturday dinner"])
        self.assertIn(BucketLayout.calendar_snapshot_key(), self.store.objects)
        reloaded = self.calendar.load_snapshot()
        self.assertEqual(reloaded["events"][0]["title"], "Saturday dinner")

    def _assert_home_calendar_has_no_operator_chrome(self, html: str) -> None:
        calendar_html = html
        if 'data-calendar="this-week"' in html:
            calendar_html = html[html.find('data-calendar="this-week"') :]
        self.assertNotIn("America/New_York", calendar_html)
        self.assertNotIn("Europe/London", calendar_html)
        self.assertNotIn("America/Los_Angeles", calendar_html)
        self.assertNotRegex(calendar_html, r"(?:America|Europe|Asia|Pacific|Africa|Australia)/[A-Za-z_]+")
