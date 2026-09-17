import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from time import sleep

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

TIMEFRAME = "60"
LIMIT = 100
TOP_PAIRS = 30
MIN_VOLUME_USDT = 3_000_000
ATR_MULTIPLIER = 1.6
RR = 2.0

BASE_URL = "https://api.bybit.com"

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
    url = f"{BASE_URL}/v5/market/tickers"
    params = {"category": "linear"}
    
    try:
        response = requests.get(url, params=params, timeout=15)
        
        # Cek status code
        print(f"Status Code: {response.status_code}")
        
        # Coba parse JSON
        try:
            data = response.json()
        except Exception as e:
            print("Gagal parse JSON. Isi response:")
            print(response.text[:500])
            return []

        if data.get("retCode") != 0:
            print("Bybit retMsg:", data.get("retMsg"))
            return []

        tickers = data.get("result", {}).get("list", [])
        if not tickers:
            print("Tidak ada data ticker")
            return []

        usdt = []
        for item in tickers:
            symbol = item.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            try:
                volume = float(item.get("turnover24h", 0))
                if volume >= MIN_VOLUME_USDT:
                    usdt.append((symbol, volume))
            except:
                continue

        usdt.sort(key=lambda x: x[1], reverse=True)
        pairs = [x[0] for x in usdt[:limit]]
        print(f"Berhasil dapat {len(pairs)} pair")
        return pairs

    except Exception as e:
        print("Error get_top_pairs:", str(e))
        return []

def get_klines(symbol, interval="60", limit=100):
    url = f"{BASE_URL}/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if data.get("retCode") != 0:
            return None

        klines = data.get("result", {}).get("list", [])
        if not klines or len(klines) < 50:
            return None

        klines = list(reversed(klines))

        df = pd.DataFrame(klines, columns=[
            "time", "open", "high", "low", "close", "volume", "turnover"
        ])
        df["open"] = pd.to_numeric(df["open"], errors="coerce")
        df["high"] = pd.to_numeric(df["high"], errors="coerce")
        df["low"] = pd.to_numeric(df["low"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        return df.dropna()
    except:
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

    if adx > 23:
        if (prev["ema_fast"] > prev["ema_slow"] and last["close"] > last["ema_fast"] and 52 < rsi < 68):
            signal = "LONG"
            reason = "Trend Following"
        elif (prev["ema_fast"] < prev["ema_slow"] and last["close"] < last["ema_fast"] and 32 < rsi < 48):
            signal = "SHORT"
            reason = "Trend Following"
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
    print(f"Mulai scan Bybit | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    pairs = get_top_pairs()
    print(f"Total pair di-scan: {len(pairs)}")

    if not pairs:
        print("Tidak ada pair yang bisa di-scan")
        return

    signals = []

    for i, symbol in enumerate(pairs):
        try:
            df = get_klines(symbol)
            if df is None or len(df) < 60:
                continue

            df = calculate_indicators(df)
            sig = check_signal(df, symbol)

            if sig:
                signals.append(sig)
                print(f"Signal: {symbol} {sig['side']}")

            if i % 7 == 0:
                sleep(0.35)

        except Exception as e:
            print(f"Error {symbol}: {e}")
            continue

    if not signals:
        print("Tidak ada signal saat ini")
        return

    message = f"🚨 *SIGNAL 1H BYBIT* 🚨\n"
    message += f"Waktu: `{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC`\n"
    message += f"Total: *{len(signals)}*\n\n"

    for s in signals:
        message += f"*{s['side']}* `{s['symbol']}`\n"
        message += f"Entry: `{s['entry']}`\n"
        message += f"SL: `{s['sl']}` | TP: `{s['tp']}`\n"
        message += f"ADX: `{s['adx']}` | RSI: `{s['rsi']}`\n"
        message += f"_{s['reason']}_\n"
        message += "----------------\n"

    message += "\n_Educational only_"

    send_telegram(message)
    print(f"Berhasil kirim {len(signals)} signal")

if __name__ == "__main__":
    main()
