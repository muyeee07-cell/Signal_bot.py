"""
ALPHAQUANT V4.0
4H Multi-Setup Telegram Signal Engine
Signal-only / OKX USDT perpetuals

Setups:
- PULLBACK  : trend pullback to EMA50 (RR 1:2)
- BREAKOUT  : squeeze + 20-candle channel breakout with volume (RR 1:2)
- MEAN_REV  : Bollinger reversal in ranging markets, TP at the mean

V4.0 changes:
- Timeframe 4H, trade monitoring on 15m candles
- Scan runs only when a new 4H candle has closed
- Per-trade RR (mean reversion uses a variable RR)
- Per-setup rejection report and per-setup performance stats
- No automatic trading
"""

from __future__ import annotations

import os, json, time, math, logging
from datetime import datetime, timezone
from typing import Optional
import requests

# ================= CONFIG =================

OKX = "https://www.okx.com"
# Telegram credentials: use GitHub Actions Secrets with the primary names below.
# Aliases are also accepted for easier deployment.
def env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""

TOKEN = env_first("TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
CHAT_ID = env_first("CHAT_ID", "TELEGRAM_CHAT_ID", "TELEGRAM_CHAT")

TIMEFRAME = "4H"
TF_MS = 4 * 3_600_000          # 4H candle length (ms)
MONITOR_TF = "15m"
MONITOR_MS = 15 * 60_000       # 15m candle length (ms)

TOP_PAIRS = 150
MIN_VOLUME_USDT = 3_000_000

HISTORY_BARS = 350
MONITOR_BARS = 500
# Upper cap for 15m monitoring history (~14.5 days). OKX /market/candles
# only serves a limited recent window.
MONITOR_MAX_BARS = 1400

# Minimum confirmed candles required for EMA200 + structure.
# Newly listed contracts below this threshold are skipped safely.
MIN_HISTORY_BARS = 230

EMA_FAST = 50
EMA_SLOW = 200
RSI_PERIOD = 14
ADX_PERIOD = 14
ATR_PERIOD = 14
VOL_PERIOD = 20

SWING = 2
BOS_ATR_BUFFER = 0.10
SL_ATR_BUFFER = 0.30

ADX_MIN = 20.0
ADX_STRONG = 25.0
VOL_MIN = 0.80

MIN_SCORE = 75
MIN_SL_ATR = 0.50
MAX_SL_ATR = 3.00

RR = 2.0
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.004"))
ACCOUNT_EQUITY = float(os.getenv("ACCOUNT_EQUITY", "1000"))

MAX_OPEN = 12
COOLDOWN_HOURS = 12
SCAN_INTERVAL = 300

# GitHub Actions starts a fresh job every scheduled run.
# Default: run ONE cycle and exit. Set RUN_FOREVER=1 only on a persistent VPS/runner.
RUN_FOREVER = os.getenv("RUN_FOREVER", "0").strip() == "1"

HISTORY_FILE = os.getenv("SIGNAL_HISTORY_FILE", "signals_history.json")
TIMEOUT = 15
RETRIES = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("V4.0")

S = requests.Session()
S.headers.update({"User-Agent": "ALPHAQUANT-V4.0"})

TELEGRAM = bool(TOKEN and CHAT_ID)

# ================= HELPERS =================

def iso(ms):
    return datetime.fromtimestamp(
        ms / 1000, tz=timezone.utc
    ).isoformat()

def now():
    return datetime.now(timezone.utc).isoformat()

def api(path, params=None):
    for attempt in range(RETRIES):
        try:
            r = S.get(
                OKX + path,
                params=params,
                timeout=TIMEOUT
            )
            r.raise_for_status()
            d = r.json()
            if d.get("code") == "0":
                return d
            log.warning("OKX error: %s", d)
        except Exception as e:
            log.warning(
                "Request failed %s/%s: %s",
                attempt + 1, RETRIES, e
            )
        if attempt + 1 < RETRIES:
            time.sleep(1.5)
    return None

def tg(text):
    if not TELEGRAM:
        return False
    try:
        r = S.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=TIMEOUT
        )
        r.raise_for_status()
        return True
    except Exception as e:
        log.error("Telegram error: %s", e)
        return False

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"open": [], "closed": []}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("open", [])
        d.setdefault("closed", [])
        return d
    except Exception as e:
        log.error("History load failed: %s", e)
        return {"open": [], "closed": []}

def save_history(h):
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2, ensure_ascii=False)
    os.replace(tmp, HISTORY_FILE)

# ================= MARKET DATA =================

def top_pairs():
    d = api("/api/v5/market/tickers", {"instType": "SWAP"})
    if not d:
        return []
    a = []
    for x in d.get("data", []):
        inst = x.get("instId", "")
        if not inst.endswith("-USDT-SWAP"):
            continue
        try:
            v = float(x.get("volCcy24h", 0))
        except:
            continue
        if v >= MIN_VOLUME_USDT:
            a.append((inst, v))
    a.sort(key=lambda x: x[1], reverse=True)
    return [x[0] for x in a[:TOP_PAIRS]]

def instruments():
    d = api("/api/v5/public/instruments", {"instType": "SWAP"})
    out = {}
    if not d:
        return out
    for x in d.get("data", []):
        inst = x.get("instId", "")
        if inst.endswith("-USDT-SWAP"):
            try:
                out[inst] = {
                    "tick": float(x.get("tickSz", "0.00000001"))
                }
            except:
                pass
    return out

def price(inst):
    d = api("/api/v5/market/ticker", {"instId": inst})
    try:
        return float(d["data"][0]["last"])
    except:
        return None

def candles(inst, bar, needed):
    """
    OKX pagination using `after`.
    Returns confirmed candles oldest -> newest.
    """
    found = {}
    cursor = None
    max_requests = math.ceil(needed / 100) + 6

    for _ in range(max_requests):
        p = {
            "instId": inst,
            "bar": bar,
            "limit": "100"
        }
        if cursor is not None:
            p["after"] = str(cursor)

        d = api("/api/v5/market/candles", p)
        if not d:
            break

        rows = d.get("data", [])
        if not rows:
            break

        oldest = None

        for x in rows:
            try:
                ts = int(x[0])
                oldest = ts if oldest is None else min(oldest, ts)

                # x[8] == 1 means confirmed candle.
                if int(x[8]) != 1:
                    continue

                found[ts] = [
                    ts,
                    float(x[1]),  # open
                    float(x[2]),  # high
                    float(x[3]),  # low
                    float(x[4]),  # close
                    float(x[5])   # volume
                ]
            except:
                continue

        if len(found) >= needed:
            break

        if oldest is None or oldest == cursor:
            break

        cursor = oldest
        time.sleep(0.12)

    out = sorted(found.values(), key=lambda x: x[0])
    return out[-needed:]

def latest_candle_ts():
    """Open time of the newest confirmed candle (BTC as reference)."""
    cs = candles("BTC-USDT-SWAP", TIMEFRAME, 3)
    return cs[-1][0] if cs else None

# ================= INDICATORS =================

def rma(v, n):
    out = [None] * len(v)
    if len(v) < n:
        return out
    x = sum(v[:n]) / n
    out[n - 1] = x
    for i in range(n, len(v)):
        x = ((x * (n - 1)) + v[i]) / n
        out[i] = x
    return out

def ema(v, n):
    out = [None] * len(v)
    if len(v) < n:
        return out
    k = 2 / (n + 1)
    x = sum(v[:n]) / n
    out[n - 1] = x
    for i in range(n, len(v)):
        x = v[i] * k + x * (1 - k)
        out[i] = x
    return out

def atr(cs, n=14):
    tr = []
    for i, c in enumerate(cs):
        if i == 0:
            tr.append(c[2] - c[3])
        else:
            pc = cs[i-1][4]
            tr.append(max(
                c[2] - c[3],
                abs(c[2] - pc),
                abs(c[3] - pc)
            ))
    return rma(tr, n)

def rsi(cs, n=14):
    closes = [x[4] for x in cs]
    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i-1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    ag, al = rma(gains, n), rma(losses, n)
    out = [None] * len(cs)
    for i in range(len(cs)):
        if ag[i] is None or al[i] is None:
            continue
        if al[i] == 0:
            out[i] = 100.0
        else:
            rs = ag[i] / al[i]
            out[i] = 100 - 100 / (1 + rs)
    return out

def adx(cs, n=14):
    tr = []
    plus = [0.0]
    minus = [0.0]

    for i, c in enumerate(cs):
        if i == 0:
            tr.append(c[2] - c[3])
            continue
        pc = cs[i-1]
        tr.append(max(
            c[2]-c[3],
            abs(c[2]-pc[4]),
            abs(c[3]-pc[4])
        ))
        up = c[2] - pc[2]
        dn = pc[3] - c[3]
        plus.append(up if up > dn and up > 0 else 0)
        minus.append(dn if dn > up and dn > 0 else 0)

    atrv = rma(tr, n)
    ps = rma(plus, n)
    ms = rma(minus, n)

    pdi = [None]*len(cs)
    mdi = [None]*len(cs)
    dx = [0.0]*len(cs)

    for i in range(len(cs)):
        if atrv[i] is None or atrv[i] == 0:
            continue
        pdi[i] = 100 * ps[i] / atrv[i]
        mdi[i] = 100 * ms[i] / atrv[i]
        den = pdi[i] + mdi[i]
        if den:
            dx[i] = 100 * abs(pdi[i]-mdi[i]) / den

    return rma(dx, n), pdi, mdi

def volume_ratio(cs, n=20):
    if len(cs) < n:
        return None
    avg = sum(x[5] for x in cs[-n:]) / n
    return cs[-1][5] / avg if avg else None

# ================= STRUCTURE =================

def swings(cs):
    highs, lows = [], []
    for i in range(SWING, len(cs)-SWING):
        h, l = cs[i][2], cs[i][3]
        if all(h > cs[i-j][2] for j in range(1, SWING+1)) and \
           all(h > cs[i+j][2] for j in range(1, SWING+1)):
            highs.append((i, h))
        if all(l < cs[i-j][3] for j in range(1, SWING+1)) and \
           all(l < cs[i+j][3] for j in range(1, SWING+1)):
            lows.append((i, l))
    return highs, lows

def structure(highs, lows):
    hhhl = False
    lhll = False
    if len(highs) >= 2 and len(lows) >= 2:
        hhhl = highs[-1][1] > highs[-2][1] and lows[-1][1] > lows[-2][1]
        lhll = highs[-1][1] < highs[-2][1] and lows[-1][1] < lows[-2][1]
    return hhhl, lhll

def bos(cs, highs, lows, atrv):
    if not atrv[-1]:
        return False, False
    close = cs[-1][4]
    buf = atrv[-1] * BOS_ATR_BUFFER
    bull = bool(highs and close > highs[-1][1] + buf)
    bear = bool(lows and close < lows[-1][1] - buf)
    return bull, bear

# ================= SIGNAL =================

def tick_round(x, tick):
    if tick <= 0:
        return x
    return round(round(x/tick)*tick, 12)

# ================= 4H SETUP CONFIG =================

PB_MAX_DIST_ATR = 0.75      # pullback: max distance from EMA50 (ATR)

BB_N = 20
BB_K = 2.0

BO_LOOKBACK = 20            # breakout: N-candle high/low channel
BO_ATR_BUFFER = 0.10        # close must clear the level by this many ATR
BO_SQ_LOOKBACK = 100        # bandwidth history used to rank the squeeze
BO_SQ_PCTL = 0.35           # prior-candle bandwidth must be in lowest 35%
BO_VOL_MIN = 1.50
BO_BODY_MIN = 0.50
BO_CLOSE_POS = 0.70
BO_RSI_LONG = 55.0
BO_RSI_SHORT = 45.0
BO_MAX_EXT_ATR = 1.50       # do not chase: max ATR past the broken level
BO_SL_BUFFER = 0.50         # SL sits this many ATR beyond the broken level

MR_ADX_MAX = 25.0           # mean reversion only in non-trending markets
MR_RSI_LOW = 35.0
MR_RSI_HIGH = 65.0
MR_MIN_RR = 1.30            # min reward/risk to the mean

# ================= REJECT TRACKING =================

SETUP_STAGES = {
    "PULLBACK": [
        "Regime", "Struktur", "RSI", "DI", "ADX", "Volume",
        "Jarak EMA50", "Retracement", "Konfirmasi", "Skor", "SL/RR"
    ],
    "BREAKOUT": [
        "Level", "Trend", "Squeeze", "Volume", "Kandel", "RSI",
        "Kejar", "SL/RR"
    ],
    "MEAN_REV": ["ADX", "Band", "RSI", "Konfirmasi", "SL/RR"],
}

SETUP_NAME = {
    "PULLBACK": "Pullback",
    "BREAKOUT": "Breakout",
    "MEAN_REV": "Mean Rev",
    "ALL": "Umum"
}

CUR_SETUP = "ALL"

# (setup, stage) -> [(pair, detail)], reset at the start of every scan.
REJECTS = {}

def _safe(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _rej(inst, stage, detail="", setup=None):
    key = (setup or CUR_SETUP, stage)
    REJECTS.setdefault(key, []).append((inst, _safe(detail)))
    return None

def _setup_lines():
    lines = []
    for setup, order in SETUP_STAGES.items():
        parts = [
            f"{st} {len(REJECTS[(setup, st)])}"
            for st in order if REJECTS.get((setup, st))
        ]
        lines.append(
            f"<b>{SETUP_NAME[setup]}</b>: " +
            (" · ".join(parts) if parts else "-")
        )

    other = {}
    for (setup, st), v in REJECTS.items():
        if st not in SETUP_STAGES.get(setup, []):
            other[st] = other.get(st, 0) + len(v)
    if other:
        lines.append(
            "<b>Lainnya</b>: " +
            " · ".join(f"{k} {n}" for k, n in other.items())
        )
    return lines

def _near_misses(limit=5):
    rows = []
    for (setup, st), v in REJECTS.items():
        order = SETUP_STAGES.get(setup)
        if st == "Diblokir":
            depth = 2.0
        elif order and st in order and order.index(st) >= 1:
            depth = order.index(st) / len(order)
        else:
            continue
        for inst, detail in v:
            rows.append((depth, inst, setup, st, detail))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows[:limit]

def reject_summary(scanned, created, candle_ts=None, compact=False):
    no_signal = max(0, scanned - created)

    if compact:
        return (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "<b>🔎 SCAN INFO</b>\n"
            f"Dipindai {scanned} | Sinyal {created} | Tanpa sinyal {no_signal}\n"
            + "\n".join(_setup_lines())
        )

    lines = [f"<b>🔎 SCAN REPORT · {TIMEFRAME}</b>", "━━━━━━━━━━━━━━━━━━"]
    if candle_ts:
        lines.append(f"Candle       : {iso(candle_ts)}")
    lines += [
        f"Dipindai     : {scanned} pair",
        f"Sinyal baru  : {created}",
        f"Tanpa sinyal : {no_signal}",
        "",
        "<b>Gugur di filter</b> (filter pertama yang gagal, per setup)"
    ]
    lines += _setup_lines()

    near = _near_misses()
    if near:
        lines += ["", "<b>Paling dekat lolos</b>"]
        for depth, inst, setup, st, detail in near:
            lines.append(f"{inst} → {SETUP_NAME[setup]} · {st}: {detail}")

    return "\n".join(lines)

def build_pullback(inst, cs, meta):
    if len(cs) < MIN_HISTORY_BARS:
        log.info(
            "SKIP %s | only %s confirmed candles "
            "(need %s for EMA200/structure)",
            inst, len(cs), MIN_HISTORY_BARS
        )
        return _rej(inst, "Data", f"hanya {len(cs)} candle")

    closes = [x[4] for x in cs]
    e50 = ema(closes, EMA_FAST)
    e200 = ema(closes, EMA_SLOW)
    at = atr(cs, ATR_PERIOD)
    rs = rsi(cs, RSI_PERIOD)
    ax, pdi, mdi = adx(cs, ADX_PERIOD)
    vr = volume_ratio(cs, VOL_PERIOD)

    vals = [e50[-1], e200[-1], at[-1], rs[-1], ax[-1], vr]
    if any(x is None for x in vals):
        return _rej(inst, "Data", "indikator belum siap")

    slope = e50[-1] - e50[-6]
    close = cs[-1][4]

    bull_regime = close > e200[-1] and e50[-1] > e200[-1] and slope > 0
    bear_regime = close < e200[-1] and e50[-1] < e200[-1] and slope < 0

    if not bull_regime and not bear_regime:
        return _rej(inst, "Regime", "tren tidak jelas")

    hs, ls = swings(cs)
    hhhl, lhll = structure(hs, ls)
    bull_bos, bear_bos = bos(cs, hs, ls, at)

    if bull_regime:
        side = "LONG"
        if not (hhhl or bull_bos):
            return _rej(inst, "Struktur", "LONG tanpa HH-HL/BOS")
        if not 50 < rs[-1] < 70:
            return _rej(inst, "RSI", f"LONG RSI {rs[-1]:.1f} (perlu 50-70)")
        if pdi[-1] is not None and mdi[-1] is not None and pdi[-1] <= mdi[-1]:
            return _rej(inst, "DI", "LONG tapi +DI tidak di atas -DI")
    else:
        side = "SHORT"
        if not (lhll or bear_bos):
            return _rej(inst, "Struktur", "SHORT tanpa LH-LL/BOS")
        if not 30 < rs[-1] < 50:
            return _rej(inst, "RSI", f"SHORT RSI {rs[-1]:.1f} (perlu 30-50)")
        if pdi[-1] is not None and mdi[-1] is not None and mdi[-1] <= pdi[-1]:
            return _rej(inst, "DI", "SHORT tapi -DI tidak di atas +DI")

    if ax[-1] < ADX_MIN:
        return _rej(inst, "ADX", f"{side} ADX {ax[-1]:.1f} (min {ADX_MIN})")
    if vr < VOL_MIN:
        return _rej(inst, "Volume", f"{side} volume {vr:.2f}x (min {VOL_MIN}x)")

    # Pullback to EMA50/value zone.
    distance_atr = abs(close-e50[-1]) / at[-1]
    if distance_atr > PB_MAX_DIST_ATR:
        return _rej(
            inst, "Jarak EMA50",
            f"{side} {distance_atr:.2f} ATR dari EMA50 (maks {PB_MAX_DIST_ATR})"
        )

    recent = cs[-31:]
    if side == "LONG":
        lo = min(x[3] for x in recent)
        hi = max(x[2] for x in recent)
        retr = (hi-cs[-1][3])/(hi-lo) if hi > lo else 0
        confirm = cs[-1][4] > cs[-1][1] and cs[-1][4] > cs[-2][2]
    else:
        hi = max(x[2] for x in recent)
        lo = min(x[3] for x in recent)
        retr = (cs[-1][2]-lo)/(hi-lo) if hi > lo else 0
        confirm = cs[-1][4] < cs[-1][1] and cs[-1][4] < cs[-2][3]

    if not 0.30 <= retr <= 0.70:
        return _rej(
            inst, "Retracement",
            f"{side} retracement {retr*100:.0f}% (perlu 30-70%)"
        )
    if not confirm:
        return _rej(inst, "Konfirmasi", f"{side} candle belum konfirmasi")

    # Score = 100 possible.
    score = 0
    reasons = []

    if bull_regime or bear_regime:
        score += 20
        reasons.append("EMA regime +20")

    if side == "LONG" and hhhl:
        score += 15
        reasons.append("HH-HL +15")
    if side == "SHORT" and lhll:
        score += 15
        reasons.append("LH-LL +15")

    if (side == "LONG" and bull_bos) or (side == "SHORT" and bear_bos):
        score += 20
        reasons.append("BOS +20")

    if side == "LONG":
        score += 10 if 60 <= rs[-1] < 70 else 5
    else:
        score += 10 if 30 < rs[-1] <= 40 else 5
    reasons.append("RSI")

    if ax[-1] >= ADX_STRONG:
        score += 15
        reasons.append("ADX strong +15")
    else:
        score += 8
        reasons.append("ADX +8")

    if vr >= 1.30:
        score += 10
        reasons.append("Volume strong +10")
    elif vr >= 1.00:
        score += 6
        reasons.append("Volume +6")
    else:
        score += 3
        reasons.append("Volume +3")

    score += 10
    reasons.append("Pullback +10")

    if score < MIN_SCORE:
        return _rej(inst, "Skor", f"{side} skor {score} (min {MIN_SCORE})")

    if side == "LONG":
        if not ls:
            return _rej(inst, "SL/RR", "LONG tanpa swing low")
        sl = ls[-1][1] - SL_ATR_BUFFER*at[-1]
        risk = close - sl
        if risk <= 0:
            return _rej(inst, "SL/RR", "LONG SL tidak valid")
        tp = close + RR*risk
    else:
        if not hs:
            return _rej(inst, "SL/RR", "SHORT tanpa swing high")
        sl = hs[-1][1] + SL_ATR_BUFFER*at[-1]
        risk = sl - close
        if risk <= 0:
            return _rej(inst, "SL/RR", "SHORT SL tidak valid")
        tp = close - RR*risk

    sl_atr = risk/at[-1]
    if not MIN_SL_ATR <= sl_atr <= MAX_SL_ATR:
        return _rej(
            inst, "SL/RR",
            f"{side} SL {sl_atr:.2f} ATR (perlu {MIN_SL_ATR}-{MAX_SL_ATR})"
        )

    tick = meta.get(inst, {}).get("tick", 0.00000001)
    entry = tick_round(close, tick)
    sl = tick_round(sl, tick)
    tp = tick_round(tp, tick)

    signal_id = f"{inst}|{side}|{cs[-1][0]}"

    return {
        "signal_id": signal_id,
        "symbol": inst,
        "direction": side,
        "timeframe": TIMEFRAME,
        "setup": "PULLBACK",
        "signal_candle_time": cs[-1][0],
        "signal_candle_iso": iso(cs[-1][0]),
        "created_at": now(),
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": RR,
        "atr": at[-1],
        "sl_atr": sl_atr,
        "ema50": e50[-1],
        "ema200": e200[-1],
        "rsi": rs[-1],
        "adx": ax[-1],
        "volume_ratio": vr,
        "regime": "BULL" if bull_regime else "BEAR",
        "structure": "HH-HL" if side == "LONG" else "LH-LL",
        "bos": "BULLISH" if side == "LONG" and bull_bos else
               "BEARISH" if side == "SHORT" and bear_bos else "NONE",
        "pullback": retr,
        "score": score,
        "score_reasons": reasons,
        "risk_usdt": ACCOUNT_EQUITY*RISK_PER_TRADE,
        "status": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "result_r": None,
        "result": None
    }

# ================= BREAKOUT / MEAN REVERSION =================

def sma_series(v, n):
    out = [None] * len(v)
    if len(v) < n:
        return out
    t = sum(v[:n])
    out[n - 1] = t / n
    for i in range(n, len(v)):
        t += v[i] - v[i - n]
        out[i] = t / n
    return out

def bollinger(closes, n=20, k=2.0):
    mid = sma_series(closes, n)
    up = [None] * len(closes)
    lo = [None] * len(closes)
    bw = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        w = closes[i - n + 1:i + 1]
        m = mid[i]
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        up[i] = m + k * sd
        lo[i] = m - k * sd
        bw[i] = (up[i] - lo[i]) / m if m else None
    return mid, up, lo, bw

def _pack(inst, cs, meta, setup, side, sl, tp, rr, note,
          regime, a, vr, rs_v, e200_v):
    close = cs[-1][4]
    closes = [x[4] for x in cs]
    e50_v = ema(closes, EMA_FAST)[-1]
    adx_v = adx(cs, ADX_PERIOD)[0][-1]
    tick = meta.get(inst, {}).get("tick", 0.00000001)
    risk = abs(close - sl)

    return {
        "signal_id": f"{inst}|{side}|{cs[-1][0]}",
        "symbol": inst,
        "direction": side,
        "timeframe": TIMEFRAME,
        "setup": setup,
        "note": note,
        "signal_candle_time": cs[-1][0],
        "signal_candle_iso": iso(cs[-1][0]),
        "created_at": now(),
        "entry": tick_round(close, tick),
        "sl": tick_round(sl, tick),
        "tp": tick_round(tp, tick),
        "rr": round(rr, 2),
        "atr": a,
        "sl_atr": risk / a,
        "ema50": e50_v or 0.0,
        "ema200": e200_v,
        "rsi": rs_v,
        "adx": adx_v or 0.0,
        "volume_ratio": vr,
        "regime": regime,
        "structure": "-",
        "bos": "NONE",
        "pullback": None,
        "score": None,
        "score_reasons": [],
        "risk_usdt": ACCOUNT_EQUITY * RISK_PER_TRADE,
        "status": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "result_r": None,
        "result": None
    }

def build_breakout(inst, cs, meta):
    closes = [x[4] for x in cs]
    e200 = ema(closes, EMA_SLOW)
    at = atr(cs, ATR_PERIOD)
    rs = rsi(cs, RSI_PERIOD)
    vr = volume_ratio(cs, VOL_PERIOD)
    _, _, _, bw = bollinger(closes, BB_N, BB_K)

    if any(x is None for x in (e200[-1], at[-1], rs[-1], vr, bw[-2])):
        return _rej(inst, "Data", "indikator belum siap")

    c = cs[-1]
    o, hi, lo, cl = c[1], c[2], c[3], c[4]
    a = at[-1]
    if not a:
        return _rej(inst, "Data", "ATR nol")

    prior = cs[-1 - BO_LOOKBACK:-1]
    lvl_hi = max(x[2] for x in prior)
    lvl_lo = min(x[3] for x in prior)

    if cl > lvl_hi + BO_ATR_BUFFER * a:
        side, level = "LONG", lvl_hi
    elif cl < lvl_lo - BO_ATR_BUFFER * a:
        side, level = "SHORT", lvl_lo
    else:
        gap = min(abs(lvl_hi - cl), abs(cl - lvl_lo)) / a
        return _rej(
            inst, "Level",
            f"{gap:.2f} ATR dari batas channel {BO_LOOKBACK} candle"
        )

    if side == "LONG" and cl <= e200[-1]:
        return _rej(inst, "Trend", "LONG tapi harga di bawah EMA200")
    if side == "SHORT" and cl >= e200[-1]:
        return _rej(inst, "Trend", "SHORT tapi harga di atas EMA200")

    window = [x for x in bw[-(BO_SQ_LOOKBACK + 1):-1] if x is not None]
    if len(window) < 30:
        return _rej(inst, "Data", "riwayat bandwidth kurang")
    rank = sum(1 for x in window if x <= bw[-2]) / len(window)
    if rank > BO_SQ_PCTL:
        return _rej(
            inst, "Squeeze",
            f"{side} volatilitas sebelum break di persentil "
            f"{rank*100:.0f}% (perlu maks {BO_SQ_PCTL*100:.0f}%)"
        )

    if vr < BO_VOL_MIN:
        return _rej(
            inst, "Volume",
            f"{side} volume {vr:.2f}x (min {BO_VOL_MIN}x)"
        )

    rng = hi - lo
    if rng <= 0:
        return _rej(inst, "Kandel", "candle tanpa range")
    body = abs(cl - o) / rng
    pos = (cl - lo) / rng
    if side == "LONG":
        strong = cl > o and body >= BO_BODY_MIN and pos >= BO_CLOSE_POS
    else:
        strong = cl < o and body >= BO_BODY_MIN and pos <= 1 - BO_CLOSE_POS
    if not strong:
        return _rej(
            inst, "Kandel",
            f"{side} body {body*100:.0f}% range, close di {pos*100:.0f}% range"
        )

    if side == "LONG" and rs[-1] < BO_RSI_LONG:
        return _rej(inst, "RSI", f"LONG RSI {rs[-1]:.1f} (min {BO_RSI_LONG:.0f})")
    if side == "SHORT" and rs[-1] > BO_RSI_SHORT:
        return _rej(inst, "RSI", f"SHORT RSI {rs[-1]:.1f} (maks {BO_RSI_SHORT:.0f})")

    ext = abs(cl - level) / a
    if ext > BO_MAX_EXT_ATR:
        return _rej(
            inst, "Kejar",
            f"{side} sudah {ext:.2f} ATR di luar level (maks {BO_MAX_EXT_ATR})"
        )

    if side == "LONG":
        # Breakout is invalidated if price closes back through the level.
        sl = level - BO_SL_BUFFER * a
        risk = cl - sl
    else:
        sl = level + BO_SL_BUFFER * a
        risk = sl - cl
    if risk <= 0:
        return _rej(inst, "SL/RR", f"{side} SL tidak valid")

    sl_atr = risk / a
    if not MIN_SL_ATR <= sl_atr <= MAX_SL_ATR:
        return _rej(
            inst, "SL/RR",
            f"{side} SL {sl_atr:.2f} ATR (perlu {MIN_SL_ATR}-{MAX_SL_ATR})"
        )

    tp = cl + RR * risk if side == "LONG" else cl - RR * risk
    note = (
        f"Break {BO_LOOKBACK}-candle {'high' if side == 'LONG' else 'low'} "
        f"@ {level:.8g} | squeeze P{rank*100:.0f} | vol {vr:.2f}x"
    )
    return _pack(
        inst, cs, meta, "BREAKOUT", side, sl, tp, RR, note,
        "BULL" if side == "LONG" else "BEAR", a, vr, rs[-1], e200[-1]
    )

def build_meanrev(inst, cs, meta):
    closes = [x[4] for x in cs]
    e200 = ema(closes, EMA_SLOW)
    at = atr(cs, ATR_PERIOD)
    rs = rsi(cs, RSI_PERIOD)
    ax, _, _ = adx(cs, ADX_PERIOD)
    vr = volume_ratio(cs, VOL_PERIOD)
    mid, up, lo_b, _ = bollinger(closes, BB_N, BB_K)

    need = (e200[-1], at[-1], rs[-1], ax[-1], vr,
            mid[-1], up[-1], lo_b[-1], up[-2], lo_b[-2])
    if any(x is None for x in need):
        return _rej(inst, "Data", "indikator belum siap")

    a = at[-1]
    if not a:
        return _rej(inst, "Data", "ATR nol")

    if ax[-1] > MR_ADX_MAX:
        return _rej(
            inst, "ADX",
            f"ADX {ax[-1]:.1f} (maks {MR_ADX_MAX:.0f}) - pasar trending"
        )

    c, pv = cs[-1], cs[-2]
    o, hi, lo, cl = c[1], c[2], c[3], c[4]

    touch_lo = lo <= lo_b[-1] or pv[3] <= lo_b[-2]
    touch_hi = hi >= up[-1] or pv[2] >= up[-2]
    if not touch_lo and not touch_hi:
        d = min(lo - lo_b[-1], up[-1] - hi) / a
        return _rej(
            inst, "Band",
            f"{max(d, 0):.2f} ATR dari Bollinger band terdekat"
        )

    if touch_lo and touch_hi:
        side = "LONG" if rs[-1] < 50 else "SHORT"
    else:
        side = "LONG" if touch_lo else "SHORT"

    rsi3 = [x for x in rs[-3:] if x is not None]
    if side == "LONG" and min(rsi3) > MR_RSI_LOW:
        return _rej(
            inst, "RSI",
            f"LONG RSI terendah {min(rsi3):.1f} (perlu maks {MR_RSI_LOW:.0f})"
        )
    if side == "SHORT" and max(rsi3) < MR_RSI_HIGH:
        return _rej(
            inst, "RSI",
            f"SHORT RSI tertinggi {max(rsi3):.1f} (perlu min {MR_RSI_HIGH:.0f})"
        )

    rng = hi - lo
    if rng <= 0:
        return _rej(inst, "Konfirmasi", "candle tanpa range")
    pos = (cl - lo) / rng
    if side == "LONG":
        ok = cl > o and cl > lo_b[-1] and pos >= 0.5
    else:
        ok = cl < o and cl < up[-1] and pos <= 0.5
    if not ok:
        return _rej(
            inst, "Konfirmasi",
            f"{side} candle belum berbalik masuk ke dalam band"
        )

    if side == "LONG":
        sl = min(lo, pv[3]) - SL_ATR_BUFFER * a
        risk = cl - sl
        reward = mid[-1] - cl
    else:
        sl = max(hi, pv[2]) + SL_ATR_BUFFER * a
        risk = sl - cl
        reward = cl - mid[-1]

    if risk <= 0:
        return _rej(inst, "SL/RR", f"{side} SL tidak valid")
    sl_atr = risk / a
    if not MIN_SL_ATR <= sl_atr <= MAX_SL_ATR:
        return _rej(
            inst, "SL/RR",
            f"{side} SL {sl_atr:.2f} ATR (perlu {MIN_SL_ATR}-{MAX_SL_ATR})"
        )
    if reward <= 0:
        return _rej(inst, "SL/RR", f"{side} harga sudah melewati mean")

    rr = reward / risk
    if rr < MR_MIN_RR:
        return _rej(
            inst, "SL/RR",
            f"{side} RR ke mean {rr:.2f} (min {MR_MIN_RR})"
        )

    note = (
        f"Reversal dari Bollinger {'bawah' if side == 'LONG' else 'atas'} "
        f"| RSI {rs[-1]:.1f} | ADX {ax[-1]:.1f} | TP di mean SMA{BB_N}"
    )
    return _pack(
        inst, cs, meta, "MEAN_REV", side, sl, mid[-1], rr, note,
        "RANGE", a, vr, rs[-1], e200[-1]
    )

def build_signal(inst, cs, meta):
    global CUR_SETUP

    CUR_SETUP = "ALL"
    if len(cs) < MIN_HISTORY_BARS:
        log.info(
            "SKIP %s | only %s confirmed candles "
            "(need %s for EMA200/structure)",
            inst, len(cs), MIN_HISTORY_BARS
        )
        return _rej(inst, "Data", f"hanya {len(cs)} candle")

    for name, fn in (
        ("PULLBACK", build_pullback),
        ("BREAKOUT", build_breakout),
        ("MEAN_REV", build_meanrev),
    ):
        CUR_SETUP = name
        sig = fn(inst, cs, meta)
        if sig:
            CUR_SETUP = "ALL"
            # A pair that produced a signal is not a rejection: drop the
            # rejections earlier setups recorded for it.
            for key in list(REJECTS):
                REJECTS[key] = [x for x in REJECTS[key] if x[0] != inst]
            return sig

    CUR_SETUP = "ALL"
    return None

# ================= DEDUPE =================

def blocked(h, sig):
    sid = sig["signal_id"]
    if any(x.get("signal_id") == sid for x in h["open"]+h["closed"]):
        return True

    # One open position per symbol (prevents stacking on the same pair).
    if any(x.get("symbol") == sig["symbol"] for x in h["open"]):
        return True

    cutoff = time.time() - COOLDOWN_HOURS*3600
    for x in h["closed"]:
        if x.get("symbol") != sig["symbol"]:
            continue
        try:
            if datetime.fromisoformat(x["exit_time"]).timestamp() > cutoff:
                return True
        except:
            pass
    return False

# ================= MONITOR =================

def monitor(trade):
    # Entry = close of the signal candle, so monitoring must begin
    # when that candle ENDS (open time + timeframe), not when it opened.
    start = trade.get("signal_candle_time", 0) + TF_MS

    # Fetch enough monitor candles to cover the full trade age (not a fixed 500).
    age_ms = max(0, int(time.time() * 1000) - start)
    needed = max(60, age_ms // MONITOR_MS + 24)
    if needed > MONITOR_MAX_BARS:
        log.warning(
            "Monitor %s: trade age needs %s %s bars, capped at %s "
            "(older TP/SL hits may be missed)",
            trade["symbol"], needed, MONITOR_TF, MONITOR_MAX_BARS
        )
        needed = MONITOR_MAX_BARS

    cs = candles(trade["symbol"], MONITOR_TF, needed)
    if not cs:
        return None

    for c in [x for x in cs if x[0] >= start]:
        hi, lo = c[2], c[3]
        sl, tp = trade["sl"], trade["tp"]

        if trade["direction"] == "LONG":
            hit_sl, hit_tp = lo <= sl, hi >= tp
        else:
            hit_sl, hit_tp = hi >= sl, lo <= tp

        # Same monitor candle touches both: conservative SL first.
        if hit_sl and hit_tp:
            exit_price, r, result = sl, -1.0, "LOSS"
        elif hit_tp:
            exit_price, r, result = tp, float(trade.get("rr", RR)), "WIN"
        elif hit_sl:
            exit_price, r, result = sl, -1.0, "LOSS"
        else:
            continue

        t = dict(trade)
        t.update({
            "status": "CLOSED",
            "exit_price": exit_price,
            "exit_time": iso(c[0]),
            "result_r": r,
            "result": result
        })
        return t
    return None

def check_open(h):
    if not h["open"]:
        return

    remain, closed = [], []

    for t in h["open"]:
        try:
            result = monitor(t)
            if result:
                closed.append(result)
            else:
                remain.append(t)
        except Exception as e:
            log.error("Monitor %s failed: %s", t["symbol"], e)
            remain.append(t)

    h["open"] = remain
    if closed:
        h["closed"].extend(closed)
        save_history(h)

    for t in closed:
        emoji = "✅" if t["result"] == "WIN" else "❌"
        tg(
            f"<b>{emoji} TRADE CLOSED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>{t['symbol']}</b> {t['direction']}\n"
            f"Entry: <code>{t['entry']}</code>\n"
            f"Exit: <code>{t['exit_price']}</code>\n"
            f"Result: <b>{t['result_r']:+.2f}R</b>\n"
            f"Setup: {SETUP_NAME.get(t.get('setup', 'PULLBACK'), '-')}\n"
            f"Closed: {t['exit_time']}"
        )

# ================= REPORT =================

def float_r(t, p):
    risk = abs(t["entry"]-t["sl"])
    if risk <= 0:
        return 0
    return ((p-t["entry"])/risk
            if t["direction"]=="LONG"
            else (t["entry"]-p)/risk)

def running_report(h):
    if not h["open"]:
        tg("<b>📡 RUNNING POSITIONS</b>\n━━━━━━━━━━━━━━━━━━\nNo open positions.")
        return

    blocks, rs = [], []

    for t in h["open"]:
        p = price(t["symbol"])
        if p is None:
            continue
        r = float_r(t, p)
        rs.append(r)
        emoji = "🟢" if r > 0 else "🔴" if r < 0 else "⚪"
        blocks.append(
            f"{emoji} <b>{t['symbol']}</b> · {t['direction']} · "
            f"{SETUP_NAME.get(t.get('setup', 'PULLBACK'), '-')}\n"
            f"Entry <code>{t['entry']}</code> | Now <code>{p}</code>\n"
            f"SL <code>{t['sl']}</code> | TP <code>{t['tp']}</code>\n"
            f"Float <b>{r:+.2f}R</b>"
        )

    if not rs:
        return

    total = sum(rs)
    avg = total/len(rs)

    tg(
        "<b>📡 RUNNING POSITIONS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n" +
        "\n\n".join(blocks) +
        "\n\n━━━━━━━━━━━━━━━━━━\n"
        f"Open Positions : {len(h['open'])}\n"
        f"Profitable     : {sum(x>0 for x in rs)}\n"
        f"Negative       : {sum(x<0 for x in rs)}\n"
        f"Floating R     : <b>{total:+.2f}R</b>\n"
        f"Average Float  : {avg:+.2f}R\n"
        f"Best           : {max(rs):+.2f}R\n"
        f"Worst          : {min(rs):+.2f}R\n\n"
        f"TP Potential   : +{sum(float(x.get('rr', RR)) for x in h['open']):.2f}R\n"
        f"SL Exposure    : -{len(h['open']):.2f}R\n\n"
        "⚠️ Floating R is unrealized."
    )

def stats(h):
    ts = h["closed"]
    if not ts:
        return

    wins = [x for x in ts if x.get("result") == "WIN"]
    losses = [x for x in ts if x.get("result") == "LOSS"]
    total_r = sum(float(x.get("result_r",0)) for x in ts)
    gp = sum(max(float(x.get("result_r",0)),0) for x in ts)
    gl = abs(sum(min(float(x.get("result_r",0)),0) for x in ts))
    pf = gp/gl if gl else float("inf")

    eq = peak = dd = 0
    for x in ts:
        eq += float(x.get("result_r",0))
        peak = max(peak, eq)
        dd = max(dd, peak-eq)

    pf_text = "∞" if math.isinf(pf) else f"{pf:.2f}"

    rrs = [float(x.get("rr", RR)) for x in ts]
    avg_rr = sum(rrs) / len(rrs)
    bep = 100 / (1 + avg_rr)

    groups = {}
    for x in ts:
        groups.setdefault(x.get("setup", "PULLBACK"), []).append(x)
    by_setup = ""
    for k, arr in groups.items():
        w = sum(1 for x in arr if x.get("result") == "WIN")
        tr_ = sum(float(x.get("result_r", 0)) for x in arr)
        by_setup += (
            f"\n{SETUP_NAME.get(k, k)}: {len(arr)} trade · "
            f"WR {w/len(arr)*100:.0f}% · {tr_:+.2f}R"
        )

    tg(
        "<b>📊 V4.0 PERFORMANCE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Trades        : {len(ts)}\n"
        f"Wins          : {len(wins)}\n"
        f"Losses        : {len(losses)}\n"
        f"Win Rate      : <b>{len(wins)/len(ts)*100:.2f}%</b>\n"
        f"Total R       : <b>{total_r:+.2f}R</b>\n"
        f"Avg R/Trade   : {total_r/len(ts):+.3f}R\n"
        f"Profit Factor : {pf_text}\n"
        f"Max Drawdown  : -{dd:.2f}R\n"
        f"Avg RR Target : 1:{avg_rr:.2f}\n"
        f"BEP WR        : <b>{bep:.2f}%</b>\n\n"
        f"<b>Per setup</b>{by_setup}"
    )

# ================= SCAN =================

def signal_message(s):
    setup = s.get("setup", "PULLBACK")
    title = {
        "PULLBACK": "TREND PULLBACK",
        "BREAKOUT": "BREAKOUT",
        "MEAN_REV": "MEAN REVERSION"
    }.get(setup, setup)

    if setup == "PULLBACK":
        head = (
            f"{s['timeframe']} | {title} | Score <b>{s['score']}/100</b>\n"
            f"Regime: {s['regime']}\n"
            f"Structure: {s['structure']}\n"
            f"BOS: {s['bos']}\n\n"
        )
    else:
        head = (
            f"{s['timeframe']} | <b>{title}</b>\n"
            f"{_safe(s.get('note', ''))}\n\n"
        )

    return (
        "<b>🚨 ALPHAQUANT V4.0 SIGNAL</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"<b>{s['symbol']}</b> · <b>{s['direction']}</b>\n" +
        head +
        "<b>TRADE PLAN</b>\n"
        f"Entry: <code>{s['entry']}</code>\n"
        f"SL: <code>{s['sl']}</code>\n"
        f"TP: <code>{s['tp']}</code>\n"
        f"RR: <b>1:{float(s.get('rr', RR)):.2f}</b>\n"
        f"SL: {s['sl_atr']:.2f} ATR\n\n"
        "<b>FILTERS</b>\n"
        f"RSI: {s['rsi']:.2f}\n"
        f"ADX: {s['adx']:.2f}\n"
        f"Volume: {s['volume_ratio']:.2f}x\n"
        f"EMA50: {s['ema50']:.8f}\n"
        f"EMA200: {s['ema200']:.8f}\n\n"
        f"Risk: {s['risk_usdt']:.2f} USDT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ SIGNAL ONLY — NO AUTO EXECUTION\n"
        f"Candle: {s['signal_candle_iso']}"
    )

def scan(h):
    """Returns True when the scan completed (or was deliberately skipped)."""
    REJECTS.clear()

    if len(h["open"]) >= MAX_OPEN:
        log.info("Max open positions reached.")
        tg(
            "<b>🔎 SCAN REPORT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Scan dilewati: posisi open sudah maksimal ({MAX_OPEN})."
        )
        return True

    pairs = top_pairs()
    meta = instruments()

    if not pairs:
        log.warning("No pairs returned by OKX; scan aborted.")
        return False

    log.info("Scanning %s pairs on %s...", len(pairs), TIMEFRAME)
    created = 0
    scanned = 0
    last_ts = None
    new_signals = []

    for inst in pairs:
        if len(h["open"]) >= MAX_OPEN:
            break

        scanned += 1

        try:
            cs = candles(inst, TIMEFRAME, HISTORY_BARS)
            if len(cs) < MIN_HISTORY_BARS:
                log.info(
                    "SKIP %s | only %s confirmed candles "
                    "(need %s for EMA200/structure)",
                    inst, len(cs), MIN_HISTORY_BARS
                )
                _rej(inst, "Data", f"hanya {len(cs)} candle", setup="ALL")
                continue

            last_ts = max(last_ts or 0, cs[-1][0])

            s = build_signal(inst, cs, meta)
            if not s:
                continue

            if blocked(h, s):
                _rej(
                    inst, "Diblokir",
                    f"{s['direction']} {SETUP_NAME.get(s['setup'], '')} "
                    "duplikat/cooldown/posisi open",
                    setup="ALL"
                )
                continue

            h["open"].append(s)
            save_history(h)
            new_signals.append(s)

            log.info(
                "NEW SIGNAL %s %s %s rr=%s",
                s["symbol"], s["direction"], s["setup"], s["rr"]
            )
            created += 1

        except Exception as e:
            log.exception("Scan error %s: %s", inst, e)
            _rej(inst, "Error", str(e)[:60], setup="ALL")

    log.info("Scan complete. New signals: %s", created)

    # Signals are sent after the loop so each one can carry the
    # complete rejection summary of this scan.
    footer = reject_summary(scanned, created, last_ts, compact=True)
    for sig in new_signals:
        tg(signal_message(sig) + footer)
        time.sleep(0.3)

    tg(reject_summary(scanned, created, last_ts))
    return True

# ================= MAIN =================

def main():
    global TELEGRAM

    log.info("==========================================")
    log.info("ALPHAQUANT V4.0 STARTING")
    log.info("==========================================")

    if not TOKEN or not CHAT_ID:
        TELEGRAM = False
        missing = []
        if not TOKEN:
            missing.append("TELEGRAM_TOKEN")
        if not CHAT_ID:
            missing.append("CHAT_ID")
        log.warning(
            "Telegram disabled. Missing Secret/Environment variable: %s",
            ", ".join(missing)
        )
        log.warning(
            "GitHub: Settings > Secrets and variables > Actions"
        )
    else:
        TELEGRAM = True
        log.info("Telegram credentials detected. Notifications ENABLED.")

    h = load_history()

    log.info(
        "Open trades: %s | Closed trades: %s",
        len(h["open"]), len(h["closed"])
    )
    log.info(
        "Config | TF=%s | Monitor=%s | RR=1:%.1f | "
        "MinHistory=%s | History=%s | Telegram=%s | RunForever=%s",
        TIMEFRAME, MONITOR_TF, RR, MIN_HISTORY_BARS, HISTORY_FILE,
        "ON" if TELEGRAM else "OFF", RUN_FOREVER
    )

    if TELEGRAM:
        tg(
            "<b>🟢 ALPHAQUANT V4.0 ONLINE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "4H Multi-Setup Engine\n"
            "Pullback • Breakout • Mean Reversion\n"
            "EMA • Structure • BB • RSI • ADX • ATR • Volume\n"
            "Signal-only\n"
            "Candle pagination: ENABLED"
        )

    # GitHub Actions mode: execute exactly one cycle, then exit.
    # This is required so the workflow can reach its commit/push step.
    cycles = 0

    while True:
        cycles += 1
        started = time.time()

        try:
            log.info("Starting engine cycle...")
            check_open(h)
            running_report(h)
            stats(h)
            ts = latest_candle_ts()
            if ts is not None and h.get("last_scan_candle") == ts:
                log.info(
                    "No new %s candle since %s - scan skipped.",
                    TIMEFRAME, iso(ts)
                )
            else:
                done = scan(h)
                if done and ts is not None:
                    h["last_scan_candle"] = ts
            save_history(h)
        except KeyboardInterrupt:
            log.info("Engine stopped.")
            break
        except Exception as e:
            log.exception("MAIN LOOP ERROR: %s", e)

        elapsed = time.time() - started
        log.info(
            "Cycle finished in %.1fs. History: %s | Open: %s | Closed: %s",
            elapsed, HISTORY_FILE, len(h["open"]), len(h["closed"])
        )

        if not RUN_FOREVER:
            log.info("RUN_ONCE mode: exiting for GitHub Actions.")
            break

        sleep_for = max(10, SCAN_INTERVAL - elapsed)
        log.info(
            "Cycle finished. Sleeping %.1f seconds.",
            sleep_for
        )
        time.sleep(sleep_for)

if __name__ == "__main__":
    main()
