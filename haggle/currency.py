"""Multi-currency support using open.er-api.com (no key required)."""

import requests
import time
from typing import Optional

_cache: dict = {}
_cache_time: float = 0
_CACHE_TTL = 3600  # 1 hour

SUPPORTED_CURRENCIES = {
    "USD": "US Dollar",
    "EUR": "Euro",
    "GBP": "British Pound",
    "JPY": "Japanese Yen",
    "CNY": "Chinese Yuan",
    "INR": "Indian Rupee",
    "THB": "Thai Baht",
    "MXN": "Mexican Peso",
    "BRL": "Brazilian Real",
    "TRY": "Turkish Lira",
    "EGP": "Egyptian Pound",
    "MAD": "Moroccan Dirham",
    "IDR": "Indonesian Rupiah",
    "VND": "Vietnamese Dong",
    "PHP": "Philippine Peso",
    "KES": "Kenyan Shilling",
    "NGN": "Nigerian Naira",
    "ZAR": "South African Rand",
    "AED": "UAE Dirham",
    "SGD": "Singapore Dollar",
    "MYR": "Malaysian Ringgit",
    "HKD": "Hong Kong Dollar",
    "NZD": "New Zealand Dollar",
    "AUD": "Australian Dollar",
    "CAD": "Canadian Dollar",
}

# Fallback rates (USD base) if API is unreachable
_FALLBACK_RATES = {
    "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 149.5, "CNY": 7.24,
    "INR": 83.1, "THB": 35.1, "MXN": 17.2, "BRL": 4.97, "TRY": 32.3,
    "EGP": 30.9, "MAD": 10.0, "IDR": 15650.0, "VND": 24500.0, "PHP": 56.5,
    "KES": 130.0, "NGN": 1480.0, "ZAR": 18.7, "AED": 3.67, "SGD": 1.34,
    "MYR": 4.72, "HKD": 7.82, "NZD": 1.63, "AUD": 1.53, "CAD": 1.36,
}


def get_rates() -> dict:
    global _cache, _cache_time
    now = time.time()
    if _cache and (now - _cache_time) < _CACHE_TTL:
        return _cache

    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        data = resp.json()
        if data.get("result") == "success":
            _cache = {k: v for k, v in data["rates"].items() if k in SUPPORTED_CURRENCIES}
            _cache_time = now
            return _cache
    except Exception:
        pass

    return _FALLBACK_RATES


def convert_to_usd(amount: float, currency: str) -> Optional[float]:
    if currency.upper() == "USD":
        return amount
    rates = get_rates()
    rate = rates.get(currency.upper())
    if rate and rate > 0:
        return round(amount / rate, 2)
    return None


def convert_from_usd(amount_usd: float, target_currency: str) -> Optional[float]:
    if target_currency.upper() == "USD":
        return amount_usd
    rates = get_rates()
    rate = rates.get(target_currency.upper())
    if rate:
        return round(amount_usd * rate, 2)
    return None


def format_price(amount: float, currency: str) -> str:
    symbols = {
        "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥",
        "INR": "₹", "THB": "฿", "MXN": "$", "BRL": "R$", "TRY": "₺",
        "IDR": "Rp", "VND": "₫", "PHP": "₱", "KES": "KSh", "NGN": "₦",
        "ZAR": "R", "AED": "د.إ", "SGD": "S$", "HKD": "HK$",
    }
    symbol = symbols.get(currency.upper(), currency + " ")

    if currency.upper() in ("JPY", "IDR", "VND", "KES", "NGN"):
        return f"{symbol}{int(amount):,}"
    return f"{symbol}{amount:.2f}"
