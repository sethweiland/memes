# Life Ops

A human-gated life-ops shell. One human. Many agents. Self-hosted.

This document is the product contract for the Flask shell in this repo
(`ops.sethweiland.com` today). A friend should be able to fork, plug in
their projects, and run their own instance. It is not a multi-tenant SaaS.

Long-term the shell should leave this repository as a clean `life-ops`
extract, once it no longer imports meme code. Until then the shell lives
here and is **config-driven**.

---

## What it is

Agents write work. The human decides. Spend and routines attribute to
projects.

Home is an inbox of decisions, not a chatbot log and not a project-management
suite. It is Waiting on you first, then — when the calendar module is on —
This week and On the horizon from a snapshot or optional ICS feed. Never
invented events. Horizon starts the Monday after this week's Sunday, not
14 days out. The app never posts, buys, or cancels. There are no hub cards.

## What it is not

- Not Linear
- Not Notion
- Not a meme app (memes are an optional module)
- Not a chatbot transcript
- Not a hosted SaaS

Domain UIs (memes, X, shopping, calendar) are optional modules. They must
not own the shell. The shell owns navigation, Home, Projects, and the
five primitives below.

Top nav is always **Home · Projects · Spend · X · More ▾**. X stays a
peer tab (human-gate inbox). Grok Bot and Memes tools nest under More
folders from tenant `folders:` — navigation config, not a sixth primitive.

---

## Five primitives

This release refuses a sixth. Do not add Goals, Areas, People, or a
generic “Workspace” object. Tenant `folders:` are More-menu bookmarks
only. They are not stored as objects and they are not a sixth primitive.

### 1. Project

A named bet. One row on `/projects/`. Not a spend bucket with a different label.

| Field | Type | Notes |
|---|---|---|
| `id` | kebab-case string | Stable. Used by spend, queues, and routines. |
| `name` | string | Human label |
| `lane` | enum | Attention, not agile. See lanes below. |
| `owner_agent` | string or null | Who is supposed to move this (Grok Bot, Codex, Stevie, …) |
| `updated_at` | ISO-8601 | Last write (human or agent) |
| `links.repo` | URL or null | |
| `links.prod` | URL or null | |
| `summary` | string or null | One-liner. Do not invent. |
| `last_done` | string or null | Agent-written. Empty if unknown. |
| `next_steps` | string or null | Agent-written. Empty if unknown. |

**Lanes** (attention, not sprint state):

| id | Product copy |
|---|---|
| `idea` | Idea |
| `active` | Active |
| `blocked` | Blocked |
| `waiting_on_you` | Waiting on you |
| `parked` | Parked |

Product copy and templates use `waiting_on_you`. Never hardcode
`waiting_on_seth`. On read, the alias `waiting_on_seth` normalizes to
`waiting_on_you` so old files do not break.

`shared` and `unallocated` are **Spend-only**. They are never project rows.

### 2. Queue item

One reviewable, agent-written thing.

| Field | Notes |
|---|---|
| `kind` | Module-specific (X: `follow` / `post` / `reply`; memes: daily candidate; …) |
| `payload` | The thing to review |
| `status` | `pending` \| `approved` \| `skipped` \| `done` |
| `project` | **Required.** Stamp a project id. |

X drafts (`ops/queue/x-activity/`) and meme daily candidates
(`ops/queue/daily-candidates/`) are modules of this shape. This release
does not rewrite those modules. New reviewable work should use the same
envelope rather than inventing a sixth primitive.

### 3. Human gate

Home (`/`) is the inbox of decisions.

The app **never**:

- posts to X
- publishes to Instagram on its own
- buys anything
- cancels a subscription
- starts or stops a Grok Bot routine

Approve / skip / move-lane are the verbs. Execution stays with the human
or with an agent the human already runs.

### 4. Cost event

Tokens and subscriptions stamp a project id.

- Token events: `ops/usage/{provider}/{YYYY}/{MM}.json` (`project` on each event)
- Subscriptions: `data/tech_spend.json` (`project` or `projects` shares)

Leftovers stay visible as `shared` (overhead that is not one product) and
`unallocated` (missing tag). Spend never hides unlabeled dollars to clean
up a chart.

Project ids for Spend come from tenant config (project rows) plus the
two Spend-only ids. Do not keep a second hardcoded product list in Python
when the tenant file already has the ids.

`/spend/` shows a **Tokens** widget at the top (this month’s calls, tokens,
and heuristic $ — not the xAI invoice), then the ledger. Unallocated means
“Missing project tag — shown on purpose.” Shared is overhead that is not one
product.

### 5. Routine

A scheduled job with an owner and a last run. The catalog already exists
at `ops/grok-bot/routines.json` (git / local seed: `data/grok_bot_routines.json`).

Routines attach to the shell via:

- `owner_agent` — already on each catalog row
- `project_id` (or `project`) — optional; accepted by the normalizer, not
  required on existing rows

This release documents the attachment. It does not start, stop, or invent
routine rows.

---

## Tenant config

Projects belong in config, not code.

| Path | Who |
|---|---|
| `config/tenant.example.yaml` | Friend template. Committed. Placeholder name. 2–3 example projects. 1–2 example folders. Modules off except `projects` + `spend` + `calendar` (empty snapshot is fine). No meme / X / Grok Bot links. `secrets.backend: env`. |
| `config/tenant.yaml` | Operator-private. **Gitignored.** Copy the example and put your bets in. Never commit this file. |
| `s3://$MEME_ASSETS_BUCKET/ops/tenant.yaml` | What Fly / Jeffy use after the local file is gone from git. Same YAML shape. No secrets. |
| `tests/fixtures/` | Example tenants and spend ledgers for tests only. |

A friend configures their instance from the five primitives plus the
example files. Operator-private life data does not live in git.

**Load order** (never crash a friend clone):

1. `TENANT_CONFIG` if set
2. S3 `ops/tenant.yaml` when `MEME_ASSETS_BUCKET` is set
3. `config/tenant.yaml` if present on disk
4. `config/tenant.example.yaml`

Relative `TENANT_CONFIG` paths resolve from the process cwd, then the repo root.
Jeffy / operators upload their tenant to `ops/tenant.yaml`. Do not put secrets
in the YAML. This is not a multi-tenant SaaS — one human, one file.

### Reference

```yaml
human:
  name: Your Name          # display only
  timezone: America/New_York
  handle: ""               # optional public handle

site:
  title: Ops
  domain: ops.example.com  # footer / docs; not a bind address

modules:
  projects: true
  spend: true
  x: false
  grok_bot: false
  memes: false
  calendar: true

calendar:
  enabled: true            # Home This week / Horizon. No Google OAuth.

secrets:
  backend: env             # env | aws | bitwarden
  # Never put credentials in this file.
  # aws / bitwarden are documented backends; only `env` is implemented.

agents:                    # the humans-you-already-have, as ids
  - id: grok-bot
    name: Grok Bot
  - id: codex
    name: Codex

defaults:
  usage_project: home-ops  # stamped on token events when USAGE_PROJECT is unset

folders:                   # More menu. Nav only — not a sixth primitive.
  - id: life
    name: Life
    project_ids: [home-ops]
    links:                 # optional extra bookmarks
      - label: Home
        href: /            # or named route: route: home.index
  - id: work
    name: Work
    project_ids: [side-project]

projects:                  # named bets (list rows). Not shared / unallocated.
  - id: home-ops
    name: Home Ops
    lane: active
    owner_agent: grok-bot
    color: "#2563eb"       # optional; Spend pie
    description: ""        # optional; Spend subtitle
    links:
      repo: https://github.com/you/your-fork
      prod: ""
    summary: Personal life-ops shell
    last_done: null
    next_steps: null
```

Rules:

- `id` must match `^[a-z0-9]+(?:-[a-z0-9]+)*$` (projects and folders)
- `lane` must be one of the five lanes (or the `waiting_on_seth` alias)
- `shared` and `unallocated` in `projects:` are ignored (Spend-only)
- Folder `project_ids` that are not in `projects:` are skipped. Projects
  with no folder still appear on `/projects/`; they just do not show in More.
- Extra `links` may use `href` or a Flask `route`. If the href/route belongs
  to a disabled module, the link is omitted so the menu never 404s.
- A project with a module homepage (`memes` → `/memes/`, `x` → `/x/`) links
  there when that module is on; otherwise it links to `/projects/`.
- No API keys, tokens, passwords, or ARNs in the YAML

---

## S3 / private key layout

All application S3 writes go through `S3Store` + `BucketLayout`
(`src/core/s3_store.py`). Public GET is only `public/memes/*`.

```
s3://$MEME_ASSETS_BUCKET/
├── public/memes/                         # PUBLIC (Instagram JPEGs + templates)
│   ├── templates/{id}.{ext}
│   └── generated/{hash}_{stem}.jpg
└── ops/                                  # PRIVATE
    ├── tenant.yaml                       # operator tenant (Jeffy uploads this)
    ├── projects/board.json               # project list
    ├── calendar/snapshot.json            # read-only Home calendar
    ├── queue/daily-candidates/{YYYY-MM-DD}.json
    ├── queue/x-activity/{YYYY-MM-DD}.json
    ├── grok-bot/routines.json
    └── usage/{provider}/{YYYY}/{MM}.json
```

| Key | Local fallback when `MEME_ASSETS_BUCKET` is unset |
|---|---|
| `ops/tenant.yaml` | `config/tenant.yaml` or `config/tenant.example.yaml` |
| `ops/projects/board.json` | `data/projects/board.json` |
| `ops/calendar/snapshot.json` | `data/calendar/snapshot.json` |
| `ops/queue/x-activity/{date}.json` | `data/x_activity/{date}.json` |
| `ops/queue/daily-candidates/{date}.json` | `data/daily_candidates/` |
| `ops/grok-bot/routines.json` | `data/grok_bot_routines.json` |
| `ops/usage/{provider}/{YYYY}/{MM}.json` | `data/usage/{provider}/{YYYY}/{MM}.json` |

If `ops/projects/board.json` (and the local file) are missing, the app
seeds the board from `tenant.yaml` `projects:` and writes through once.
Later tenant ids that are not yet on the board are merged in; existing
lanes / `last_done` / `next_steps` are not overwritten.

Never write ops JSON under `public/`.

---

## Module enable flags

| Flag | Routes | This release |
|---|---|---|
| `projects` | `/projects/` | Compact list (status pill = lane). Required for the friend path. |
| `spend` | `/spend/` | Ledger plus a Tokens widget at the top. Project ids from tenant. |
| `x` | `/x/` | Existing Stevie draft review. Stays a top-level tab (human-gate inbox). |
| `grok_bot` | `/grok-bot/` | Existing routine catalog. Nested under More → Agents, not a peer tab. |
| `memes` | `/memes/` and children | Existing pipeline. Nested under More → Software → Memes. Subnav remains on `/memes/`. |
| `calendar` | Home widgets only | This week + On the horizon (Monday after this Sunday through ~3 months). Snapshot or optional `CALENDAR_ICS_URL`. No in-app Google OAuth. Not a sixth primitive. |

Disabled modules are hidden from the top nav and from More (module links
only). Their URLs still 404. The More menu itself never 404s. Home is
always on. Empty folders after filtering are omitted.

A friend who only wants a board and a spend page leaves `x`, `grok_bot`,
and `memes` false. They can leave `calendar` on with an empty snapshot.
They do not need Imgflip, Instagram, X, or Google credentials. Their
example folders have no meme / X / Grok Bot links.

---

## Secrets adapter

No secrets in git. No secrets in tenant YAML.

```
SecretsBackend.get(name, default="") -> str
```

| `secrets.backend` | Status |
|---|---|
| `env` | Implemented. Reads `os.environ` (and therefore `.env` / Fly secrets). |
| `aws` | Documented. Future: AWS Secrets Manager (the existing `src/core/secrets.py` helper already used by S3/memes is the likely backend). |
| `bitwarden` | Documented. Future: Bitwarden Secrets Manager. |

Tenant YAML may name the backend and, later, a secret *container* id
(ARN, collection). It must never contain the credential value.

Runtime today: set `TENANT_CONFIG` if you want a non-default file, or
upload `ops/tenant.yaml` to the bucket. Then put keys in the environment:

```
XAI_API_KEY=...
MEME_ASSETS_BUCKET=...          # optional; board falls back to data/projects/
CALENDAR_ICS_URL=...            # optional secret ICS; never put this in YAML
AWS_DEFAULT_REGION=us-east-1
```

See `.env.example` and `infra/secrets/README.md`.

---

## Agent contract

Agents you already run (Grok Bot, Codex, Cursor, …) write the published
JSON. The Flask app does not spawn them.

### Update a project card

1. Read `ops/projects/board.json` (or `data/projects/board.json` locally).
2. Canonical shape: `{ "updated_at": ISO-8601, "projects": [ card, ... ] }`.
   A bare array is accepted **on read** as `projects` and is never written
   back as an array.
3. Find the card by `id`. Update only what you know:

   ```json
   {
     "id": "memes",
     "name": "Memes",
     "lane": "waiting_on_you",
     "owner_agent": "codex",
     "updated_at": "2026-09-11T22:00:00+00:00",
     "links": { "repo": "https://github.com/you/memes", "prod": null },
     "summary": "Bluegrass meme pipeline",
     "last_done": "Shipped the project list",
     "next_steps": "Human: confirm status"
   }
   ```

4. Set `updated_at` on the card **and** the document.
5. Write the full object back to the same key. Do not put it under
   `public/`.
6. Do not invent `last_done` / `next_steps`. Leave them `null` if unknown.
7. Do not add `shared` or `unallocated` cards.
8. Lane moves from the human UI are `POST /projects/api/projects/<id>/lane`
   with `{ "lane": "active" }` (same-origin JSON, same pattern as `/x/`).
   Agents may write the file directly; they should not start routines or
   post to X from this contract.

Python helper (same process): `ProjectBoard.update_card(...)` /
`ProjectBoard.move_lane(...)`.

### Refresh the calendar snapshot

This is a read-only module, not a sixth primitive. Jeffy / another agent
writes the snapshot. Flask does not talk to Google.

1. Read `ops/calendar/snapshot.json` (or `data/calendar/snapshot.json`).
2. Canonical shape:

   ```json
   {
     "updated_at": "2026-09-12T12:00:00+00:00",
     "timezone": "America/New_York",
     "events": [
       {
         "id": "dentist",
         "title": "Dentist",
         "start": "2026-09-12T14:00:00-04:00",
         "end": "2026-09-12T14:45:00-04:00",
         "all_day": false,
         "location": null,
         "url": null
       }
     ]
   }
   ```

3. Do not invent events. Leave `events` empty if you do not know them.
4. Never write calendar credentials into `tenant.yaml`. Friends who share a
   secret ICS set `CALENDAR_ICS_URL` in the environment; the app fetches,
   parses, and caches that feed into the same snapshot shape.
5. Home shows two lists only: **This week** (now through Sunday ET) and
   **On the horizon** (Monday after this Sunday through ~3 months). Other
   events stay in the snapshot and are not shown.

Python helper: `CalendarStore.save(...)` / `CalendarStore.home_lists()`.

### Enqueue a queue item

Do not invent a new store. Use the module that already owns the kind:

| Kind | Write |
|---|---|
| X follow / post / reply | `ops/queue/x-activity/{YYYY-MM-DD}.json` — `{ date, candidates }` |
| Meme daily candidate | `ops/queue/daily-candidates/{YYYY-MM-DD}.json` |

Every item must include:

- `id` — stable
- `kind`
- `status`: `pending` on create
- `project` — a tenant project id (not `shared` / `unallocated` unless
  the work truly is overhead; prefer a real bet)
- `created_at`
- module payload (`body`, `target`, image fields, …)

The app will not post, buy, or publish as a side effect of the write.
The human reviews on `/x/` or `/memes/gallery/daily-candidates/`.

### Update a routine row

Write `ops/grok-bot/routines.json`. Set `owner_agent`, `last_run_at`,
`status`, and optionally `project_id`. The `/grok-bot/` page does not
start or stop jobs.

---

## Friend quickstart

The point of this release: a stranger can stand up **their** life ops
app without becoming Seth.

1. **Fork or clone** this repo.
2. **Copy the example tenant** and put your bets in it:

   ```bash
   cp config/tenant.example.yaml config/tenant.yaml
   ```

   Edit `human`, `site.domain`, `projects`, and optional `folders`.
   Leave `shared` / `unallocated` out. Leave `last_done` / `next_steps`
   null if you do not know them. `config/tenant.yaml` is gitignored.

   For a deploy with S3, Jeffy (or you) uploads that file to
   `ops/tenant.yaml`. Do not put secrets in it.

3. **Secrets** — use the backend you already use. For localhost:

   ```bash
   cp .env.example .env
   ```

   You need meme/X/Instagram keys only if you turn those modules on.
   A board-only instance needs no provider keys. Optional S3:

   ```
   MEME_ASSETS_BUCKET=your-private-bucket
   AWS_DEFAULT_REGION=us-east-1
   ```

   Without a bucket, the board lives at `data/projects/board.json`.

4. **Run locally**

   ```bash
   pip install -r requirements.txt
   python web/run.py
   # http://localhost:5050  → Home, then Projects
   ```

   You should see your projects in a list (not five empty swim lanes).
   Home is Waiting on you above This week / On the horizon — no hub cards.
   Spend is empty-ish until you add a local `data/tech_spend.json` (also
   gitignored); that is fine. Calendar widgets say “No calendar snapshot
   yet.” until an agent writes the snapshot or you set `CALENDAR_ICS_URL`.

5. **Fly (optional)** — same container as today (`fly.toml`, `Dockerfile`).
   Set Fly secrets for whatever modules you enabled. Point a hostname
   at the app.

6. **Cloudflare Access (optional)** — put Access in front of the hostname
   for a real deploy. Skip it on localhost. The Flask app does not
   replace Access.

7. **Agents** — point Grok Bot / Codex / whatever you already run at the
   board and queue contracts above. The app will not provision agents.

`TENANT_CONFIG=/absolute/path/to/tenant.yaml` wins over S3 and the local
file (useful in tests or a second checkout).

---

## Non-goals (this release)

- Multi-tenant SaaS, orgs, invites, or billing
- A sixth primitive
- Extracting a separate `life-ops` git repo
- Rewriting the X, memes, Spend ledger, or Grok Bot catalog UIs
- In-app Google OAuth or a live Google Calendar API (snapshot / ICS only)
- Implementing the AWS or Bitwarden secrets backends
- Starting / stopping Grok Bot routines from `/projects/` or Home
- Posting to X, buying, or canceling subscriptions
- Invented `last_done` / `next_steps`, spend figures, X drafts, or
  routine rows
- Hardcoded `waiting_on_seth` product copy
- Project rows for `shared` / `unallocated`
- Equinox (or any other) project that is not in the tenant file
- Committing an operator `config/tenant.yaml` or a personal spend ledger
- Multi-tenant SaaS (one human, one tenant file, optionally uploaded to S3)
