import os
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from time import sleep

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

TIMEFRAME = "1H"        # bar OKX untuk sinyal utama (setara TF60 di Bybit)
LIMIT = 100
TOP_PAIRS = 30
MIN_VOLUME_USDT = 3_000_000
ATR_MULTIPLIER = 1.6
RR = 2.0

MONITOR_TF = "15m"       # bar OKX untuk cek TP/SL
MONITOR_CANDLES = 10     # jumlah candle terakhir yang dicek (termasuk wick)

BASE_URL = "https://www.okx.com"
HISTORY_FILE = "signals_history.json"


# ==================== TELEGRAM ====================

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


# ==================== HISTORY SIGNAL (persist ke file) ====================

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print("Gagal simpan history:", e)


# ==================== DATA OKX ====================

def get_top_pairs(limit=TOP_PAIRS):
    """Ambil pair USDT-SWAP (perpetual) dengan volume 24h tertinggi dari OKX."""
    url = f"{BASE_URL}/api/v5/market/tickers"
    params = {"instType": "SWAP"}

    try:
        response = requests.get(url, params=params, timeout=15)
        print(f"Status Code: {response.status_code}")

        try:
            data = response.json()
        except Exception:
            print("Gagal parse JSON. Isi response:")
            print(response.text[:500])
            return []

        if data.get("code") != "0":
            print("OKX msg:", data.get("msg"))
            return []

        tickers = data.get("data", [])
        if not tickers:
            print("Tidak ada data ticker")
            return []

        usdt = []
        for item in tickers:
            inst_id = item.get("instId", "")
            if not inst_id.endswith("-USDT-SWAP"):
                continue
            try:
                # volCcy24h = volume 24h dalam mata uang quote (USDT)
                volume = float(item.get("volCcy24h", 0))
                if volume >= MIN_VOLUME_USDT:
                    usdt.append((inst_id, volume))
            except Exception:
                continue

        usdt.sort(key=lambda x: x[1], reverse=True)
        pairs = [x[0] for x in usdt[:limit]]
        print(f"Berhasil dapat {len(pairs)} pair")
        return pairs

    except Exception as e:
        print("Error get_top_pairs:", str(e))
        return []


def get_klines(inst_id, bar="1H", limit=100):
    url = f"{BASE_URL}/api/v5/market/candles"
    params = {
        "instId": inst_id,
        "bar": bar,
        "limit": limit
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if data.get("code") != "0":
            return None

        klines = data.get("data", [])
        if not klines or len(klines) < 5:
            return None

        # OKX mengembalikan data dari yang terbaru ke terlama -> balik urutannya
        klines = list(reversed(klines))

        df = pd.DataFrame(klines, columns=[
            "time", "open", "high", "low", "close",
            "volume", "volCcy", "volCcyQuote", "confirm"
        ])
        df["time"] = pd.to_numeric(df["time"], errors="coerce")
        df["open"] = pd.to_numeric(df["open"], errors="coerce")
        df["high"] = pd.to_numeric(df["high"], errors="coerce")
        df["low"] = pd.to_numeric(df["low"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        return df.dropna()
    except Exception:
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


# ==================== CEK TP/SL REALTIME (TF15, 10 candle terakhir, wick termasuk) ====================

def check_open_signals():
    history = load_history()
    open_signals = [s for s in history if s["status"] == "open"]

    if not open_signals:
        return history

    closed_messages = []

    for sig in open_signals:
        symbol = sig["symbol"]
        df = get_klines(symbol, bar=MONITOR_TF, limit=MONITOR_CANDLES + 5)
        if df is None or len(df) == 0:
            continue

        recent = df.tail(MONITOR_CANDLES)

        hit = None
        hit_price = None

        for _, candle in recent.iterrows():
            high = float(candle["high"])
            low = float(candle["low"])

            if sig["side"] == "LONG":
                tp_touched = high >= sig["tp"]
                sl_touched = low <= sig["sl"]
            else:
                tp_touched = low <= sig["tp"]
                sl_touched = high >= sig["sl"]

            if tp_touched and sl_touched:
                # TP dan SL sama-sama kena wick-nya di candle yang sama.
                # Dari data OHLC saja urutan pastinya tidak bisa dipastikan,
                # jadi diasumsikan konservatif: SL duluan.
                hit, hit_price = "SL", sig["sl"]
                break
            elif tp_touched:
                hit, hit_price = "TP", sig["tp"]
                break
            elif sl_touched:
                hit, hit_price = "SL", sig["sl"]
                break

        if hit:
            sig["status"] = hit
            sig["closed_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            sig["r_result"] = RR if hit == "TP" else -1.0

            emoji = "✅" if hit == "TP" else "❌"
            closed_messages.append(
                f"{emoji} *{hit}* `{sig['symbol']}` ({sig['side']}) | "
                f"Entry `{sig['entry']}` -> `{hit_price}` | R: `{sig['r_result']}`"
            )

    if closed_messages:
        msg = "📊 *UPDATE HASIL SIGNAL*\n\n" + "\n".join(closed_messages)
        send_telegram(msg)
        print("\n".join(closed_messages))

    save_history(history)
    return history


# ==================== STATISTIK WINRATE & R ====================

def compute_stats(history):
    closed = [s for s in history if s["status"] in ("TP", "SL")]
    if not closed:
        return None

    wins = [s for s in closed if s["status"] == "TP"]
    losses = [s for s in closed if s["status"] == "SL"]

    total = len(closed)
    win_rate = len(wins) / total * 100
    total_r = sum(s["r_result"] for s in closed)
    avg_r = total_r / total

    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_r": round(total_r, 2),
        "avg_r": round(avg_r, 2),
    }


def send_stats_report(history):
    stats = compute_stats(history)
    if not stats:
        print("Belum ada signal yang closed untuk dihitung statistiknya")
        return

    msg = (
        "📈 *TRADING RESULT SUMMARY*\n\n"
        f"Total Signal Selesai: `{stats['total']}`\n"
        f"Win: `{stats['wins']}` | Loss: `{stats['losses']}`\n"
        f"Winrate: `{stats['win_rate']}%`\n"
        f"Total R: `{stats['total_r']}R`\n"
        f"Rata-rata R/trade: `{stats['avg_r']}R`"
    )
    send_telegram(msg)
    print(msg)


# ==================== MAIN ====================

def main():
    print(f"Mulai scan OKX | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # 1. Cek signal lama yang masih 'open', lihat apakah sudah kena TP/SL
    #    dengan mengecek wick 10 candle terakhir di TF15
    history = check_open_signals()

    # 2. Kirim laporan winrate & total R dari semua signal yang sudah closed
    send_stats_report(history)

    # 3. Scan pair & cari signal baru seperti biasa
    pairs = get_top_pairs()
    print(f"Total pair di-scan: {len(pairs)}")

    if not pairs:
        print("Tidak ada pair yang bisa di-scan")
        return

    new_signals = []

    for i, symbol in enumerate(pairs):
        try:
            df = get_klines(symbol, bar=TIMEFRAME, limit=LIMIT)
            if df is None or len(df) < 60:
                continue

            df = calculate_indicators(df)
            sig = check_signal(df, symbol)

            if sig:
                sig["status"] = "open"
                sig["opened_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                sig["closed_time"] = None
                sig["r_result"] = None
                new_signals.append(sig)
                print(f"Signal: {symbol} {sig['side']}")

            if i % 7 == 0:
                sleep(0.35)

        except Exception as e:
            print(f"Error {symbol}: {e}")
            continue

    if not new_signals:
        print("Tidak ada signal baru saat ini")
        return

    history.extend(new_signals)
    save_history(history)

    message = f"🚨 *SIGNAL 1H OKX* 🚨\n"
    message += f"Waktu: `{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC`\n"
    message += f"Total: *{len(new_signals)}*\n\n"

    for s in new_signals:
        message += f"*{s['side']}* `{s['symbol']}`\n"
        message += f"Entry: `{s['entry']}`\n"
        message += f"SL: `{s['sl']}` | TP: `{s['tp']}`\n"
        message += f"ADX: `{s['adx']}` | RSI: `{s['rsi']}`\n"
        message += f"_{s['reason']}_\n"
        message += "----------------\n"

    message += "\n_Educational only_"

    send_telegram(message)
    print(f"Berhasil kirim {len(new_signals)} signal")


if __name__ == "__main__":
    main()


