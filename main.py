import asyncio
import aiohttp
import time

BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"

TIMEFRAME = "15m"
KLIMIT = 210
EMA_LEN = 200


def ema(values, length):
    if len(values) < length:
        return [None] * len(values)

    out = [None] * len(values)
    seed = sum(values[:length]) / length
    out[length - 1] = seed

    alpha = 2 / (length + 1)
    for i in range(length, len(values)):
        out[i] = out[i - 1] + alpha * (values[i] - out[i - 1])

    return out


async def fetch_json(url, params=None):
    try:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        ) as s:
            async with s.get(url, params=params) as r:
                return await r.json()
    except:
        return None


async def get_usdt_symbols():
    data = await fetch_json(BINANCE_EXCHANGE_INFO)
    syms = []
    for s in data["symbols"]:
        if s["status"] == "TRADING" and s["quoteAsset"] == "USDT":
            syms.append(s["symbol"])
    return syms


async def fetch_15m(symbol):
    params = {"symbol": symbol, "interval": TIMEFRAME, "limit": KLIMIT}
    return await fetch_json(BINANCE_KLINES, params)


async def check_symbol(symbol):
    kl = await fetch_15m(symbol)
    if not kl or len(kl) < EMA_LEN + 2:
        return None

    # CLOSED candles only
    closes = [float(k[4]) for k in kl]
    close_times = [int(k[6]) for k in kl]

    ema_list = ema(closes, EMA_LEN)

    last = len(closes) - 1
    prev = last - 1

    # verify candle is closed
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


async def main():
    syms = await get_usdt_symbols()
    print(f"Scanning {len(syms)} USDT symbols…")

    tasks = [asyncio.create_task(check_symbol(s)) for s in syms]
    results = await asyncio.gather(*tasks)

    print("\n=== EMA200 CROSS RESULTS (15m) ===")
    for r in results:
        if r:
            print(r[0], "→", r[1])


if __name__ == "__main__":
    asyncio.run(main())
