"""Grounding gate + daily queue rationale schema."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import tests.bootstrap  # noqa: F401

from src.core.daily_queue import (
    build_candidate_record,
    build_queue_document,
    candidate_has_why,
    parse_topic_response,
    select_daily_candidates,
    why_preview,
)
from src.core.grounding import (
    GroundingNote,
    apply_grounding,
    idea_rationale,
    parse_grounding_response,
)
from src.core.grok import GrokClient, MemeIdea
from src.core.meme_assets import QueueStorage
from src.core.two_stage import EvaluatedMeme
from tests.fakes import MemoryS3Store


def _idea(**overrides) -> MemeIdea:
    data = dict(
        format="Gru's Plan",
        top_text="Billy unplug the Telecaster",
        bottom_text="Monroe's ghost tells him to plug it back in",
        explanation="",
        source_quote="",
        artist_reference="Billy Strings",
        rationale="",
    )
    data.update(overrides)
    return MemeIdea(**data)


def _evaluated(idea: MemeIdea, overall: float = 8.0) -> EvaluatedMeme:
    return EvaluatedMeme(
        idea=idea,
        scores={"humor": 8, "accuracy": 7},
        overall_score=overall,
        evaluation_notes="Looks punchy",
    )


TELECASTER_RESPONSE = """
MEME 1:
HINGES: yes
CLAIM: Billy Strings unplugs a Telecaster
SUPPORT: no known beat
CONFIDENCE: low
ACTION: skip
RATIONALE: Invented gear lore, not a documented Billy/Telecaster moment.

MEME 2:
HINGES: no
ACTION: ok
RATIONALE: Generic jam-volume roast; no named fact.
"""


class GroundingParseTests(unittest.TestCase):
    def test_telecaster_thin_claim_is_skip(self):
        notes = parse_grounding_response(TELECASTER_RESPONSE, 2)
        self.assertEqual(len(notes), 2)
        self.assertTrue(notes[0].hinges)
        self.assertIn("Telecaster", notes[0].claim)
        self.assertEqual(notes[0].confidence, "low")
        self.assertEqual(notes[0].action, "skip")
        self.assertFalse(notes[1].hinges)
        self.assertEqual(notes[1].action, "ok")

    def test_apply_grounding_downscores_and_skips(self):
        thin = _evaluated(_idea(), overall=8.2)
        safe = _evaluated(_idea(top_text="Too loud", bottom_text="Still too loud"), overall=7.0)
        notes = parse_grounding_response(TELECASTER_RESPONSE, 2)
        apply_grounding([thin, safe], notes)
        self.assertEqual(thin.grounding_action, "skip")
        self.assertLessEqual(thin.overall_score, 3.0)
        self.assertEqual(thin.grounding["claim"], notes[0].claim)
        self.assertEqual(safe.grounding_action, "ok")
        self.assertEqual(safe.overall_score, 7.0)
        self.assertIsNone(safe.grounding)

    def test_select_drops_skip_unless_batch_would_be_empty(self):
        thin = _evaluated(_idea(), overall=8.2)
        safe = _evaluated(_idea(top_text="Chop", bottom_text="Louder chop"), overall=6.5)
        apply_grounding(
            [thin, safe],
            parse_grounding_response(TELECASTER_RESPONSE, 2),
        )
        picked = select_daily_candidates([thin, safe], count=5)
        self.assertEqual(picked, [safe])

        only_thin = select_daily_candidates([thin], count=1)
        self.assertEqual(only_thin, [thin])

    def test_fills_missing_rationale_from_grounding(self):
        item = _evaluated(_idea(rationale="", explanation=""), overall=5.0)
        notes = [GroundingNote(hinges=False, action="ok", rationale="It's a volume joke.")]
        apply_grounding([item], notes)
        self.assertEqual(idea_rationale(item.idea), "It's a volume joke.")


class TopicAndQueueSchemaTests(unittest.TestCase):
    def test_parse_topic_response(self):
        topic, rationale = parse_topic_response(
            "TOPIC: Billy Strings festival run\nRATIONALE: He's headlining a lot of sheds this month."
        )
        self.assertEqual(topic, "Billy Strings festival run")
        self.assertIn("headlining", rationale)

    def test_bare_topic_string_still_parses(self):
        topic, rationale = parse_topic_response("banjo jokes")
        self.assertEqual(topic, "banjo jokes")
        self.assertEqual(rationale, "")

    def test_queue_document_persists_rationale_fields(self):
        candidate = build_candidate_record(
            date_str="2026-09-15",
            index=1,
            template="Gru's Plan",
            top_text="Billy unplug the Telecaster",
            bottom_text="Monroe's ghost",
            caption="observational caption",
            public_url="https://example.com/m.jpg",
            s3_key="public/memes/generated/m.jpg",
            local_path="output/m.jpg",
            filename="m.jpg",
            created_at="2026-09-15T12:00:00",
            scores={"humor": 4, "accuracy": 2},
            overall_score=3.1,
            rationale="Joke assumes Billy plays a Telecaster.",
            evaluation_notes="Thin invented gear claim.",
            grounding={
                "claim": "Billy Strings unplugs a Telecaster",
                "support": "no known beat",
                "confidence": "low",
            },
        )
        doc = build_queue_document(
            date_str="2026-09-15",
            topic="Billy Strings",
            topic_rationale="He's on a big festival run.",
            domain="bluegrass",
            generated_at="2026-09-15T12:00:00",
            output_dir="output/memes",
            candidates=[candidate],
        )
        self.assertEqual(doc["topic_rationale"], "He's on a big festival run.")
        stored = doc["candidates"][0]
        self.assertEqual(stored["rationale"], "Joke assumes Billy plays a Telecaster.")
        self.assertEqual(stored["evaluation_notes"], "Thin invented gear claim.")
        self.assertEqual(stored["scores"]["humor"], 4)
        self.assertEqual(stored["overall_score"], 3.1)
        self.assertEqual(stored["grounding"]["confidence"], "low")

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        queue = QueueStorage(store=MemoryS3Store(), local_dir=Path(tmp.name))
        self.assertTrue(queue.save("2026-09-15", doc))
        loaded = queue.load("2026-09-15")
        self.assertEqual(loaded["topic_rationale"], doc["topic_rationale"])
        self.assertEqual(loaded["candidates"][0]["rationale"], stored["rationale"])
        self.assertEqual(loaded["candidates"][0]["grounding"]["claim"], stored["grounding"]["claim"])

    def test_old_queue_has_no_why(self):
        old = {
            "id": "2026-09-15_1",
            "template": "Drake",
            "top_text": "a",
            "bottom_text": "b",
            "caption": "c",
            "scores": {},
            "overall_score": None,
        }
        self.assertFalse(candidate_has_why(old, ""))
        self.assertEqual(why_preview(old, ""), "Why")

    def test_why_preview_prefers_meme_rationale(self):
        candidate = {"rationale": "It's a chop joke.", "evaluation_notes": "ok"}
        self.assertTrue(candidate_has_why(candidate, "timely topic"))
        self.assertEqual(why_preview(candidate, "timely topic"), "It's a chop joke.")


class MemeParseRationaleTests(unittest.TestCase):
    def test_parse_rationale_field(self):
        text = """FORMAT: Drake Hotline Bling
TOP_TEXT: Acoustic jam
BOTTOM_TEXT: Pedalboard the size of a coffee table
RATIONALE: Scene roast of over-geared guitar players.
"""
        memes = GrokClient._parse_meme_response(None, text)
        self.assertEqual(len(memes), 1)
        self.assertEqual(memes[0].rationale, "Scene roast of over-geared guitar players.")
        self.assertEqual(memes[0].explanation, memes[0].rationale)


if __name__ == "__main__":
    unittest.main()
