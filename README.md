# Binance USDT EMA200 15m Telegram Bot

This package contains a simple Telegram bot (Python) that:
- discovers Binance trading symbols with quote asset USDT,
- fetches recent 15m candlesticks for each symbol,
- computes EMA(200) and detects when a CLOSED 15m candle closes above or below the EMA,
- sends a Telegram message when a crossover occurs (one alert per crossover).

## Files
- `main.py` - main bot script (async, uses aiohttp)
- `requirements.txt` - Python dependencies
- `.env.example` - example environment variables

## Quick start
1. Copy `.env.example` to `.env` and fill `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
2. Create a virtual environment, install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Run:
   ```bash
   python main.py
   ```

## Notes
- The script seeds the last relation on the first run and does not alert during the seed.
- Aligns to 15-minute candle closes (UTC) and sends alerts on closed candles only.
- If you plan to monitor hundreds of symbols reliably, consider using Binance websocket combined streams (I can provide that version if you'd like).
