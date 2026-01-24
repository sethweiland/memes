#!/usr/bin/env python3
"""
Example usage of the Bluegrass RAG pipeline.

Before running:
1. Install dependencies: pip install -r requirements.txt
2. Set up .env file with API keys:
   OPENAI_API_KEY=your_openai_key
   XAI_API_KEY=your_xai_key
"""

from src.rag import BluegrassRAG


def example_indexing():
    """Index articles into the vector store."""
    print("=" * 60)
    print("INDEXING ARTICLES")
    print("=" * 60)

    rag = BluegrassRAG()

    # Index articles (only needs to be done once)
    chunk_count = rag.index_articles(
        "articles/bluegrass_unlimited_archives.json",
        clear_existing=False,  # Set to True to reindex
    )

    print(f"\nIndexed {chunk_count} chunks")
    print(f"Stats: {rag.get_stats()}")


def example_search():
    """Demonstrate various search capabilities."""
    print("\n" + "=" * 60)
    print("SEARCH EXAMPLES")
    print("=" * 60)

    rag = BluegrassRAG()

    # Basic search
    print("\n--- Basic Search: 'Earl Scruggs banjo' ---")
    results = rag.search("Earl Scruggs banjo", k=3)
    for i, r in enumerate(results, 1):
        print(f"\n{i}. Score: {r.combined_score:.3f}")
        print(f"   Artist: {r.metadata.get('artist_subject', 'N/A')}")
        print(f"   Source: {r.metadata.get('source', 'N/A')}")
        print(f"   Text: {r.text[:200]}...")

    # Search with metadata filter
    print("\n--- Filtered Search: mandolin technique (1960-1980) ---")
    results = rag.search(
        "mandolin technique",
        k=3,
        filters={"year_range": (1960, 1980)}
    )
    for i, r in enumerate(results, 1):
        print(f"\n{i}. Score: {r.combined_score:.3f}")
        print(f"   Year: {r.metadata.get('year', 'N/A')}")
        print(f"   Text: {r.text[:200]}...")

    # Search by artist
    print("\n--- Search by Artist: Bill Monroe ---")
    results = rag.search_by_artist("Bill Monroe", k=3)
    for i, r in enumerate(results, 1):
        print(f"\n{i}. Score: {r.combined_score:.3f}")
        print(f"   Title: {r.metadata.get('title', 'N/A')}")
        print(f"   Text: {r.text[:200]}...")

    # Search by instrument
    print("\n--- Search by Instrument: banjo ---")
    results = rag.search_by_instrument("banjo", "picking style", k=3)
    for i, r in enumerate(results, 1):
        print(f"\n{i}. Score: {r.combined_score:.3f}")
        print(f"   Instruments: {r.metadata.get('instruments', 'N/A')}")
        print(f"   Text: {r.text[:200]}...")


def example_meme_generation():
    """Generate meme ideas using RAG."""
    print("\n" + "=" * 60)
    print("MEME GENERATION")
    print("=" * 60)

    rag = BluegrassRAG()

    # Generate meme ideas
    print("\n--- Generating memes for: 'Bill Monroe being stubborn about what counts as bluegrass' ---")

    try:
        ideas = rag.generate_meme_ideas(
            "Bill Monroe being stubborn about what counts as bluegrass",
            num_ideas=2,
            num_context_chunks=5,
        )

        for i, idea in enumerate(ideas, 1):
            print(f"\n--- Meme {i} ---")
            print(f"Format: {idea.format}")
            print(f"Top: {idea.top_text}")
            print(f"Bottom: {idea.bottom_text}")
            print(f"Explanation: {idea.explanation}")
            print(f"Source: {idea.source_quote}")
            print(f"Artist: {idea.artist_reference}")

    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Grok API error (check XAI_API_KEY): {e}")


def example_brainstorm():
    """Brainstorm meme topics from the archive."""
    print("\n" + "=" * 60)
    print("TOPIC BRAINSTORMING")
    print("=" * 60)

    rag = BluegrassRAG()

    try:
        print("\n--- Brainstorming meme topics ---")
        topics = rag.brainstorm_topics(
            seed_query="funny bluegrass stories personalities",
            num_topics=5,
        )

        print("\nSuggested topics:")
        for i, topic in enumerate(topics, 1):
            print(f"  {i}. {topic}")

    except Exception as e:
        print(f"Grok API error (check XAI_API_KEY): {e}")


def example_query_expansion():
    """Demonstrate query expansion."""
    print("\n" + "=" * 60)
    print("QUERY EXPANSION")
    print("=" * 60)

    from src.retriever import BluegrassRetriever

    retriever = BluegrassRetriever()

    queries = [
        "weird banjo players",
        "mandolin chop technique",
        "high lonesome sound",
    ]

    for query in queries:
        print(f"\nOriginal: '{query}'")
        expanded = retriever.expand_query(query, num_variants=3)
        print("Expanded:")
        for v in expanded:
            print(f"  - {v}")


if __name__ == "__main__":
    import sys

    examples = {
        "index": example_indexing,
        "search": example_search,
        "meme": example_meme_generation,
        "brainstorm": example_brainstorm,
        "expand": example_query_expansion,
        "all": lambda: [f() for f in [
            example_indexing,
            example_search,
            example_query_expansion,
            example_meme_generation,
            example_brainstorm,
        ]],
    }

    if len(sys.argv) > 1:
        example_name = sys.argv[1]
        if example_name in examples:
            examples[example_name]()
        else:
            print(f"Unknown example: {example_name}")
            print(f"Available: {', '.join(examples.keys())}")
    else:
        print("Bluegrass RAG Examples")
        print("=" * 60)
        print("\nUsage: python example.py <example>")
        print("\nAvailable examples:")
        print("  index     - Index articles into vector store")
        print("  search    - Demonstrate search capabilities")
        print("  meme      - Generate meme ideas")
        print("  brainstorm - Brainstorm meme topics")
        print("  expand    - Show query expansion")
        print("  all       - Run all examples")
        print("\nExample: python example.py search")
