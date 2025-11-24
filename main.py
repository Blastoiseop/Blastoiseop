import aiohttp
import asyncio
import time
import ssl

# ======================================
# HARD-CODED TELEGRAM CREDENTIALS
# ======================================
TELEGRAM_BOT_TOKEN = "8420434829:AAFvBIh9iD_hhcDjsXg70xst8RNGLuGPtYc"
TELEGRAM_CHAT_ID = "966269191"

SEND_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
INTERVAL = "1h"
KLIMIT = 210
EMA_LEN = 200

# ======================================
# FULL STATIC BINANCE USDT-M FUTURES LIST (UPDATED)
# ======================================
FUTURES_USDT = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","DOTUSDT","AVAXUSDT",
    "TRXUSDT","LINKUSDT","MATICUSDT","LTCUSDT","BCHUSDT","ATOMUSDT","UNIUSDT","XLMUSDT","ALGOUSDT",
    "VETUSDT","ICPUSDT","FILUSDT","APTUSDT","ARBUSDT","SUIUSDT","OPUSDT","INJUSDT","MKRUSDT",
    "NEARUSDT","AAVEUSDT","RNDRUSDT","FLOWUSDT","EGLDUSDT","FTMUSDT","THETAUSDT","RUNEUSDT",
    "GRTUSDT","AXSUSDT","SANDUSDT","MANAUSDT","LDOUSDT","DYDXUSDT","IMXUSDT","CRVUSDT","KAVAUSDT",
    "KLAYUSDT","ZILUSDT","1INCHUSDT","CELOUSDT","COMPUSDT","CHZUSDT","ROSEUSDT","ARUSDT","GMXUSDT",
    "TWTUSDT","ZRXUSDT","DASHUSDT","ENJUSDT","CEEKUSDT","HOTUSDT","DENTUSDT","COTIUSDT","LRCUSDT",
    "STMXUSDT","WAVESUSDT","XEMUSDT","XTZUSDT","OGNUSDT","BELUSDT","BLZUSDT","OCEANUSDT","RVNUSDT",
    "MASKUSDT","MAGICUSDT","HIGHUSDT","WOOUSDT","OOKIUSDT","LINAUSDT","ANTUSDT","HNTUSDT","PYTHUSDT",
    "JUPUSDT","TIAUSDT","STRKUSDT","SEIUSDT","JTOUSDT","ACEUSDT","BICOUSDT","GALUSDT","HOOKUSDT",
    "IDUSDT","JOEUSDT","SFPUSDT","GLMRUSDT","DARUSDT","ALICEUSDT","GALAUSDT","YGGUSDT","ILVUSDT",
    "PEPEUSDT","BONKUSDT","CHILLUSDT","WIFUSDT","PORTALUSDT","DOGSUSDT","TNSRUSDT","PIXELUSDT",
    "MAVUSDT","AUCTIONUSDT","BATUSDT","DEFIUSDT","PENDLEUSDT","XAIUSDT","CYBERUSDT","ARKMUSDT",
    "FETUSDT","AGIXUSDT","NMRUSDT","IQUSDT","POLYXUSDT","VANRYUSDT","NTRNUSDT","SKLUSDT","TRBUSDT",
    "YFIIUSDT","KNCUSDT","STGUSDT","PLAUSDT","CTKUSDT","QNTUSDT","OMGUSDT","SRMUSDT","MTLUSDT",
    "OXTUSDT","ICXUSDT","SCUSDT","FLMUSDT","PERPUSDT","ANKRUSDT","ZECUSDT","RLCUSDT","API3USDT",
    "POWRUSDT","GLMUSDT","ACHUSDT","DODOUSDT","BAKEUSDT","SXPUSDT","CKBUSDT","LOOMUSDT","CELRUSDT",
    "RENUSDT","SYSUSDT","STORJUSDT","KSMUSDT","ZENUSDT","BALUSDT","OMGUSDT","ALPHAUSDT",
    "FLOKIUSDT","1000SHIBUSDT"
]
# ======================================
# EMA CALCULATION (EMA-200)
# ======================================
def ema(values, length):
    if len(values) < length:
        return [None] * len(values)

    ema_list = [None] * len(values)
    alpha = 2 / (length + 1)

    # Seed value: SMA of first 200
    seed = sum(values[:length]) / length
    ema_list[length - 1] = seed

    # Apply EMA recursively
    for i in range(length, len(values)):
        ema_list[i] = ema_list[i - 1] + alpha * (values[i] - ema_list[i - 1])

    return ema_list


# ======================================
# FETCH KLINES (Futures 1h)
# ======================================
async def get_klines(symbol, session):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": INTERVAL, "limit": KLIMIT}

    try:
        async with session.get(url, params=params) as r:
            if r.status != 200:
                print("Kline error for", symbol, await r.text())
                return None
            return await r.json()
    except:
        return None


# ======================================
# PROCESS A SINGLE SYMBOL
# ======================================
async def check_symbol(symbol, session, bullish, bearish):
    data = await get_klines(symbol, session)
    if not data:
        return

    closes = [float(k[4]) for k in data]
    if len(closes) < EMA_LEN + 2:
        return

    ema_list = ema(closes, EMA_LEN)

    last_close = closes[-1]
    prev_close = closes[-2]

    last_ema = ema_list[-1]
    prev_ema = ema_list[-2]

    if last_ema is None or prev_ema is None:
        return

    # True CROSS detection
    prev_rel = prev_close - prev_ema
    last_rel = last_close - last_ema

    if prev_rel < 0 and last_rel > 0:
        bullish.append((symbol, last_close, last_ema))

    elif prev_rel > 0 and last_rel < 0:
        bearish.append((symbol, last_close, last_ema))
# ======================================
# SEND TELEGRAM MESSAGE
# ======================================
async def send_telegram(msg, session):
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        async with session.post(SEND_URL, json=payload) as r:
            if r.status != 200:
                print("Telegram Error:", await r.text())
    except Exception as e:
        print("Telegram Exception:", e)


# ======================================
# WAIT FOR NEXT 1-HOUR CANDLE CLOSE
# ======================================
async def wait_next_hour():
    now = time.time()
    gm = time.gmtime(now)

    seconds_now = gm.tm_min * 60 + gm.tm_sec
    wait = 3600 - seconds_now + 3   # +3 seconds safety margin

    print(f"Sleeping {wait}s until next 1h candle close...")
    await asyncio.sleep(wait)


# ======================================
# MAIN BOT LOOP
# ======================================
async def main():
    print(f"Loaded {len(FUTURES_USDT)} USDT-M Futures symbols (static list)")

    # SSL bypass for Railway
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_ctx)
    ) as session:
        while True:

            # Wait for next hourly candle
            await wait_next_hour()

            bullish = []
            bearish = []

            print("Scanning EMA200 crosses...")

            tasks = [
                check_symbol(sym, session, bullish, bearish)
                for sym in FUTURES_USDT
            ]

            await asyncio.gather(*tasks)

            # If NO signals → print only
            if not bullish and not bearish:
                print("No crosses found this candle.")
                continue

            # BUILD MESSAGE (Format A)
            msg = "=== EMA200 Cross (1H) ===\n"

            for sym, close, ema_val in bullish:
                msg += f"{sym} | Close {close} | EMA200 {ema_val} | BULLISH\n"

            for sym, close, ema_val in bearish:
                msg += f"{sym} | Close {close} | EMA200 {ema_val} | BEARISH\n"

            print(msg)

            # SEND TG ALERT
            await send_telegram(msg, session)


# ======================================
# BOT START
# ======================================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
