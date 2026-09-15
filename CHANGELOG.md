# Changelog

## Bigger crests + US TV/streaming providers for sports (2026-09-15)

- **Bigger team crests**: increased from 16×16 to 30×30 pixels for better readability in the week grid view.
- **Broadcast providers**: Home calendar now shows US TV and streaming networks (e.g., ABC, FOX, ESPN+, Peacock) for sports events when data is available.
- Data source: `ops/calendar/broadcasts.json` (S3) / `data/calendar/broadcasts.json` (local fallback). Shape: `{ updated_at, timezone, entries: [{ event_id?, date, teams[], title_contains[], providers[], source }] }`.
- Matching order: calendar `event_id` if present, else date + team IDs, else date + title needles. Longest/most-specific match wins. Never invents entries.
- Weekly refresh script: `scripts/refresh_broadcasts.py` queries ESPN public scoreboard API (no API key needed) for NCAA football, Premier League, Champions League, and Carabao Cup. Usage: `python scripts/refresh_broadcasts.py [--date YYYY-MM-DD] [--days N]`.
- Missing/incomplete ESPN data = no provider line on the event (graceful degradation).
- Documented next to `team-logos.json` in `docs/life-ops.md` + `BucketLayout.calendar_broadcasts_key()`.

---

## Home calendar opponent crests + category colors (2026-09-14)

- Port of [life-ops PR #4](https://github.com/sethweiland/life-ops/pull/4) so live Fly `meme-ops` / ops.sethweiland.com can show opponent crests and category left-borders.
- `ops/calendar/team-logos.json` uses Stevie’s shape: `match[]`, `teams[]`+aliases, `title_parse.separators` (`vs` / `@` / `against` / `v` / `—`), `categories[]` (hex + `google_color_id`).
- Two crests when both sides of a matchup are in the map; one crest if the opponent is missing; never invent logos or events. Longest alias wins.
- Category left-border on This week + On the horizon. Defaults: sports `#2563eb`/9, music `#be185d`/4, family_friends `#059669`/10, travel `#d97706`/6, other `#6b7280`/8.

---

## Folders nav, project deep-links (2026-09-12)

- Top nav control is **Folders ▾** (was More). Native `<details>` so it opens without JS. Inner folders default open.
- Folder project links deep-link to `/projects/?project=<id>#<id>`. The projects list scrolls, highlights, and selects that row.
- `nav` is `overflow: visible` so the Folders panel is not clipped.

---

## Folders menu, Home inbox, private tenant (2026-09-12)

- Top nav is Home · Projects · Spend · X · **Folders ▾**. Grok Bot and Memes are no longer peer tabs.
- Folders is a bookmarks-style dropdown from tenant `folders:` (nav config, not a sixth primitive). Disabled-module links are hidden.
- Home is Waiting on you above This week / On the horizon. Hub cards are gone.
- Horizon starts the Monday after this week's Sunday, not 14 days out.
- `config/tenant.yaml` and `data/tech_spend.json` are gitignored. Friends use `config/tenant.example.yaml`. Fly reads S3 `ops/tenant.yaml`.
- Spend ledger load order: S3 `ops/spend/tech_spend.json`, else local `data/tech_spend.json`, else empty `{subscriptions: []}`. No invented rows.

---

## Projects list, Tokens widget, Home calendar (2026-09-12)

- `/projects/` is a compact sorted list (status pill = lane). Empty swim lanes no longer dominate.
- `/spend/` has a Tokens card at the top from `token_tracker` (heuristic $ is not the xAI invoice).
- Home shows This week + On the horizon when `calendar: true`. Snapshot at `ops/calendar/snapshot.json` or optional `CALENDAR_ICS_URL`. No Google OAuth.

---

## Meme Diversity Improvements (2026-02-03)

### Summary

Four changes to reduce topic repetition across generated memes. Previously, the same RAG chunks, current events, and topics (IBMA, Bill Monroe, Steve Martin) dominated output because retrieval was identical across batches, current events were injected uniformly, and there was no cross-batch dedup signal.

### Changes

#### 1. Per-batch context exclusion — `src/core/retriever.py`, `src/core/rag.py`, `web/blueprints/generate.py`, `src/core/two_stage.py`

**What:**
- `hybrid_search()` accepts `exclude_ids: set[str] | None` — filters out previously-used chunk IDs before ranking
- `DomainRAG.search()` and `get_context()` thread `exclude_ids` through the call chain
- `get_context()` now returns an `id` field in each dict (from `RetrievalResult.id`) so callers can track used chunks
- Both `_run_stage1()` (web) and `TwoStagePipeline.run()` (CLI) track `used_chunk_ids` across batches and pass them as exclusions

**Impact:** Each batch sees different RAG context instead of the same top-k results repeated.

---

#### 2. Current events rotation — `web/blueprints/generate.py`, `src/core/two_stage.py`

**What:** The current events string (newline-delimited list of news items) is split into individual items. Each batch receives 1–2 items via round-robin (`batch_num * items_per_batch % len(items)`) instead of all items identically.

**Impact:** Stops a single headline from dominating every batch's output.

---

#### 3. Diversity instruction in generation prompt — `src/core/two_stage.py`, `web/blueprints/generate.py`

**What:**
- `generate_freely()` accepts `previously_covered: list[str] | None` parameter
- Every call appends: `"IMPORTANT: Each meme must reference a DIFFERENT topic, person, or situation. No repeats."`
- For batch 2+, also appends: `"Avoid these topics already covered: {list}"` using capitalized words and format names extracted from prior batch outputs
- Both web and CLI batch loops extract topic references after each batch and pass them forward

**Impact:** Prompt-level guardrail against topic repetition across batches.

---

#### 4. Topic-level feedback — `web/feedback.py`, `web/static/app.js`

**What:**
- `build_feedback_context()` now extracts proper nouns from meme text (`top_text`, `bottom_text`) of rated memes
- Topics appearing in 2+ low-rated memes produce: `"Overused topics (vary these): ..."`
- Topics appearing in 2+ high-rated memes produce: `"Topics user enjoyed: ..."`
- Explicit `topic_notes` field from user feedback is incorporated
- Results page now shows a "Any topics you're tired of seeing?" textarea
- Topic notes are saved alongside ratings in feedback JSON as `topic_notes`

**Impact:** Closes the human-in-the-loop for topic diversity — users can flag overused topics and the system incorporates that signal into future generations.

---

### Files Changed

| File | Action |
|------|--------|
| `src/core/retriever.py` | Modified — `exclude_ids` param on `hybrid_search()` |
| `src/core/rag.py` | Modified — `exclude_ids` threading, `id` field in context dicts |
| `src/core/two_stage.py` | Modified — per-batch context/CE rotation, diversity prompt, `previously_covered` param |
| `web/blueprints/generate.py` | Modified — per-batch context/CE rotation, topic tracking |
| `web/feedback.py` | Modified — topic extraction, `topic_notes` support |
| `web/static/app.js` | Modified — topic notes textarea on results page |

---

## Architectural Hardening + Pipeline Split (2026-02-01)

### Summary

Seven architectural fixes addressing input validation, budget tracking, parsing resilience, evaluation wiring, and code organization. All changes are backward-compatible — `daily.py` requires no modifications.

### Changes

#### Fix 6: Input Validation — `src/core/pipeline.py`

**What:** Added `__post_init__` to `PipelineConfig` with range validation:
- `num_concepts`: 1–500
- `concepts_per_batch`: 1–25
- `creativity` / `generation_creativity`: 0.0–2.0
- `num_images`: 1–50
- `token_budget`: >= 1000 or None

Override parameters in `generate_concepts()` and `generate_images_from_concepts()` are clamped to valid ranges.

---

#### Fix 5: Query Expansion Toggle — `src/core/pipeline.py`, `src/core/rag.py`

**What:** Added `expand_queries: bool = True` to `PipelineConfig`. Plumbed `expand_query` parameter through `DomainRAG.get_context()` → `self.search()`. Both `generate_concepts()` and `run_two_stage()` pass the config value through.

**Rationale:** Query expansion uses an LLM call per search. For tight budgets or deterministic workflows, disabling it saves tokens and reduces latency.

---

#### Fix 7: Token Budget Consistency — `src/core/pipeline.py`, `src/core/rag.py`

**What:**
- Added `TOKENS_PER_CAPTION = 500` to `TokenBudget`
- `generate_concepts()` batch loop: `budget.check()` before each batch, breaks on `TokenBudgetExceeded`
- `generate_captions()`: `budget.check()` + `budget.record()` per caption, breaks on exceeded
- `search_by_artist/instrument/era` now route through `self.search()` instead of `self.retriever.hybrid_search()` directly, so budget tracking applies

**Cross-module impact:** Any code calling `search_by_artist/instrument/era` on `DomainRAG` will now have those searches counted against the token budget. Previously they were untracked.

---

#### Fix 3: Template Descriptions — Single Source of Truth — `src/core/templates.py`

**What:**
- Added `get_description(template_name, template_id)` to `TemplatesCatalog` with explicit priority resolution: hand-written → AI-approved → empty string
- Cached `_ai_descriptions` dict in `_apply_ai_descriptions()` for lookup
- Added docstring to `TEMPLATE_DESCRIPTIONS` documenting the priority system

**Architectural alignment:** Hand-written descriptions stay in code (version-controlled, easy to edit). The review queue JSON remains a staging area only — never loaded at runtime.

---

#### Fix 2: LLM Output Parsing Hardening — `src/core/grok.py`, `src/core/evaluator.py`, `src/core/pipeline.py`

**What:**
- `grok.py` `_parse_meme_response()`: JSON fallback when no `FORMAT:` markers found and response starts with `{` or `[`. Accepts `TEMPLATE:` as alias for `FORMAT:`. Parse rate warning when < 50% of sections yield memes.
- `evaluator.py` `_parse_scores()`: Parse rate warning when parsed < 50% of input memes
- `pipeline.py` `_parse_evaluations()`: Same parse rate warning pattern

**Rationale:** Text-based parsing is intentional (JSON mode constrains creative generation), but these changes make it more resilient to format drift and observable when parsing degrades.

---

#### Fix 4: Wire Evaluation into run() — `src/core/pipeline.py`

**What:**
- Added `evaluate: bool = True` and `min_score: float = 0.0` to `PipelineConfig`
- `run()` now calls `evaluate_concepts()` after generation, filters by `min_score`, and reorders concepts by score before image generation
- `concepts_evaluated` field in `PipelineResult` is now populated

**Impact on daily.py:** With 20 concepts and 5 images, evaluation now picks the best 5 instead of the first 5. Opt-out: `PipelineConfig(evaluate=False)`.

---

#### Fix 1: Split pipeline.py — `src/core/pipeline.py`, `src/core/output.py` (NEW), `src/core/two_stage.py` (NEW), `src/core/__init__.py`

**What:**
- **`output.py`** (91 lines): Extracted `save_manifest()`, `save_meme_metadata()`, `print_summary()` as standalone functions
- **`two_stage.py`** (415 lines): Extracted `TwoStagePipeline` wrapper class with `generate_freely()`, `evaluate_for_review()`, `_parse_evaluations()`, `_create_evaluated_meme()`, `review_candidates()`, `run()`, `generate_selected()`. Also contains `EvaluatedMeme` dataclass and shared `_format_context_text()` helper.
- **`pipeline.py`** (494 lines): Config, core orchestration, `run()`. Delegates `run_two_stage()` and `generate_selected()` to `TwoStagePipeline`.
- **`__init__.py`**: Added exports for `TwoStagePipeline`, `EvaluatedMeme`

**Public API preserved:** `daily.py` keeps importing `MemePipeline` and `PipelineConfig` from `src.core.pipeline` — no changes needed. `EvaluatedMeme` is re-exported from `pipeline.py` for backward compatibility.

---

### Files Changed

| File | Action |
|------|--------|
| `src/core/pipeline.py` | Modified (fixes 1, 2, 4, 5, 6, 7) |
| `src/core/rag.py` | Modified (fixes 5, 7) |
| `src/core/grok.py` | Modified (fix 2) |
| `src/core/templates.py` | Modified (fix 3) |
| `src/core/evaluator.py` | Modified (fix 2) |
| `src/core/__init__.py` | Modified (fix 1) |
| `src/core/output.py` | **NEW** (fix 1) |
| `src/core/two_stage.py` | **NEW** (fix 1) |

---

## Template Review UI + Improved Vision Prompt (2026-02-01)

### Changes

#### 1. `scripts/review_templates.py` — NEW: Flask review web app

**What:** Local web app (port 5050) for reviewing AI-generated template descriptions. Three pages:
- **Review Queue** (`/`) — Cards with template image, editable description, metadata, Approve/Reject buttons
- **Approved** (`/approved`) — Read-only view of approved descriptions with "Move to Review" option
- **Stats** (`/stats`) — Dashboard with counts (total catalog, hand-written, AI-approved, review queue, undescribed)

API endpoints: `POST /api/approve/<id>`, `POST /api/reject/<id>`, `POST /api/unapprove/<id>`, `GET /api/stats`.

Inline HTML/CSS/JS — no external dependencies beyond Flask. Vanilla JS fetch calls with card fade-out animations.

**Architectural alignment:** Reads/writes the same two JSON files (`ai_template_descriptions.json`, `template_descriptions_review.json`) that `refresh_templates.py` uses. No new data stores. Single-user local tool — no auth or file locking needed.

---

#### 2. `scripts/refresh_templates.py` — Removed `--approve-reviewed` batch logic

**What:** `run_approve_reviewed()` now prints a message directing users to the review web UI instead of doing batch promotion. The `--approve-reviewed` flag is kept for discoverability but just points to the web app.

**Rationale:** The web UI provides a better review experience — you can see template images, edit descriptions inline, and make per-template decisions instead of bulk-approving everything with a description.

---

#### 3. `src/core/template_describer.py` — Improved vision prompt for multi-panel templates

**What:** Updated `VISION_PROMPT` to explicitly request per-panel sequence descriptions. Previously asked only for visual layout details, which produced generic descriptions like "text is typically added above or below each character's face." Now asks Grok to describe each panel's role in sequence and explain the comedic progression.

**Before:** "Write 1-2 sentences describing the visual layout..."
**After:** "Write 2-3 sentences... For multi-panel templates, describe what happens in EACH panel in sequence (e.g., 'Panel 1: character makes a bold claim. Panel 2: someone asks a follow-up...'). Explain the comedic progression, not just the visual layout."

**Impact:** Affects all future `--backfill` runs. Existing descriptions in the review queue can be re-generated by rejecting and re-running backfill.

---

#### 4. `requirements.txt` — Added `flask>=3.0.0`

---

## Current Events + Optional RAG (2026-01-31)

### Architecture Overview

```
daily.py → MemePipeline → DomainRAG → (vectorstore, retriever, grok)
                        → CurrentEventsSearch (NEW)
                        → TemplatesCatalog
                        → MemeEvaluator
                        → MemeImageGenerator
```

### Changes

#### 1. `src/config/domain_config.py` — Added `CurrentEventsConfig` dataclass

**What:** New `CurrentEventsConfig` dataclass (enabled, search_queries, max_results). Added as a field on `DomainConfig` and parsed in `from_yaml()`.

**Architectural alignment:** Follows the existing pattern exactly — same as `AbsurdismDetection` (dataclass + field + YAML parsing). Config layer stays declarative; no logic here.

**Cross-module impact:** None. `DomainConfig` is read-only data passed into core modules. New field is ignored by any module that doesn't reference it.

---

#### 2. `src/core/current_events.py` — NEW module

**What:** `CurrentEventsSearch` class with three methods:
- `search_news()` — DuckDuckGo news search, deduplicates by title
- `filter_relevant()` — Grok call to pick meme-worthy headlines
- `get_current_events_context()` — orchestrates search → filter → formatted string

**Architectural alignment:** Follows the same pattern as other core modules:
- Takes `DomainConfig` in constructor
- Uses `GrokClient` for LLM calls (same as evaluator, generator)
- Returns plain data (string) — no side effects

**Cross-module impact:** Minimal. Only imported by `pipeline.py`. Creates its own `GrokClient` instance for the filter call (not shared with RAG's client). This is a one-shot call so the extra client is acceptable.

**Key design decisions:**
- `ddgs` import is inside try/except — module works without the package installed
- Fail-open on filter errors — false positives are harmless for meme generation
- Returns a plain string, not structured data — keeps pipeline injection simple

---

#### 3. `src/core/rag.py` — Made RAG optional

**What:**
- `generate_meme_ideas()`: Changed `raise ValueError` on empty context to a log message. Generation proceeds with whatever context is available (possibly none).
- `brainstorm_topics()`: If `get_context()` returns empty, falls back to a standalone Grok call using general domain knowledge.

**Architectural alignment:** RAG was the only module that hard-failed on missing data. This aligns it with the rest of the pipeline's graceful-degradation approach.

**Cross-module impact: ⚠️ IMPORTANT** — Any code that previously caught `ValueError` from `generate_meme_ideas()` to detect "no content" will no longer see that exception. Currently only `daily.py` calls it (indirectly through pipeline), and it didn't catch that error, so this is safe. But if future code relied on that ValueError, it would need updating.

---

#### 4. `src/core/pipeline.py` — Wired current events into generation

**What:**
- Added `self.current_events_context: str` field
- Added `_fetch_current_events()` method — creates `CurrentEventsSearch`, calls `get_current_events_context()`
- `run()`: calls `_fetch_current_events()` once at start
- `run_two_stage()`: same
- `_generate_batch()`: appends current events to `context_text` if non-empty
- `run_two_stage()`: same context injection

**Architectural alignment:** Pipeline already orchestrates RAG context → Grok generation. Current events is injected as an additional labeled section in the same context string. No new data flow patterns.

**Cross-module impact: ⚠️ NOTE** — `generate_freely()` in the two-stage path receives `context_text` as a parameter from `run_two_stage()`. The current events injection happens in `run_two_stage()` before passing to `generate_freely()`, so it's covered. However, any external caller of `generate_freely()` with their own `context_text` would NOT automatically get current events — they'd need to handle it themselves.

---

#### 5. `domains/bluegrass/config.yaml` — Added `current_events` section

**What:** Three fixed search queries: "bluegrass music", "bluegrass festival", "IBMA". Enabled by default, max 10 results.

**Architectural alignment:** Follows existing YAML config pattern. Other domains can add their own `current_events` section or omit it (defaults to disabled).

**Cross-module impact:** None — config is domain-specific.

---

#### 6. `src/core/__init__.py` — Export `CurrentEventsSearch`

**What:** Added import and `__all__` entry.

**Architectural alignment:** Standard — all core classes are exported here.

**Cross-module impact:** None.

---

#### 7. `requirements.txt` — Added `ddgs>=6.0.0`

**What:** DuckDuckGo search package (renamed from `duckduckgo-search`).

**Cross-module impact:** None — import is guarded by try/except.

---

#### 8. `daily.py` — Fallback topic generation

**What:** Wrapped `brainstorm_topics()` in try/except. On failure, makes a standalone Grok call to generate a creative random topic (high temperature for variety).

**Architectural alignment:** Follows the same pattern as the RAG brainstorm fallback — uses GrokClient directly for a one-shot call.

**Cross-module impact:** None — `daily.py` is a top-level script.

---

#### 9. `src/core/current_events.py` — Fixed package import + socket cleanup

**What:** Updated import to prefer `ddgs` package (falling back to `duckduckgo_search`). Use `with DDGS()` context manager to properly close connections.

**Architectural alignment:** Resource cleanup — prevents leaked sockets.

**Cross-module impact:** None.
