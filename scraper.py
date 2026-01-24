#!/usr/bin/env python3
"""
Bluegrass Unlimited Archives Scraper
Scrapes articles from https://bluegrassunlimited.com/article-categories/the-archives/
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import os
from datetime import datetime

BASE_URL = "https://bluegrassunlimited.com"
ARCHIVES_URL = f"{BASE_URL}/article-categories/the-archives/"
OUTPUT_DIR = "articles"
DELAY_BETWEEN_REQUESTS = 1  # seconds, be polite to the server

def get_soup(url):
    """Fetch a URL and return BeautifulSoup object."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return BeautifulSoup(response.text, 'html.parser')

def get_article_urls_from_page(page_num):
    """Extract all article URLs from an archive listing page."""
    if page_num == 1:
        url = ARCHIVES_URL
    else:
        url = f"{ARCHIVES_URL}page/{page_num}/"

    print(f"Fetching archive page {page_num}: {url}")
    soup = get_soup(url)

    article_urls = []
    # Look for article links - adjust selector based on actual HTML structure
    for link in soup.find_all('a', href=True):
        href = link['href']
        if '/article/' in href and href not in article_urls:
            if href.startswith('/'):
                href = BASE_URL + href
            article_urls.append(href)

    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for url in article_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    return unique_urls

def scrape_article(url):
    """Scrape a single article and return its data."""
    print(f"  Scraping: {url}")
    soup = get_soup(url)

    article_data = {
        'url': url,
        'scraped_at': datetime.now().isoformat()
    }

    # Title - try common selectors
    title_tag = soup.find('h1') or soup.find('title')
    article_data['title'] = title_tag.get_text(strip=True) if title_tag else None

    # Author - look for common patterns
    author_tag = soup.find('span', class_='author') or soup.find(class_='byline')
    if not author_tag:
        # Try looking for "By" text
        for tag in soup.find_all(['p', 'span', 'div']):
            text = tag.get_text()
            if text.strip().startswith('By ') and len(text) < 100:
                article_data['author'] = text.strip().replace('By ', '')
                break
    else:
        article_data['author'] = author_tag.get_text(strip=True)

    # Original publication info - look for issue/date references
    article_text = soup.get_text()
    article_data['original_source'] = None
    for line in article_text.split('\n'):
        if 'Bluegrass Unlimited' in line and any(month in line for month in
            ['January', 'February', 'March', 'April', 'May', 'June',
             'July', 'August', 'September', 'October', 'November', 'December']):
            article_data['original_source'] = line.strip()
            break

    # Main content - try to find the article body
    content_div = (
        soup.find('article') or
        soup.find('div', class_='entry-content') or
        soup.find('div', class_='post-content') or
        soup.find('div', class_='article-content') or
        soup.find('main')
    )

    if content_div:
        # Get text content, preserving paragraph breaks
        paragraphs = content_div.find_all(['p', 'h2', 'h3', 'blockquote'])
        article_data['content'] = '\n\n'.join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
    else:
        # Fallback: get body text
        body = soup.find('body')
        article_data['content'] = body.get_text(separator='\n', strip=True) if body else None

    return article_data

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_articles = []
    all_article_urls = []

    # First, collect all article URLs from all archive pages
    print("=" * 60)
    print("Phase 1: Collecting article URLs from archive pages")
    print("=" * 60)

    for page_num in range(1, 47):  # 46 pages total
        try:
            urls = get_article_urls_from_page(page_num)
            all_article_urls.extend(urls)
            print(f"  Found {len(urls)} articles on page {page_num}")
            time.sleep(DELAY_BETWEEN_REQUESTS)
        except Exception as e:
            print(f"  Error on page {page_num}: {e}")
            continue

    # Deduplicate URLs
    all_article_urls = list(dict.fromkeys(all_article_urls))
    print(f"\nTotal unique articles found: {len(all_article_urls)}")

    # Save URL list for reference
    with open(f"{OUTPUT_DIR}/article_urls.json", 'w') as f:
        json.dump(all_article_urls, f, indent=2)
    print(f"Saved URL list to {OUTPUT_DIR}/article_urls.json")

    # Now scrape each article
    print("\n" + "=" * 60)
    print("Phase 2: Scraping individual articles")
    print("=" * 60)

    for i, url in enumerate(all_article_urls, 1):
        try:
            print(f"[{i}/{len(all_article_urls)}]", end="")
            article = scrape_article(url)
            all_articles.append(article)
            time.sleep(DELAY_BETWEEN_REQUESTS)
        except Exception as e:
            print(f"  Error scraping {url}: {e}")
            continue

        # Save progress every 50 articles
        if i % 50 == 0:
            with open(f"{OUTPUT_DIR}/articles_progress.json", 'w') as f:
                json.dump(all_articles, f, indent=2, ensure_ascii=False)
            print(f"  Progress saved ({i} articles)")

    # Save final results
    output_file = f"{OUTPUT_DIR}/bluegrass_unlimited_archives.json"
    with open(output_file, 'w') as f:
        json.dump(all_articles, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print(f"Done! Scraped {len(all_articles)} articles")
    print(f"Saved to: {output_file}")
    print("=" * 60)

if __name__ == "__main__":
    main()
