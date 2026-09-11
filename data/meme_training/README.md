# Meme Training Dataset

This folder stores approved and rejected meme examples for prompt-time taste retrieval.

These records are for learning structure, rhythm, and humor patterns. They are not a
license to repost or copy the original jokes.

## Files

- `approved.jsonl`: examples the user likes.
- `rejected.jsonl`: examples or generated outputs the user rejects.

## Record Shape

```json
{
  "id": "bg_0001",
  "source_image_ref": "chat_2026-05-10_001",
  "image_path": "",
  "domain": "bluegrass",
  "template": "",
  "visible_text": {
    "top": "",
    "bottom": "",
    "other": []
  },
  "humor_patterns": [],
  "tags": [],
  "why_it_works": "",
  "generation_lesson": "",
  "do_not_copy": true,
  "approved": true
}
```
