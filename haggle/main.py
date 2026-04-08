"""Haggle — The Negotiator's App
Community-powered haggling guide with AI negotiation advice, map, and reference prices.
"""

import os
import uuid
import math
import random
import shutil
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from database import (
    init_db, get_prices, submit_price, get_ads,
    seed_sample_data, get_item_suggestions,
    create_vendor_story, get_vendor_story,
    add_vendor_photo, get_vendor_stories_for_city,
    waitlist_add, waitlist_count, waitlist_referral_count, waitlist_city_counts,
)
from scraper import scrape_reddit_prices
from negotiator import stream_negotiation_advice
from currency import get_rates, convert_to_usd, SUPPORTED_CURRENCIES
from reference_prices import get_reference_price
from wages import get_fair_price, get_wage_for_country

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
    with open(os.path.join(STATIC_DIR, "landing.html")) as f:
        return f.read()


@app.get("/app", response_class=HTMLResponse)
async def app_ui():
    with open(os.path.join(STATIC_DIR, "index.html")) as f:
        return f.read()


# ── Waitlist ──────────────────────────────────────────────────

class WaitlistEntry(BaseModel):
    email: str = Field(..., min_length=5, max_length=200)
    city: Optional[str] = Field(None, max_length=60)
    role: str = Field(default="traveller")          # traveller | vendor | both
    ref: Optional[str] = Field(None, max_length=8)  # referral code


@app.post("/api/waitlist", status_code=201)
async def api_waitlist(body: WaitlistEntry):
    import re
    if not re.match(r"[^@]+@[^@]+\.[^@]+", body.email):
        raise HTTPException(400, "Invalid email")
    if body.role not in ("traveller", "vendor", "both"):
        raise HTTPException(400, "Invalid role")

    result = waitlist_add(
        email=body.email,
        city=body.city or None,
        role=body.role,
        referred_by=body.ref or None,
    )
    total = waitlist_count()
    return {
        "ref_code": result["ref_code"],
        "position": result.get("position", total),
        "total": total,
        "already_registered": result.get("already_registered", False),
        "share_url": f"/?ref={result['ref_code']}",
        "message": "You're on the list!",
    }


@app.get("/api/waitlist/count")
async def api_waitlist_count():
    return {"count": waitlist_count()}


@app.get("/api/waitlist/referrals/{ref_code}")
async def api_waitlist_referrals(ref_code: str):
    count = waitlist_referral_count(ref_code.upper())
    return {"ref_code": ref_code.upper(), "referrals": count}


@app.get("/api/waitlist/cities")
async def api_waitlist_cities():
    return {"cities": waitlist_city_counts()}


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

    # Fair price context
    fair = None
    country_guess = community[0]["country"] if community else None
    if country_guess:
        fair = get_fair_price(item, country_guess)

    # Vendor stories for this city/item
    vendor_stories = get_vendor_stories_for_city(city, item)

    return {
        "item": item,
        "city": city,
        "community_reports": community,
        "reddit_data": reddit,
        "stats": stats,
        "markers": markers,
        "city_center": list(city_center) if city_center else None,
        "fair_price": fair,
        "vendor_stories": vendor_stories,
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


# ── Fair price ────────────────────────────────────────────────

@app.get("/api/fair-price")
async def api_fair_price(
    item: str = Query(..., min_length=1),
    country: str = Query(..., min_length=1),
):
    result = get_fair_price(item, country)
    return result


# ── Vendor stories ─────────────────────────────────────────────

class VendorStoryCreate(BaseModel):
    city: str = Field(..., min_length=1)
    country: str = Field(..., min_length=1)
    craft: str = Field(..., min_length=1, description="What you make")
    story: Optional[str] = Field(None, max_length=800)
    time_to_make: Optional[str] = Field(None, max_length=100,
        description="e.g. '2 days per carpet'")
    materials: Optional[str] = Field(None, max_length=200,
        description="e.g. 'hand-spun wool, natural dyes'")
    generation: Optional[str] = Field(None, max_length=100,
        description="e.g. '3rd generation weaver'")


@app.post("/api/vendors", status_code=201)
async def api_create_vendor(body: VendorStoryCreate):
    vendor_code = uuid.uuid4().hex[:10].upper()
    create_vendor_story(
        vendor_code=vendor_code,
        city=body.city,
        country=body.country,
        craft=body.craft,
        story=body.story or "",
        time_to_make=body.time_to_make or "",
        materials=body.materials or "",
        generation=body.generation or "",
    )
    return {
        "vendor_code": vendor_code,
        "share_url": f"/vendor/{vendor_code}",
        "message": "Your story has been created. Share your code with travellers!",
    }


@app.get("/api/vendors/{vendor_code}")
async def api_get_vendor(vendor_code: str):
    story = get_vendor_story(vendor_code.upper())
    if not story:
        raise HTTPException(404, "Vendor story not found")
    return story


@app.post("/api/vendors/{vendor_code}/photos", status_code=201)
async def api_upload_vendor_photo(
    vendor_code: str,
    photo: UploadFile = File(...),
):
    story = get_vendor_story(vendor_code.upper())
    if not story:
        raise HTTPException(404, "Vendor story not found")

    ext = os.path.splitext(photo.filename)[-1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "Invalid image format")

    fname = f"vendor_{vendor_code}_{uuid.uuid4().hex[:8]}{ext}"
    save_path = os.path.join(UPLOADS_DIR, fname)
    with open(save_path, "wb") as f:
        shutil.copyfileobj(photo.file, f)

    photo_path = f"/uploads/{fname}"
    add_vendor_photo(vendor_code.upper(), photo_path)
    return {"photo_path": photo_path}


@app.get("/vendor/{vendor_code}", response_class=HTMLResponse)
async def vendor_page(vendor_code: str):
    """Public vendor story page — shareable URL."""
    with open(os.path.join(STATIC_DIR, "index.html")) as f:
        html = f.read()
    # Inject vendor code for the SPA to pick up
    return html.replace(
        "</head>",
        f'<script>window.VENDOR_CODE="{vendor_code.upper()}";</script></head>'
    )


# ── WhatsApp webhooks ─────────────────────────────────────────

from whatsapp import (
    parse_message, send_message,
    HELP_MSG, VENDOR_INFO_MSG, UNKNOWN_MSG,
    META_VERIFY_TOKEN, PROVIDER,
    build_price_reply, build_negotiate_reply, build_vendor_lookup_reply,
)
from negotiator import get_bot_advice
import asyncio


async def _handle_whatsapp(sender: str, text: str):
    """Process an incoming WhatsApp message and send a reply."""
    parsed = parse_message(text)
    intent = parsed["intent"]

    if intent == "help":
        await send_message(sender, HELP_MSG)
        return

    if intent == "vendor_info":
        await send_message(sender, VENDOR_INFO_MSG)
        return

    if intent == "vendor_lookup":
        story = get_vendor_story(parsed["code"])
        await send_message(sender, build_vendor_lookup_reply(story))
        return

    if intent == "prices":
        item, city = parsed["item"], parsed["city"]
        country = parsed.get("country")

        data = get_prices(item, city)
        prices_usd = [r["price_usd"] for r in data if r.get("price_usd")]
        stats = None
        if prices_usd:
            s = sorted(prices_usd)
            stats = {
                "low": min(s), "high": max(s),
                "median": s[len(s) // 2], "count": len(s),
            }

        fair = get_fair_price(item, country) if country else None

        ai_text = get_bot_advice(
            intent="prices", item=item, city=city,
            community_low=stats["low"] if stats else None,
            community_high=stats["high"] if stats else None,
            community_median=stats["median"] if stats else None,
            community_count=stats["count"] if stats else 0,
            fair_context=fair["context"] if fair else "",
        )

        reply = build_price_reply(item, city, stats, fair, ai_text)
        await send_message(sender, reply)
        return

    if intent == "negotiate":
        item = parsed["item"]
        city = parsed["city"]
        price = parsed["price"]
        currency = parsed["currency"]
        country = parsed.get("country")

        data = get_prices(item, city)
        prices_usd = [r["price_usd"] for r in data if r.get("price_usd")]
        low = min(prices_usd) if prices_usd else None
        high = max(prices_usd) if prices_usd else None

        fair = get_fair_price(item, country) if country else None

        ai_text = get_bot_advice(
            intent="negotiate", item=item, city=city,
            asking_price=price, currency=currency,
            community_low=low, community_high=high,
            fair_usd=fair["fair_price_usd"] if fair else None,
        )

        reply = build_negotiate_reply(item, city, price, currency, ai_text)
        await send_message(sender, reply)
        return

    await send_message(sender, UNKNOWN_MSG)


# Twilio webhook (form-encoded)
@app.post("/webhook/whatsapp/twilio")
async def whatsapp_twilio(
    request: Request,
    Body: str = Form(default=""),
    From: str = Form(default=""),
):
    asyncio.create_task(_handle_whatsapp(From, Body))
    # Twilio expects TwiML response; empty = no immediate reply (we reply async)
    return Response(
        content='<?xml version="1.0"?><Response></Response>',
        media_type="text/xml",
    )


# Meta Cloud API webhook — verification
@app.get("/webhook/whatsapp/meta")
async def whatsapp_meta_verify(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
):
    if hub_mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(403, "Verification failed")


# Meta Cloud API webhook — messages
@app.post("/webhook/whatsapp/meta")
async def whatsapp_meta_receive(request: Request):
    payload = await request.json()
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                messages = change.get("value", {}).get("messages", [])
                for msg in messages:
                    if msg.get("type") == "text":
                        sender = msg["from"]
                        text = msg["text"]["body"]
                        asyncio.create_task(_handle_whatsapp(sender, text))
    except Exception as e:
        print(f"[Meta webhook] Error: {e}")
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
