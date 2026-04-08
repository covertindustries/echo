"""AI negotiation advisor powered by Claude Opus 4.6."""

import os
import json
from typing import Generator, Optional
import anthropic
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


SYSTEM_PROMPT = """You are HaggleAI — a master negotiator and cultural expert who has spent decades
in markets around the world. You know the unwritten rules of bargaining in every culture, the right
tone to strike, and exactly what a fair price looks like.

Your job is to give travelers practical, specific, culturally-aware advice so they can negotiate
confidently without being rude or getting ripped off.

Always be:
- Specific: give exact words to say, exact prices to target
- Cultural: adapt your advice to the local market culture
- Honest: tell people when they're already being offered a fair price
- Practical: focus on what works, not theory
- Brief: be direct and actionable"""


def _build_prompt(
    item: str,
    city: str,
    vendor_opening: str,
    asking_price: float,
    currency: str,
    community_low: Optional[float],
    community_high: Optional[float],
    community_currency: str = "USD",
) -> str:
    range_info = ""
    if community_low and community_high:
        range_info = f"""
Community data from other travelers: Similar {item} in {city} typically sell
for {community_low:.0f}–{community_high:.0f} {community_currency} after haggling."""
    elif community_low:
        range_info = f"\nCommunity data: Others have paid around {community_low:.0f} {community_currency} for similar {item} in {city}."

    return f"""A traveler is at a market in **{city}** and wants to buy: **{item}**

The vendor's opening line: "{vendor_opening}"
Vendor's asking price: **{asking_price:.2f} {currency}**
{range_info}

Give me a complete haggling plan with these exact sections:

## Counter Offer
The exact words to say right now (in English, but with the right cultural tone for {city}).
Make it friendly, not aggressive.

## Target Price
What they should realistically aim to pay in {currency}. Be specific.

## Walk Away Price
The absolute maximum they should pay before walking away.

## Negotiation Script
A short back-and-forth script showing the likely negotiation flow (2-3 exchanges).

## Market Tips
3 specific tactics for {city}'s market culture.

## Cultural Note
One important cultural consideration to avoid offense or missed opportunity."""


def stream_negotiation_advice(
    item: str,
    city: str,
    vendor_opening: str,
    asking_price: float,
    currency: str,
    community_low: Optional[float] = None,
    community_high: Optional[float] = None,
) -> Generator[str, None, None]:
    """Stream negotiation advice as Server-Sent Events."""
    client = _get_client()
    prompt = _build_prompt(
        item, city, vendor_opening, asking_price, currency,
        community_low, community_high,
    )

    try:
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=1500,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield f"data: {json.dumps({'text': text})}\n\n"
        yield "data: {\"done\": true}\n\n"
    except anthropic.AuthenticationError:
        yield f"data: {json.dumps({'error': 'API key not configured. Add ANTHROPIC_API_KEY to your .env file.'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
