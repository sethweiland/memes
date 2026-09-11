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
suite. The app never posts, buys, or cancels.

## What it is not

- Not Linear
- Not Notion
- Not a meme app (memes are an optional module)
- Not a chatbot transcript
- Not a hosted SaaS

Domain UIs (memes, X, shopping, calendar) are optional modules. They must
not own the shell. The shell owns navigation, Home, Projects, and the
five primitives below.

---

## Five primitives

This release refuses a sixth. Do not add Goals, Areas, People, or a
generic “Workspace” object.

### 1. Project

A named bet. Kanban card. Not a spend bucket with a different label.

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

`shared` and `unallocated` are **Spend-only**. They are never kanban cards.

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

Project ids for Spend come from tenant config (kanban projects) plus the
two Spend-only ids. Do not keep a second hardcoded product list in Python
when the tenant file already has the ids.

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
| `config/tenant.example.yaml` | Friend template. Placeholder name. 2–3 example projects. Modules off except `projects` + `spend`. Calendar off. `secrets.backend: env`. |
| `config/tenant.yaml` | The operator’s tenant. Seth’s reference file is committed here (no secrets). |

**Load path:** `TENANT_CONFIG` if set, else `config/tenant.yaml`.
Relative paths resolve from the process cwd, then the repo root.

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
  calendar: false

calendar:
  enabled: false           # reserved; no calendar UI in this release

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

projects:                  # kanban cards. Not shared / unallocated.
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

- `id` must match `^[a-z0-9]+(?:-[a-z0-9]+)*$`
- `lane` must be one of the five lanes (or the `waiting_on_seth` alias)
- `shared` and `unallocated` in `projects:` are ignored (Spend-only)
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
    ├── projects/board.json               # kanban (this release)
    ├── queue/daily-candidates/{YYYY-MM-DD}.json
    ├── queue/x-activity/{YYYY-MM-DD}.json
    ├── grok-bot/routines.json
    └── usage/{provider}/{YYYY}/{MM}.json
```

| Key | Local fallback when `MEME_ASSETS_BUCKET` is unset |
|---|---|
| `ops/projects/board.json` | `data/projects/board.json` |
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
| `projects` | `/projects/` | Kanban. Required for the friend path. |
| `spend` | `/spend/` | Existing ledger. Project ids from tenant. |
| `x` | `/x/` | Existing Stevie draft review. Unchanged. |
| `grok_bot` | `/grok-bot/` | Existing routine catalog. Unchanged. |
| `memes` | `/memes/` and children | Existing pipeline. Unchanged. |
| `calendar` | — | Flag only. No UI. |

Disabled modules are hidden from Home and the top nav. Their URLs 404.
Home itself is always on.

A friend who only wants a board and a spend page leaves `x`, `grok_bot`,
`memes`, and `calendar` false. They do not need Imgflip, Instagram, or
X credentials.

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

Runtime today: set `TENANT_CONFIG` if you want a non-default file, then
put keys in the environment:

```
XAI_API_KEY=...
MEME_ASSETS_BUCKET=...          # optional; board falls back to data/projects/
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
     "last_done": "Shipped the kanban seed",
     "next_steps": "Human: confirm lane"
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

   Edit `human`, `site.domain`, and `projects`. Leave `shared` /
   `unallocated` out. Leave `last_done` / `next_steps` null if you do
   not know them.

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

   You should see your cards in the five lanes. Spend is empty-ish until
   you add a ledger; that is fine.

5. **Fly (optional)** — same container as today (`fly.toml`, `Dockerfile`).
   Set Fly secrets for whatever modules you enabled. Point a hostname
   at the app.

6. **Cloudflare Access (optional)** — put Access in front of the hostname
   for a real deploy. Skip it on localhost. The Flask app does not
   replace Access.

7. **Agents** — point Grok Bot / Codex / whatever you already run at the
   board and queue contracts above. The app will not provision agents.

`TENANT_CONFIG=/absolute/path/to/tenant.yaml` overrides the default file
(useful in tests or a second checkout).

---

## Non-goals (this release)

- Multi-tenant SaaS, orgs, invites, or billing
- A sixth primitive
- Extracting a separate `life-ops` git repo
- Rewriting the X, memes, Spend ledger, or Grok Bot catalog UIs
- Calendar UI (flag only)
- Implementing the AWS or Bitwarden secrets backends
- Starting / stopping Grok Bot routines from `/projects/` or Home
- Posting to X, buying, or canceling subscriptions
- Invented `last_done` / `next_steps`, spend figures, X drafts, or
  routine rows
- Hardcoded `waiting_on_seth` product copy
- Kanban cards for `shared` / `unallocated`
- Equinox (or any other) project that is not in the tenant file
