# Domain Packs

This app is intended to be a niche meme generator, not only a bluegrass meme
generator. A domain pack defines what a community cares about, what it finds
funny, which references matter, and how to evaluate whether a meme feels native.

## Existing Pack

```text
domains/bluegrass/
  config.yaml
  entities.yaml
  prompts/
```

## Create A Pack

```bash
python scripts/create_domain_pack.py golf "Golf Culture"
```

Then edit:

- `domains/<name>/config.yaml` for tone, humor focus, topic categories, and current event searches.
- `domains/<name>/entities.yaml` for important people, groups, events, places, and terms.
- `domains/<name>/prompts/*.j2` for niche-specific generation, evaluation, captions, and brainstorming.
- `topic_radar` in `config.yaml` for seed topics, priority entities, event terms, and recurring rituals.

## What Makes A Good Pack

Define the inside jokes before chasing templates:

- Who is the audience?
- What do they love?
- What do they argue about?
- What behaviors or rituals are instantly recognizable?
- Which references are beloved, overused, or risky?
- What current sources should the radar watch?

For bluegrass, examples include festival culture, jam session dynamics, Billy
Strings as a mainstream bridge, gear debates, and traditionalist vs newgrass
tension.

## Runtime Behavior

The Generate screen now lists installed domain packs. Choosing a pack forces the
generator to use that pack's config, prompts, current-event searches, and RAG
knowledge base when available.

Use `Generic / Auto` for broad topics that do not yet have a pack.

## Topic Radar

The Topic Radar proposes candidates before generation. Each candidate includes:

- `topic`
- `lane`
- `source`
- `why_now`
- `meme_angle`
- `audience`
- freshness, relevance, and comedy scores

Example config:

```yaml
topic_radar:
  priority_entities:
    - Billy Strings
    - Molly Tuttle
  event_terms:
    - festival lineup
    - campground jam
  rituals:
    - arguing whether a very good song is legally bluegrass
  seed_topics:
    - topic: Billy Strings fans explaining this is definitely still bluegrass
      lane: anchor_artist
      source: manual seed
      why_now: Billy is the biggest bridge into the wider internet.
      meme_angle: Contrast crossover fame with tiny genre rule debates.
      audience: Billy fans and bluegrass lifers
      freshness_score: 9
      relevance_score: 10
      comedy_score: 9
```
