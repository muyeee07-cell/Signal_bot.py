import os
import json
import math
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone
# ============================================================
# OKX TELEGRAM SIGNAL ENGINE V2
# Closed-Candle | Wilder Indicators | Regime | Volume
# Structure | Cooldown | RR 1:2 | Signal Only
# ============================================================
# =========================
# CONFIG
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BASE_URL = "https://www.okx.com"
TIMEFRAME = "1H"
MONITOR_TF = "5m"
LIMIT = 150
TOP_PAIRS = 30
MIN_VOLUME_USDT = 3_000_000
# Risk / Reward
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.6
RR = 2.0
# Indicators
EMA_FAST = 21
EMA_SLOW = 55
RSI_PERIOD = 14
ADX_PERIOD = 14
# Filters
MIN_ADX_TREND = 23
MIN_VOLUME_RATIO = 1.15
# Signal quality
MIN_SCORE = 4
# Cooldown
COOLDOWN_HOURS = 3
# Monitoring
MONITOR_LIMIT = 300
MONITOR_POLL_MINUTES = 5
# History
HISTORY_FILE = "signals_history.json"
# ============================================================
# UTILITIES
# ============================================================
def utc_now():
    return datetime.now(timezone.utc)
def utc_string(dt=None):
    if dt is None:
        dt = utc_now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")
def fmt_price(x, sig_figs=6):
    """
    Format harga tanpa scientific notation.
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
    result = f"{x:.{decimals}f}"
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result
# ============================================================
# TELEGRAM
# ============================================================
def split_message(text, max_len=3800):
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    return chunks
def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("TELEGRAM_TOKEN / CHAT_ID belum tersedia.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chunk in split_message(text):
        payload = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=15
            )
            print(
                f"Telegram: {response.status_code}"
            )
            if response.status_code != 200:
                print(response.text[:500])
        except Exception as e:
            print("Telegram error:", e)
        time.sleep(0.3)
# ============================================================
# HISTORY
# ============================================================
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print("History load error:", e)
        return []
def save_history(history):
    try:
        temp_file = HISTORY_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(
                history,
                f,
                indent=2
            )
        os.replace(
            temp_file,
            HISTORY_FILE
        )
    except Exception as e:
        print("History save error:", e)
# ============================================================
# OKX DATA
# ============================================================
def get_top_pairs(limit=TOP_PAIRS):
    url = f"{BASE_URL}/api/v5/market/tickers"
    params = {
        "instType": "SWAP"
    }
    try:
        response = requests.get(
            url,
            params=params,
            timeout=15
        )
        data = response.json()
        if data.get("code") != "0":
            print("OKX:", data.get("msg"))
            return []
        pairs = []
        for item in data.get("data", []):
            symbol = item.get("instId", "")
            if not symbol.endswith("-USDT-SWAP"):
                continue
            try:
                volume = float(
                    item.get("volCcy24h", 0)
                )
            except Exception:
                continue
            if volume >= MIN_VOLUME_USDT:
                pairs.append(
                    (symbol, volume)
                )
        pairs.sort(
            key=lambda x: x[1],
            reverse=True
        )
        return [
            symbol
            for symbol, _ in pairs[:limit]
        ]
    except Exception as e:
        print("get_top_pairs:", e)
        return []
def get_klines(
    inst_id,
    bar="1H",
    limit=150,
    after=None,
    before=None
):
    url = f"{BASE_URL}/api/v5/market/candles"
    params = {
        "instId": inst_id,
        "bar": bar,
        "limit": min(limit, 300)
    }
    if after is not None:
        params["after"] = str(after)
    if before is not None:
        params["before"] = str(before)
    try:
        response = requests.get(
            url,
            params=params,
            timeout=15
        )
        data = response.json()
        if data.get("code") != "0":
            return None
        rows = data.get("data", [])
        if not rows:
            return None
        df = pd.DataFrame(
            rows,
            columns=[
                "time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "volCcy",
                "volCcyQuote",
                "confirm"
            ]
        )
        numeric_columns = [
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "volCcy",
            "volCcyQuote"
        ]
        for col in numeric_columns:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )
        df["confirm"] = df["confirm"].astype(str)
        df = df.dropna(
            subset=[
                "time",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )
        # OKX newest -> oldest
        df = df.sort_values(
            "time"
        ).reset_index(drop=True)
        return df
    except Exception as e:
        print(
            f"Kline error {inst_id}:",
            e
        )
        return None
# ============================================================
# CLOSED CANDLE
# ============================================================
def get_closed_klines(
    inst_id,
    bar="1H",
    limit=150
):
    df = get_klines(
        inst_id,
        bar,
        limit
    )
    if df is None:
        return None
    # confirm == 1 = candle selesai
    df = df[
        df["confirm"] == "1"
    ].copy()
    if len(df) < 60:
        return None
    return df.reset_index(drop=True)
# ============================================================
# WILDER RMA
# ============================================================
def wilder_rma(series, period):
    return series.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()
# ============================================================
# INDICATORS
# ============================================================
def calculate_indicators(df):
    df = df.copy()
    # -------------------------
    # EMA
    # -------------------------
    df["ema_fast"] = (
        df["close"]
        .ewm(
            span=EMA_FAST,
            adjust=False
        )
        .mean()
    )
    df["ema_slow"] = (
        df["close"]
        .ewm(
            span=EMA_SLOW,
            adjust=False
        )
        .mean()
    )
    # -------------------------
    # TRUE RANGE
    # -------------------------
    previous_close = df["close"].shift(1)
    tr1 = (
        df["high"] -
        df["low"]
    )
    tr2 = (
        df["high"] -
        previous_close
    ).abs()
    tr3 = (
        df["low"] -
        previous_close
    ).abs()
    tr = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)
    df["tr"] = tr
    # -------------------------
    # ATR - WILDER
    # -------------------------
    df["atr"] = wilder_rma(
        tr,
        ATR_PERIOD
    )
    # -------------------------
    # DIRECTIONAL MOVEMENT
    # -------------------------
    up_move = (
        df["high"]
        .diff()
    )
    down_move = (
        -df["low"]
        .diff()
    )
    plus_dm = pd.Series(
        np.where(
            (up_move > down_move) &
            (up_move > 0),
            up_move,
            0
        ),
        index=df.index
    )
    minus_dm = pd.Series(
        np.where(
            (down_move > up_move) &
            (down_move > 0),
            down_move,
            0
        ),
        index=df.index
    )
    atr_rma = wilder_rma(
        tr,
        ADX_PERIOD
    )
    plus_dm_rma = wilder_rma(
        plus_dm,
        ADX_PERIOD
    )
    minus_dm_rma = wilder_rma(
        minus_dm,
        ADX_PERIOD
    )
    df["plus_di"] = (
        100 *
        plus_dm_rma /
        (atr_rma + 1e-12)
    )
    df["minus_di"] = (
        100 *
        minus_dm_rma /
        (atr_rma + 1e-12)
    )
    dx = (
        100 *
        (
            (
                df["plus_di"] -
                df["minus_di"]
            ).abs()
        )
        /
        (
            df["plus_di"] +
            df["minus_di"] +
            1e-12
        )
    )
    df["adx"] = wilder_rma(
        dx,
        ADX_PERIOD
    )
    # -------------------------
    # RSI - WILDER
    # -------------------------
    delta = df["close"].diff()
    gain = delta.clip(
        lower=0
    )
    loss = -delta.clip(
        upper=0
    )
    avg_gain = wilder_rma(
        gain,
        RSI_PERIOD
    )
    avg_loss = wilder_rma(
        loss,
        RSI_PERIOD
    )
    rs = (
        avg_gain /
        (avg_loss + 1e-12)
    )
    df["rsi"] = (
        100 -
        (
            100 /
            (1 + rs)
        )
    )
    # -------------------------
    # VOLUME
    # -------------------------
    df["volume_ma20"] = (
        df["volume"]
        .rolling(20)
        .mean()
    )
    df["volume_ratio"] = (
        df["volume"] /
        (df["volume_ma20"] + 1e-12)
    )
    # -------------------------
    # ATR %
    # -------------------------
    df["atr_pct"] = (
        df["atr"] /
        df["close"] *
        100
    )
    # -------------------------
    # STRUCTURE
    # -------------------------
    df["previous_high"] = (
        df["high"]
        .shift(1)
        .rolling(5)
        .max()
    )
    df["previous_low"] = (
        df["low"]
        .shift(1)
        .rolling(5)
        .min()
    )
    return df.dropna().reset_index(
        drop=True
    )
# ============================================================
# SIGNAL ENGINE
# ============================================================
def check_signal(df, symbol):
    if len(df) < 80:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(last["close"])
    atr = float(last["atr"])
    rsi = float(last["rsi"])
    adx = float(last["adx"])
    ema_fast = float(last["ema_fast"])
    ema_slow = float(last["ema_slow"])
    volume_ratio = float(
        last["volume_ratio"]
    )
    plus_di = float(
        last["plus_di"]
    )
    minus_di = float(
        last["minus_di"]
    )
    score_long = 0
    score_short = 0
    reasons_long = []
    reasons_short = []
    # ========================================================
    # LONG TREND
    # ========================================================
    if ema_fast > ema_slow:
        score_long += 1
        reasons_long.append(
            "EMA trend bullish"
        )
    if close > ema_fast:
        score_long += 1
        reasons_long.append(
            "Price above EMA21"
        )
    if adx >= MIN_ADX_TREND:
        if plus_di > minus_di:
            score_long += 1
            reasons_long.append(
                "ADX directional bullish"
            )
    if 52 <= rsi <= 68:
        score_long += 1
        reasons_long.append(
            "RSI bullish zone"
        )
    if volume_ratio >= MIN_VOLUME_RATIO:
        score_long += 1
        reasons_long.append(
            "Volume confirmation"
        )
    # ========================================================
    # SHORT TREND
    # ========================================================
    if ema_fast < ema_slow:
        score_short += 1
        reasons_short.append(
            "EMA trend bearish"
        )
    if close < ema_fast:
        score_short += 1
        reasons_short.append(
            "Price below EMA21"
        )
    if adx >= MIN_ADX_TREND:
        if minus_di > plus_di:
            score_short += 1
            reasons_short.append(
                "ADX directional bearish"
            )
    if 32 <= rsi <= 48:
        score_short += 1
        reasons_short.append(
            "RSI bearish zone"
        )
    if volume_ratio >= MIN_VOLUME_RATIO:
        score_short += 1
        reasons_short.append(
            "Volume confirmation"
        )
    # ========================================================
    # RANGE / MEAN REVERSION
    # ========================================================
    range_long = False
    range_short = False
    if adx < MIN_ADX_TREND:
        if rsi < 30:
            # Need bullish reversal confirmation
            if close > float(prev["close"]):
                range_long = True
        if rsi > 70:
            # Need bearish reversal confirmation
            if close < float(prev["close"]):
                range_short = True
    # ========================================================
    # SELECT SIGNAL
    # ========================================================
    signal = None
    score = 0
    reason = ""
    if score_long >= MIN_SCORE:
        signal = "LONG"
        score = score_long
        reason = " | ".join(
            reasons_long
        )
    elif score_short >= MIN_SCORE:
        signal = "SHORT"
        score = score_short
        reason = " | ".join(
            reasons_short
        )
    elif range_long:
        signal = "LONG"
        score = 4
        reason = (
            "Range regime | "
            "RSI oversold | "
            "bullish reversal"
        )
    elif range_short:
        signal = "SHORT"
        score = 4
        reason = (
            "Range regime | "
            "RSI overbought | "
            "bearish reversal"
        )
    if signal is None:
        return None
    # ========================================================
    # SL / TP
    # ========================================================
    risk_distance = (
        ATR_MULTIPLIER *
        atr
    )
    if risk_distance <= 0:
        return None
    if signal == "LONG":
        sl = close - risk_distance
        tp = (
            close +
            risk_distance * RR
        )
    else:
        sl = close + risk_distance
        tp = (
            close -
            risk_distance * RR
        )
    # ========================================================
    # RESULT
    # ========================================================
    return {
        "symbol": symbol,
        "side": signal,
        "entry": float(close),
        "sl": float(sl),
        "tp": float(tp),
        "rr": RR,
        "atr": float(atr),
        "adx": round(adx, 2),
        "rsi": round(rsi, 2),
        "volume_ratio": round(
            volume_ratio,
            2
        ),
        "score": score,
        "reason": reason,
        "signal_candle_time": int(
            last["time"]
        )
    }
# ============================================================
# COOLDOWN
# ============================================================
def is_in_cooldown(
    history,
    symbol
):
    now = utc_now()
    for signal in reversed(history):
        if signal.get("symbol") != symbol:
            continue
        if signal.get("status") not in (
            "TP",
            "SL"
        ):
            continue
        closed_time = signal.get(
            "closed_time"
        )
        if not closed_time:
            continue
        try:
            closed_dt = datetime.strptime(
                closed_time,
                "%Y-%m-%d %H:%M:%S"
            ).replace(
                tzinfo=timezone.utc
            )
            elapsed_hours = (
                now - closed_dt
            ).total_seconds() / 3600
            return (
                elapsed_hours <
                COOLDOWN_HOURS
            )
        except Exception:
            return False
    return False
# ============================================================
# MONITORING DATA
# ============================================================
def get_monitor_candles(
    symbol,
    opened_ms
):
    df = get_klines(
        symbol,
        bar=MONITOR_TF,
        limit=MONITOR_LIMIT
    )
    if df is None:
        return None
    # Ambil candle yang:
    # 1. mulai sebelum / sekitar entry
    # 2. atau setelah entry
    #
    # Candle entry tidak dibuang.
    #
    # Ini penting agar pergerakan dalam candle
    # tempat signal muncul tetap bisa diperiksa.
    df = df[
        df["time"] >= (
            opened_ms -
            5 * 60 * 1000
        )
    ].copy()
    if len(df) == 0:
        return None
    return df.sort_values(
        "time"
    ).reset_index(drop=True)
# ============================================================
# CHECK TP / SL
# ============================================================
def check_open_signals():
    history = load_history()
    open_signals = [
        s for s in history
        if s.get("status") == "open"
    ]
    if not open_signals:
        return history
    closed_messages = []
    for sig in open_signals:
        symbol = sig["symbol"]
        try:
            opened_dt = datetime.strptime(
                sig["opened_time"],
                "%Y-%m-%d %H:%M:%S"
            ).replace(
                tzinfo=timezone.utc
            )
            opened_ms = int(
                opened_dt.timestamp()
                * 1000
            )
        except Exception:
            opened_ms = 0
        df = get_monitor_candles(
            symbol,
            opened_ms
        )
        if df is None:
            continue
        hit = None
        hit_price = None
        hit_time = None
        for _, candle in df.iterrows():
            candle_time = int(
                candle["time"]
            )
            high = float(
                candle["high"]
            )
            low = float(
                candle["low"]
            )
            # Jangan menggunakan candle yang
            # selesai sebelum signal dibuat.
            #
            # Candle tempat signal dibuat
            # tetap diperiksa secara konservatif.
            if sig["side"] == "LONG":
                tp_hit = (
                    high >=
                    float(sig["tp"])
                )
                sl_hit = (
                    low <=
                    float(sig["sl"])
                )
            else:
                tp_hit = (
                    low <=
                    float(sig["tp"])
                )
                sl_hit = (
                    high >=
                    float(sig["sl"])
                )
            # =================================================
            # BOTH HIT SAME CANDLE
            # =================================================
            if tp_hit and sl_hit:
                hit = "SL"
                hit_price = float(
                    sig["sl"]
                )
                hit_time = candle_time
                break
            elif tp_hit:
                hit = "TP"
                hit_price = float(
                    sig["tp"]
                )
                hit_time = candle_time
                break
            elif sl_hit:
                hit = "SL"
                hit_price = float(
                    sig["sl"]
                )
                hit_time = candle_time
                break
        if hit is None:
            continue
        sig["status"] = hit
        sig["closed_time"] = utc_string()
        sig["hit_time"] = (
            datetime.fromtimestamp(
                hit_time / 1000,
                timezone.utc
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if hit_time
            else None
        )
        sig["hit_price"] = hit_price
        sig["r_result"] = (
            RR
            if hit == "TP"
            else -1.0
        )
        if hit == "TP":
            closed_messages.append(
                "🟢 *TP HIT*\n"
                f"`{symbol}` · {sig['side']}\n"
                f"Entry: `{fmt_price(sig['entry'])}`\n"
                f"TP: `{fmt_price(sig['tp'])}`\n"
                f"Result: `+{RR:.1f}R`"
            )
        else:
            closed_messages.append(
                "🔴 *SL HIT*\n"
                f"`{symbol}` · {sig['side']}\n"
                f"Entry: `{fmt_price(sig['entry'])}`\n"
                f"SL: `{fmt_price(sig['sl'])}`\n"
                f"Result: `-1.0R`"
            )
    save_history(history)
    if closed_messages:
        send_telegram(
            "📊 *TRADE UPDATE*\n\n"
            +
            "\n\n".join(
                closed_messages
            )
        )
    return history
# ============================================================
# CURRENT PRICE
# ============================================================
def get_current_price(symbol):
    df = get_klines(
        symbol,
        bar=MONITOR_TF,
        limit=2
    )
    if df is None or len(df) == 0:
        return None
    return float(
        df.iloc[-1]["close"]
    )
# ============================================================
# RUNNING POSITION
# ============================================================
def build_running_position(
    sig,
    current_price
):
    entry = float(
        sig["entry"]
    )
    sl = float(
        sig["sl"]
    )
    tp = float(
        sig["tp"]
    )
    risk = abs(
        entry - sl
    )
    if risk <= 0:
        floating_r = 0
    elif sig["side"] == "LONG":
        floating_r = (
            current_price -
            entry
        ) / risk
    else:
        floating_r = (
            entry -
            current_price
        ) / risk
    if sig["side"] == "LONG":
        distance_to_sl = (
            current_price - sl
        )
        distance_to_tp = (
            tp - current_price
        )
    else:
        distance_to_sl = (
            sl - current_price
        )
        distance_to_tp = (
            current_price - tp
        )
    if distance_to_tp > 0:
        tp_distance_pct = (
            distance_to_tp /
            current_price *
            100
        )
    else:
        tp_distance_pct = 0
    if distance_to_sl > 0:
        sl_distance_pct = (
            distance_to_sl /
            current_price *
            100
        )
    else:
        sl_distance_pct = 0
    return {
        "floating_r": floating_r,
        "tp_distance_pct": tp_distance_pct,
        "sl_distance_pct": sl_distance_pct
    }
def send_open_signals_report(
    history
):
    open_signals = [
        s for s in history
        if s.get("status") == "open"
    ]
    if not open_signals:
        return
    lines = []
    for sig in open_signals:
        symbol = sig["symbol"]
        price = get_current_price(
            symbol
        )
        if price is None:
            lines.append(
                f"⏳ `{symbol}` · "
                f"{sig['side']} · "
                f"harga tidak tersedia"
            )
            continue
        position = build_running_position(
            sig,
            price
        )
        floating_r = position[
            "floating_r"
        ]
        if floating_r >= 0:
            state = "🟢"
        else:
            state = "🔴"
        lines.append(
            f"{state} *{symbol}* · "
            f"`{sig['side']}`\n"
            f"Entry `{fmt_price(sig['entry'])}`"
            f" → Now `{fmt_price(price)}`\n"
            f"SL `{fmt_price(sig['sl'])}`"
            f" · TP `{fmt_price(sig['tp'])}`\n"
            f"Floating `{floating_r:+.2f}R`"
        )
    message = (
        "📡 *RUNNING POSITIONS*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        +
        "\n\n".join(lines)
    )
    send_telegram(
        message
    )
# ============================================================
# STATISTICS
# ============================================================
def compute_stats(history):
    closed = [
        s for s in history
        if s.get("status")
        in ("TP", "SL")
    ]
    if not closed:
        return None
    wins = [
        s for s in closed
        if s["status"] == "TP"
    ]
    losses = [
        s for s in closed
        if s["status"] == "SL"
    ]
    total = len(closed)
    win_rate = (
        len(wins) /
        total *
        100
    )
    total_r = sum(
        float(
            s.get(
                "r_result",
                0
            )
        )
        for s in closed
    )
    gross_profit = sum(
        float(
            s.get(
                "r_result",
                0
            )
        )
        for s in wins
    )
    gross_loss = abs(
        sum(
            float(
                s.get(
                    "r_result",
                    0
                )
            )
            for s in losses
        )
    )
    profit_factor = (
        gross_profit /
        gross_loss
        if gross_loss > 0
        else float("inf")
    )
    avg_r = (
        total_r /
        total
    )
    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_r": total_r,
        "avg_r": avg_r,
        "profit_factor":
            profit_factor
    }
def send_stats_report(history):
    stats = compute_stats(
        history
    )
    if not stats:
        return
    pf = stats[
        "profit_factor"
    ]
    pf_text = (
        "∞"
        if math.isinf(pf)
        else f"{pf:.2f}"
    )
    message = (
        "📊 *SYSTEM PERFORMANCE*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Trades: `{stats['total']}`\n"
        f"Wins: `{stats['wins']}`\n"
        f"Losses: `{stats['losses']}`\n"
        f"WR: `{stats['win_rate']:.1f}%`\n"
        f"Total: `{stats['total_r']:+.2f}R`\n"
        f"Avg: `{stats['avg_r']:+.2f}R`\n"
        f"Profit Factor: `{pf_text}`"
    )
    send_telegram(
        message
    )
# ============================================================
# SIGNAL NOTIFICATION
# ============================================================
def send_new_signals(
    signals
):
    if not signals:
        return
    blocks = []
    for sig in signals:
        side_emoji = (
            "🟢"
            if sig["side"] == "LONG"
            else "🔴"
        )
        blocks.append(
            f"{side_emoji} *{sig['side']} "
            f"{sig['symbol']}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Entry  `{fmt_price(sig['entry'])}`\n"
            f"SL     `{fmt_price(sig['sl'])}`\n"
            f"TP     `{fmt_price(sig['tp'])}`\n"
            f"RR     `1:{RR:.0f}`\n"
            f"Score  `{sig['score']}/5`\n"
            f"ADX    `{sig['adx']}`\n"
            f"RSI    `{sig['rsi']}`\n"
            f"Volume `{sig['volume_ratio']}x`\n"
            f"Reason: {sig['reason']}"
        )
    message = (
        "🚨 *NEW SIGNALS · OKX 1H*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Generated: `{utc_string()} UTC`\n\n"
        +
        "\n\n".join(blocks)
        +
        "\n\n_Educational only · Signal only_"
    )
    send_telegram(
        message
    )
# ============================================================
# MAIN SCANNER
# ============================================================
def scan_new_signals(
    history
):
    pairs = get_top_pairs()
    if not pairs:
        print(
            "Tidak ada pair."
        )
        return history
    already_open = {
        s["symbol"]
        for s in history
        if s.get("status") == "open"
    }
    new_signals = []
    print(
        f"Scanning {len(pairs)} pairs..."
    )
    for index, symbol in enumerate(
        pairs
    ):
        try:
            # --------------------------------
            # Existing open position
            # --------------------------------
            if symbol in already_open:
                continue
            # --------------------------------
            # Cooldown
            # --------------------------------
            if is_in_cooldown(
                history,
                symbol
            ):
                print(
                    f"{symbol}: cooldown"
                )
                continue
            # --------------------------------
            # Closed H1 candles
            # --------------------------------
            df = get_closed_klines(
                symbol,
                TIMEFRAME,
                LIMIT
            )
            if df is None:
                continue
            # --------------------------------
            # Indicators
            # --------------------------------
            df = calculate_indicators(
                df
            )
            if len(df) < 80:
                continue
            # --------------------------------
            # Signal
            # --------------------------------
            signal = check_signal(
                df,
                symbol
            )
            if signal is None:
                continue
            # --------------------------------
            # Create record
            # --------------------------------
            signal["status"] = "open"
            signal["opened_time"] = (
                utc_string()
            )
            signal["closed_time"] = None
            signal["r_result"] = None
            signal["hit_price"] = None
            signal["hit_time"] = None
            history.append(
                signal
            )
            new_signals.append(
                signal
            )
            already_open.add(
                symbol
            )
            print(
                f"NEW: "
                f"{symbol} "
                f"{signal['side']} "
                f"score={signal['score']}"
            )
            # --------------------------------
            # Small delay
            # --------------------------------
            if index % 5 == 0:
                time.sleep(0.4)
        except Exception as e:
            print(
                f"{symbol}: {e}"
            )
    if new_signals:
        save_history(
            history
        )
        send_new_signals(
            new_signals
        )
    else:
        print(
            "Tidak ada signal baru."
        )
    return history
# ============================================================
# MAIN
# ============================================================
def main():
    print(
        "===================================="
    )
    print(
        "OKX SIGNAL ENGINE V2"
    )
    print(
        utc_string(),
        "UTC"
    )
    print(
        "===================================="
    )
    # ========================================================
    # 1. UPDATE POSITIONS
    # ========================================================
    history = check_open_signals()
    # ========================================================
    # 2. RUNNING POSITIONS
    # ========================================================
    send_open_signals_report(
        history
    )
    # ========================================================
    # 3. PERFORMANCE
    # ========================================================
    send_stats_report(
        history
    )
    # ========================================================
    # 4. SCAN NEW SIGNALS
    # ========================================================
    history = scan_new_signals(
        history
    )
    print(
        "Scan selesai."
    )
if __name__ == "__main__":
    main()



