"""Reference price scraper — fetches wholesale/factory prices from Temu and AliExpress.

Used to show users the true cost of goods at source, giving context for haggling.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from typing import Optional

# Known reference prices (factory/wholesale estimates) as fallback
# These represent approximate Temu/AliExpress floor prices in USD
_REFERENCE_DB = {
    "silk scarf": {"low": 2.5, "high": 8.0, "source": "Wholesale reference"},
    "pashmina shawl": {"low": 4.0, "high": 12.0, "source": "Wholesale reference"},
    "leather bag": {"low": 8.0, "high": 25.0, "source": "Wholesale reference"},
    "leather belt": {"low": 2.0, "high": 6.0, "source": "Wholesale reference"},
    "handwoven textile": {"low": 5.0, "high": 15.0, "source": "Wholesale reference"},
    "batik sarong": {"low": 1.5, "high": 5.0, "source": "Wholesale reference"},
    "cotton shirt": {"low": 3.0, "high": 8.0, "source": "Wholesale reference"},
    "ceramic bowl": {"low": 2.0, "high": 7.0, "source": "Wholesale reference"},
    "wood carving": {"low": 5.0, "high": 18.0, "source": "Wholesale reference"},
    "silver jewelry": {"low": 3.0, "high": 12.0, "source": "Wholesale reference"},
    "evil eye bracelet": {"low": 0.5, "high": 2.0, "source": "Wholesale reference"},
    "evil eye": {"low": 0.5, "high": 2.0, "source": "Wholesale reference"},
    "papyrus art": {"low": 1.0, "high": 5.0, "source": "Wholesale reference"},
    "carpet": {"low": 20.0, "high": 80.0, "source": "Wholesale reference"},
    "painting": {"low": 5.0, "high": 20.0, "source": "Wholesale reference"},
    "metal lantern": {"low": 3.0, "high": 10.0, "source": "Wholesale reference"},
    "tea set": {"low": 5.0, "high": 15.0, "source": "Wholesale reference"},
    "spice mix": {"low": 0.5, "high": 3.0, "source": "Wholesale reference"},
    "saffron": {"low": 2.0, "high": 8.0, "source": "Wholesale reference"},
    "tailored shirt": {"low": 8.0, "high": 18.0, "source": "Wholesale reference"},
    "tailored suit": {"low": 30.0, "high": 70.0, "source": "Wholesale reference"},
    "watch": {"low": 3.0, "high": 20.0, "source": "Wholesale reference"},
    "sunglasses": {"low": 1.5, "high": 6.0, "source": "Wholesale reference"},
    "phone case": {"low": 0.5, "high": 3.0, "source": "Wholesale reference"},
    "handbag": {"low": 8.0, "high": 30.0, "source": "Wholesale reference"},
    "shoes": {"low": 8.0, "high": 25.0, "source": "Wholesale reference"},
    "brass tray": {"low": 3.0, "high": 12.0, "source": "Wholesale reference"},
    "pottery": {"low": 3.0, "high": 10.0, "source": "Wholesale reference"},
    "beaded necklace": {"low": 1.0, "high": 5.0, "source": "Wholesale reference"},
    "wool blanket": {"low": 8.0, "high": 22.0, "source": "Wholesale reference"},
    "cotton galabeya": {"low": 4.0, "high": 10.0, "source": "Wholesale reference"},
    "keffiyeh": {"low": 2.0, "high": 7.0, "source": "Wholesale reference"},
    "sari": {"low": 5.0, "high": 18.0, "source": "Wholesale reference"},
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _scrape_aliexpress(item: str) -> Optional[dict]:
    """Try to scrape AliExpress search for price range."""
    try:
        url = (
            f"https://www.aliexpress.com/wholesale"
            f"?SearchText={requests.utils.quote(item)}&SortType=price_asc"
        )
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        if resp.status_code != 200:
            return None

        # AliExpress prices are usually in data attributes
        prices = re.findall(r'"salePrice":\{"minPrice":(\d+\.?\d*)', resp.text)
        if not prices:
            prices = re.findall(r'\$\s*(\d+\.?\d*)', resp.text[:5000])

        if prices:
            vals = [float(p) for p in prices[:10] if 0.1 <= float(p) <= 500]
            if vals:
                return {
                    "low": round(min(vals), 2),
                    "high": round(sorted(vals)[len(vals)//2], 2),
                    "source": "AliExpress",
                    "url": url,
                }
    except Exception:
        pass
    return None


def _fuzzy_lookup(item: str) -> Optional[dict]:
    """Fuzzy match item against known reference prices."""
    item_lower = item.lower().strip()

    # Exact match
    if item_lower in _REFERENCE_DB:
        return dict(_REFERENCE_DB[item_lower])

    # Partial match
    for key, val in _REFERENCE_DB.items():
        if key in item_lower or item_lower in key:
            return dict(val)

    # Word overlap
    item_words = set(item_lower.split())
    best_match = None
    best_score = 0
    for key, val in _REFERENCE_DB.items():
        key_words = set(key.split())
        score = len(item_words & key_words)
        if score > best_score:
            best_score = score
            best_match = val

    if best_score > 0:
        return dict(best_match)

    return None


def get_reference_price(item: str) -> Optional[dict]:
    """Get factory/wholesale reference price for an item.

    Tries AliExpress first, falls back to internal database.
    Returns dict with keys: low, high, source (and optionally url).
    """
    # Try AliExpress live scrape
    result = _scrape_aliexpress(item)
    if result:
        return result

    # Fall back to internal reference DB
    return _fuzzy_lookup(item)
