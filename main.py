# main.py
# Telegram EMA-200 15m scanner for Binance USDT pairs.
# - Finds all BINANCE symbols that end with "USDT"
# - Fetches last KLIMIT 15m klines (so we can compute EMA200)
# - Detects when a CLOSED 15m candle closes above or below EMA200
# - Sends a Telegram message once per crossover (avoids duplicates)
# - Async with concurrent request limiter

import os
import asyncio
import time
from typing import List, Dict
import aiohttp
from aiohttp import ClientSession
from dotenv import load_dotenv

load_dotenv()

BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
TELEGRAM_SEND = "https://api.telegram.org/bot{token}/sendMessage"

# CONFIG (from env)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # required
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")      # required (int or string)
CONCURRENT_REQUESTS = int(os.getenv("CONCURRENT_REQUESTS", "12"))  # tune to avoid rate limits
KLIMIT = int(os.getenv("KLIMIT", "210"))  # number of klines to fetch (>= 201 recommended)
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))  # seconds between scan loops (we align to 15m)
TIMEFRAME = os.getenv("TIMEFRAME", "15m")  # 15m
EMA_LEN = int(os.getenv("EMA_LEN", "200"))
SYMBOLS_LIMIT = int(os.getenv("SYMBOLS_LIMIT", "0"))  # 0 = all USDT pairs

# Safety checks
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment variables.")

# Helper: compute EMA (simple, numeric-stable)
def compute_ema(values: List[float], length: int) -> List[float]:
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

# Determine relation: above = 1, below = -1, equal = 0
def relation_to_ema(close: float, ema: float) -> int:
    if ema is None:
        return 0
    if close > ema:
        return 1
    if close < ema:
        return -1
    return 0

class EMA200Scanner:
    def __init__(self, session: ClientSession):
        self.session = session
        self.semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
        self.last_relation: Dict[str, int] = {}  # symbol -> last known relation (1 or -1 or 0)
        self.symbols: List[str] = []

    async def fetch_usdt_symbols(self) -> List[str]:
        async with self.session.get(BINANCE_EXCHANGE_INFO, timeout=30) as resp:
            data = await resp.json()
        syms = []
        for s in data.get("symbols", []):
            if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
                syms.append(s["symbol"])
        syms.sort()
        if SYMBOLS_LIMIT and SYMBOLS_LIMIT > 0:
            syms = syms[:SYMBOLS_LIMIT]
        self.symbols = syms
        print(f"Discovered {len(syms)} USDT symbols.")
        return syms

    async def fetch_klines(self, symbol: str) -> List[List]:
        params = {"symbol": symbol, "interval": TIMEFRAME, "limit": KLIMIT}
        async with self.semaphore:
            async with self.session.get(BINANCE_KLINES, params=params, timeout=30) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"Klines fetch error {resp.status} for {symbol}: {text[:200]}")
                    return []
                return await resp.json()

    async def send_telegram(self, text: str):
        url = TELEGRAM_SEND.format(token=TELEGRAM_BOT_TOKEN)
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        try:
            async with self.session.post(url, json=payload, timeout=15) as resp:
                if resp.status != 200:
                    print("Telegram send error:", await resp.text())
        except Exception as e:
            print("Telegram send exception:", e)

    async def handle_symbol(self, symbol: str):
        klines = await self.fetch_klines(symbol)
        if not klines:
            return
        closes = [float(k[4]) for k in klines]
        ema_list = compute_ema(closes, EMA_LEN)
        last_idx = len(closes) - 1
        last_ema = ema_list[last_idx]
        last_close = closes[last_idx]
        rel = relation_to_ema(last_close, last_ema)
        prev_rel = self.last_relation.get(symbol, 0)
        if prev_rel == 0:
            self.last_relation[symbol] = rel
            return
        if rel != prev_rel and rel != 0:
            direction = "ABOVE" if rel == 1 else "BELOW"
            close_time = klines[last_idx][6] / 1000.0
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(close_time))
            msg = (f"{symbol} — 15m CLOSED {direction} EMA{EMA_LEN}\n"
                   f"Close: {last_close}\nEMA{EMA_LEN}: {round(last_ema, 8) if last_ema else 'n/a'}\n"
                   f"Time(UTC): {ts}")
            await self.send_telegram(msg)
            print("Alert sent:", msg.replace("\n", " | "))
        self.last_relation[symbol] = rel

    async def run_scan_once(self):
        tasks = []
        for s in self.symbols:
            tasks.append(asyncio.create_task(self.handle_symbol(s)))
        await asyncio.gather(*tasks)

async def align_to_next_15m():
    now = time.time()
    gm = time.gmtime(now)
    minutes = gm.tm_min
    seconds = gm.tm_sec
    next_min = ((minutes // 15) + 1) * 15
    add_minutes = (next_min - minutes) % 60
    wait_seconds = add_minutes * 60 - seconds + 3
    if wait_seconds < 0:
        wait_seconds += 15 * 60
    print(f"Aligning to next 15m close: sleeping {int(wait_seconds)}s...")
    await asyncio.sleep(wait_seconds)

async def main_loop():
    async with aiohttp.ClientSession() as session:
        scanner = EMA200Scanner(session)
        await scanner.fetch_usdt_symbols()
        print("Initial seed scan (no alerts will be sent during seed)...")
        await scanner.run_scan_once()
        print("Seed complete. Entering aligned loop to check on each closed 15m candle.")
        while True:
            await align_to_next_15m()
            start = time.time()
            try:
                await scanner.run_scan_once()
            except Exception as e:
                print("Error during scan:", e)
            elapsed = time.time() - start
            print(f"Scan finished in {elapsed:.1f}s. Next align.")
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("Stopped by user")
