# EMA200 Cross Scanner (Continuous 15m) – Option B
# FIXED:
# - Handles Binance failures
# - Fallback to Vision API
# - No KeyError: 'symbols'
# - Stable on Railway
# - Sends ONE TG message every 15m with all EMA200 cross coins

import asyncio
import aiohttp
import time

# ---- TELEGRAM CONFIG ----
TELEGRAM_BOT_TOKEN = "8420434829:AAFvBIh9iD_hhcDjsXg70xst8RNGLuGPtYc"
TELEGRAM_CHAT_ID = "966269191"

# ---- API ENDPOINTS ----
BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
VISION_EXCHANGE_INFO = "https://data-api.binance.vision/api/v3/exchangeInfo"

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
VISION_KLINES = "https://data-api.binance.vision/api/v3/klines"

# ---- SCANNER CONFIG ----
TIMEFRAME = "15m"
KLIMIT = 210
EMA_LEN = 200
CONCURRENT_REQUESTS = 10


# --------- EMA FUNCTION ----------
def calc_ema(values, length):
    if len(values) < length:
        return [None] * len(values)

    ema = [None] * len(values)
    seed = sum(values[:length]) / length
    ema[length - 1] = seed

    alpha = 2 / (length + 1)
    for i in range(length, len(values)):
        ema[i] = ema[i - 1] + alpha * (values[i] - ema[i - 1])
    return ema


# --------- SAFE JSON FETCH ----------
async def fetch_json(url, params=None):
    try:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        ) as s:
            async with s.get(url, params=params, timeout=30) as r:
                return await r.json()
    except:
        return None


# --------- SYMBOL FETCH (with fallback) ----------
async def get_usdt_symbols():
    # Try main Binance API
    data = await fetch_json(BINANCE_EXCHANGE_INFO)

    # If missing `symbols`, fallback to Vision API
    if not data or "symbols" not in data:
        print("Main Binance API failed → Using Vision API instead...")
        data = await fetch_json(VISION_EXCHANGE_INFO)

        if not data or "symbols" not in data:
            print("Both APIs failed → No symbols loaded.")
            return []

    usdt_list = []
    for s in data["symbols"]:
        if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
            usdt_list.append(s["symbol"])

    usdt_list.sort()
    print(f"Loaded {len(usdt_list)} USDT symbols.")
    return usdt_list


# --------- KLNINES (with fallback) ----------
async def fetch_klines(symbol):
    params = {"symbol": symbol, "interval": TIMEFRAME, "limit": KLIMIT}

    # Try main API
    data = await fetch_json(BINANCE_KLINES, params)
    if data and isinstance(data, list):
        return data

    # Fall back to Vision API
    data = await fetch_json(VISION_KLINES, params)
    if data and isinstance(data, list):
        return data

    print(f"Failed to fetch klines for {symbol}")
    return None


# --------- TELEGRAM SENDER ----------
async def send_tg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}

    try:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        ) as s:
            await s.post(url, json=payload)
    except:
        pass


# --------- CROSS CHECK PER SYMBOL ----------
async def check_symbol(symbol):
    kl = await fetch_klines(symbol)
    if not kl or len(kl) < EMA_LEN + 2:
        return None

    closes = [float(k[4]) for k in kl]
    close_times = [int(k[6]) for k in kl]
    ema_list = calc_ema(closes, EMA_LEN)

    last = len(closes) - 1
    prev = last - 1

    # ensure last candle is CLOSED
    if close_times[last] > int(time.time() * 1000) - 2000:
        return None

    prev_close = closes[prev]
    last_close = closes[last]
    prev_ema = ema_list[prev]
    last_ema = ema_list[last]

    if prev_ema is None or last_ema is None:
        return None

    # BULLISH CROSS
    if prev_close < prev_ema and last_close > last_ema:
        return (symbol, "BULLISH")

    # BEARISH CROSS
    if prev_close > prev_ema and last_close < last_ema:
        return (symbol, "BEARISH")

    return None


# --------- ALIGN TO NEXT 15m CANDLE ----------
async def align_next_15m():
    now = time.time()
    gm = time.gmtime(now)

    next_min = ((gm.tm_min // 15) + 1) * 15
    wait = (next_min - gm.tm_min) * 60 - gm.tm_sec + 3

    if wait < 0:
        wait += 900

    print(f"Sleeping {int(wait)}s until next 15m close...")
    await asyncio.sleep(wait)


# --------- MAIN BOT LOOP ----------
async def main():
    symbols = await get_usdt_symbols()
    if not symbols:
        print("No symbols loaded. Exiting.")
        return

    while True:
        await align_next_15m()

        print("Checking EMA200 crosses...")
        tasks = [asyncio.create_task(check_symbol(sym)) for sym in symbols]
        results = await asyncio.gather(*tasks)

        crossed = [r for r in results if r]

        if crossed:
            msg = "📊 *EMA200 Cross Signals (15m)*\n\n"
            for sym, typ in crossed:
                msg += f"{sym} → {typ}\n"

            await send_tg(msg)
            print("Telegram sent:", msg.replace("\n", " | "))
        else:
            print("No crosses this candle.")

        await asyncio.sleep(1)


# --------- EXECUTE BOT ----------
if __name__ == "__main__":
    asyncio.run(main())
