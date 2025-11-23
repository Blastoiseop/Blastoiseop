# main.py
# Fully working Telegram EMA200 15m scanner
# Works on Python 3.13 + Railway (no event loop errors)

import asyncio
import time
from typing import List, Dict
import aiohttp

# ---- Your Provided Values ----
TELEGRAM_BOT_TOKEN = "8420434829:AAFvBIh9iD_hhcDjsXg70xst8RNGLuGPtYc"
TELEGRAM_CHAT_ID = "966269191"

HEADERS = {"User-Agent": "Mozilla/5.0"}

BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
TELEGRAM_SEND = "https://api.telegram.org/bot{token}/sendMessage"

# CONFIG
CONCURRENT_REQUESTS = 12
KLIMIT = 210
TIMEFRAME = "15m"
EMA_LEN = 200
SYMBOLS_LIMIT = 0


# ---- EMA ----
def compute_ema(values: List[float], length: int):
    n = len(values)
    ema = [None] * n
    if n < length:
        return ema
    seed = sum(values[:length]) / length
    ema[length - 1] = seed
    alpha = 2 / (length + 1)
    for i in range(length, n):
        ema[i] = (values[i] - ema[i - 1]) * alpha + ema[i - 1]
    return ema


def relation_to_ema(close: float, ema: float):
    if ema is None:
        return 0
    if close > ema:
        return 1
    if close < ema:
        return -1
    return 0


# ---- MAIN SCANNER CLASS ----
class EMA200Scanner:
    def __init__(self):
        self.last_relation: Dict[str, int] = {}
        self.symbols: List[str] = []
        self.semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)

    # ---- FETCH USDT SYMBOLS ----
    async def fetch_usdt_symbols(self):
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        ) as session:
            async with session.get(BINANCE_EXCHANGE_INFO, headers=HEADERS) as resp:
                try:
                    data = await resp.json()
                except:
                    print("Error decoding exchangeInfo")
                    return []

        syms = []
        for s in data.get("symbols", []):
            if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
                syms.append(s["symbol"])

        syms.sort()

        if SYMBOLS_LIMIT > 0:
            syms = syms[:SYMBOLS_LIMIT]

        self.symbols = syms
        print(f"Discovered {len(syms)} USDT symbols.")
        return syms

    # ---- FETCH KLINES ----
    async def fetch_klines(self, symbol):
        params = {"symbol": symbol, "interval": TIMEFRAME, "limit": KLIMIT}

        async with self.semaphore:
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=False)
            ) as session:
                async with session.get(BINANCE_KLINES, params=params, headers=HEADERS) as resp:
                    if resp.status != 200:
                        print(f"Klines error {resp.status} for {symbol}")
                        return []
                    try:
                        return await resp.json()
                    except:
                        return []

    # ---- SEND TELEGRAM ----
    async def send_telegram(self, text):
        url = TELEGRAM_SEND.format(token=TELEGRAM_BOT_TOKEN)
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}

        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        ) as session:
            try:
                await session.post(url, json=payload, headers=HEADERS)
            except:
                print("Telegram send failed")

    # ---- PROCESS SYMBOL ----
    async def handle_symbol(self, symbol):
        kl = await self.fetch_klines(symbol)
        if not kl:
            return

        closes = [float(k[4]) for k in kl]
        ema_list = compute_ema(closes, EMA_LEN)

        last_idx = len(closes) - 1
        last_close = closes[last_idx]
        last_ema = ema_list[last_idx]

        rel = relation_to_ema(last_close, last_ema)
        prev_rel = self.last_relation.get(symbol, 0)

        # Skip first detection
        if prev_rel == 0:
            self.last_relation[symbol] = rel
            return

        if rel != prev_rel and rel != 0:
            direction = "ABOVE" if rel == 1 else "BELOW"
            msg = f"{symbol} CLOSED {direction} EMA{EMA_LEN} — {last_close}"
            print("Alert:", msg)
            await self.send_telegram(msg)

        self.last_relation[symbol] = rel

    # ---- BATCH RUN ----
    async def run_scan_once(self):
        tasks = [asyncio.create_task(self.handle_symbol(s)) for s in self.symbols]
        await asyncio.gather(*tasks)


# ---- ALIGN TO 15M ----
async def align_to_next_15m():
    now = time.time()
    gm = time.gmtime(now)
    mins = gm.tm_min
    secs = gm.tm_sec
    next_min = ((mins // 15) + 1) * 15
    wait = (next_min - mins) * 60 - secs + 3
    if wait < 0:
        wait += 900
    print(f"Sleeping {int(wait)}s until next 15m close...")
    await asyncio.sleep(wait)


# ---- MAIN LOOP ----
async def main_loop():
    scanner = EMA200Scanner()

    await scanner.fetch_usdt_symbols()
    print("Initial seed scan...")
    await scanner.run_scan_once()

    print("Starting loop...")
    while True:
        await align_to_next_15m()
        await scanner.run_scan_once()


if __name__ == "__main__":
    asyncio.run(main_loop())
