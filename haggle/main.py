"""Haggle — The Negotiator's App
Community-powered haggling guide with AI negotiation advice, map, and reference prices.
"""

import os
import uuid
import math
import random
import shutil
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from database import (
    init_db, get_prices, submit_price, get_ads,
    seed_sample_data, get_item_suggestions,
)
from scraper import scrape_reddit_prices
from negotiator import stream_negotiation_advice
from currency import get_rates, convert_to_usd, SUPPORTED_CURRENCIES
from reference_prices import get_reference_price

app = FastAPI(title="Haggle", description="The Negotiator's App")

BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# City center coordinates for map context
CITY_COORDS = {
    "bangkok": (13.7563, 100.5018),
    "marrakech": (31.6295, -7.9811),
    "istanbul": (41.0082, 28.9784),
    "delhi": (28.7041, 77.1025),
    "mexico city": (19.4326, -99.1332),
    "cairo": (30.0444, 31.2357),
    "bali": (-8.4095, 115.1889),
    "ubud": (-8.5069, 115.2625),
    "hanoi": (21.0285, 105.8542),
    "ho chi minh city": (10.7769, 106.7009),
    "saigon": (10.7769, 106.7009),
    "beijing": (39.9042, 116.4074),
    "shanghai": (31.2304, 121.4737),
    "hong kong": (22.3193, 114.1694),
    "singapore": (1.3521, 103.8198),
    "kuala lumpur": (3.1390, 101.6869),
    "phnom penh": (11.5564, 104.9282),
    "siem reap": (13.3671, 103.8448),
    "dubai": (25.2048, 55.2708),
    "abu dhabi": (24.4539, 54.3773),
    "cairo": (30.0444, 31.2357),
    "luxor": (25.6872, 32.6396),
    "nairobi": (-1.2921, 36.8219),
    "cape town": (-33.9249, 18.4241),
    "lagos": (6.5244, 3.3792),
    "accra": (5.6037, -0.1870),
    "new delhi": (28.6139, 77.2090),
    "mumbai": (19.0760, 72.8777),
    "jaipur": (26.9124, 75.7873),
    "agra": (27.1767, 78.0081),
    "kathmandu": (27.7172, 85.3240),
    "colombo": (6.9271, 79.8612),
    "lima": (-12.0464, -77.0428),
    "cusco": (-13.5319, -71.9675),
    "buenos aires": (-34.6037, -58.3816),
    "rio de janeiro": (-22.9068, -43.1729),
    "havana": (23.1136, -82.3666),
    "mexico city": (19.4326, -99.1332),
    "oaxaca": (17.0732, -96.7266),
    "chiang mai": (18.7883, 98.9853),
    "phuket": (7.8804, 98.3923),
}


def _get_city_coords(city: str) -> tuple[float, float] | None:
    key = city.lower().strip()
    coords = CITY_COORDS.get(key)
    if coords:
        # Add small jitter (~500m) for privacy
        dlat = random.uniform(-0.005, 0.005)
        dlng = random.uniform(-0.005, 0.005)
        return round(coords[0] + dlat, 5), round(coords[1] + dlng, 5)
    return None


@app.on_event("startup")
async def startup():
    init_db()
    seed_sample_data()


@app.get("/", response_class=HTMLResponse)
async def root():
    with open(os.path.join(STATIC_DIR, "index.html")) as f:
        return f.read()


# ── Item suggestions ──────────────────────────────────────────

@app.get("/api/items")
async def api_items():
    return {"categories": get_item_suggestions()}


# ── Reference prices ──────────────────────────────────────────

@app.get("/api/reference-price")
async def api_reference_price(item: str = Query(..., min_length=1)):
    result = get_reference_price(item)
    if not result:
        raise HTTPException(404, "No reference price found")
    return result


# ── Prices ────────────────────────────────────────────────────

@app.get("/api/prices")
async def api_get_prices(
    item: str = Query(..., min_length=1, max_length=100),
    city: str = Query(..., min_length=1, max_length=100),
):
    community = get_prices(item, city)
    reddit = scrape_reddit_prices(item, city)

    all_prices_usd = [
        r["price_usd"] for r in community if r.get("price_usd")
    ] + [
        r["price"] for r in reddit if r.get("currency") == "USD"
    ]

    stats = None
    if all_prices_usd:
        sorted_p = sorted(all_prices_usd)
        stats = {
            "low": round(min(all_prices_usd), 2),
            "high": round(max(all_prices_usd), 2),
            "median": round(sorted_p[len(sorted_p) // 2], 2),
            "count": len(all_prices_usd),
        }

    # Map markers: only include reports with coordinates
    markers = [
        {
            "lat": r["lat"],
            "lng": r["lng"],
            "price": r["price"],
            "currency": r["currency"],
            "area": r.get("fuzzy_area") or city,
        }
        for r in community
        if r.get("lat") and r.get("lng")
    ]

    # City center for map default view
    city_center = CITY_COORDS.get(city.lower().strip())

    return {
        "item": item,
        "city": city,
        "community_reports": community,
        "reddit_data": reddit,
        "stats": stats,
        "markers": markers,
        "city_center": list(city_center) if city_center else None,
    }


# ── Submit (with optional photo) ──────────────────────────────

@app.post("/api/prices", status_code=201)
async def api_submit_price(
    item: str = Form(...),
    city: str = Form(...),
    country: str = Form(default=""),
    price: float = Form(...),
    currency: str = Form(default="USD"),
    condition: str = Form(default="new"),
    fuzzy_area: str = Form(default=""),
    notes: str = Form(default=""),
    photo: UploadFile = File(default=None),
):
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(400, f"Unsupported currency: {currency}")

    if price <= 0:
        raise HTTPException(400, "Price must be positive")

    price_usd = convert_to_usd(price, currency)

    # Save photo if provided
    photo_path = None
    if photo and photo.filename:
        ext = os.path.splitext(photo.filename)[-1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
            raise HTTPException(400, "Invalid image format")
        fname = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(UPLOADS_DIR, fname)
        with open(save_path, "wb") as f:
            shutil.copyfileobj(photo.file, f)
        photo_path = f"/uploads/{fname}"

    # Geocode city to fuzzy coordinates
    coords = _get_city_coords(city)
    lat, lng = (coords[0], coords[1]) if coords else (None, None)

    report_id = submit_price(
        item=item,
        city=city,
        country=country,
        price=price,
        currency=currency,
        price_usd=price_usd or price,
        condition=condition,
        fuzzy_area=fuzzy_area,
        notes=notes,
        lat=lat,
        lng=lng,
        photo_path=photo_path,
    )
    return {"id": report_id, "message": "Price submitted. Thank you!"}


# ── Negotiate ──────────────────────────────────────────────────

class NegotiateRequest(BaseModel):
    item: str = Field(..., min_length=1, max_length=100)
    city: str = Field(..., min_length=1, max_length=100)
    vendor_opening: str = Field(..., min_length=1, max_length=300)
    asking_price: float = Field(..., gt=0)
    currency: str = Field(default="USD", max_length=3)


@app.post("/api/negotiate")
async def api_negotiate(body: NegotiateRequest):
    prices = get_prices(body.item, body.city)
    prices_usd = [r["price_usd"] for r in prices if r.get("price_usd")]
    low = min(prices_usd) if prices_usd else None
    high = max(prices_usd) if prices_usd else None

    return StreamingResponse(
        stream_negotiation_advice(
            item=body.item,
            city=body.city,
            vendor_opening=body.vendor_opening,
            asking_price=body.asking_price,
            currency=body.currency.upper(),
            community_low=low,
            community_high=high,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Currencies ────────────────────────────────────────────────

@app.get("/api/currencies")
async def api_currencies():
    return {"base": "USD", "rates": get_rates(), "supported": SUPPORTED_CURRENCIES}


# ── Ads ───────────────────────────────────────────────────────

@app.get("/api/ads")
async def api_ads(city: str = Query(default="global")):
    return {"ads": get_ads(city)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
