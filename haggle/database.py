"""SQLite database for community price reports and tourism ads."""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "haggle.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS price_reports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                item        TEXT NOT NULL,
                item_slug   TEXT NOT NULL,
                city        TEXT NOT NULL,
                city_slug   TEXT NOT NULL,
                country     TEXT,
                price       REAL NOT NULL,
                currency    TEXT NOT NULL DEFAULT 'USD',
                price_usd   REAL,
                condition   TEXT DEFAULT 'new',
                fuzzy_area  TEXT,
                lat         REAL,
                lng         REAL,
                notes       TEXT,
                photo_path  TEXT,
                source      TEXT DEFAULT 'community',
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tourism_ads (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                tagline     TEXT,
                city        TEXT NOT NULL,
                city_slug   TEXT NOT NULL,
                country     TEXT,
                category    TEXT,
                link        TEXT,
                active      INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_prices_item_city
                ON price_reports(item_slug, city_slug);
        """)


def slugify(text: str) -> str:
    return text.lower().strip().replace(" ", "_").replace("-", "_")


def get_prices(item: str, city: str) -> list[dict]:
    item_slug = slugify(item)
    city_slug = slugify(city)
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT item, city, country, price, currency, price_usd,
                   condition, fuzzy_area, lat, lng, notes, photo_path, source, created_at
            FROM price_reports
            WHERE item_slug LIKE ? AND city_slug LIKE ?
            ORDER BY created_at DESC
            LIMIT 50
        """, (f"%{item_slug}%", f"%{city_slug}%")).fetchall()
    return [dict(r) for r in rows]


# Common items by category used for the dropdown suggestions
COMMON_ITEMS = {
    "Clothing & Textiles": [
        "silk scarf", "pashmina shawl", "leather bag", "leather belt",
        "handwoven textile", "batik sarong", "cotton shirt", "tailored suit",
        "embroidered dress", "wool blanket", "keffiyeh", "sari",
    ],
    "Souvenirs & Crafts": [
        "ceramic bowl", "wood carving", "silver jewelry", "evil eye bracelet",
        "papyrus art", "carpet", "painting", "metal lantern", "pottery",
        "hand-painted tile", "brass tray", "beaded necklace",
    ],
    "Food & Spice": [
        "spice mix", "saffron", "vanilla pods", "dried fruit", "local honey",
        "olive oil", "tea set", "coffee beans", "street food",
    ],
    "Transport": [
        "tuk-tuk ride", "taxi ride", "motorbike taxi", "rickshaw ride",
        "boat trip", "guided tour",
    ],
    "Electronics & Other": [
        "phone case", "watch", "sunglasses", "luggage", "handbag", "shoes",
    ],
}


def get_item_suggestions() -> dict:
    return COMMON_ITEMS


def submit_price(
    item: str, city: str, country: str, price: float,
    currency: str, price_usd: float, condition: str,
    fuzzy_area: str, notes: str,
    lat: float = None, lng: float = None,
    photo_path: str = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO price_reports
              (item, item_slug, city, city_slug, country, price, currency,
               price_usd, condition, fuzzy_area, lat, lng, notes, photo_path, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'community')
        """, (
            item.strip(), slugify(item),
            city.strip(), slugify(city),
            country.strip() if country else None,
            price, currency.upper(), price_usd,
            condition, fuzzy_area.strip() if fuzzy_area else None,
            lat, lng,
            notes.strip() if notes else None,
            photo_path,
        ))
        return cur.lastrowid


def get_ads(city: str) -> list[dict]:
    city_slug = slugify(city)
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT title, tagline, city, country, category, link
            FROM tourism_ads
            WHERE (city_slug = ? OR city_slug = 'global') AND active = 1
            ORDER BY RANDOM()
            LIMIT 3
        """, (city_slug,)).fetchall()
    return [dict(r) for r in rows]


def seed_sample_data():
    """Seed demo price data and ads if the DB is empty."""
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM price_reports").fetchone()[0]
        if count > 0:
            return

        import random, math
        def jitter(lat, lng, km=1.5):
            """Add ~km of random offset for privacy."""
            dlat = random.uniform(-km, km) / 111.0
            dlng = random.uniform(-km, km) / (111.0 * math.cos(math.radians(lat)))
            return round(lat + dlat, 5), round(lng + dlng, 5)

        # (item, city, country, price, currency, price_usd, area, base_lat, base_lng)
        prices = [
            # Bangkok  13.7563, 100.5018
            ("silk scarf", "Bangkok", "Thailand", 8.00, "USD", 8.00, "Near Chatuchak", 13.7563, 100.5018),
            ("silk scarf", "Bangkok", "Thailand", 12.00, "USD", 12.00, "Near Chatuchak", 13.7563, 100.5018),
            ("tuk-tuk ride", "Bangkok", "Thailand", 2.50, "USD", 2.50, "Silom area", 13.7248, 100.5291),
            ("tuk-tuk ride", "Bangkok", "Thailand", 4.00, "USD", 4.00, "Tourist center", 13.7469, 100.5350),
            ("tailored shirt", "Bangkok", "Thailand", 35.00, "USD", 35.00, "Near Silom", 13.7248, 100.5291),
            ("tailored shirt", "Bangkok", "Thailand", 55.00, "USD", 55.00, "MBK area", 13.7453, 100.5310),
            # Marrakech  31.6295, -7.9811
            ("leather bag", "Marrakech", "Morocco", 30.00, "USD", 30.00, "Medina souks", 31.6295, -7.9811),
            ("leather bag", "Marrakech", "Morocco", 55.00, "USD", 55.00, "Medina souks", 31.6295, -7.9811),
            ("spice mix", "Marrakech", "Morocco", 5.00, "USD", 5.00, "Jemaa el-Fna", 31.6258, -7.9891),
            ("spice mix", "Marrakech", "Morocco", 8.00, "USD", 8.00, "Near tanneries", 31.6352, -7.9826),
            ("carpet", "Marrakech", "Morocco", 120.00, "USD", 120.00, "Medina", 31.6295, -7.9811),
            ("carpet", "Marrakech", "Morocco", 200.00, "USD", 200.00, "Medina souks", 31.6295, -7.9811),
            # Istanbul  41.0082, 28.9784
            ("tea set", "Istanbul", "Turkey", 18.00, "USD", 18.00, "Grand Bazaar area", 41.0106, 28.9681),
            ("tea set", "Istanbul", "Turkey", 30.00, "USD", 30.00, "Grand Bazaar", 41.0106, 28.9681),
            ("ceramic bowl", "Istanbul", "Turkey", 12.00, "USD", 12.00, "Spice market", 41.0161, 28.9709),
            ("ceramic bowl", "Istanbul", "Turkey", 22.00, "USD", 22.00, "Tourist district", 41.0082, 28.9784),
            ("evil eye bracelet", "Istanbul", "Turkey", 3.00, "USD", 3.00, "Grand Bazaar", 41.0106, 28.9681),
            ("evil eye bracelet", "Istanbul", "Turkey", 8.00, "USD", 8.00, "Tourist shops", 41.0082, 28.9784),
            # Delhi  28.7041, 77.1025
            ("pashmina shawl", "Delhi", "India", 15.00, "USD", 15.00, "Janpath market", 28.6283, 77.2210),
            ("pashmina shawl", "Delhi", "India", 25.00, "USD", 25.00, "Connaught Place", 28.6329, 77.2195),
            ("handicraft figurine", "Delhi", "India", 5.00, "USD", 5.00, "Dilli Haat area", 28.5718, 77.1975),
            ("handicraft figurine", "Delhi", "India", 12.00, "USD", 12.00, "Tourist area", 28.6562, 77.2410),
            # Mexico City  19.4326, -99.1332
            ("handwoven textile", "Mexico City", "Mexico", 20.00, "USD", 20.00, "Mercado area", 19.4270, -99.1276),
            ("handwoven textile", "Mexico City", "Mexico", 35.00, "USD", 35.00, "Centro", 19.4326, -99.1332),
            ("silver jewelry", "Mexico City", "Mexico", 15.00, "USD", 15.00, "Mercado Artesanias", 19.4207, -99.1803),
            ("silver jewelry", "Mexico City", "Mexico", 28.00, "USD", 28.00, "Tourist zone", 19.4326, -99.1332),
            # Cairo  30.0444, 31.2357
            ("papyrus art", "Cairo", "Egypt", 8.00, "USD", 8.00, "Khan el-Khalili", 30.0478, 31.2619),
            ("papyrus art", "Cairo", "Egypt", 20.00, "USD", 20.00, "Tourist area", 30.0478, 31.2619),
            ("cotton galabeya", "Cairo", "Egypt", 12.00, "USD", 12.00, "Khan el-Khalili", 30.0478, 31.2619),
            ("cotton galabeya", "Cairo", "Egypt", 25.00, "USD", 25.00, "Bazaar area", 30.0444, 31.2357),
            # Bali  -8.4095, 115.1889
            ("wood carving", "Bali", "Indonesia", 15.00, "USD", 15.00, "Ubud market", -8.5069, 115.2625),
            ("wood carving", "Bali", "Indonesia", 30.00, "USD", 30.00, "Kuta tourist area", -8.7217, 115.1685),
            ("batik sarong", "Bali", "Indonesia", 5.00, "USD", 5.00, "Local market", -8.5069, 115.2625),
            ("batik sarong", "Bali", "Indonesia", 12.00, "USD", 12.00, "Beach vendor", -8.7217, 115.1685),
        ]

        for item, city, country, price, currency, price_usd, area, base_lat, base_lng in prices:
            lat, lng = jitter(base_lat, base_lng)
            conn.execute("""
                INSERT INTO price_reports
                  (item, item_slug, city, city_slug, country, price, currency,
                   price_usd, fuzzy_area, lat, lng, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'community')
            """, (item, slugify(item), city, slugify(city), country,
                  price, currency, price_usd, area, lat, lng))

        ads = [
            ("Bangkok Night Bazaar Tours", "Private guided tours of Bangkok's best night markets",
             "Bangkok", "Thailand", "tours", "#"),
            ("Marrakech Medina Walks", "Expert-led walking tours through Marrakech's historic souks",
             "Marrakech", "Morocco", "tours", "#"),
            ("Istanbul Grand Bazaar Guide", "Navigate 4,000 shops with a local insider",
             "Istanbul", "Turkey", "tours", "#"),
            ("Delhi Street Food & Market Tour", "Explore Old Delhi's markets with a food guide",
             "Delhi", "India", "food", "#"),
            ("Bali Artisan Workshop", "Learn to bargain and create with local Balinese artists",
             "Bali", "Indonesia", "experience", "#"),
            ("Cairo Khan el-Khalili Experience", "Discover Cairo's ancient bazaar with a guide",
             "Cairo", "Egypt", "tours", "#"),
            ("Mexico City Mercado Hop", "Three markets, one guide, all the best deals",
             "Mexico City", "Mexico", "tours", "#"),
        ]

        for title, tagline, city, country, category, link in ads:
            conn.execute("""
                INSERT INTO tourism_ads (title, tagline, city, city_slug, country, category, link)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (title, tagline, city, slugify(city), country, category, link))
