import os
import asyncio
import time
import aiohttp

BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
TELEGRAM_SEND = "https://api.telegram.org/bot{token}/sendMessage"

TELEGRAM_BOT_TOKEN = os.getenv("8420434829:AAFvBIh9iD_hhcDjsXg70xst8RNGLuGPtYc")
TELEGRAM_CHAT_ID   = os.getenv("966269191")

EMA_LEN = 200
KLIMIT = 210
TIMEFRAME = "15m"

async def send_telegram(session, text):
    url = TELEGRAM_SEND.format(token=TELEGRAM_BOT_TOKEN)
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        async with session.post(url, json=payload, timeout=10):
            pass
    except:
        pass

def compute_ema(values, length):
    if len(values) < length:
        return [None] * len(values)
    ema = [None] * len(values)
    seed = sum(values[:length]) / length
    ema[length - 1] = seed
    alpha = 2 / (length + 1)
    for i in range(length, len(values)):
        ema[i] = (values[i] - ema[i - 1]) * alpha + ema[i - 1]
    return ema

async def get_usdt_symbols(session):
    try:
        async with session.get(BINANCE_EXCHANGE_INFO, timeout=20) as resp:
            data = await resp.json()
        syms = [
            s["symbol"]
            for s in data.get("symbols", [])
            if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"
        ]
        syms.sort()
        print(f"Loaded {len(syms)} USDT symbols.")
        return syms
    except:
        print("Main API failed. Using fallback list...")
        return fallback_symbols()

def fallback_symbols():
    # Fallback ∼439 USDT pairs
    return ["BTCUSDT","ETHUSDT","SOLUSDT","GIGGLEUSDT","BNBUSDT","XRPUSDT"]  # minimal sample
    # (I can give you full 439 list again if needed)

async def fetch_klines(session, symbol):
    params = {"symbol": symbol, "interval": TIMEFRAME, "limit": KLIMIT}
    try:
        async with session.get(BINANCE_KLINES, params=params, timeout=20) as resp:
            if resp.status != 200:
                return []
            return await resp.json()
    except:
        return []

async def check_symbol(session, symbol):
    klines = await fetch_klines(session, symbol)
    if len(klines) < EMA_LEN + 5:
        return None

    closes = [float(k[4]) for k in klines]
    ema = compute_ema(closes, EMA_LEN)

    # Candle indexing:
    # -1 → current live candle (ignore)
    # -2 → last *closed* candle
    # -3 → closed candle before that
    c3, c2 = closes[-3], closes[-2]
    e3, e2 = ema[-3], ema[-2]

    if e3 is None or e2 is None:
        return None

    bull_cross = c3 < e3 and c2 > e2
    bear_cross = c3 > e3 and c2 < e2

    if bull_cross:
        return f"🟩 {symbol} — Bullish EMA200 CROSS (15m)\nPrev: {c3} < EMA\nNow : {c2} > EMA"

    if bear_cross:
        return f"🟥 {symbol} — Bearish EMA200 CROSS (15m)\nPrev: {c3} > EMA\nNow : {c2} < EMA"

    return None

async def wait_next_15m():
    now = time.time()
    gm = time.gmtime(now)
    mins = gm.tm_min % 15
    wait = (15 - mins) * 60 - gm.tm_sec + 2
    if wait < 0: wait += 900
    print(f"Sleeping {wait}s until next 15m close...")
    await asyncio.sleep(wait)

async def main():
    async with aiohttp.ClientSession() as session:
        symbols = await get_usdt_symbols(session)

        while True:
            await wait_next_15m()
            print("Checking EMA200 crosses...")

            tasks = [check_symbol(session, s) for s in symbols]
            results = await asyncio.gather(*tasks)

            signals = [r for r in results if r is not None]

            if not signals:
                print("No crosses this candle.")
            else:
                for msg in signals:
                    await send_telegram(session, msg)
                    print("Sent:", msg)

            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
print("GIGGLE exists:", "GIGGLEUSDT" in symbols)
