"""
Stage 1: Ingestion.

Difference from a single-feed design: this pulls from a *list* of RSS
sources (Google News + Bing News + any direct publisher feeds you add in
SOURCES) instead of one feed, because a single feed misses stories a
second feed catches, and having several sources report the same deal is
also exactly the signal Stage 3 (credibility) uses for corroboration.

Live mode needs outbound internet (fine on Streamlit Cloud / Vercel).
Demo mode reads data/demo_seed.json so the pipeline can be reviewed and
re-run with zero network calls and zero API keys.
"""
import json
import os
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from .models import Article

DEMO_SEED_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "demo_seed.json")

# Search terms used to build query URLs for each feed. Kept short and
# composable so adding a region or category later is a one-line change.
DEFAULT_QUERIES = [
    "FMCG acquisition",
    "FMCG merger",
    "consumer goods acquires",
    "consumer packaged goods investment",
    "private equity stake FMCG",
]

RSS_FEED_TEMPLATES = {
    "Google News": "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
    "Bing News": "https://www.bing.com/news/search?q={query}&format=rss",
}


def build_feed_urls(queries=None, region_hint=None):
    """Build the list of RSS URLs to hit for live ingestion."""
    queries = queries or DEFAULT_QUERIES
    urls = []
    for query in queries:
        q = query if not region_hint else f"{query} {region_hint}"
        for name, template in RSS_FEED_TEMPLATES.items():
            urls.append((name, template.format(query=quote_plus(q))))
    return urls


def fetch_live(queries=None, region_hint=None, days_back=14, feedparser_module=None):
    """
    Fetch and parse RSS feeds. Requires the `feedparser` package and
    outbound network access -- this is the path used when the app is
    deployed (Streamlit Cloud / Vercel), not inside this offline demo.
    """
    if feedparser_module is None:
        import feedparser as feedparser_module

    cutoff = datetime.utcnow() - timedelta(days=days_back)
    articles = []
    for source_name, url in build_feed_urls(queries, region_hint):
        parsed = feedparser_module.parse(url)
        for entry in parsed.entries:
            published = entry.get("published", "") or entry.get("updated", "")
            articles.append(
                Article(
                    title=entry.get("title", "").strip(),
                    source=source_name,
                    url=entry.get("link", ""),
                    published=published,
                    snippet=(entry.get("summary", "") or "").strip(),
                )
            )
    return articles


def load_demo(path=DEMO_SEED_PATH):
    """Load the offline demo dataset (real, recently reported FMCG deals
    gathered by hand, plus a couple of intentional duplicates and two
    off-topic/low-credibility items used to prove the later stages work)."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [Article(**item) for item in raw]
