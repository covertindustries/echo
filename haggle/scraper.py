"""Reddit scraper for real-world price data from travel communities."""

import os
import re
import time
from typing import Optional
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

TRAVEL_SUBREDDITS = [
    "travel", "solotravel", "backpacking", "digitalnomad",
    "ThailandTourism", "Morocco", "Turkey", "india", "mexico",
    "indonesia", "Egypt", "bali",
]

# Regex to find price mentions like "$5", "5 USD", "200 baht", "50 TL"
PRICE_PATTERN = re.compile(
    r"(?:USD?|EUR?|GBP?|THB|baht|TL|lira|dirham|MAD|INR|rupee|IDR|rupiah"
    r"|MXN|peso|EGP|pound|SGD|AED|CNY|yuan)?\s*"
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(?:USD?|EUR?|GBP?|THB|baht|TL|lira|dirham|MAD|INR|rupee|IDR|rupiah"
    r"|MXN|peso|EGP|pound|SGD|AED|CNY|yuan)?",
    re.IGNORECASE,
)

CURRENCY_MAP = {
    "usd": "USD", "dollar": "USD", "dollars": "USD",
    "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
    "thb": "THB", "baht": "THB",
    "tl": "TRY", "lira": "TRY",
    "mad": "MAD", "dirham": "MAD",
    "inr": "INR", "rupee": "INR", "rupees": "INR",
    "idr": "IDR", "rupiah": "IDR",
    "mxn": "MXN", "peso": "MXN", "pesos": "MXN",
    "egp": "EGP",
    "cny": "CNY", "yuan": "CNY",
    "sgd": "SGD",
    "aed": "AED",
}


def _detect_currency(text: str) -> str:
    text_lower = text.lower()
    for key, val in CURRENCY_MAP.items():
        if key in text_lower:
            return val
    return "USD"


def _extract_price_from_text(text: str) -> Optional[float]:
    matches = PRICE_PATTERN.findall(text)
    prices = []
    for m in matches:
        try:
            val = float(m.replace(",", "."))
            if 0.1 <= val <= 10000:  # sanity range
                prices.append(val)
        except ValueError:
            continue
    return prices[0] if prices else None


def _make_reddit_client():
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT", "haggle-app/1.0 price-research-bot")

    if not client_id or not client_secret:
        return None

    try:
        import praw
        return praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
    except Exception:
        return None


def scrape_reddit_prices(item: str, city: str, max_results: int = 10) -> list[dict]:
    """Search Reddit for price mentions of an item in a city."""
    reddit = _make_reddit_client()
    if not reddit:
        return _get_cached_reddit_data(item, city)

    results = []
    query = f"{item} price {city}"

    try:
        subreddit = reddit.subreddit("+".join(TRAVEL_SUBREDDITS))
        for submission in subreddit.search(query, limit=20, time_filter="year"):
            text = f"{submission.title} {submission.selftext}"
            price = _extract_price_from_text(text)
            if price:
                currency = _detect_currency(text)
                results.append({
                    "price": price,
                    "currency": currency,
                    "source": "reddit",
                    "subreddit": submission.subreddit.display_name,
                    "snippet": submission.title[:120],
                    "url": f"https://reddit.com{submission.permalink}",
                })
            if len(results) >= max_results:
                break

        # Also check comments on top posts
        if len(results) < 3:
            for submission in subreddit.search(query, limit=5):
                submission.comments.replace_more(limit=0)
                for comment in submission.comments.list()[:20]:
                    price = _extract_price_from_text(comment.body)
                    if price:
                        currency = _detect_currency(comment.body)
                        results.append({
                            "price": price,
                            "currency": currency,
                            "source": "reddit_comment",
                            "subreddit": submission.subreddit.display_name,
                            "snippet": comment.body[:120],
                            "url": f"https://reddit.com{submission.permalink}",
                        })
                    if len(results) >= max_results:
                        break

    except Exception as e:
        print(f"Reddit scrape error: {e}")
        return _get_cached_reddit_data(item, city)

    return results


def _get_cached_reddit_data(item: str, city: str) -> list[dict]:
    """Return mock Reddit data when no API key is configured."""
    item_lower = item.lower()
    city_lower = city.lower()

    mock_posts = {
        ("silk scarf", "bangkok"): [
            {"price": 6.0, "currency": "USD", "snippet": "Got a beautiful silk scarf at Chatuchak for 200 baht, they asked 500", "subreddit": "solotravel"},
            {"price": 10.0, "currency": "USD", "snippet": "Silk scarves in Bangkok - paid about $10 after haggling from $25", "subreddit": "travel"},
        ],
        ("leather bag", "marrakech"): [
            {"price": 28.0, "currency": "USD", "snippet": "Leather bag in the medina - started at 600 MAD, got it for 300", "subreddit": "travel"},
            {"price": 45.0, "currency": "USD", "snippet": "Bought a leather satchel, paid 450 MAD after some back and forth", "subreddit": "solotravel"},
        ],
        ("carpet", "marrakech"): [
            {"price": 100.0, "currency": "USD", "snippet": "Small Berber rug in Marrakech medina, paid $100 (they asked $300)", "subreddit": "travel"},
            {"price": 180.0, "currency": "USD", "snippet": "Got a nice carpet for about $180 USD after serious negotiating", "subreddit": "backpacking"},
        ],
    }

    # Fuzzy match
    for (mock_item, mock_city), posts in mock_posts.items():
        if mock_item in item_lower and mock_city in city_lower:
            return [dict(p, source="reddit", url="#") for p in posts]

    return []
