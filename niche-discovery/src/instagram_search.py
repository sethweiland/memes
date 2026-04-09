"""
Instagram competitor search via Apify.

Uses Apify's Instagram Search Scraper to find existing meme pages
for each niche, helping identify market saturation.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"

# Apify Instagram Search Scraper actor ID
INSTAGRAM_SEARCH_ACTOR = "apify/instagram-search-scraper"

# Base URL for Apify API
APIFY_API_BASE = "https://api.apify.com/v2"


@dataclass
class InstagramAccount:
    """An Instagram account found via search."""
    username: str
    full_name: str = ""
    biography: str = ""
    followers: int = 0
    following: int = 0
    posts_count: int = 0
    is_verified: bool = False
    is_business: bool = False
    category: str = ""
    profile_url: str = ""

    @property
    def is_meme_page(self) -> bool:
        """Heuristic: likely a meme page if bio/name contains meme keywords."""
        text = f"{self.username} {self.full_name} {self.biography}".lower()
        meme_keywords = ["meme", "memes", "funny", "humor", "comedy", "jokes", "lol", "lmao"]
        return any(kw in text for kw in meme_keywords)


@dataclass
class SearchResult:
    """Results from searching Instagram for a niche."""
    niche_name: str
    search_terms: list[str]
    accounts_found: list[InstagramAccount] = field(default_factory=list)
    meme_pages_found: int = 0
    largest_competitor: str = ""
    largest_competitor_followers: int = 0
    search_completed: bool = False
    error: str = ""


def get_apify_token() -> str:
    """Get Apify API token from environment."""
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        raise ValueError("APIFY_API_TOKEN not set in environment")
    return token


def generate_search_terms(niche_name: str) -> list[str]:
    """
    Generate Instagram search terms for a niche.

    Args:
        niche_name: The niche name (e.g., "Gym Addicts")

    Returns:
        List of search terms to try
    """
    # Clean up niche name
    base = niche_name.lower().strip()

    # Remove common suffixes
    for suffix in [" enthusiasts", " lovers", " addicts", " fans", " community", " crew",
                   " owners", " users", " players", " practitioners", " experts", " pros",
                   " specialists", " hobbyists", " collectors", " wizards", " masters",
                   " gurus", " artists", " makers", " creators", " warriors", " ninjas"]:
        if base.endswith(suffix):
            base = base[:-len(suffix)].strip()

    # Remove filler words for long names
    filler_words = ["electric", "vehicle", "the", "and", "of", "for", "in", "on"]
    words = base.split()
    if len(words) > 2:
        words = [w for w in words if w not in filler_words]
        base = " ".join(words)

    # If still too long, take first 2 meaningful words
    words = base.split()
    if len(words) > 3:
        base = " ".join(words[:2])

    # Generate variations
    terms = [
        f"{base} memes",
        f"{base.replace(' ', '')}memes",  # no space version
        f"{base} humor",
    ]

    # Add singular/plural variations
    if base.endswith("s") and len(base) > 3:
        singular = base[:-1]
        terms.append(f"{singular} memes")
    elif not base.endswith("s"):
        terms.append(f"{base}s memes")

    # Dedupe while preserving order
    seen = set()
    unique = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    return unique[:4]  # Limit to 4 searches per niche


def run_instagram_search(search_term: str, max_results: int = 10) -> list[dict]:
    """
    Run Instagram search via Apify.

    Args:
        search_term: What to search for
        max_results: Maximum number of results per search

    Returns:
        List of account data dictionaries
    """
    token = get_apify_token()

    # Prepare the actor input
    actor_input = {
        "search": search_term,
        "searchType": "user",  # Search for users/accounts
        "resultsLimit": max_results,
    }

    # Start the actor run
    run_url = f"{APIFY_API_BASE}/acts/{INSTAGRAM_SEARCH_ACTOR}/runs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    logger.debug(f"  Starting Apify search for: {search_term}")

    try:
        # Start run (synchronous - waits for completion)
        response = requests.post(
            run_url,
            headers=headers,
            json=actor_input,
            params={"waitForFinish": 120},  # Wait up to 2 minutes
            timeout=180,
        )
        response.raise_for_status()
        run_data = response.json()

        # Get the dataset ID from the run
        dataset_id = run_data.get("data", {}).get("defaultDatasetId")
        if not dataset_id:
            logger.warning(f"  No dataset ID in response")
            return []

        # Fetch results from the dataset
        dataset_url = f"{APIFY_API_BASE}/datasets/{dataset_id}/items"
        dataset_response = requests.get(
            dataset_url,
            headers=headers,
            timeout=30,
        )
        dataset_response.raise_for_status()

        items = dataset_response.json()
        logger.debug(f"  Found {len(items)} results for '{search_term}'")
        return items

    except requests.exceptions.RequestException as e:
        logger.warning(f"  Apify request failed: {e}")
        return []


def parse_account_data(data: dict) -> InstagramAccount:
    """Parse raw Apify response into InstagramAccount."""
    return InstagramAccount(
        username=data.get("username", ""),
        full_name=data.get("fullName", "") or data.get("full_name", ""),
        biography=data.get("biography", "") or data.get("bio", ""),
        followers=data.get("followersCount", 0) or data.get("followers", 0),
        following=data.get("followingCount", 0) or data.get("following", 0),
        posts_count=data.get("postsCount", 0) or data.get("posts", 0),
        is_verified=data.get("verified", False) or data.get("isVerified", False),
        is_business=data.get("isBusinessAccount", False),
        category=data.get("businessCategory", "") or data.get("category", ""),
        profile_url=f"https://instagram.com/{data.get('username', '')}",
    )


def search_niche_competitors(niche_name: str, max_results_per_term: int = 10) -> SearchResult:
    """
    Search Instagram for competitor meme pages for a niche.

    Args:
        niche_name: The niche to search for
        max_results_per_term: Max results per search term

    Returns:
        SearchResult with found accounts
    """
    result = SearchResult(
        niche_name=niche_name,
        search_terms=generate_search_terms(niche_name),
    )

    seen_usernames = set()
    all_accounts = []

    for term in result.search_terms:
        logger.info(f"  Searching: '{term}'")

        try:
            raw_results = run_instagram_search(term, max_results_per_term)

            for data in raw_results:
                account = parse_account_data(data)
                if account.username and account.username not in seen_usernames:
                    seen_usernames.add(account.username)
                    all_accounts.append(account)

            # Rate limit between searches
            time.sleep(2)

        except Exception as e:
            logger.warning(f"  Search failed for '{term}': {e}")
            continue

    # Filter to likely meme pages and sort by followers
    meme_pages = [a for a in all_accounts if a.is_meme_page]
    meme_pages.sort(key=lambda x: -x.followers)

    result.accounts_found = all_accounts
    result.meme_pages_found = len(meme_pages)
    result.search_completed = True

    if meme_pages:
        result.largest_competitor = meme_pages[0].username
        result.largest_competitor_followers = meme_pages[0].followers

    return result


def search_all_niches(
    niches: list[str] | None = None,
    max_niches: int = 50,
    max_results_per_term: int = 10,
) -> dict[str, SearchResult]:
    """
    Search Instagram for competitors for multiple niches.

    Args:
        niches: List of niche names to search, or None to load from all_niches.json
        max_niches: Maximum number of niches to search
        max_results_per_term: Max results per search term

    Returns:
        Dict mapping niche name to SearchResult
    """
    # Load niches if not provided
    if niches is None:
        niches_file = DATA_DIR / "all_niches.json"
        if niches_file.exists():
            data = json.loads(niches_file.read_text())
            niches = list(data.keys())[:max_niches]
        else:
            logger.error("No niches file found and no niches provided")
            return {}

    results = {}

    for i, niche_name in enumerate(niches[:max_niches], 1):
        logger.info(f"[{i}/{len(niches)}] Searching for: {niche_name}")

        try:
            result = search_niche_competitors(niche_name, max_results_per_term)
            results[niche_name] = result

            if result.meme_pages_found > 0:
                logger.info(f"  Found {result.meme_pages_found} meme pages, "
                           f"largest: @{result.largest_competitor} ({result.largest_competitor_followers:,} followers)")
            else:
                logger.info(f"  No meme pages found - potential opportunity!")

            # Rate limit between niches
            time.sleep(3)

        except Exception as e:
            logger.error(f"  Failed to search {niche_name}: {e}")
            results[niche_name] = SearchResult(
                niche_name=niche_name,
                search_terms=[],
                error=str(e),
            )

    return results


def update_niches_with_instagram_data(results: dict[str, SearchResult]):
    """
    Update all_niches.json with Instagram competitor data.

    Args:
        results: Dict of niche name to SearchResult
    """
    niches_file = DATA_DIR / "all_niches.json"
    if not niches_file.exists():
        logger.error("all_niches.json not found")
        return

    niches = json.loads(niches_file.read_text())

    for niche_key, niche_data in niches.items():
        niche_name = niche_data.get("niche_name", niche_key)

        if niche_name in results:
            result = results[niche_name]

            if result.search_completed:
                # Update Instagram fields
                niche_data["instagram_searched"] = True
                niche_data["instagram_meme_pages_found"] = result.meme_pages_found

                if result.meme_pages_found > 0:
                    niche_data["instagram_page_exists"] = True
                    niche_data["instagram_largest_competitor"] = result.largest_competitor
                    niche_data["instagram_largest_followers"] = result.largest_competitor_followers
                    niche_data["instagram_page_url"] = f"https://instagram.com/{result.largest_competitor}"
                else:
                    niche_data["instagram_page_exists"] = False

    # Save updated data
    with open(niches_file, "w") as f:
        json.dump(niches, f, indent=2)

    logger.info(f"Updated {len(results)} niches with Instagram data")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    import argparse
    parser = argparse.ArgumentParser(description="Search Instagram for niche competitors")
    parser.add_argument("--niche", type=str, help="Single niche to search")
    parser.add_argument("--max-niches", type=int, default=10, help="Max niches to search")
    parser.add_argument("--dry-run", action="store_true", help="Just show search terms, don't call API")
    args = parser.parse_args()

    if args.niche:
        if args.dry_run:
            terms = generate_search_terms(args.niche)
            print(f"Search terms for '{args.niche}':")
            for t in terms:
                print(f"  - {t}")
        else:
            result = search_niche_competitors(args.niche)
            print(f"\nResults for '{args.niche}':")
            print(f"  Search terms: {result.search_terms}")
            print(f"  Accounts found: {len(result.accounts_found)}")
            print(f"  Meme pages: {result.meme_pages_found}")
            if result.largest_competitor:
                print(f"  Largest: @{result.largest_competitor} ({result.largest_competitor_followers:,} followers)")
    else:
        results = search_all_niches(max_niches=args.max_niches)
        update_niches_with_instagram_data(results)

        print("\n" + "=" * 60)
        print("INSTAGRAM SEARCH SUMMARY")
        print("=" * 60)

        # Sort by opportunity (no competitors = good)
        opportunities = [(n, r) for n, r in results.items() if r.meme_pages_found == 0]
        saturated = [(n, r) for n, r in results.items() if r.meme_pages_found > 0]

        print(f"\nOpen opportunities (no meme pages found): {len(opportunities)}")
        for name, _ in opportunities[:10]:
            print(f"  - {name}")

        print(f"\nSaturated niches: {len(saturated)}")
        for name, r in sorted(saturated, key=lambda x: -x[1].largest_competitor_followers)[:10]:
            print(f"  - {name}: @{r.largest_competitor} ({r.largest_competitor_followers:,})")
