# main.py
# Binance Futures EMA200 (1h) scanner — FUTURES-ONLY, perfect Binance EMA when available
# - Uses Binance Futures indicator endpoint when available for exact EMA values
# - Falls back to fetching futures klines and computing EMA locally if indicator endpoint fails
# - Aligns to exact 1-hour candle close before scanning
# - Detects TRUE cross on the last CLOSED 1-hour candle (prev < EMA_prev and last > EMA_last => bullish, or reverse)
# - Sends ONE Telegram message listing all bullish/bearish crosses each hour
# - Uses aiohttp with per-request SSL=False connector (Railway-friendly)
#
# USAGE:
# - Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment variables (or hard-code below)
# - Deploy to Railway (or run locally). The script will run continuously.

import os
import time
import asyncio
from typing import List, Optional, Tuple
import aiohttp

# ----------------------------
# Configuration (edit as needed)
# ----------------------------
# Prefer reading from environment; if not present, you may hard-code values here.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")  # e.g. "123:ABC..."
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")      # e.g. "966269191"

# Binance Futures endpoints
FAPI_EXCHANGE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"
FAPI_KLINES = "https://fapi.binance.com/fapi/v1/klines"
# Futures EMA indicator endpoint (we will try this first)
FAPI_EMA = "https://fapi.binance.com/fapi/v1/indicator/ema"         # expected params: symbol, interval, period
# If FAPI_EMA is not available or fails, fallback to klines -> compute EMA locally

# Operational parameters
INTERVAL = "1h"       # 1-hour timeframe as you requested
EMA_PERIOD = 200      # 200 EMA
KLINES_LIMIT = 260    # fetch some extra candles (>= EMA_PERIOD + 2)
CONCURRENT_REQUESTS = 12
CANDLE_CLOSE_BUFFER_MS = 1000  # consider candle closed if closeTime <= now_ms - buffer

# Retry / timeouts
HTTP_TIMEOUT = 30

# ----------------------------
# Helpers
# ----------------------------
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ema200-bot/1.0)"}


def compute_ema_list(values: List[float], period: int) -> List[Optional[float]]:
    """Return EMA list where indices < period-1 are None.
       Standard recursive EMA seeded with SMA of first `period` values.
    """
    n = len(values)
    ema = [None] * n
    if n < period:
        return ema
    seed = sum(values[0:period]) / period
    ema[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    for i in range(period, n):
        prev = ema[i - 1]
        ema[i] = prev + alpha * (values[i] - prev)
    return ema


def kline_is_closed(kline: List) -> bool:
    """kline[6] is closeTime in ms. Consider closed if <= now - buffer."""
    try:
        close_time_ms = int(kline[6])
    except Exception:
        return False
    return close_time_ms <= int(time.time() * 1000) - CANDLE_CLOSE_BUFFER_MS


# ----------------------------
# HTTP fetch helper (with per-call connector)
# ----------------------------
async def fetch_json(url: str, params: dict = None, timeout: int = HTTP_TIMEOUT) -> Optional[dict]:
    try:
        # create ClientSession per call with ssl disabled (Railway-friendly)
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
            async with session.get(url, params=params, headers=HEADERS, timeout=timeout) as resp:
                # attempt to parse JSON; return None on non-JSON or error
                try:
                    return await resp.json()
                except Exception:
                    text = await resp.text()
                    print(f"[fetch_json] non-json response from {url} (status {resp.status}) -> {text[:200]}")
                    return None
    except Exception as e:
        print(f"[fetch_json] network error for {url}: {e}")
        return None


async def post_json(url: str, json_payload: dict, timeout: int = 15) -> Tuple[int, Optional[dict]]:
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
            async with session.post(url, json=json_payload, headers=HEADERS, timeout=timeout) as resp:
                status = resp.status
                try:
                    return status, await resp.json()
                except Exception:
                    return status, None
    except Exception as e:
        print(f"[post_json] error posting to {url}: {e}")
        return 0, None


# ----------------------------
# Binance Futures utilities
# ----------------------------
async def load_futures_symbols() -> List[str]:
    """Load futures symbols (USDT margined) from futures exchangeInfo."""
    data = await fetch_json(FAPI_EXCHANGE_INFO)
    if not data or "symbols" not in data:
        print("[symbols] Failed to load exchangeInfo or 'symbols' missing.")
        return []
    symbols = []
    for s in data.get("symbols", []):
        # filter USDT contracts; only include those trading
        if s.get("status") == "TRADING" and s.get("symbol", "").endswith("USDT"):
            symbols.append(s["symbol"])
    symbols.sort()
    print(f"[symbols] Loaded {len(symbols)} futures USDT symbols.")
    return symbols


async def get_binance_futures_ema(symbol: str, interval: str = INTERVAL, period: int = EMA_PERIOD) -> Optional[dict]:
    """
    Try Binance Futures indicator endpoint to get EMA for the latest candles.
    We expect the endpoint to return the EMA for the most recent closed candle.
    The exact response format may vary; we'll attempt to read standard numeric result(s).
    If successful, return a dict with keys: 'last_ema' and optionally 'prev_ema' and 'close_time_ms' if available.
    If endpoint fails, return None.
    """
    params = {"symbol": symbol, "interval": interval, "period": period}
    data = await fetch_json(FAPI_EMA, params=params)
    if not data:
        return None

    # There is variety across Binance API versions. Try to extract a value robustly.
    # Common responses might be {"symbol":"BTCUSDT","interval":"1h","period":200,"value":12345.6,...}
    # Or an array. We'll try several keys/structures.
    try:
        # If it's a dict with a numeric "value" or "ema" key
        if isinstance(data, dict):
            # try common keys
            for key in ("value", "ema", "EMA", "result", "v"):
                if key in data and isinstance(data[key], (int, float)):
                    return {"last_ema": float(data[key])}
            # maybe it has "data" or "values"
            if "data" in data and isinstance(data["data"], (list, dict)):
                # if list and last element numeric
                if isinstance(data["data"], list) and len(data["data"]) > 0:
                    last = data["data"][-1]
                    if isinstance(last, (int, float)):
                        return {"last_ema": float(last)}
                    if isinstance(last, dict):
                        # try key 'value' or 'ema'
                        for k in ("value", "ema"):
                            if k in last and isinstance(last[k], (int, float)):
                                return {"last_ema": float(last[k])}
                # if dict with 'value'
                if isinstance(data["data"], dict):
                    for k in ("value", "ema"):
                        if k in data["data"] and isinstance(data["data"][k], (int, float)):
                            return {"last_ema": float(data["data"][k])}
        # if it's a list of numbers
        if isinstance(data, list) and len(data) > 0:
            # try last number
            last = data[-1]
            if isinstance(last, (int, float)):
                return {"last_ema": float(last)}
            if isinstance(last, list) and len(last) > 0 and isinstance(last[-1], (int, float)):
                return {"last_ema": float(last[-1])}
    except Exception as e:
        print(f"[get_binance_futures_ema] parse error for {symbol}: {e}")
        return None

    # If reach here, cannot interpret response
    return None


async def fetch_futures_klines(symbol: str, interval: str = INTERVAL, limit: int = KLINES_LIMIT) -> Optional[List]:
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    data = await fetch_json(FAPI_KLINES, params=params)
    if not data or not isinstance(data, list):
        return None
    return data


# ----------------------------
# Cross detection for one symbol
# ----------------------------
async def check_symbol_for_cross(symbol: str) -> Optional[Tuple[str, str]]:
    """
    Returns tuple (symbol, "BULLISH"|"BEARISH") if last closed 1h candle crossed EMA200, otherwise None.
    Process:
      1) Try Binance futures indicator endpoint for EMA. If it returns only the latest EMA value,
         we still need previous EMA or previous close — so use fallback to klines when necessary.
      2) On fallback, fetch klines, compute EMA list and check prev/last relation using last closed candle.
    """
    # First try indicator endpoint (may return just last EMA)
    indicator = await get_binance_futures_ema(symbol)
    # We'll still fetch klines if we need prev_ema or closes
    # Fetch klines (we need closes anyway to verify last closed candle and compute prev/last relations)
    kl = await fetch_futures_klines(symbol)
    if not kl or len(kl) < EMA_PERIOD + 3:
        return None

    # Ensure last returned kline is closed
    if not kline_is_closed(kl[-1]):
        # last candle still forming; skip this symbol this cycle
        return None

    # Extract close prices and close times
    closes = [float(k[4]) for k in kl]
    close_times_ms = [int(k[6]) for k in kl]

    # We want to compare prev and last closed candles.
    # If indicator provided only last_ema, we still compute ema_list to have prev_ema for reliable check.
    ema_list = compute_ema_list(closes, EMA_PERIOD)

    last_idx = len(closes) - 1
    prev_idx = last_idx - 1

    last_close = closes[last_idx]
    prev_close = closes[prev_idx]

    # Try to get last_ema and prev_ema:
    last_ema = None
    prev_ema = None

    if indicator and "last_ema" in indicator:
        # indicator returned some EMA value -- assume it's the latest closed EMA
        last_ema = float(indicator["last_ema"])
        # but prev_ema is needed: take ema_list[prev_idx] if available
        if len(ema_list) > prev_idx and ema_list[prev_idx] is not None:
            prev_ema = ema_list[prev_idx]
        else:
            # fallback prev ema by computing a smaller window or compute by local ema_list
            prev_ema = ema_list[prev_idx] if prev_idx < len(ema_list) else None
    else:
        # no indicator info; use local ema_list
        last_ema = ema_list[last_idx] if last_idx < len(ema_list) else None
        prev_ema = ema_list[prev_idx] if prev_idx < len(ema_list) else None

    if last_ema is None or prev_ema is None:
        # Insufficient EMA precision; skip
        return None

    # Now apply strict crossover check (prev < prev_ema and last > last_ema => bullish)
    if prev_close < prev_ema and last_close > last_ema:
        return (symbol, "BULLISH")

    if prev_close > prev_ema and last_close < last_ema:
        return (symbol, "BEARISH")

    return None


# ----------------------------
# Telegram send helper (single grouped message)
# ----------------------------
async def send_grouped_telegram(bullish: List[str], bearish: List[str]):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[tg] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; printing results instead.")
        if bullish or bearish:
            print("BULLISH:", bullish)
            print("BEARISH:", bearish)
        return

    lines = []
    lines.append("📡 *Binance Futures EMA200 (1h) Cross Report*")
    lines.append(time.strftime("Time(UTC): %Y-%m-%d %H:%M:%S", time.gmtime()))
    lines.append("")
    if bullish:
        lines.append("🔥 *Bullish Breakouts*")
        for s in bullish:
            lines.append(f"• {s}")
        lines.append("")
    if bearish:
        lines.append("⚠️ *Bearish Breakdowns*")
        for s in bearish:
            lines.append(f"• {s}")
        lines.append("")
    if not bullish and not bearish:
        lines.append("No crosses this hour.")

    text = "\n".join(lines)
    # Telegram requires that we don't exceed message length; we assume lists are modest.
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    # Use POST with per-request session
    status, _ = await post_json(url, payload)
    if status == 200:
        print("[tg] Report sent.")
    else:
        print(f"[tg] Failed to send report (status {status}). Text preview:\n{text}")


# ----------------------------
# Alignment helper for hourly candle
# ----------------------------
async def align_to_next_hour_close():
    """Sleep until the next full hour close + small buffer to ensure exchange finished writing bar."""
    now = time.time()
    gm = time.gmtime(now)
    secs_until_next_hour = (60 - gm.tm_min % 60) * 60 - gm.tm_sec
    # If we're very close to the top of hour (e.g., within 2 seconds), wait the full hour to be safe
    wait = secs_until_next_hour + 2
    print(f"[align] Sleeping {int(wait)}s until next 1h candle close...")
    await asyncio.sleep(wait)


# ----------------------------
# Main loop
# ----------------------------
async def main_loop():
    print("[start] Binance Futures EMA200 (1h) scanner starting...")
    symbols = await load_futures_symbols()
    if not symbols:
        print("[start] No futures symbols loaded — exiting.")
        return

    # Some deployment environments might add new futures symbols; you may optionally refresh symbols periodically.
    # But for now we'll use the loaded list for stability.
    while True:
        await align_to_next_hour_close()

        print("[scan] Checking symbols for EMA200 crosses (this may take a minute)...")
        # Run checks concurrently but limited by semaphore in aiohttp per-request sessions
        sem = asyncio.Semaphore(CONCURRENT_REQUESTS)

        async def bounded_check(sym):
            async with sem:
                try:
                    return await check_symbol_for_cross(sym)
                except Exception as e:
                    print(f"[check] Exception for {sym}: {e}")
                    return None

        tasks = [asyncio.create_task(bounded_check(s)) for s in symbols]
        results = await asyncio.gather(*tasks)

        bullish = []
        bearish = []
        for r in results:
            if not r:
                continue
            sym, typ = r
            if typ == "BULLISH":
                bullish.append(sym)
            elif typ == "BEARISH":
                bearish.append(sym)

        # Send one grouped telegram message (or print if no token)
        await send_grouped_telegram(bullish, bearish)

        # short sleep before next align loop to avoid tight-loop on error
        await asyncio.sleep(1)


# ----------------------------
# Entrypoint
# ----------------------------
if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("Stopped by user")
