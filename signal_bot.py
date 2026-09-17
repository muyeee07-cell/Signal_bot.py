import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from time import sleep

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

TIMEFRAME = "1h"
LIMIT = 100
TOP_PAIRS = 35
MIN_VOLUME_USDT = 8_000_000
ATR_MULTIPLIER = 1.6
RR = 2.0

BASE_URL = "https://fapi.binance.com"

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Token atau Chat ID belum di-set")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Gagal kirim Telegram:", e)

def get_top_pairs(limit=TOP_PAIRS):
    url = f"{BASE_URL}/fapi/v1/ticker/24hr"
    try:
        response = requests.get(url, timeout=15)
        data = response.json()

        if not isinstance(data, list):
            print("Response Binance tidak valid:", str(data)[:200])
            return []

        EXCLUDE = [
            "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "USDPUSDT",
            "DAIUSDT", "EURUSDT", "GBPUSDT", "USDEUSDT",
            "BFUSDUSDT", "XUSDUSDT", "TUSDUSDT"
        ]

        usdt = []
        for item in data:
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol", "")
            if symbol.endswith("USDT") and symbol not in EXCLUDE:
                try:
                    volume = float(item.get("quoteVolume", 0))
                    if volume >= MIN_VOLUME_USDT:
                        usdt.append((symbol, volume))
                except:
                    continue

        usdt.sort(key=lambda x: x[1], reverse=True)
        return [x[0] for x in usdt[:limit]]

    except Exception as e:
        print("Gagal ambil daftar pair:", e)
        return []

def get_klines(symbol, interval="1h", limit=100):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if not isinstance(data, list) or len(data) < 50:
            return None

        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        df["open"] = pd.to_numeric(df["open"], errors="coerce")
        df["high"] = pd.to_numeric(df["high"], errors="coerce")
        df["low"] = pd.to_numeric(df["low"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        return df.dropna()
    except Exception as e:
        print(f"Gagal ambil klines {symbol}: {e}")
        return None

def calculate_indicators(df):
    df = df.copy()

    df["ema_fast"] = df["close"].ewm(span=21, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=55, adjust=False).mean()

    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift())
    low_close = np.abs(df["low"] - df["close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()

    plus_dm = df["high"].diff()
    minus_dm = df["low"].diff() * -1
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0

    tr14 = tr.rolling(14).mean()
    plus_di = 100 * (plus_dm.rolling(14).mean() / tr14)
    minus_di = 100 * (minus_dm.rolling(14).mean() / tr14)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
    df["adx"] = dx.rolling(14).mean()

    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))

    return df.dropna()

def check_signal(df, symbol):
    if len(df) < 60:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    atr = float(last["atr"])
    close = float(last["close"])
    adx = float(last["adx"])
    rsi = float(last["rsi"])

    signal = None
    reason = ""

    # Trend mode
    if adx > 23:
        if (prev["ema_fast"] > prev["ema_slow"] and
            last["close"] > last["ema_fast"] and
            52 < rsi < 68):
            signal = "LONG"
            reason = "Trend Following"
        elif (prev["ema_fast"] < prev["ema_slow"] and
              last["close"] < last["ema_fast"] and
              32 < rsi < 48):
            signal = "SHORT"
            reason = "Trend Following"

    # Range mode
    else:
        if rsi < 30:
            signal = "LONG"
            reason = "Mean Reversion Oversold"
        elif rsi > 70:
            signal = "SHORT"
            reason = "Mean Reversion Overbought"

    if not signal:
        return None

    if signal == "LONG":
        sl = close - ATR_MULTIPLIER * atr
        tp = close + RR * (close - sl)
    else:
        sl = close + ATR_MULTIPLIER * atr
        tp = close - RR * (sl - close)

    return {
        "symbol": symbol,
        "side": signal,
        "entry": round(close, 6),
        "sl": round(sl, 6),
        "tp": round(tp, 6),
        "adx": round(adx, 1),
        "rsi": round(rsi, 1),
        "reason": reason
    }

def main():
    print(f"Mulai scan | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    pairs = get_top_pairs()
    print(f"Total pair di-scan: {len(pairs)}")

    if not pairs:
        print("Tidak ada pair yang bisa di-scan")
        return

    signals = []

    for i, symbol in enumerate(pairs):
        try:
            df = get_klines(symbol, interval=TIMEFRAME, limit=LIMIT)
            if df is None or len(df) < 60:
                continue

            df = calculate_indicators(df)
            sig = check_signal(df, symbol)

            if sig:
                signals.append(sig)
                print(f"Signal: {symbol} {sig['side']}")

            if i % 8 == 0:
                sleep(0.4)

        except Exception as e:
            print(f"Error {symbol}: {e}")
            continue

    if not signals:
        print("Tidak ada signal saat ini")
        return

    message = f"🚨 *SIGNAL 1H BINANCE FUTURES* 🚨\n"
    message += f"Waktu: `{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC`\n"
    message += f"Total signal: *{len(signals)}*\n\n"

    for s in signals:
        message += f"*{s['side']}* `{s['symbol']}`\n"
        message += f"Entry: `{s['entry']}`\n"
        message += f"SL: `{s['sl']}` | TP: `{s['tp']}`\n"
        message += f"ADX: `{s['adx']}` | RSI: `{s['rsi']}`\n"
        message += f"_{s['reason']}_\n"
        message += "----------------\n"

    message += "\n⚠️ Risk kecil | RR 1:2\n"
    message += "_Educational only_"

    send_telegram(message)
    print(f"Berhasil kirim {len(signals)} signal")

if __name__ == "__main__":
    main()
