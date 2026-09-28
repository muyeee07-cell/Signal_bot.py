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
# ============================================================
# Closed Candle
# Wilder RSI / ATR / ADX
# EMA Trend
# Volume Confirmation
# Structure Filter
# Signal Score
# Cooldown
# RR 1:2
# TP/SL Monitoring 5M
# Running Position Summary
# Performance Statistics
# SIGNAL ONLY — NO LIVE TRADING
# ============================================================
# ============================================================
# CONFIGURATION
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BASE_URL = "https://www.okx.com"
# -------------------------
# MAIN TIMEFRAME
# -------------------------
TIMEFRAME = "1H"
# -------------------------
# MONITOR TIMEFRAME
# -------------------------
MONITOR_TF = "5m"
# -------------------------
# MARKET SCAN
# -------------------------
LIMIT = 150
TOP_PAIRS = 30
MIN_VOLUME_USDT = 3_000_000
# -------------------------
# RISK / REWARD
# -------------------------
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.6
RR = 2.0
# -------------------------
# EMA
# -------------------------
EMA_FAST = 21
EMA_SLOW = 55
# -------------------------
# RSI
# -------------------------
RSI_PERIOD = 14
# -------------------------
# ADX
# -------------------------
ADX_PERIOD = 14
MIN_ADX_TREND = 23
# -------------------------
# VOLUME
# -------------------------
MIN_VOLUME_RATIO = 1.15
# -------------------------
# SIGNAL QUALITY
# -------------------------
MIN_SCORE = 4
# -------------------------
# COOLDOWN
# -------------------------
COOLDOWN_HOURS = 3
# -------------------------
# MONITORING
# -------------------------
MONITOR_LIMIT = 300
# -------------------------
# HISTORY
# -------------------------
HISTORY_FILE = "signals_history.json"
# ============================================================
# TIME UTILITIES
# ============================================================
def utc_now():
    return datetime.now(
        timezone.utc
    )
def utc_string(dt=None):
    if dt is None:
        dt = utc_now()
    return dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
# ============================================================
# PRICE FORMAT
# ============================================================
def fmt_price(
    x,
    sig_figs=6
):
    try:
        x = float(x)
    except (
        TypeError,
        ValueError
    ):
        return str(x)
    if x == 0:
        return "0"
    exponent = math.floor(
        math.log10(
            abs(x)
        )
    )
    decimals = max(
        0,
        sig_figs -
        exponent -
        1
    )
    decimals = min(
        decimals,
        12
    )
    result = f"{x:.{decimals}f}"
    if "." in result:
        result = (
            result
            .rstrip("0")
            .rstrip(".")
        )
    return result
# ============================================================
# TELEGRAM
# ============================================================
def split_message(
    text,
    max_len=3800
):
    chunks = []
    current = ""
    for line in text.split(
        "\n"
    ):
        if (
            len(current)
            + len(line)
            + 1
            > max_len
            and current
        ):
            chunks.append(
                current
            )
            current = ""
        current += (
            line +
            "\n"
        )
    if current.strip():
        chunks.append(
            current
        )
    return chunks
def send_telegram(
    text
):
    if (
        not TELEGRAM_TOKEN
        or not CHAT_ID
    ):
        print(
            "TELEGRAM_TOKEN / CHAT_ID belum tersedia."
        )
        return
    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )
    for chunk in split_message(
        text
    ):
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
                "Telegram:",
                response.status_code
            )
            if response.status_code != 200:
                print(
                    response.text[:500]
                )
        except Exception as e:
            print(
                "Telegram error:",
                e
            )
        time.sleep(
            0.3
        )
# ============================================================
# HISTORY
# ============================================================
def load_history():
    if not os.path.exists(
        HISTORY_FILE
    ):
        return []
    try:
        with open(
            HISTORY_FILE,
            "r"
        ) as f:
            data = json.load(f)
        if isinstance(
            data,
            list
        ):
            return data
        return []
    except Exception as e:
        print(
            "History load error:",
            e
        )
        return []
def save_history(
    history
):
    try:
        temp_file = (
            HISTORY_FILE +
            ".tmp"
        )
        with open(
            temp_file,
            "w"
        ) as f:
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
        print(
            "History save error:",
            e
        )
# ============================================================
# OKX TOP PAIRS
# ============================================================
def get_top_pairs(
    limit=TOP_PAIRS
):
    url = (
        f"{BASE_URL}/api/v5/"
        f"market/tickers"
    )
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
        if data.get(
            "code"
        ) != "0":
            print(
                "OKX:",
                data.get("msg")
            )
            return []
        pairs = []
        for item in data.get(
            "data",
            []
        ):
            symbol = item.get(
                "instId",
                ""
            )
            if not symbol.endswith(
                "-USDT-SWAP"
            ):
                continue
            try:
                volume = float(
                    item.get(
                        "volCcy24h",
                        0
                    )
                )
            except Exception:
                continue
            if (
                volume >=
                MIN_VOLUME_USDT
            ):
                pairs.append(
                    (
                        symbol,
                        volume
                    )
                )
        pairs.sort(
            key=lambda x: x[1],
            reverse=True
        )
        return [
            symbol
            for symbol, _ in
            pairs[:limit]
        ]
    except Exception as e:
        print(
            "get_top_pairs:",
            e
        )
        return []
# ============================================================
# OKX KLINES
# ============================================================
def get_klines(
    inst_id,
    bar="1H",
    limit=150,
    after=None,
    before=None
):
    url = (
        f"{BASE_URL}/api/v5/"
        f"market/candles"
    )
    params = {
        "instId": inst_id,
        "bar": bar,
        "limit": min(
            limit,
            300
        )
    }
    if after is not None:
        params["after"] = str(
            after
        )
    if before is not None:
        params["before"] = str(
            before
        )
    try:
        response = requests.get(
            url,
            params=params,
            timeout=15
        )
        data = response.json()
        if data.get(
            "code"
        ) != "0":
            return None
        rows = data.get(
            "data",
            []
        )
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
        df["confirm"] = (
            df["confirm"]
            .astype(str)
        )
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
        df = df.sort_values(
            "time"
        ).reset_index(
            drop=True
        )
        return df
    except Exception as e:
        print(
            f"Kline error {inst_id}:",
            e
        )
        return None
# ============================================================
# CLOSED CANDLES ONLY
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
    # OKX:
    # confirm = 1
    # berarti candle selesai
    df = df[
        df["confirm"] == "1"
    ].copy()
    if len(df) < 60:
        return None
    return (
        df
        .reset_index(
            drop=True
        )
    )
# ============================================================
# WILDER RMA
# ============================================================
def wilder_rma(
    series,
    period
):
    return series.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()
# ============================================================
# INDICATORS
# ============================================================
def calculate_indicators(
    df
):
    df = df.copy()
    # ========================================================
    # EMA
    # ========================================================
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
    # ========================================================
    # TRUE RANGE
    # ========================================================
    previous_close = (
        df["close"]
        .shift(1)
    )
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
        [
            tr1,
            tr2,
            tr3
        ],
        axis=1
    ).max(
        axis=1
    )
    df["tr"] = tr
    # ========================================================
    # ATR
    # ========================================================
    df["atr"] = wilder_rma(
        tr,
        ATR_PERIOD
    )
    # ========================================================
    # DIRECTIONAL MOVEMENT
    # ========================================================
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
            (
                up_move >
                down_move
            )
            &
            (
                up_move > 0
            ),
            up_move,
            0
        ),
        index=df.index
    )
    minus_dm = pd.Series(
        np.where(
            (
                down_move >
                up_move
            )
            &
            (
                down_move > 0
            ),
            down_move,
            0
        ),
        index=df.index
    )
    atr_rma = wilder_rma(
        tr,
        ADX_PERIOD
    )
    plus_dm_rma = (
        wilder_rma(
            plus_dm,
            ADX_PERIOD
        )
    )
    minus_dm_rma = (
        wilder_rma(
            minus_dm,
            ADX_PERIOD
        )
    )
    df["plus_di"] = (
        100 *
        plus_dm_rma /
        (
            atr_rma +
            1e-12
        )
    )
    df["minus_di"] = (
        100 *
        minus_dm_rma /
        (
            atr_rma +
            1e-12
        )
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
    # ========================================================
    # RSI
    # ========================================================
    delta = (
        df["close"]
        .diff()
    )
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
        (
            avg_loss +
            1e-12
        )
    )
    df["rsi"] = (
        100 -
        (
            100 /
            (1 + rs)
        )
    )
    # ========================================================
    # VOLUME
    # ========================================================
    df["volume_ma20"] = (
        df["volume"]
        .rolling(20)
        .mean()
    )
    df["volume_ratio"] = (
        df["volume"] /
        (
            df["volume_ma20"] +
            1e-12
        )
    )
    # ========================================================
    # ATR %
    # ========================================================
    df["atr_pct"] = (
        df["atr"] /
        df["close"] *
        100
    )
    # ========================================================
    # STRUCTURE
    # ========================================================
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
    return (
        df
        .dropna()
        .reset_index(
            drop=True
        )
    )
# ============================================================
# SIGNAL ENGINE
# ============================================================
def check_signal(
    df,
    symbol
):
    if len(df) < 80:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(
        last["close"]
    )
    atr = float(
        last["atr"]
    )
    rsi = float(
        last["rsi"]
    )
    adx = float(
        last["adx"]
    )
    ema_fast = float(
        last["ema_fast"]
    )
    ema_slow = float(
        last["ema_slow"]
    )
    volume_ratio = float(
        last["volume_ratio"]
    )
    plus_di = float(
        last["plus_di"]
    )
    minus_di = float(
        last["minus_di"]
    )
    # ========================================================
    # SCORES
    # ========================================================
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
            "EMA bullish"
        )
    if close > ema_fast:
        score_long += 1
        reasons_long.append(
            "Price > EMA21"
        )
    if adx >= MIN_ADX_TREND:
        if plus_di > minus_di:
            score_long += 1
            reasons_long.append(
                "Directional strength"
            )
    if 52 <= rsi <= 68:
        score_long += 1
        reasons_long.append(
            "RSI bullish zone"
        )
    if volume_ratio >= MIN_VOLUME_RATIO:
        score_long += 1
        reasons_long.append(
            "Volume confirmed"
        )
    # ========================================================
    # SHORT TREND
    # ========================================================
    if ema_fast < ema_slow:
        score_short += 1
        reasons_short.append(
            "EMA bearish"
        )
    if close < ema_fast:
        score_short += 1
        reasons_short.append(
            "Price < EMA21"
        )
    if adx >= MIN_ADX_TREND:
        if minus_di > plus_di:
            score_short += 1
            reasons_short.append(
                "Directional strength"
            )
    if 32 <= rsi <= 48:
        score_short += 1
        reasons_short.append(
            "RSI bearish zone"
        )
    if volume_ratio >= MIN_VOLUME_RATIO:
        score_short += 1
        reasons_short.append(
            "Volume confirmed"
        )
    # ========================================================
    # RANGE REVERSAL
    # ========================================================
    range_long = False
    range_short = False
    if adx < MIN_ADX_TREND:
        if (
            rsi < 30
            and
            close >
            float(
                prev["close"]
            )
        ):
            range_long = True
        if (
            rsi > 70
            and
            close <
            float(
                prev["close"]
            )
        ):
            range_short = True
    # ========================================================
    # SELECT
    # ========================================================
    signal = None
    score = 0
    reason = ""
    if (
        score_long >=
        MIN_SCORE
    ):
        signal = "LONG"
        score = score_long
        reason = " | ".join(
            reasons_long
        )
    elif (
        score_short >=
        MIN_SCORE
    ):
        signal = "SHORT"
        score = score_short
        reason = " | ".join(
            reasons_short
        )
    elif range_long:
        signal = "LONG"
        score = 4
        reason = (
            "Range | "
            "RSI oversold | "
            "bullish reversal"
        )
    elif range_short:
        signal = "SHORT"
        score = 4
        reason = (
            "Range | "
            "RSI overbought | "
            "bearish reversal"
        )
    if signal is None:
        return None
    # ========================================================
    # RISK DISTANCE
    # ========================================================
    risk_distance = (
        ATR_MULTIPLIER *
        atr
    )
    if (
        risk_distance <= 0
    ):
        return None
    # ========================================================
    # SL / TP
    # ========================================================
    if signal == "LONG":
        sl = (
            close -
            risk_distance
        )
        tp = (
            close +
            risk_distance *
            RR
        )
    else:
        sl = (
            close +
            risk_distance
        )
        tp = (
            close -
            risk_distance *
            RR
        )
    # ========================================================
    # SIGNAL OBJECT
    # ========================================================
    return {
        "symbol":
            symbol,
        "side":
            signal,
        "entry":
            float(close),
        "sl":
            float(sl),
        "tp":
            float(tp),
        "rr":
            RR,
        "atr":
            float(atr),
        "adx":
            round(
                adx,
                2
            ),
        "rsi":
            round(
                rsi,
                2
            ),
        "volume_ratio":
            round(
                volume_ratio,
                2
            ),
        "score":
            score,
        "reason":
            reason,
        "signal_candle_time":
            int(
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
    for signal in reversed(
        history
    ):
        if (
            signal.get(
                "symbol"
            )
            != symbol
        ):
            continue
        if (
            signal.get(
                "status"
            )
            not in (
                "TP",
                "SL"
            )
        ):
            continue
        closed_time = (
            signal.get(
                "closed_time"
            )
        )
        if not closed_time:
            continue
        try:
            closed_dt = (
                datetime.strptime(
                    closed_time,
                    "%Y-%m-%d %H:%M:%S"
                )
                .replace(
                    tzinfo=timezone.utc
                )
            )
            elapsed_hours = (
                now -
                closed_dt
            ).total_seconds() / 3600
            return (
                elapsed_hours <
                COOLDOWN_HOURS
            )
        except Exception:
            return False
    return False
# ============================================================
# MONITOR CANDLES
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
    # Include candle sekitar waktu entry.
    #
    # Kita mundurkan 5 menit supaya candle
    # tempat signal dibuat tidak hilang.
    df = df[
        df["time"] >=
        (
            opened_ms -
            5 * 60 * 1000
        )
    ].copy()
    if len(df) == 0:
        return None
    return (
        df
        .sort_values(
            "time"
        )
        .reset_index(
            drop=True
        )
    )
# ============================================================
# CHECK OPEN POSITIONS
# ============================================================
def check_open_signals():
    history = load_history()
    open_signals = [
        s for s in history
        if s.get(
            "status"
        ) == "open"
    ]
    if not open_signals:
        return history
    closed_messages = []
    for sig in open_signals:
        symbol = sig["symbol"]
        try:
            opened_dt = (
                datetime.strptime(
                    sig[
                        "opened_time"
                    ],
                    "%Y-%m-%d %H:%M:%S"
                )
                .replace(
                    tzinfo=timezone.utc
                )
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
            if sig["side"] == "LONG":
                tp_hit = (
                    high >=
                    float(
                        sig["tp"]
                    )
                )
                sl_hit = (
                    low <=
                    float(
                        sig["sl"]
                    )
                )
            else:
                tp_hit = (
                    low <=
                    float(
                        sig["tp"]
                    )
                )
                sl_hit = (
                    high >=
                    float(
                        sig["sl"]
                    )
                )
            # =================================================
            # SAME CANDLE TP + SL
            # =================================================
            if (
                tp_hit
                and
                sl_hit
            ):
                # Conservative assumption:
                # SL first.
                hit = "SL"
                hit_price = float(
                    sig["sl"]
                )
                hit_time = (
                    candle_time
                )
                break
            elif tp_hit:
                hit = "TP"
                hit_price = float(
                    sig["tp"]
                )
                hit_time = (
                    candle_time
                )
                break
            elif sl_hit:
                hit = "SL"
                hit_price = float(
                    sig["sl"]
                )
                hit_time = (
                    candle_time
                )
                break
        if hit is None:
            continue
        # =====================================================
        # CLOSE POSITION
        # =====================================================
        sig["status"] = hit
        sig["closed_time"] = (
            utc_string()
        )
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
        sig["hit_price"] = (
            hit_price
        )
        sig["r_result"] = (
            RR
            if hit == "TP"
            else -1.0
        )
        # =====================================================
        # NOTIFICATION
        # =====================================================
        if hit == "TP":
            closed_messages.append(
                "🟢 *TP HIT*\n"
                f"`{symbol}` · "
                f"`{sig['side']}`\n"
                f"Entry `{fmt_price(sig['entry'])}`\n"
                f"TP `{fmt_price(sig['tp'])}`\n"
                f"Result `+{RR:.1f}R`"
            )
        else:
            closed_messages.append(
                "🔴 *SL HIT*\n"
                f"`{symbol}` · "
                f"`{sig['side']}`\n"
                f"Entry `{fmt_price(sig['entry'])}`\n"
                f"SL `{fmt_price(sig['sl'])}`\n"
                f"Result `-1.0R`"
            )
    save_history(
        history
    )
    if closed_messages:
        send_telegram(
            "📊 *TRADE UPDATE*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            +
            "\n\n".join(
                closed_messages
            )
        )
    return history
# ============================================================
# CURRENT PRICE
# ============================================================
def get_current_price(
    symbol
):
    df = get_klines(
        symbol,
        bar=MONITOR_TF,
        limit=2
    )
    if (
        df is None
        or len(df) == 0
    ):
        return None
    return float(
        df.iloc[-1]["close"]
    )
# ============================================================
# FLOATING R
# ============================================================
def calculate_floating_r(
    sig,
    current_price
):
    entry = float(
        sig["entry"]
    )
    sl = float(
        sig["sl"]
    )
    risk = abs(
        entry - sl
    )
    if risk <= 0:
        return 0.0
    if sig["side"] == "LONG":
        return (
            current_price -
            entry
        ) / risk
    return (
        entry -
        current_price
    ) / risk
# ============================================================
# RUNNING POSITION REPORT
# ============================================================
def send_open_signals_report(
    history
):
    open_signals = [
        s for s in history
        if s.get(
            "status"
        ) == "open"
    ]
    if not open_signals:
        print(
            "Tidak ada posisi running."
        )
        return
    position_blocks = []
    total_floating_r = 0.0
    profitable_count = 0
    negative_count = 0
    best_position = None
    worst_position = None
    valid_price_count = 0
    # ========================================================
    # EACH POSITION
    # ========================================================
    for sig in open_signals:
        symbol = sig[
            "symbol"
        ]
        side = sig[
            "side"
        ]
        entry = float(
            sig["entry"]
        )
        sl = float(
            sig["sl"]
        )
        tp = float(
            sig["tp"]
        )
        current_price = (
            get_current_price(
                symbol
            )
        )
        if current_price is None:
            position_blocks.append(
                f"⏳ *{symbol}* · "
                f"`{side}`\n"
                f"Entry `{fmt_price(entry)}`\n"
                f"Now `N/A`\n"
                f"SL `{fmt_price(sl)}`\n"
                f"TP `{fmt_price(tp)}`\n"
                f"Float `N/A`"
            )
            continue
        valid_price_count += 1
        floating_r = (
            calculate_floating_r(
                sig,
                current_price
            )
        )
        total_floating_r += (
            floating_r
        )
        # ====================================================
        # PROFIT / LOSS
        # ====================================================
        if floating_r >= 0:
            profitable_count += 1
            state = "🟢"
        else:
            negative_count += 1
            state = "🔴"
        # ====================================================
        # BEST
        # ====================================================
        if (
            best_position is None
            or
            floating_r >
            best_position[
                "floating_r"
            ]
        ):
            best_position = {
                "symbol":
                    symbol,
                "floating_r":
                    floating_r
            }
        # ====================================================
        # WORST
        # ====================================================
        if (
            worst_position is None
            or
            floating_r <
            worst_position[
                "floating_r"
            ]
        ):
            worst_position = {
                "symbol":
                    symbol,
                "floating_r":
                    floating_r
            }
        # ====================================================
        # POSITION CARD
        # ====================================================
        position_blocks.append(
            f"{state} *{symbol}* · "
            f"`{side}`\n"
            f"Entry  `{fmt_price(entry)}`\n"
            f"Now    `{fmt_price(current_price)}`\n"
            f"SL     `{fmt_price(sl)}`\n"
            f"TP     `{fmt_price(tp)}`\n"
            f"Float  `{floating_r:+.2f}R`"
        )
    # ========================================================
    # SUMMARY
    # ========================================================
    total_positions = (
        len(open_signals)
    )
    if valid_price_count > 0:
        avg_floating_r = (
            total_floating_r /
            valid_price_count
        )
    else:
        avg_floating_r = 0.0
    total_sl_exposure = (
        total_positions *
        -1.0
    )
    total_tp_potential = (
        total_positions *
        RR
    )
    # ========================================================
    # BEST / WORST
    # ========================================================
    if best_position:
        best_text = (
            f"`{best_position['symbol']}` "
            f"`{best_position['floating_r']:+.2f}R`"
        )
    else:
        best_text = "`N/A`"
    if worst_position:
        worst_text = (
            f"`{worst_position['symbol']}` "
            f"`{worst_position['floating_r']:+.2f}R`"
        )
    else:
        worst_text = "`N/A`"
    # ========================================================
    # FINAL MESSAGE
    # ========================================================
    message = (
        "📡 *RUNNING POSITIONS*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        +
        "\n\n".join(
            position_blocks
        )
        +
        "\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *OPEN SUMMARY*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Open Positions : "
        f"`{total_positions}`\n"
        f"🟢 Profitable   : "
        f"`{profitable_count}`\n"
        f"🔴 Negative     : "
        f"`{negative_count}`\n\n"
        f"Floating R      : "
        f"`{total_floating_r:+.2f}R`\n"
        f"Avg Floating R  : "
        f"`{avg_floating_r:+.2f}R`\n\n"
        f"Best            : "
        f"{best_text}\n"
        f"Worst           : "
        f"{worst_text}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Target RR     : "
        f"`1:{RR:.0f}`\n"
        f"📈 TP Potential  : "
        f"`+{total_tp_potential:.2f}R`\n"
        f"🛑 SL Exposure   : "
        f"`{total_sl_exposure:.2f}R`"
    )
    send_telegram(
        message
    )
    print(
        message
    )
# ============================================================
# PERFORMANCE STATISTICS
# ============================================================
def compute_stats(
    history
):
    closed = [
        s for s in history
        if s.get(
            "status"
        )
        in (
            "TP",
            "SL"
        )
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
    total = len(
        closed
    )
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
    if gross_loss > 0:
        profit_factor = (
            gross_profit /
            gross_loss
        )
    else:
        profit_factor = float(
            "inf"
        )
    avg_r = (
        total_r /
        total
    )
    return {
        "total":
            total,
        "wins":
            len(wins),
        "losses":
            len(losses),
        "win_rate":
            win_rate,
        "total_r":
            total_r,
        "avg_r":
            avg_r,
        "profit_factor":
            profit_factor
    }
def send_stats_report(
    history
):
    stats = compute_stats(
        history
    )
    if not stats:
        return
    pf = stats[
        "profit_factor"
    ]
    if math.isinf(
        pf
    ):
        pf_text = "∞"
    else:
        pf_text = (
            f"{pf:.2f}"
        )
    message = (
        "📊 *SYSTEM PERFORMANCE*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Trades        : "
        f"`{stats['total']}`\n"
        f"Wins          : "
        f"`{stats['wins']}`\n"
        f"Losses        : "
        f"`{stats['losses']}`\n"
        f"Win Rate      : "
        f"`{stats['win_rate']:.1f}%`\n"
        f"Total R       : "
        f"`{stats['total_r']:+.2f}R`\n"
        f"Avg R/Trade   : "
        f"`{stats['avg_r']:+.2f}R`\n"
        f"Profit Factor : "
        f"`{pf_text}`"
    )
    send_telegram(
        message
    )
# ============================================================
# NEW SIGNAL NOTIFICATION
# ============================================================
def send_new_signals(
    signals
):
    if not signals:
        return
    blocks = []
    for sig in signals:
        if (
            sig["side"]
            == "LONG"
        ):
            side_emoji = "🟢"
        else:
            side_emoji = "🔴"
        blocks.append(
            f"{side_emoji} "
            f"*{sig['side']} "
            f"{sig['symbol']}*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Entry  "
            f"`{fmt_price(sig['entry'])}`\n"
            f"SL     "
            f"`{fmt_price(sig['sl'])}`\n"
            f"TP     "
            f"`{fmt_price(sig['tp'])}`\n"
            f"RR     "
            f"`1:{RR:.0f}`\n"
            f"Score  "
            f"`{sig['score']}/5`\n"
            f"ADX    "
            f"`{sig['adx']}`\n"
            f"RSI    "
            f"`{sig['rsi']}`\n"
            f"Volume "
            f"`{sig['volume_ratio']}x`\n"
            f"Reason: "
            f"{sig['reason']}"
        )
    message = (
        "🚨 *NEW SIGNALS · OKX 1H*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Generated: "
        f"`{utc_string()} UTC`\n\n"
        +
        "\n\n".join(
            blocks
        )
        +
        "\n\n"
        "_Educational only · Signal only_"
    )
    send_telegram(
        message
    )
# ============================================================
# SCAN NEW SIGNALS
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
        if s.get(
            "status"
        ) == "open"
    }
    new_signals = []
    print(
        f"Scanning "
        f"{len(pairs)} pairs..."
    )
    for index, symbol in enumerate(
        pairs
    ):
        try:
            # =================================================
            # OPEN POSITION
            # =================================================
            if (
                symbol
                in already_open
            ):
                continue
            # =================================================
            # COOLDOWN
            # =================================================
            if is_in_cooldown(
                history,
                symbol
            ):
                print(
                    f"{symbol}: "
                    f"cooldown"
                )
                continue
            # =================================================
            # CLOSED H1
            # =================================================
            df = get_closed_klines(
                symbol,
                TIMEFRAME,
                LIMIT
            )
            if df is None:
                continue
            # =================================================
            # INDICATORS
            # =================================================
            df = calculate_indicators(
                df
            )
            if len(df) < 80:
                continue
            # =================================================
            # SIGNAL
            # =================================================
            signal = check_signal(
                df,
                symbol
            )
            if signal is None:
                continue
            # =================================================
            # RECORD
            # =================================================
            signal["status"] = (
                "open"
            )
            signal["opened_time"] = (
                utc_string()
            )
            signal["closed_time"] = (
                None
            )
            signal["r_result"] = (
                None
            )
            signal["hit_price"] = (
                None
            )
            signal["hit_time"] = (
                None
            )
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
                f"NEW SIGNAL: "
                f"{symbol} "
                f"{signal['side']} "
                f"score="
                f"{signal['score']}"
            )
            if index % 5 == 0:
                time.sleep(
                    0.4
                )
        except Exception as e:
            print(
                f"{symbol}:",
                e
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
        "======================================"
    )
    print(
        "OKX TELEGRAM SIGNAL ENGINE V2"
    )
    print(
        utc_string(),
        "UTC"
    )
    print(
        "======================================"
    )
    # ========================================================
    # 1. CHECK TP / SL
    # ========================================================
    history = (
        check_open_signals()
    )
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
    history = (
        scan_new_signals(
            history
        )
    )
    print(
        "Scan selesai."
    )
# ============================================================
# START
# ============================================================
if __name__ == "__main__":
    main()



