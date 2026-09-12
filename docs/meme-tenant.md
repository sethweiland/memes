# Meme page tenant (sketch)

A friend should be able to fork **this repo** and run **their** meme page — brand, prompts, queue, and posting — without becoming Seth and without touching the life-ops dashboard.

This is a product / architecture outline, not the extract. No code in this epic. Do not change Flask nav, life-ops, or production Fly (`meme-ops`).

**Read this in one sitting.** The inventory below is from the current tree, not a wish list.

---

## 1. The split

Two products. Two repos. Two friend paths.

| Who | Fork | What they get |
|---|---|---|
| Friend who wants a dashboard | [`sethweiland/life-ops`](https://github.com/sethweiland/life-ops) | Home, Projects, Spend, calendar, queues. No generator. `/memes/` 404s on purpose. |
| Friend who wants a meme page | [`sethweiland/memes`](https://github.com/sethweiland/memes) (this repo) | Generator, Imgflip, daily approve queue, Instagram publish. |

**Today this repo still ships both.** Production [ops.sethweiland.com](https://ops.sethweiland.com) still runs from here on Fly app `meme-ops`. `life-ops` is already extracted; cutover is later and **out of this epic**. Do not merge the generator back into life-ops. Do not put meme-page identity into the life-ops tenant file.

`config/tenant.example.yaml` is the **life-ops** tenant (human, projects, modules, folders). A friend who copies it here gets a dashboard with `memes: false`. That is not a meme-page tenant. The meme product needs its own file.

```
life-ops = shell
  Projects / Spend / calendar / X queue / Grok Bot catalog

memes = generator product
  brand + page → domain pack + prompts → (optional RAG) → Imgflip/S3 → human approve → Instagram
```

---

## 2. Friend-ready shape (target)

One YAML file. No secrets in it. Copy, edit, boot a second brand.

```yaml
# config/meme-tenant.example.yaml  (does not exist yet — target for milestone b)
# Safe to commit. Never put tokens, passwords, or ARNs here.

brand:
  id: your-page                 # kebab-case; session / queue stamp
  name: Your Meme Page
  description: ""               # one line; not a prompt pack

# Page IDs and tokens live in env (names only here).
instagram:
  access_token_env: META_IG_ACCESS_TOKEN
  ig_user_id_env: META_IG_USER_ID
  page_id_env: META_PAGE_ID
  app_id_env: META_APP_ID

domain: your-niche              # domains/<name>/  (pack + prompts)
# prompt_pack: your-niche       # only if we later split prompts from domain

rag:
  enabled: false                # default off; Generate UI already has LLM-only / web
  corpus_path: ""               # user-provided JSON; not required; not in git

assets:
  bucket_env: MEME_ASSETS_BUCKET
  public_base_url_env: MEME_ASSETS_PUBLIC_BASE_URL
  # generated JPEGs stay under public/memes/generated/

queue:
  prefix: ops/queue/daily-candidates/   # private JSON in the assets bucket
  local_dir: data/daily_candidates      # fallback when S3 is unset

taste:
  examples_path: data/meme_training/approved.jsonl
  evaluator: two_stage          # domain-pack criteria, not the legacy bluegrass evaluator

secrets:
  backend: env                  # env now; aws / bitwarden later — values never here
```

**Secrets stay out of the file:** `.env`, Fly secrets, AWS Secrets Manager, or (later) Bitwarden. Today the meme stack reads AWS SM when `BLUEGRASS_SECRET_ARN` or `APP_SECRET_ARN` is set, then env. Life-ops `secrets.backend: aws | bitwarden` is named but not implemented.

A friend who only wants Generate + a daily queue should need: Imgflip, xAI (or the model they pick), optional OpenAI if they turn RAG on, optional Meta token if they publish. They should not need Seth’s bucket, Fly app, or High Lonesome IDs.

---

## 3. Inventory — what is already a lever vs still Seth/bluegrass

Honest list. If it is not here, it is not a documented lever.

### Already a taste / product lever

| Lever | Where | What a friend can do today |
|---|---|---|
| **Domain pack** | `domains/<name>/config.yaml` + `entities.yaml` | Tone, style, humor focus, evaluation weights, current-events queries, topic-radar seeds. Only `bluegrass` ships. `scripts/create_domain_pack.py golf "Golf Culture"` scaffolds another. |
| **Prompt pack** | `domains/<name>/prompts/*.j2` | Generation, caption, brainstorm, query expansion, evaluation, video. Two-stage uses these when a pack is selected. |
| **Generate UI pack picker** | `/memes/generate/` | Default is **Generic / Auto**, not bluegrass. Context: LLM only / web / auto. Humor edge, creativity, model, optional critic loop. |
| **Generic path** | `src/core/generic_config.py`, `GenericTwoStagePipeline` | Works without a pack. Evaluation criteria are generic (humor / relevance / novelty / compression / fit). |
| **Two-stage evaluator** | Domain `evaluation_criteria` | Pack-defined scores. This is the real taste lever for ranking. |
| **Taste examples** | `data/meme_training/approved.jsonl` | Injected at generate time. Path is a constructor arg (`TasteExampleStore(path=...)`) but callers use the default file. |
| **Human feedback** | `data/feedback.json` | Soft prompt memory from thumbs in the UI. Local file, not tenant-scoped. |
| **Template catalog** | Imgflip + `data/ai_template_descriptions.json` + hand-written dict in `templates.py` | Generic internet templates, not bluegrass-specific. S3 copies live at `public/memes/templates/`. |
| **Imgflip render** | `IMGFLIP_USERNAME` / `IMGFLIP_PASSWORD` | Already env. No Seth account baked into code. |
| **S3 assets + queue** | `MEME_ASSETS_BUCKET`, `MEME_ASSETS_PUBLIC_BASE_URL` | Bucket name is already env. Prefixes are code (`public/memes/generated/`, `ops/queue/daily-candidates/`). Local fallback if unset. |
| **Approve / daily-candidates** | `scripts/generate_daily_candidates.py`, `/memes/gallery/daily-candidates/` | Human gate. Approve publishes; skip does not. Nothing auto-posts. `--domain` exists (default still `bluegrass`). Daily path currently **skips RAG** (`num_context_chunks=0`). |
| **Instagram brands file** | `instagram_brands.json` (gitignored) + example | Multi-page sketch: name, IDs, `access_token_env`, `active_brand`. Token is env. **IDs are in the JSON today**, not env. |
| **Topic radar** | Domain pack `topic_radar:` | Per-pack, not a separate tenant field. |

### Still hardcoded to High Lonesome / bluegrass / Seth infra

These are the blockers for “second brand, no code edits.”

**Brand / page**

- `instagram_brands.example.json` is High Lonesome, with Seth’s IG user / page / app IDs in the file.
- Dashboard fallback if the file is missing: `id: high_lonesome` (`web/blueprints/dashboard.py`).
- `InstagramPublisher` defaults: `DEFAULT_IG_USER_ID`, `DEFAULT_PAGE_ID`, `DEFAULT_META_APP_ID` (High Lonesome / “Bluegrass Memes Publisher”).
- `.env.example` fills those same IDs as META_* defaults.
- Brand file shape is inconsistent: example is a **dict** of brands; dashboard `_load_brands` treats `brands` as a **list**. Publisher `load_brand_config` expects the dict. A friend copying the example will not get a working selector without a code look.

**Domain / prompts / RAG**

- Only shipped pack is `domains/bluegrass/`.
- `daily.py` always `load_domain("bluegrass")` and brainstorms `"funny bluegrass"`.
- `scripts/generate_daily_candidates.py` and topic-radar API default `--domain` / `?domain=` to `bluegrass`.
- RAG corpus is in-repo convention, not a switch: gitignored `articles/bluegrass_unlimited_archives.json`; `articles/article_urls.json` is Bluegrass Unlimited URLs; indexes at `data/<domain>/chroma` with a **legacy** fallback to `data/chroma` (old bluegrass index).
- Generate can already run with RAG off. There is **no** tenant field for “use this corpus file” or “RAG on/off at boot.”
- `data/topic_radar/bluegrass.json` is committed as a cache.

**Taste that still assumes bluegrass**

- `src/core/evaluator.py` (legacy `MemeEvaluator`, still used by the old `MemePipeline` evaluate path) hardcodes “evaluating **bluegrass** music meme concepts.”
- `taste_examples.py` fallback tags: jam session, fiddle tune, banjo, festival, gatekeeping, instrument stereotypes, …
- `data/meme_training/approved.jsonl` is almost all `domain: "bluegrass"`.
- Two-stage “page voice” / fermented edge copy talks about festival / jam / campsite energy even on the generic path.

**Infra names**

- Fly app `meme-ops` in `fly.toml` (Seth’s production. Do not rename it in this epic).
- S3 example / docs / comments: `bluegrass-meme-pipeline-dev-meme-assets`.
- Terraform `app_name` default: `bluegrass-meme-pipeline` (`infra/meme-assets`, `infra/secrets`). Variables exist; defaults do not.
- Secret ARN env: `BLUEGRASS_SECRET_ARN` (also `APP_SECRET_ARN`, `KLING_SECRET_ARN`).
- Queue **location** is the bucket env + hardcoded prefix `ops/queue/daily-candidates/`. `QueueStorage` accepts a prefix; nothing reads one from a tenant file.
- The same bucket also holds **life-ops** private keys (`ops/tenant.yaml`, projects, spend, calendar, X queue, Grok Bot). A meme-only friend should get a bucket of their own, or at least not be told to reuse Seth’s.

**Pipeline knobs in code, not tenant**

- `PipelineConfig`: `num_concepts=100`, `num_images=5`, `creativity=1.0`, `humor_edge=7`, `two_stage=True`, `token_budget=100000`. Daily script overrides some (`count` default 5, creativity 1.2). Fine to leave as code/CLI until a second brand boots.

**Not inventing these as levers** (they look related; they are not tenant-ready):

- Video ads (`video_*` prompts, Kling, ElevenLabs) — still under the bluegrass pack; separate product surface.
- Niche discovery (`niche-discovery/`) — its own config and Reddit keys.
- Life-ops tenant / Folders / Spend / X — other product.
- Critic loop — optional Generate flag, not a brand identity file.

---

## 4. Target runtime (after the milestones)

```
meme-tenant.yaml
        │
        ├─ brand id / name
        ├─ domain pack + prompts
        ├─ rag on/off + corpus path
        ├─ assets bucket (env)
        └─ approve-queue prefix
                │
                ▼
     generate → Imgflip / S3 templates → queue JSON → human approve → Instagram
```

IG / page IDs: **env only** (or AWS SM / Bitwarden). The YAML names the env keys. Tokens never in git, never in the example file.

One process, one tenant file. Not a multi-tenant SaaS. A second brand is a second checkout (or a second YAML + env), not an org switcher.

---

## 5. Milestones (smallest first)

### (a) Document current levers — **this doc**

Stop rediscovering the list. Point friends here. No code.

### (b) `config/meme-tenant.example.yaml` that boots a second brand without code edits

New file. Do **not** overload `config/tenant.example.yaml` (life-ops). Loader reads brand id, domain pack, queue prefix, RAG flag/path. Instagram IDs from env. Example brand is a placeholder (“Your Meme Page”), not High Lonesome. A friend should be able to:

1. Copy the example.
2. Set `domain:` to a pack they created with `create_domain_pack.py`.
3. Set Imgflip + model keys in `.env`.
4. Run Generate and daily-candidates against **their** brand id.

Until this lands, a second brand is: copy JSON, fight the list-vs-dict brands bug, and still hit bluegrass defaults in scripts.

### (c) Parameterize bucket / Fly / app names

Terraform `app_name` / `environment` already exist — change **defaults and docs**, and make the app read only env (no High Lonesome / `bluegrass-meme-pipeline-*` fallbacks in Python comments that get copied). Friend Fly app name is theirs (`fly launch`), not `meme-ops`. **Do not rename Seth’s production `meme-ops`.**

### (d) Optional RAG drop-in

Corpus is user-provided. Default off. If `rag.enabled` and `corpus_path` point at a JSON file, index into `data/<domain>/` (or a path the tenant names). If off or missing, Generate stays on LLM-only / web — which the UI already supports. Daily candidates can keep skipping RAG until someone opts in. Do not ship Seth’s Bluegrass Unlimited archive as the friend default (it is already gitignored for copyright).

### (e) Strip High Lonesome from defaults

Example brands, dashboard fallback, publisher `DEFAULT_*` IDs, `.env.example` META IDs, `daily.py`, topic-radar default, taste fallback tags, legacy evaluator copy. Keep `domains/bluegrass/` as **an** example pack Seth uses, not the silent default for a friend clone.

### Can wait

- Pulling the life-ops Flask shell out of this repo (cutover is a deploy-source change on `life-ops`; not this epic).
- Video pipeline / Kling / ElevenLabs as tenant fields.
- Niche discovery.
- Multi-brand in one running app (the JSON sketch is enough; one active brand per process is fine).
- Implementing AWS / Bitwarden backends (names are enough; env works).
- Topic radar as its own tenant key (it already lives on the domain pack).
- Renaming `BLUEGRASS_SECRET_ARN` (keep as alias; prefer `APP_SECRET_ARN`).
- Charging anyone. Hosting SaaS. Orgs / invites.

---

## 6. What we will not do in this epic

- **Merge memes back into life-ops.** Dashboard friends fork `life-ops`. Meme friends fork `memes`. Shared S3 `ops/` layout can stay as a convention; the products do not become one repo again.
- **Auto-post without a human gate.** Approve stays a click. The app does not schedule Instagram.
- **Charge Seth money.** No billed multi-tenant, no “we’ll host it for you” that shows up on his card. Friend runs their own Fly / bucket / keys.

Also out of scope here: changing production Fly, Cloudflare Access, or the Folders / Home / Projects nav.

---

## Pointers (existing docs, not replaced)

- Domain packs: [`docs/domain-packs.md`](domain-packs.md)
- Daily queue + human approve: [`docs/daily-candidates.md`](daily-candidates.md)
- Instagram publish: [`docs/instagram-publishing.md`](instagram-publishing.md)
- Life-ops shell (other product): [`docs/life-ops.md`](life-ops.md) and the `life-ops` repo
- S3 layout: [`infra/meme-assets/README.md`](../infra/meme-assets/README.md)
