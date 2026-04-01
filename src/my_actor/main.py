"""
Daily Amar Desh News Scraper - Apify Actor

Scrapes news articles from www.dailyamardesh.com based on date filtering.
Extracts title (h1), description (main content), and published_date from each article page.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from apify import Actor


# Constants
BASE_URL = "https://www.dailyamardesh.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
}


async def fetch_xml(url: str) -> Optional[str]:
    """Fetch XML content from a URL."""
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        Actor.log.warning(f"Failed to fetch {url}: {e}")
        return None


async def fetch_html(url: str) -> Optional[str]:
    """Fetch HTML content from a URL."""
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        Actor.log.warning(f"Failed to fetch article page {url}: {e}")
        return None


def parse_sitemap_index(xml_content: str) -> List[str]:
    """Parse a sitemap index XML to extract all sitemap URLs."""
    sitemap_urls = []
    soup = BeautifulSoup(xml_content, "lxml-xml")

    for loc in soup.find_all("loc"):
        if loc.string:
            sitemap_urls.append(loc.string.strip())

    Actor.log.info(f"Found {len(sitemap_urls)} sitemaps in sitemap index")
    return sitemap_urls


def parse_news_sitemap(xml_content: str) -> List[Dict[str, Any]]:
    """Parse a news sitemap XML to extract article information."""
    articles = []
    soup = BeautifulSoup(xml_content, "lxml-xml")

    for url_elem in soup.find_all("url"):
        try:
            loc = url_elem.find("loc")
            if not loc or not loc.string:
                continue
            article_url = loc.string.strip()

            news_elem = url_elem.find("news:news")
            if not news_elem:
                continue

            pub_date_elem = news_elem.find("news:publication_date")
            published_date = None
            if pub_date_elem and pub_date_elem.string:
                published_date = pub_date_elem.string.strip()

            if article_url and published_date:
                articles.append({
                    "url": article_url,
                    "published_date": published_date,
                })

        except Exception as e:
            Actor.log.warning(f"Error parsing article entry: {e}")
            continue

    return articles


def parse_article_sitemap(xml_content: str) -> List[Dict[str, Any]]:
    """Parse a regular article sitemap XML (not news format)."""
    articles = []
    soup = BeautifulSoup(xml_content, "lxml-xml")

    for url_elem in soup.find_all("url"):
        try:
            loc = url_elem.find("loc")
            if not loc or not loc.string:
                continue
            article_url = loc.string.strip()

            lastmod_elem = url_elem.find("lastmod")
            published_date = None
            if lastmod_elem and lastmod_elem.string:
                published_date = lastmod_elem.string.strip()

            if article_url and published_date:
                articles.append({
                    "url": article_url,
                    "published_date": published_date,
                })

        except Exception as e:
            Actor.log.warning(f"Error parsing article entry: {e}")
            continue

    return articles


def normalize_date(date_str: str) -> Optional[str]:
    """Normalize various date formats to yyyy-mm-dd."""
    if not date_str:
        return None

    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.strftime("%Y-%m-%d")
    except ValueError:
        try:
            dt = datetime.fromisoformat(date_str.split("T")[0])
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            Actor.log.warning(f"Failed to parse date: {date_str}")
            return None


def extract_article_data(html: str, url: str, sitemap_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Extract article data from HTML.

    Args:
        html: The HTML content of the article page
        url: The URL of the article
        sitemap_date: The published date from sitemap (fallback)

    Returns:
        Dictionary with url, title, description, published_date or None if extraction fails
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract title from <h1> tag
    h1 = soup.find("h1")
    title = ""
    if h1:
        title = h1.get_text().strip()

    # Extract description from paragraphs (main content)
    paragraphs = soup.find_all("p")
    description_parts = []
    for p in paragraphs:
        text = p.get_text().strip()
        if text and len(text) > 20:  # Only meaningful paragraphs
            # Skip common non-content patterns
            if not any(skip in text.lower() for skip in ["copyright", "all rights reserved", "facebook", "twitter"]):
                description_parts.append(text)

    description = " ".join(description_parts).strip()

    # Extract published date from multiple sources
    published_date = None

    # Try JSON-LD schema first
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get("@type") == "NewsArticle":
                if "datePublished" in data:
                    published_date = normalize_date(data["datePublished"])
                    break
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue

    # Try meta tags if not found
    if not published_date:
        meta_date = soup.find("meta", {"property": "article:published_time"})
        if meta_date and meta_date.get("content"):
            published_date = normalize_date(meta_date.get("content"))

    # Try to extract from inline scripts (Next.js data)
    if not published_date:
        import re
        date_patterns = re.findall(r'(\d{4}-\d{2}-\d{2}T[\d:]+\.?\d*[\+\-]?\d*:?\d*)', html)
        if date_patterns:
            # Use the first date found (usually the article publication date)
            published_date = normalize_date(date_patterns[0])

    # Fallback to sitemap date
    if not published_date and sitemap_date:
        published_date = normalize_date(sitemap_date)

    # Validate required fields
    if not title:
        Actor.log.warning(f"Skipping {url}: No title found")
        return None

    if not description:
        Actor.log.warning(f"Skipping {url}: No description found")
        return None

    if not published_date:
        Actor.log.warning(f"Skipping {url}: No published date found")
        return None

    return {
        "url": url,
        "title": title,
        "description": description,
        "published_date": published_date,
    }


async def process_sitemap(
    sitemap_url: str, target_date: str, max_articles: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Process a sitemap URL and extract article data for matching date.

    Args:
        sitemap_url: URL of the sitemap to process
        target_date: Target date in yyyy-mm-dd format
        max_articles: Maximum number of articles to process (None for unlimited)

    Returns:
        List of matching articles with full data
    """
    matching_articles = []
    articles_processed = 0

    Actor.log.info(f"Processing sitemap: {sitemap_url}")

    xml_content = await fetch_xml(sitemap_url)
    if not xml_content:
        return matching_articles

    soup = BeautifulSoup(xml_content, "lxml-xml")

    if soup.find("sitemapindex") or soup.find_all("sitemap"):
        # This is a sitemap index - recursively process
        sitemap_urls = parse_sitemap_index(xml_content)
        for child_sitemap_url in sitemap_urls:
            if max_articles and articles_processed >= max_articles:
                break
            child_articles = await process_sitemap(child_sitemap_url, target_date, max_articles)
            matching_articles.extend(child_articles)
            articles_processed += len(child_articles)
    else:
        # This is an actual sitemap with URLs
        # Try news sitemap format first
        sitemap_articles = parse_news_sitemap(xml_content)

        # If no articles found, try regular sitemap format
        if not sitemap_articles:
            sitemap_articles = parse_article_sitemap(xml_content)

        Actor.log.info(f"Found {len(sitemap_articles)} articles in sitemap")

        # Process each article
        for article_info in sitemap_articles:
            if max_articles and articles_processed >= max_articles:
                break

            # First check date from sitemap (quick filter)
            sitemap_date = normalize_date(article_info["published_date"])
            if sitemap_date and sitemap_date[:10] != target_date:
                continue

            Actor.log.info(f"Fetching article: {article_info['url']}")

            html = await fetch_html(article_info["url"])
            if html:
                article_data = extract_article_data(
                    html,
                    article_info["url"],
                    article_info["published_date"]
                )
                if article_data:
                    # Exact date match on first 10 characters (yyyy-mm-dd)
                    if article_data["published_date"][:10] == target_date:
                        matching_articles.append(article_data)
                        articles_processed += 1
                        Actor.log.info(f"Added article: {article_data['title'][:50]}...")
                    else:
                        Actor.log.info(
                            f"Skipping {article_info['url']}: "
                            f"date mismatch (target: {target_date}, "
                            f"article: {article_data['published_date'][:10]})"
                        )

    Actor.log.info(f"Found {len(matching_articles)} matching articles in {sitemap_url}")
    return matching_articles


async def main() -> None:
    """Main entry point for the Apify Actor."""
    async with Actor:
        # Read input
        actor_input = await Actor.get_input() or {}

        # Get target date from input
        target_date = actor_input.get("date")
        if not target_date:
            Actor.log.error("Input must include 'date' field in yyyy-mm-dd format")
            await Actor.fail("Missing required field: date")
            return

        # Validate date format
        try:
            datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            Actor.log.error(f"Invalid date format: {target_date}. Expected yyyy-mm-dd")
            await Actor.fail("Invalid date format")
            return

        Actor.log.info(f"Scraping articles for date: {target_date}")

        # Get sitemap URLs from input or use default
        start_urls = actor_input.get("startUrls", [])
        if not start_urls:
            # Default to news-sitemap.xml for most recent articles
            start_urls = [{"url": f"{BASE_URL}/news-sitemap.xml"}]

        sitemap_urls = [url_data.get("url") for url_data in start_urls if url_data.get("url")]

        if not sitemap_urls:
            Actor.log.error("No valid sitemap URLs found in input")
            await Actor.fail("No valid sitemap URLs")
            return

        Actor.log.info(f"Processing {len(sitemap_urls)} sitemap URL(s)")

        # Optional: max_articles limit for testing
        max_articles = actor_input.get("maxArticles")

        # Process all sitemaps and collect matching articles
        all_articles = []
        for sitemap_url in sitemap_urls:
            articles = await process_sitemap(sitemap_url, target_date, max_articles)
            all_articles.extend(articles)
            if max_articles and len(all_articles) >= max_articles:
                all_articles = all_articles[:max_articles]
                break

        Actor.log.info(f"Total articles found for {target_date}: {len(all_articles)}")

        # Push results to dataset
        if all_articles:
            for article in all_articles:
                await Actor.push_data(article)
            Actor.log.info(f"Successfully pushed {len(all_articles)} articles to dataset")
        else:
            Actor.log.info(f"No articles found for date: {target_date}")


if __name__ == "__main__":
    asyncio.run(main())
