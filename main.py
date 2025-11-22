import os
import time
import aiohttp
import asyncio
import ssl
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Binance endpoints
BINANCE_TICKER_24H = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"

# SSL BYPASS
ssl_context = ssl._create_unverified_context()


# --------------------------
# Fetch top 100 USDT symbols
# --------------------------
async def get_top100_usdt():
    async with aiohttp.ClientSession() as session:
        async with session.get(BINANCE_TICKER_24H, ssl=ssl_context) as r:
            data = await r.json()

    usdt_pairs = [d for d in data if d["symbol"].endswith("USDT")]

    # Sort by quote volume (largest first)
    sorted_pairs = sorted(
        usdt_pairs,
        key=lambda x: float(x.get("quoteVolume", 0)),
        reverse=True
    )

    top100 = [p["symbol"] for p in sorted_pairs[:100]]
    return top100


# --------------------------
# Fetch klines
# --------------------------
async def get_klines(symbol):
    params = {
        "symbol": symbol,
        "interval": "15m",
        "limit": 210
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(BINANCE_KLINES, params=params, ssl=ssl_context) as r:
            return await r.json()


# --------------------------
# Simple EMA200
# --------------------------
def ema200(values):
    if len(values) < 200:
        return None
    return sum(values[-200:]) / 200


# --------------------------
# Send Telegram message
# --------------------------
async def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        await session.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            ssl=ssl_context
        )


# --------------------------
# Check EMA cross
# --------------------------
async def check_symbol(symbol):
    kl = await get_klines(symbol)
    closes = [float(c[4]) for c in kl]

    prev = closes[-2]
    last = closes[-1]
    ema = ema200(closes)

    if ema is None:
        return

    if prev < ema and last > ema:
        await send_telegram(f"{symbol} closed ABOVE EMA200 (15m) — Price: {last}")

    if prev > ema and last < ema:
        await send_telegram(f"{symbol} closed BELOW EMA200 (15m) — Price: {last}")


# --------------------------
# Main Loop
# --------------------------
async def main():
    await send_telegram("Bot Started — Tracking Top 100 USDT Coins (SSL Bypass Enabled)")

    symbols = await get_top100_usdt()
    print(f"Tracking {len(symbols)} symbols")
    await send_telegram(f"Tracking {len(symbols)} USDT coins")

    # Initial wait until next candle
    while True:
        now = int(time.time())
        sec_to_wait = 900 - (now % 900)

        print(f"Waiting {sec_to_wait} seconds until next 15m candle close...")
        await asyncio.sleep(sec_to_wait)

        # Check EMA 200 for all top100 symbols
        for sym in symbols:
            try:
                await check_symbol(sym)
            except Exception as e:
                print("Error:", sym, e)

        print("Scan cycle finished.")


if __name__ == "__main__":
    asyncio.run(main())
