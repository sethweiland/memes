#!/usr/bin/env python3
"""
Offline job: discover new imgflip templates, describe them with Grok vision,
and auto-add high-confidence results to the catalog.

Usage:
    python scripts/refresh_templates.py                        # Discover new templates
    python scripts/refresh_templates.py --backfill             # Describe existing undescribed
    python scripts/refresh_templates.py --backfill --limit 50  # With limit
    python scripts/refresh_templates.py --dry-run              # Preview without API calls
    python scripts/refresh_templates.py --approve-reviewed     # Points to review web UI
    python scripts/refresh_templates.py --confidence 8         # Custom threshold
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.core.templates import TemplatesCatalog, TEMPLATE_DESCRIPTIONS
from src.core.template_describer import TemplateDescriber

AI_DESCRIPTIONS_PATH = Path("data/ai_template_descriptions.json")
REVIEW_QUEUE_PATH = Path("data/template_descriptions_review.json")


def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def discover_new_templates(catalog: TemplatesCatalog) -> list:
    """Fetch from imgflip API and find templates not in our catalog."""
    import httpx

    response = httpx.get(TemplatesCatalog.IMGFLIP_API)
    response.raise_for_status()
    data = response.json()

    if not data.get("success"):
        print(f"imgflip API error: {data}")
        return []

    new_templates = []
    for meme in data["data"]["memes"]:
        if meme["id"] not in catalog.templates:
            new_templates.append(meme)

    return new_templates


def find_undescribed(catalog: TemplatesCatalog, ai_descriptions: dict) -> list:
    """Find templates in the catalog that have no description (hand-written or AI)."""
    undescribed = []
    for template in catalog.templates.values():
        has_handwritten = template.name in TEMPLATE_DESCRIPTIONS
        has_ai = template.id in ai_descriptions
        if not has_handwritten and not has_ai:
            undescribed.append(template)
    return undescribed


def run_discover(args):
    """Discover new templates from imgflip API."""
    catalog = TemplatesCatalog()
    ai_descriptions = load_json(AI_DESCRIPTIONS_PATH)
    review_queue = load_json(REVIEW_QUEUE_PATH)

    print(f"Catalog: {len(catalog.templates)} templates")
    print(f"AI descriptions: {len(ai_descriptions)}")
    print(f"Review queue: {len(review_queue)}")

    new_templates = discover_new_templates(catalog)
    print(f"\nNew templates from imgflip: {len(new_templates)}")

    if not new_templates:
        print("No new templates found.")
        return

    if args.dry_run:
        print("\n[DRY RUN] Would process:")
        for t in new_templates[:20]:
            print(f"  - {t['name']} (id={t['id']}, {t['box_count']} boxes)")
        if len(new_templates) > 20:
            print(f"  ... and {len(new_templates) - 20} more")
        return

    # Add new templates to catalog first
    from src.core.templates import MemeTemplate

    for meme in new_templates:
        template = MemeTemplate(
            id=meme["id"],
            name=meme["name"],
            url=meme["url"],
            width=meme["width"],
            height=meme["height"],
            box_count=meme["box_count"],
        )
        catalog.templates[template.id] = template

    catalog._save_expanded_cache()
    print(f"Saved expanded cache with {len(catalog.templates)} templates")

    # Describe the new ones
    _describe_templates(
        [catalog.templates[m["id"]] for m in new_templates],
        ai_descriptions,
        review_queue,
        args,
    )


def run_backfill(args):
    """Describe existing undescribed templates."""
    catalog = TemplatesCatalog()
    ai_descriptions = load_json(AI_DESCRIPTIONS_PATH)
    review_queue = load_json(REVIEW_QUEUE_PATH)

    print(f"Catalog: {len(catalog.templates)} templates")
    print(f"Hand-written descriptions: {len(TEMPLATE_DESCRIPTIONS)}")
    print(f"AI descriptions: {len(ai_descriptions)}")
    print(f"Review queue: {len(review_queue)}")

    undescribed = find_undescribed(catalog, ai_descriptions)
    # Also exclude those already in the review queue
    undescribed = [t for t in undescribed if t.id not in review_queue]

    print(f"\nUndescribed templates: {len(undescribed)}")

    if args.limit:
        undescribed = undescribed[: args.limit]
        print(f"Processing first {len(undescribed)} (--limit {args.limit})")

    if not undescribed:
        print("Nothing to describe.")
        return

    if args.dry_run:
        print("\n[DRY RUN] Would process:")
        for t in undescribed[:20]:
            print(f"  - {t.name} (id={t.id}, {t.box_count} boxes)")
        if len(undescribed) > 20:
            print(f"  ... and {len(undescribed) - 20} more")
        return

    _describe_templates(undescribed, ai_descriptions, review_queue, args)


def _describe_templates(templates, ai_descriptions, review_queue, args):
    """Run vision description on a list of templates and route by confidence."""
    threshold = args.confidence
    describer = TemplateDescriber()

    approved_count = 0
    queued_count = 0
    error_count = 0

    for i, template in enumerate(templates, 1):
        print(f"\n[{i}/{len(templates)}] {template.name} ...", end=" ", flush=True)

        result = describer.describe_template(template)

        if result.error:
            print(f"ERROR: {result.error}")
            error_count += 1
        elif result.confidence >= threshold:
            ai_descriptions[result.template_id] = result.to_dict()
            approved_count += 1
            print(f"APPROVED (confidence={result.confidence})")
        else:
            review_queue[result.template_id] = result.to_dict()
            queued_count += 1
            print(f"QUEUED (confidence={result.confidence})")

        # Rate limiting: 1s between calls, 2s backoff on error
        if result.error:
            time.sleep(2)
        elif i < len(templates):
            time.sleep(1)

    describer.close()

    # Save results
    save_json(AI_DESCRIPTIONS_PATH, ai_descriptions)
    save_json(REVIEW_QUEUE_PATH, review_queue)

    print(f"\n{'='*50}")
    print(f"SUMMARY")
    print(f"{'='*50}")
    print(f"Processed:  {len(templates)}")
    print(f"Approved:   {approved_count} (confidence >= {threshold})")
    print(f"For review: {queued_count} (confidence < {threshold})")
    print(f"Errors:     {error_count}")
    print(f"\nTotal AI descriptions: {len(ai_descriptions)}")
    print(f"Total in review queue: {len(review_queue)}")


def run_approve_reviewed(args):
    """Point user to the review web UI."""
    review_queue = load_json(REVIEW_QUEUE_PATH)
    print(f"Review queue has {len(review_queue)} entries.")
    print()
    print("Use the review web UI to approve/reject descriptions:")
    print("  python scripts/review_templates.py")
    print("  Then open http://localhost:5000")


def main():
    parser = argparse.ArgumentParser(
        description="Discover and describe meme templates with Grok vision"
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Describe existing undescribed templates instead of discovering new ones",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max templates to process (useful with --backfill)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be processed without making API calls",
    )
    parser.add_argument(
        "--approve-reviewed",
        action="store_true",
        help="Open review web UI (see scripts/review_templates.py)",
    )
    parser.add_argument(
        "--confidence",
        type=int,
        default=7,
        help="Confidence threshold for auto-approval (default: 7)",
    )

    args = parser.parse_args()

    if args.approve_reviewed:
        run_approve_reviewed(args)
    elif args.backfill:
        run_backfill(args)
    else:
        run_discover(args)


if __name__ == "__main__":
    main()
