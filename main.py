# EMA200 Cross Scanner (1H) – Manual EMA
# Checks last 2 closed hourly candles and sends Telegram alerts

import asyncio
import aiohttp
import time

# ==== CONFIG ====
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"

TIMEFRAME = "1h"
KLIMIT = 220      # enough candles to calculate EMA200
EMA_LEN = 200
MAX_RETRIES = 5

# ===== EMA Calculation =====
def calc_ema(values, length):
    if len(values) < length:
        return [None]*len(values)
    ema = [None]*len(values)
    seed = sum(values[:length])/length
    ema[length-1] = seed
    alpha = 2/(length+1)
    for i in range(length, len(values)):
        ema[i] = ema[i-1] + alpha*(values[i] - ema[i-1])
    return ema

# ===== Fetch JSON =====
async def fetch_json(url, params=None):
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as s:
            async with s.get(url, params=params) as r:
                return await r.json()
    except Exception as e:
        print(f"[fetch_json] Error: {e}")
        return None

# ===== Get USDT symbols =====
async def get_usdt_symbols():
    for attempt in range(1, MAX_RETRIES+1):
        data = await fetch_json(BINANCE_EXCHANGE_INFO)
        if data and "symbols" in data:
            usdt = [s["symbol"] for s in data["symbols"] if s.get("quoteAsset")=="USDT" and s.get("status")=="TRADING"]
            print(f"Loaded {len(usdt)} USDT symbols")
            return sorted(usdt)
        print(f"Attempt {attempt}: Binance API failed. Retrying...")
        await asyncio.sleep(2**attempt)
    raise Exception("Could not fetch USDT symbols from Binance")

# ===== Fetch klines =====
async def fetch_klines(symbol):
    params = {"symbol": symbol, "interval": TIMEFRAME, "limit": KLIMIT}
    return await fetch_json(BINANCE_KLINES, params)

# ===== Send Telegram =====
async def send_tg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as s:
            await s.post(url, json=payload)
    except Exception as e:
        print(f"[send_tg] Error: {e}")

# ===== Check EMA200 cross =====
async def check_symbol(symbol):
    kl = await fetch_klines(symbol)
    if not kl or len(kl) < EMA_LEN + 2:
        return None

    closes = [float(k[4]) for k in kl]
    close_times = [int(k[6]) for k in kl]
    ema_list = calc_ema(closes, EMA_LEN)

    last = len(closes)-1
    prev = last-1

    # Ensure last candle is closed
    if close_times[last] > int(time.time()*1000) - 2000:
        return None

    prev_close = closes[prev]
    last_close = closes[last]
    prev_ema = ema_list[prev]
    last_ema = ema_list[last]

    # DEBUG HBAR (optional)
    if symbol == "HBARUSDT":
        print(f"DEBUG {symbol}: prev_close={prev_close}, last_close={last_close}, prev_ema={prev_ema}, last_ema={last_ema}")

    if prev_ema is None or last_ema is None:
        return None

    crossed = None
    if prev_close < prev_ema and last_close > last_ema:
        crossed = "BULLISH"
    if prev_close > prev_ema and last_close < last_ema:
        crossed = "BEARISH"

    if crossed:
        return (symbol, crossed)
    return None

# ===== Align next 1h candle =====
async def align_next_hour():
    now = time.time()
    gm = time.gmtime(now)
    next_hour = ((gm.tm_hour + 1) % 24)
    wait = (next_hour - gm.tm_hour)*3600 - gm.tm_min*60 - gm.tm_sec + 3
    if wait < 0:
        wait += 3600
    print(f"Sleeping {int(wait)}s until next 1h candle close...")
    await asyncio.sleep(wait)

# ===== Main Loop =====
async def main():
    symbols = await get_usdt_symbols()

    while True:
        await align_next_hour()
        print("Checking EMA200 crosses...")

        tasks = [check_symbol(sym) for sym in symbols]
        results = await asyncio.gather(*tasks)
        crossed = [r for r in results if r]

        if crossed:
            msg = "📊 *EMA200 Cross Signals (1H)*\n\n"
            for sym, typ in crossed:
                msg += f"{sym} → {typ}\n"
            await send_tg(msg)
            print("Telegram sent:", msg.replace("\n"," | "))
        else:
            print("No crosses this candle.")

        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
