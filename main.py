# EMA200 Cross Scanner (1h) using pandas_ta – Railway friendly
# Every 1h, after the candle closes, sends ONE Telegram message
# listing all coins where the latest closed 1h candle crosses EMA200.

import asyncio
import aiohttp
import time
import pandas as pd
import pandas_ta as ta

TELEGRAM_BOT_TOKEN = "8420434829:AAFvBIh9iD_hhcDjsXg70xst8RNGLuGPtYc"
TELEGRAM_CHAT_ID = "966269191"

BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
TIMEFRAME = "1h"
KLIMIT = 250  # >= 200 for EMA200
EMA_LEN = 200


async def fetch_json(url, params=None):
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as s:
            async with s.get(url, params=params) as r:
                return await r.json()
    except:
        return None


async def get_usdt_symbols():
    data = await fetch_json(BINANCE_EXCHANGE_INFO)
    usdt = []
    for s in data["symbols"]:
        if s["quoteAsset"] == "USDT" and s["status"] == "TRADING":
            usdt.append(s["symbol"])
    return sorted(usdt)


async def fetch_klines(symbol):
    params = {"symbol": symbol, "interval": TIMEFRAME, "limit": KLIMIT}
    return await fetch_json(BINANCE_KLINES, params)


async def send_tg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as s:
            await s.post(url, json=payload)
    except:
        pass


async def check_symbol(symbol):
    kl = await fetch_klines(symbol)
    if not kl or len(kl) < EMA_LEN + 2:
        return None

    closes = pd.Series([float(k[4]) for k in kl])
    close_times = [int(k[6]) for k in kl]

    # Calculate EMA200 using pandas_ta
    ema_list = ta.ema(closes, length=EMA_LEN).values

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

    # bullish cross
    if prev_close < prev_ema and last_close > last_ema:
        return (symbol, "BULLISH")

    # bearish cross
    if prev_close > prev_ema and last_close < last_ema:
        return (symbol, "BEARISH")

    return None


async def align_next_hour():
    now = time.time()
    gm = time.gmtime(now)
    next_hour = (gm.tm_hour + 1) % 24
    wait = (next_hour - gm.tm_hour) * 3600 - gm.tm_min * 60 - gm.tm_sec + 3
    if wait < 0:
        wait += 3600
    print(f"Sleeping {int(wait)}s until next 1h close...")
    try:
        await asyncio.sleep(wait)
    except asyncio.CancelledError:
        print("Sleep cancelled. Exiting...")
        return


async def main():
    symbols = await get_usdt_symbols()
    print(f"Loaded {len(symbols)} USDT symbols")

    while True:
        await align_next_hour()
        print("Checking EMA200 crosses...")

        tasks = [asyncio.create_task(check_symbol(sym)) for sym in symbols]
        results = await asyncio.gather(*tasks)

        crossed = [r for r in results if r]

        if crossed:
            msg = "📊 *EMA200 Cross Signals (1h)*\n\n"
            for sym, typ in crossed:
                msg += f"{sym} → {typ}\n"

            await send_tg(msg)
            print("Telegram sent:", msg.replace("\n", " | "))
        else:
            print("No crosses this candle.")

        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped manually.")
