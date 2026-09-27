import os
import json
import math
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

MONITOR_TF = "5m"        # bar OKX untuk cek TP/SL
MONITOR_TF_MINUTES = 5   # durasi 1 candle MONITOR_TF, dalam menit
MONITOR_MAX_CANDLES = 300  # batas maksimum candle per request ke OKX

BASE_URL = "https://www.okx.com"
HISTORY_FILE = "signals_history.json"


def fmt_price(x, sig_figs=5):
    """
    Format harga dengan ~sig_figs angka penting, TANPA notasi ilmiah,
    supaya harga koin kecil (mis. 0.0000281234) tetap kelihatan presisinya
    dan tidak kebulat jadi sama dengan angka lain yang berdekatan.
    """
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)

    if x == 0:
        return "0"

    exponent = math.floor(math.log10(abs(x)))
    decimals = max(0, sig_figs - exponent - 1)
    decimals = min(decimals, 12)

    s = f"{x:.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


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
        resp = requests.post(url, json=payload, timeout=10)
        print(f"Telegram status: {resp.status_code}")
        if resp.status_code != 200:
            # Cetak isi respons asli dari Telegram supaya penyebabnya kelihatan
            # (mis. "chat not found", "not enough rights to send messages", dll)
            print("Telegram response:", resp.text[:500])
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


def get_klines(inst_id, bar="1H", limit=100, before=None, after=None, min_rows=5):
    """
    before: timestamp ms. Kalau diisi, OKX hanya balikin candle yang lebih
    baru dari timestamp ini.
    after: timestamp ms. Kalau diisi, OKX hanya balikin candle yang lebih
    lama dari timestamp ini (dipakai untuk pagination mundur, ambil batch
    yang lebih tua dari batch sebelumnya).
    min_rows: jumlah baris minimum supaya dianggap valid (dibuat kecil untuk
    monitoring TP/SL, karena sinyal yang baru dibuka wajar cuma punya
    sedikit candle).
    """
    url = f"{BASE_URL}/api/v5/market/candles"
    params = {
        "instId": inst_id,
        "bar": bar,
        "limit": limit
    }
    if before is not None:
        params["before"] = str(before)
    if after is not None:
        params["after"] = str(after)
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if data.get("code") != "0":
            return None

        klines = data.get("data", [])
        if not klines or len(klines) < min_rows:
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


def get_klines_since(inst_id, bar, since_ms, page_limit=300, max_pages=10):
    """
    Ambil SEMUA candle sejak since_ms (ms) sampai candle terbaru,
    walaupun jumlahnya lebih dari 300 (limit maksimum 1x request OKX).

    Caranya: ambil batch candle terbaru dulu, lalu kalau candle paling
    lama di batch itu masih lebih baru dari since_ms (artinya rentang
    waktunya lebih dari 1 batch), minta batch berikutnya yang lebih tua
    pakai parameter 'after', lalu digabung terus sampai:
    - sudah mencapai/melewati since_ms, atau
    - sudah tidak ada data lagi, atau
    - sudah mencapai batas max_pages (jaga-jaga supaya tidak infinite loop
      kalau sinyalnya sangat lama sekali terbuka).
    """
    all_chunks = []
    after_ts = None

    for _ in range(max_pages):
        chunk = get_klines(inst_id, bar=bar, limit=page_limit, after=after_ts, min_rows=1)
        if chunk is None or len(chunk) == 0:
            break

        all_chunks.append(chunk)
        earliest_ts = int(chunk["time"].min())

        if earliest_ts <= since_ms:
            break  # sudah mencakup sampai waktu posisi dibuka

        after_ts = earliest_ts - 1  # lanjut ambil batch yang lebih tua lagi

        if len(chunk) < page_limit:
            break  # data historisnya memang sudah habis

    if not all_chunks:
        return None

    combined = pd.concat(all_chunks).drop_duplicates(subset="time")
    combined = combined[combined["time"] > since_ms].sort_values("time")

    if len(combined) == 0:
        return None

    return combined.reset_index(drop=True)


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
        "entry": close,
        "sl": sl,
        "tp": tp,
        "adx": round(adx, 1),
        "rsi": round(rsi, 1),
        "reason": reason
    }


# ==================== CEK TP/SL REALTIME (TF5, sejak posisi dibuka, wick termasuk) ====================

def check_open_signals():
    history = load_history()
    open_signals = [s for s in history if s["status"] == "open"]

    if not open_signals:
        return history

    closed_messages = []

    for sig in open_signals:
        symbol = sig["symbol"]

        # Hitung timestamp (ms) saat posisi dibuka, lalu minta candle
        # yang lebih baru dari waktu itu saja (bukan N candle terakhir).
        try:
            opened_dt = datetime.strptime(
                sig["opened_time"], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)
            opened_ms = int(opened_dt.timestamp() * 1000)
        except Exception:
            opened_ms = None

        df = get_klines_since(
            symbol,
            bar=MONITOR_TF,
            since_ms=opened_ms if opened_ms is not None else 0,
            page_limit=MONITOR_MAX_CANDLES,
        )
        if df is None or len(df) == 0:
            continue

        hit = None
        hit_price = None

        # df dari get_klines_since sudah terurut dari candle paling lama
        # ke paling baru sejak posisi dibuka.
        for _, candle in df.iterrows():
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
                f"Entry `{fmt_price(sig['entry'])}` -> `{fmt_price(hit_price)}` | R: `{sig['r_result']}`"
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


# ==================== LAPORAN SINYAL YANG MASIH OPEN ====================

def send_open_signals_report(history):
    """Kirim status semua sinyal yang masih 'open' setiap kali scan jalan,
    lengkap dengan harga sekarang dan floating R (belum realized)."""
    open_signals = [s for s in history if s["status"] == "open"]

    if not open_signals:
        print("Tidak ada sinyal open saat ini")
        return

    lines = []
    for sig in open_signals:
        symbol = sig["symbol"]
        entry = sig["entry"]
        sl = sig["sl"]
        tp = sig["tp"]

        # Ambil harga close candle MONITOR_TF paling baru sebagai harga acuan
        df = get_klines(symbol, bar=MONITOR_TF, limit=1, min_rows=1)
        if df is None or len(df) == 0:
            lines.append(f"⏳ `{symbol}` ({sig['side']}) | Entry `{fmt_price(entry)}` | harga sekarang: gagal diambil")
            continue

        current_price = float(df.iloc[-1]["close"])
        risk = abs(entry - sl)

        if risk == 0:
            floating_r = 0.0
        elif sig["side"] == "LONG":
            floating_r = (current_price - entry) / risk
        else:
            floating_r = (entry - current_price) / risk

        arrow = "🟢" if floating_r >= 0 else "🔴"
        lines.append(
            f"{arrow} `{symbol}` ({sig['side']}) | Entry `{fmt_price(entry)}` -> Now `{fmt_price(current_price)}` | "
            f"SL `{fmt_price(sl)}` TP `{fmt_price(tp)}` | Floating: `{round(floating_r, 2)}R`"
        )

    msg = "🕒 *SINYAL MASIH OPEN*\n\n" + "\n".join(lines)
    send_telegram(msg)
    print(msg)


# ==================== MAIN ====================

def main():
    print(f"Mulai scan OKX | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # 1. Cek signal lama yang masih 'open', lihat apakah sudah kena TP/SL
    #    dengan mengecek wick candle TF5 sejak posisi itu dibuka (opened_time)
    history = check_open_signals()

    # 2. Kirim status semua sinyal yang masih open (floating, belum closed)
    send_open_signals_report(history)

    # 3. Kirim laporan winrate & total R dari semua signal yang sudah closed
    send_stats_report(history)

    # 4. Scan pair & cari signal baru (skip pair yang masih punya sinyal open)
    pairs = get_top_pairs()
    print(f"Total pair di-scan: {len(pairs)}")

    if not pairs:
        print("Tidak ada pair yang bisa di-scan")
        return

    # Pair yang sudah punya sinyal berstatus 'open' tidak akan dibuka lagi
    # sampai sinyal lamanya closed (kena TP/SL) dulu.
    already_open_symbols = {s["symbol"] for s in history if s["status"] == "open"}

    new_signals = []

    for i, symbol in enumerate(pairs):
        try:
            if symbol in already_open_symbols:
                continue

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
                already_open_symbols.add(symbol)
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
        message += f"Entry: `{fmt_price(s['entry'])}`\n"
        message += f"SL: `{fmt_price(s['sl'])}` | TP: `{fmt_price(s['tp'])}`\n"
        message += f"ADX: `{s['adx']}` | RSI: `{s['rsi']}`\n"
        message += f"_{s['reason']}_\n"
        message += "----------------\n"

    message += "\n_Educational only_"

    send_telegram(message)
    print(f"Berhasil kirim {len(new_signals)} signal")


if __name__ == "__main__":
    main()


