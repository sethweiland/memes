# AI Critic Loop

The critic loop is an optional quality pass for small batches. It is intentionally bounded so the app can learn from a stronger model without turning generation into an expensive open-ended recursion.

## How it works

1. Generate and score the normal meme concept batch.
2. Select up to 3 high-potential concepts: good enough to care about, imperfect enough to improve.
3. Ask the selected critic model for a concise rewrite brief and actionable prompt rules.
4. Save that critique to `data/ai_feedback.json`.
5. Generate up to 3 critic-informed rewrites.
6. Re-score the rewrites and merge them back into the review list.
7. Include recent critic notes in future feedback context as soft guidance.

## Guardrails

- The loop is off by default.
- It critiques at most 3 candidates.
- It creates at most 3 extra concepts.
- If the critic call fails, normal generation still completes and the error is shown on the review page.
- Saved critic feedback is advisory; it does not replace human ratings or domain-pack configuration.

## UI

Open **Generate Memes**, expand **Advanced options**, then enable **Tiny AI critic loop**. The review page shows an **AI Critic Loop** details block when the pass runs successfully.

## Good uses

- Small batches where quality matters more than speed.
- Testing whether a stronger model can improve local template fit.
- Building reusable prompt memory from repeat weak spots.

## Bad uses

- Large batches where cost and latency matter most.
- Fully automatic posting.
- Repeated recursive calls without a human review step.
