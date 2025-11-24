import asyncio
import aiohttp
import time
import json

# ==============================
# CONFIG
# ==============================
TELEGRAM_BOT_TOKEN = "8420434829:AAFvBIh9iD_hhcDjsXg70xst8RNGLuGPtYc"
TELEGRAM_CHAT_ID = "966269191"

TIMEFRAME = "1h"
EMA_LENGTH = 200

# From Indian location → must use proxy for Binance
BINANCE_FUTURES_PROXY = "https://fapi.binance.com/fapi/v1/"

# Static Futures list (160 symbols)
FUTURES_LIST = [
"1000BONKUSDT","1000FLOKIUSDT","1000LUNCUSDT","1000PEPEUSDT","1INCHUSDT",
"AAVEUSDT","ACHUSDT","ADAUSDT","AGLDUSDT","AIUSDT","ALGOUSDT","ALICEUSDT",
"ALPHAUSDT","ALTUSDT","ANKRUSDT","ANTUSDT","APEUSDT","API3USDT","APTUSDT",
"ARBUSDT","ARKMUSDT","ARKUSDT","ARPAUSDT","ARUSDT","ASTRUSDT","ATAUSDT",
"ATOMUSDT","AUDIOUSDT","AVAXUSDT","AXSUSDT","BABYDOGEUSDT","BANDUSDT",
"BATUSDT","BCHUSDT","BEAMXUSDT","BELUSDT","BICOUSDT","BIGTIMEUSDT",
"BITUSDT","BLURUSDT","BLZUSDT","BNBUSDT","BNTUSDT","BOMEUSDT","BONKUSDT",
"BRETTUSDT","BSVUSDT","BTCUSDT","BCHUSDT","C98USDT","CAKEUSDT","CELOUSDT",
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
# EMA FUNCTION
# ==============================
def ema(values, length):
    if len(values) < length:
        return None
    alpha = 2 / (length + 1)
    ema_val = sum(values[:length]) / length
    for v in values[length:]:
        ema_val = (v - ema_val) * alpha + ema_val
    return ema_val

# ==============================
# TELEGRAM
# ==============================
async def send_msg(session, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    await session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text})


# ==============================
# FETCH KLINES
# ==============================
async def fetch_klines(session, symbol):
    url = f"{BINANCE_FUTURES_PROXY}klines?symbol={symbol}&interval=1h&limit=250"
    try:
        async with session.get(url, timeout=20) as r:
            data = await r.json()
            if isinstance(data, dict) and "code" in data:
                return None
            return data
    except:
        return None


# ==============================
# MAIN SCAN
# ==============================
async def check_cross(session, symbol):
    kl = await fetch_klines(session, symbol)
    if not kl:
        return None

    closes = [float(x[4]) for x in kl]
    last = closes[-1]
    prev = closes[-2]

    ema200 = ema(closes, EMA_LENGTH)
    if ema200 is None:
        return None

    prev_rel = prev > ema200
    last_rel = last > ema200

    # CROSS LOGIC
    if prev_rel != last_rel:
        direction = "BULLISH ↑ (Crossed ABOVE)" if last_rel else "BEARISH ↓ (Crossed BELOW)"
        return f"{symbol} — {direction}\nClose: {last}\nEMA200: {round(ema200, 6)}"

    return None


# ==============================
# LOOP
# ==============================
async def main():
    print(f"Loaded {len(FUTURES_LIST)} Futures symbols")
    async with aiohttp.ClientSession() as session:

        while True:
            # Align to next 1h
            now = time.time()
            next_hour = (int(now // 3600) + 1) * 3600
            wait = int(next_hour - now)
            print(f"Sleeping {wait}s until next 1h candle close...")
            await asyncio.sleep(wait)

            print("Checking EMA200 crosses...")
            tasks = [check_cross(session, s) for s in FUTURES_LIST]
            results = await asyncio.gather(*tasks)

            crosses = [r for r in results if r]

            if crosses:
                msg = "🚀 **EMA200 CROSS (1H)** 🚀\n\n" + "\n\n".join(crosses)
                await send_msg(session, msg)
                print(msg)
            else:
                print("No crosses this candle.")


if __name__ == "__main__":
    asyncio.run(main())
