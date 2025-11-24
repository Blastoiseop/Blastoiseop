# main.py
# FINAL: Scan ALL Binance Spot + Futures USDT pairs (1H), use Binance Futures EMA when available,
# fallback to local EMA calculation for spot-only symbols. Uses proxy endpoints to avoid geo-blocks.
# Sends ONE Telegram message every hour (includes "no crosses" message).
#
# Notes:
# - For symbols that exist on Binance Futures USDT-M, this script tries to use the Binance Futures
#   EMA indicator endpoint to obtain Binance's own EMA200 value (best match to Binance charts).
# - For spot-only symbols, the script falls back to fetching klines and computing EMA locally.
# - Uses proxy endpoints (sonibyte) to avoid region restrictions from Railway. If you prefer a different proxy,
#   update the BINANCE_API_PROXY_* constants below.
#
# Usage: Paste this file into your Railway project (overwrite /mnt/data/main.py), then run.
# The file contains hard-coded TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID used earlier.
#
import asyncio
import aiohttp
import time
from typing import List, Optional, Dict

# -------------------- CONFIG --------------------
TELEGRAM_BOT_TOKEN = "8420434829:AAFvBIh9iD_hhcDjsXg70xst8RNGLuGPtYc"
TELEGRAM_CHAT_ID = "966269191"

TIMEFRAME = "1h"
EMA_PERIOD = 200

# Proxied Binance base endpoints (works from Railway/India)
BINANCE_API_PROXY_SPOT = "https://api.binance.sonibyte.us/api/v3"     # spot proxy (exchangeInfo, klines)
BINANCE_API_PROXY_FUT = "https://fapi.binance.sonibyte.us/fapi/v1"    # futures proxy (exchangeInfo, klines, indicator)

# Kline limits
KLINES_LIMIT_SPOT = 1000   # many candles to compute EMA accurately for spot fallback
KLINES_LIMIT_FUT = 300     # enough for futures local fallback

# Concurrency
CONCURRENT_REQUESTS = 12
HTTP_TIMEOUT = 30

# -------------------- HELPERS --------------------
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ema200-bot/1.0)"}

async def fetch_json(url: str, params: Dict = None, timeout: int = HTTP_TIMEOUT) -> Optional[object]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=HEADERS, timeout=timeout) as resp:
                try:
                    return await resp.json()
                except Exception:
                    text = await resp.text()
                    print(f"[fetch_json] non-json from {url} -> {text[:200]}")
                    return None
    except Exception as e:
        print(f"[fetch_json] error {url}: {e}")
        return None

async def post_json(url: str, payload: Dict, timeout: int = 15):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=HEADERS, timeout=timeout) as resp:
                try:
                    return resp.status, await resp.json()
                except Exception:
                    return resp.status, None
    except Exception as e:
        print(f"[post_json] error posting to {url}: {e}")
        return 0, None

# -------------------- SYMBOLS (auto-update) --------------------
async def load_all_usdt_symbols() -> Dict[str, Dict]:
    """
    Load spot and futures USDT pairs via proxied exchangeInfo endpoints.
    Returns dict symbol -> {"spot": bool, "futures": bool}
    """
    symbols: Dict[str, Dict] = {}
    # Spot exchangeInfo
    spot_info = await fetch_json(f"{BINANCE_API_PROXY_SPOT}/exchangeInfo")
    if spot_info and "symbols" in spot_info:
        for s in spot_info["symbols"]:
            if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
                symbols.setdefault(s["symbol"], {"spot": False, "futures": False})
                symbols[s["symbol"]]["spot"] = True
    else:
        print("[symbols] Spot exchangeInfo failed or missing 'symbols'")

    # Futures exchangeInfo
    fut_info = await fetch_json(f"{BINANCE_API_PROXY_FUT}/exchangeInfo")
    if fut_info and "symbols" in fut_info:
        for s in fut_info["symbols"]:
            if s.get("status") == "TRADING" and s.get("symbol", "").endswith("USDT"):
                symbols.setdefault(s["symbol"], {"spot": False, "futures": False})
                symbols[s["symbol"]]["futures"] = True
    else:
        print("[symbols] Futures exchangeInfo failed or missing 'symbols'")

    print(f"[symbols] Loaded {len(symbols)} combined USDT symbols (spot+futures)")
    return symbols

# -------------------- EMA helpers --------------------
def compute_ema_list(values: List[float], period: int) -> List[Optional[float]]:
    n = len(values)
    ema = [None] * n
    if n < period:
        return ema
    seed = sum(values[:period]) / period
    ema[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    for i in range(period, n):
        ema[i] = ema[i - 1] + alpha * (values[i] - ema[i - 1])
    return ema

# -------------------- BINANCE FUTURES INDICATOR (preferred) --------------------
async def fetch_futures_indicator_ema(symbol: str, interval: str = TIMEFRAME, period: int = EMA_PERIOD) -> Optional[float]:
    """
    Try to fetch Binance Futures indicator EMA for latest closed candle.
    Proxy used to avoid geo-blocks. If parse fails, return None to fallback.
    """
    url = f"{BINANCE_API_PROXY_FUT}/indicator/ema"
    params = {"symbol": symbol, "interval": interval, "period": period}
    data = await fetch_json(url, params)
    if not data:
        return None
    # Try to parse common response formats
    try:
        if isinstance(data, dict):
            for k in ("value","ema","EMA","result","v"):
                if k in data and isinstance(data[k], (int, float)):
                    return float(data[k])
            # maybe data['data'] list
            if "data" in data and isinstance(data["data"], list) and len(data["data"])>0:
                last = data["data"][-1]
                if isinstance(last, (int,float)):
                    return float(last)
                if isinstance(last, dict):
                    for k in ("value","ema"):
                        if k in last and isinstance(last[k], (int,float)):
                            return float(last[k])
        if isinstance(data, list) and len(data)>0:
            last = data[-1]
            if isinstance(last, (int,float)):
                return float(last)
            if isinstance(last, list) and len(last)>0 and isinstance(last[-1], (int,float)):
                return float(last[-1])
    except Exception as e:
        print(f"[indicator parse] {symbol} error: {e}")
        return None
    return None

# -------------------- KLINES fetch via proxy --------------------
async def fetch_klines_proxy(session: aiohttp.ClientSession, symbol: str, futures: bool) -> Optional[List]:
    """
    Fetch klines via proxy endpoints. For futures use BINANCE_API_PROXY_FUT, for spot use BINANCE_API_PROXY_SPOT.
    """
    base = BINANCE_API_PROXY_FUT if futures else BINANCE_API_PROXY_SPOT
    url = f"{base}/klines"
    limit = KLINES_LIMIT_FUT if futures else KLINES_LIMIT_SPOT
    params = {"symbol": symbol, "interval": TIMEFRAME, "limit": limit}
    try:
        async with session.get(url, params=params, timeout=HTTP_TIMEOUT) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"[kline] {symbol} error {resp.status}: {text[:200]}")
                return None
            data = await resp.json()
            # defensive: if error dict returned
            if isinstance(data, dict) and data.get("code") is not None:
                print(f"[kline] {symbol} returned error: {data.get('msg') or data}")
                return None
            return data
    except Exception as e:
        print(f"[kline] {symbol} exception: {e}")
        return None

# -------------------- Symbol cross check --------------------
async def check_symbol_cross(session: aiohttp.ClientSession, symbol: str, info: Dict) -> Optional[str]:
    """
    Return formatted string for symbol if cross detected, else None.
    We will try to fetch Binance futures EMA if available (exact), otherwise compute locally.
    """
    is_futures = bool(info.get("futures", False))
    # If symbol has futures contract, try indicator endpoint first
    last_ema = None
    prev_ema = None

    # Fetch klines first (we need closes regardless to check last closed candles)
    kl = await fetch_klines_proxy(session, symbol, is_futures)
    if not kl or len(kl) < EMA_PERIOD + 2:
        return None

    closes = [float(k[4]) for k in kl]
    close_times = [int(k[6]) for k in kl]

    # Ensure the returned last kline is closed (closeTime <= now - small buffer)
    if close_times[-1] > int(time.time()*1000) - 1000:
        # last candle still forming; skip this symbol this cycle
        return None

    # Get EMA values
    if is_futures:
        # try indicator endpoint for exact EMA for last closed candle
        indicator_ema = await fetch_futures_indicator_ema(symbol)
        if indicator_ema is not None:
            # last_ema assigned from indicator; compute prev_ema using local EMA list
            ema_list = compute_ema_list(closes, EMA_PERIOD)
            last_ema = float(indicator_ema)
            prev_ema = ema_list[-2] if len(ema_list) >= 2 else None
        else:
            # fallback: compute locally using adequate klines
            ema_list = compute_ema_list(closes, EMA_PERIOD)
            last_ema = ema_list[-1]
            prev_ema = ema_list[-2] if len(ema_list)>=2 else None
    else:
        # spot-only: compute local EMA with many candles to approximate TV
        ema_list = compute_ema_list(closes, EMA_PERIOD)
        last_ema = ema_list[-1]
        prev_ema = ema_list[-2] if len(ema_list)>=2 else None

    if last_ema is None or prev_ema is None:
        return None

    last_close = closes[-1]
    prev_close = closes[-2]

    # Strict cross definition: prev below EMA and last above EMA => bullish (and reverse)
    if prev_close < prev_ema and last_close > last_ema:
        return f"{symbol} | Close {last_close} | EMA200 {round(last_ema,6)} | BULLISH"
    if prev_close > prev_ema and last_close < last_ema:
        return f"{symbol} | Close {last_close} | EMA200 {round(last_ema,6)} | BEARISH"
    return None

# -------------------- Telegram sender (grouped message) --------------------
async def send_grouped_message(session: aiohttp.ClientSession, results: List[str], scanned_count: int):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    if results:
        msg = f"🚀 EMA200 Crosses (1H) — {timestamp}\nScanned: {scanned_count}\n\n" + "\n".join(results)
    else:
        msg = f"📊 1H EMA200 Scanner — {timestamp}\nScanned: {scanned_count}\nNo EMA200 crosses detected this candle."
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        status, _ = await post_json(url, payload)
        if status != 200:
            print(f"[tg] send status {status}")
    except Exception as e:
        print(f"[tg] exception {e}")

# -------------------- ALIGN helper --------------------
async def align_to_next_hour_close():
    now = time.time()
    gm = time.gmtime(now)
    seconds = gm.tm_min * 60 + gm.tm_sec
    wait = 3600 - seconds + 2
    if wait < 0:
        wait = 2
    print(f"[align] Sleeping {int(wait)}s until next 1h candle close...")
    await asyncio.sleep(wait)

# -------------------- MAIN LOOP --------------------
async def main():
    print("[start] loading symbols...")
    symbols_info = await load_all_usdt_symbols()
    if not symbols_info:
        print("[start] No symbols loaded; exiting.")
        return

    symbols = list(symbols_info.keys())
    print(f"[start] total symbols to scan: {len(symbols)} (spot+futures)")

    sem = asyncio.Semaphore(CONCURRENT_REQUESTS)

    async with aiohttp.ClientSession() as session:
        while True:
            await align_to_next_hour_close()
            print("[scan] Starting scan for EMA200 crosses...")
            tasks = []
            scanned = 0
            for sym in symbols:
                info = symbols_info.get(sym, {"spot": False, "futures": False})
                async def worker(s=sym, info_local=info):
                    async with sem:
                        try:
                            return await check_symbol_cross(session, s, info_local)
                        except Exception as e:
                            print(f"[worker] {s} exception: {e}")
                            return None
                tasks.append(asyncio.create_task(worker()))
            results = await asyncio.gather(*tasks)

            # Filter and count
            matches = [r for r in results if r]
            scanned = len(symbols)

            # Send grouped message
            await send_grouped_message(session, matches, scanned)
            print(f"[scan] Completed. Matches: {len(matches)}. Sleeping until next hour...")

# -------------------- ENTRY --------------------
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped by user")
