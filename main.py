# main.py
# 1H EMA200 Futures scanner — sends TG every hour (even if no crosses)
# - Uses static futures list (Railway-proof)
# - Uses Binance proxy endpoint (bypasses geo-block)
# - Sends a grouped Telegram message each hour
# - Checks TRUE crosses comparing previous closed candle vs last closed candle

import asyncio
import aiohttp
import time
from typing import List, Optional

# ==============================
# CONFIG (hard-coded for Railway)
# ==============================
TELEGRAM_BOT_TOKEN = "8420434829:AAFvBIh9iD_hhcDjsXg70xst8RNGLuGPtYc"
TELEGRAM_CHAT_ID = "966269191"

TIMEFRAME = "1h"
EMA_LENGTH = 200
KLINES_LIMIT = 250

# Use Binance proxy endpoint to bypass region blocks
BINANCE_FUTURES_PROXY_BASE = "https://fapi.binance.sonibyte.us/fapi/v1"

# ==============================
# STATIC FUTURES LIST (160+ symbols)
# ==============================
FUTURES_LIST = [
"1000BONKUSDT","1000FLOKIUSDT","1000LUNCUSDT","1000PEPEUSDT","1INCHUSDT",
"AAVEUSDT","ACHUSDT","ADAUSDT","AGLDUSDT","AIUSDT","ALGOUSDT","ALICEUSDT",
"ALPHAUSDT","ALTUSDT","ANKRUSDT","ANTUSDT","APEUSDT","API3USDT","APTUSDT",
"ARBUSDT","ARKMUSDT","ARKUSDT","ARPAUSDT","ARUSDT","ASTRUSDT","ATAUSDT",
"ATOMUSDT","AUDIOUSDT","AVAXUSDT","AXSUSDT","BABYDOGEUSDT","BANDUSDT",
"BATUSDT","BCHUSDT","BEAMXUSDT","BELUSDT","BICOUSDT","BIGTIMEUSDT",
"BITUSDT","BLURUSDT","BLZUSDT","BNBUSDT","BNTUSDT","BOMEUSDT","BONKUSDT",
"BRETTUSDT","BSVUSDT","BTCUSDT","C98USDT","CAKEUSDT","CELOUSDT",
"CETUSUSDT","CFXUSDT","CHZUSDT","CKBUSDT","COMBOUSDT","COMPUSDT",
"COTIUSDT","CRVUSDT","CTKUSDT","CTSIUSDT","CVXUSDT","CYBERUSDT","DASHUSDT",
"DEFIUSDT","DENTUSDT","DGBUSDT","DODOUSDT","DOGEUSDT","DOTUSDT","DUSKUSDT",
"DYDXUSDT","EDUUSDT","EGLDUSDT","ENAUSDT","ENJUSDT","ENSUSDT","EOSUSDT",
"ETCUSDT","ETHUSDT","ETHFIUSDT","FETUSDT","FILUSDT","FIOUSDT","FLAREUSDT",
"FLOWUSDT","FLUXUSDT","FTMUSDT","FXSUSDT","GALAUSDT","GALUSDT","GASUSDT",
"GFTUSDT","GLMRUSDT","GLMUSDT","GMTUSDT","GMXUSDT","GRTUSDT","HBARUSDT",
"HFTUSDT","HIFIUSDT","HOOKUSDT","HOTUSDT","ICPUSDT","ICXUSDT","IDUSDT",
"ILVUSDT","IMXUSDT","INJUSDT","IOSTUSDT","IOTAUSDT","IOTXUSDT","JASMYUSDT",
"JOEUSDT","JTOUSDT","JUPUSDT","KAVAUSDT","KDAUSDT","KLAYUSDT","KNCUSDT",
"KSMUSDT","LDOUSDT","LEVERUSDT","LINAUSDT","LINKUSDT","LITUSDT","LPTUSDT",
"LQTYUSDT","LRCUSDT","LTCUSDT","LUNA2USDT","LUNCUSDT","MAGICUSDT","MANAUSDT",
"MATICUSDT","MAVUSDT","MDTUSDT","MEMEUSDT","MINAUSDT","MKRUSDT","MTLUSDT",
"NEARUSDT","NEOUSDT","NFPUSDT","NKNUSDT","NMRUSDT","OCEANUSDT","OGNUSDT",
"OMGUSDT","ONEUSDT","ONTUSDT","OPUSDT","ORDIUSDT","OXTUSDT","PENDLEUSDT",
"PEOPLEUSDT","PEPEUSDT","PERPUSDT","PHBUSDT","POLYXUSDT","PORTALUSDT",
"PYTHUSDT","QNTUSDT","QTUMUSDT","RAYUSDT","RDNTUSDT","REEFUSDT","RENUSDT",
"RNDRUSDT","ROSEUSDT","RSRUSDT","RUNEUSDT","RVNUSDT","SANDUSDT","SEIUSDT",
"SHIBUSDT","SKLUSDT","SLPUSDT","SNXUSDT","SOLUSDT","SSVUSDT","STEEMUSDT",
"STGUSDT","STMXUSDT","STORJUSDT","STXUSDT","SUIUSDT","SUPERUSDT","SUSHIUSDT",
"SXPUSDT","SYSUSDT","TOMIUSDT","THETAUSDT","TIAUSDT","TLMUSDT","TRBUSDT",
"TRXUSDT","TUSDT","UMAUSDT","UNFIUSDT","UNIUSDT","VETUSDT","WLDUSDT",
"WOOUSDT","XAIUSDT","XEMUSDT","XLMUSDT","XMRUSDT","XRPUSDT","XTZUSDT",
"YFIUSDT","ZECUSDT","ZENUSDT","ZILUSDT","ZRXUSDT"
]

# ==============================
# EMA calculation helpers
# ==============================
def compute_ema_list(values: List[float], period: int) -> List[Optional[float]]:
    n = len(values)
    ema = [None] * n
    if n < period:
        return ema
    # seed with SMA
    seed = sum(values[:period]) / period
    ema[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    for i in range(period, n):
        ema[i] = ema[i - 1] + alpha * (values[i] - ema[i - 1])
    return ema

# ==============================
# Telegram sender
# ==============================
async def send_telegram(session: aiohttp.ClientSession, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        async with session.post(url, json=payload, timeout=15) as resp:
            if resp.status != 200:
                text_resp = await resp.text()
                print("[tg] Error sending:", resp.status, text_resp)
    except Exception as e:
        print("[tg] Exception:", e)

# ==============================
# Fetch klines via proxy
# ==============================
async def fetch_klines(session: aiohttp.ClientSession, symbol: str) -> Optional[List]:
    url = f"{BINANCE_FUTURES_PROXY_BASE}/klines"
    params = {"symbol": symbol, "interval": TIMEFRAME, "limit": KLINES_LIMIT}
    try:
        async with session.get(url, params=params, timeout=25) as resp:
            if resp.status != 200:
                text = await resp.text()
                # print minimal info to avoid log spam
                print(f"[kline] {symbol} error {resp.status}: {text[:200]}")
                return None
            data = await resp.json()
            # defensive: if Binance returns error dict, skip
            if isinstance(data, dict) and data.get("code") is not None:
                print(f"[kline] {symbol} returned error: {data.get('msg') or data}")
                return None
            return data
    except Exception as e:
        print(f"[kline] {symbol} exception:", e)
        return None

# ==============================
# Check single symbol for EMA cross
# ==============================
async def check_symbol(session: aiohttp.ClientSession, symbol: str):
    kl = await fetch_klines(session, symbol)
    if not kl or len(kl) < EMA_LENGTH + 2:
        return None

    closes = [float(k[4]) for k in kl]
    ema_list = compute_ema_list(closes, EMA_LENGTH)

    last_idx = len(closes) - 1
    prev_idx = last_idx - 1

    last_close = closes[last_idx]
    prev_close = closes[prev_idx]
    last_ema = ema_list[last_idx]
    prev_ema = ema_list[prev_idx]

    if last_ema is None or prev_ema is None:
        return None

    # prev below EMA and last above EMA => bullish cross
    if prev_close < prev_ema and last_close > last_ema:
        return ("BULLISH", symbol, last_close, last_ema)
    # prev above EMA and last below EMA => bearish cross
    if prev_close > prev_ema and last_close < last_ema:
        return ("BEARISH", symbol, last_close, last_ema)
    return None

# ==============================
# Align to next 1h candle close
# ==============================
async def align_to_next_hour():
    now = time.time()
    gm = time.gmtime(now)
    seconds = gm.tm_min * 60 + gm.tm_sec
    wait = 3600 - seconds + 2  # small buffer
    if wait < 0:
        wait = 2
    print(f"[align] Sleeping {int(wait)}s until next 1h candle close...")
    await asyncio.sleep(wait)

# ==============================
# Main loop
# ==============================
async def main():
    print(f"[start] Loaded {len(FUTURES_LIST)} futures symbols (static list)")
    # Use a single session for efficiency, but disable SSL verification to avoid platform SSL issues
    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn) as session:
        while True:
            await align_to_next_hour()
            print("[scan] Checking EMA200 crosses on 1h candles...")
            tasks = [check_symbol(session, s) for s in FUTURES_LIST]
            results = await asyncio.gather(*tasks)

            bulls = []
            bears = []
            scanned = 0
            for r in results:
                if r:
                    typ, sym, close, ema_val = r
                    scanned += 1
                    if typ == "BULLISH":
                        bulls.append((sym, close, ema_val))
                    else:
                        bears.append((sym, close, ema_val))
                else:
                    # even if None, count as scanned (we attempted)
                    scanned += 1

            # Build message (Format A, compact)
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            if bulls or bears:
                msg_lines = [f"🚀 EMA200 Crosses (1H) — {timestamp}", f"Scanned: {scanned} symbols", ""]
                if bulls:
                    msg_lines.append("🔥 Bullish Breakouts:")
                    for s, c, e in bulls:
                        msg_lines.append(f"{s} | Close {c} | EMA200 {round(e,6)} | BULLISH")
                if bears:
                    msg_lines.append("")
                    msg_lines.append("⚠️ Bearish Breakdowns:")
                    for s, c, e in bears:
                        msg_lines.append(f"{s} | Close {c} | EMA200 {round(e,6)} | BEARISH")
                message = "\n".join(msg_lines)
            else:
                message = f"📊 1H EMA200 Scanner — {timestamp}\nScanned: {scanned} symbols\nNo EMA200 crosses detected this candle."

            # Send Telegram message (always send every hour)
            await send_telegram(session, message)
            print("[scan] Done. Message sent (or attempted). Sleeping until next hour...")

# Entry point
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped by user")
