import asyncio
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
from apify import Actor


BASE_URL = "https://www.dailyamardesh.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

TIMEOUT = 15


# -----------------------------
# FETCH
# -----------------------------
async def fetch(url: str) -> Optional[str]:
    try:
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if res.status_code == 200:
            return res.text
        Actor.log.warning(f"HTTP {res.status_code}: {url}")
        return None
    except Exception as e:
        Actor.log.warning(f"Fetch error: {e}")
        return None


# -----------------------------
# DATE NORMALIZE
# -----------------------------
def normalize_date(date_str: str) -> Optional[str]:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except:
        try:
            return date_str.split("T")[0]
        except:
            return None


# -----------------------------
# PARSE SITEMAP INDEX
# -----------------------------
def parse_sitemap_index(xml: str) -> List[str]:
    soup = BeautifulSoup(xml, "xml")
    links = []

    for loc in soup.find_all("loc"):
        if loc.text:
            links.append(loc.text.strip())

    return links


# -----------------------------
# PARSE ARTICLE SITEMAP
# -----------------------------
def parse_article_sitemap(xml: str) -> List[Dict]:
    soup = BeautifulSoup(xml, "xml")
    articles = []

    for url in soup.find_all("url"):
        try:
            loc = url.find("loc")
            lastmod = url.find("lastmod")

            if not loc or not lastmod:
                continue

            articles.append({
                "url": loc.text.strip(),
                "date": lastmod.text.strip()
            })
        except:
            continue

    return articles


# -----------------------------
# EXTRACT ARTICLE DATA
# -----------------------------
def extract_article(html: str, url: str, fallback_date: str):
    try:
        soup = BeautifulSoup(html, "html.parser")

        # title
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else None

        # description
        paragraphs = soup.find_all("p")
        description = " ".join(
            [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
        )

        # date
        published_date = None

        # JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and "datePublished" in data:
                    published_date = normalize_date(data["datePublished"])
                    break
            except:
                continue

        if not published_date:
            published_date = normalize_date(fallback_date)

        if not title or not description or not published_date:
            return None

        return {
            "url": url,
            "title": title,
            "description": description[:2000],
            "published_date": published_date
        }

    except Exception as e:
        Actor.log.warning(f"Parse error: {e}")
        return None


# -----------------------------
# MAIN
# -----------------------------
async def main():
    async with Actor:
        input_data = await Actor.get_input() or {}

        target_date = input_data.get(
            "date",
            datetime.now().strftime("%Y-%m-%d")
        )

        Actor.log.info(f"📅 Target date: {target_date}")

        start_urls = input_data.get("startUrls", [
            {"url": f"{BASE_URL}/sitemap.xml"}
        ])

        sitemap_urls = [u.get("url") for u in start_urls if u.get("url")]

        if not sitemap_urls:
            Actor.log.error("No sitemap URLs")
            return

        total_saved = 0

        for sitemap_url in sitemap_urls:

            xml = await fetch(sitemap_url)
            if not xml:
                continue

            # 🔥 STEP 1: get child sitemaps
            child_sitemaps = parse_sitemap_index(xml)

            Actor.log.info(f"Found {len(child_sitemaps)} child sitemaps")

            # 🔥 STEP 2: loop child sitemaps
            for sm_url in child_sitemaps:

                sm_xml = await fetch(sm_url)
                if not sm_xml:
                    continue

                articles = parse_article_sitemap(sm_xml)

                Actor.log.info(f"Found {len(articles)} articles")

                # 🔥 STEP 3: process articles
                for art in articles:
                    try:
                        sitemap_date = normalize_date(art["date"])

                        if sitemap_date != target_date:
                            continue

                        html = await fetch(art["url"])
                        if not html:
                            continue

                        data = extract_article(html, art["url"], art["date"])

                        if data and data["published_date"] == target_date:
                            await Actor.push_data(data)
                            total_saved += 1

                            Actor.log.info(f"✅ {data['title'][:40]}")

                    except Exception as e:
                        Actor.log.warning(f"Article error: {e}")
                        continue

        Actor.log.info(f"🔥 DONE — {total_saved} articles")


if __name__ == "__main__":
    asyncio.run(main())