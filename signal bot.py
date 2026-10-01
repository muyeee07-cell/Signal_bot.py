"""
ALPHAQUANT V4.2
4H Multi-Setup + BTC 15m Scalping (SMC + ICT) Telegram Signal Engine
Signal-only / OKX USDT perpetuals

Setups:
- PULLBACK  : trend pullback to EMA50 (RR 1:2)  [4H]
- BREAKOUT  : squeeze + 20-candle channel breakout with volume (RR 1:2)  [4H]
- MEAN_REV  : Bollinger reversal in ranging markets, TP at the mean  [4H]
- SMC_SCALP : BTC-only Smart Money Concept scalp (RR 1:1.75)  [15m]
- ICT_SCALP : BTC-only ICT model, killzone + liquidity raid + MSS + FVG  [15m]

V4.2 changes:
- Added ICT_SCALP (BTC-USDT-SWAP, 15m)
  · Killzones in New York time (London / NY AM / NY PM, Silver Bullet flagged)
  · Raid of PDH/PDL, Asian range or London range
  · Market Structure Shift with displacement + Fair Value Gap
  · Entry on FVG retest in discount/premium (OTE flagged)
  · Target = next draw on liquidity (min RR 1:2), fee-aware minimum SL
- One scalp position at a time (SMC or ICT); ICT is evaluated first
- SMC/ICT rejection tallies are appended to the 4H SCAN REPORT
"""

from __future__ import annotations

import os, json, time, math, logging
from datetime import datetime, timezone, timedelta
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

# SMC Scalp (BTC only, 15m)
SMC_TF = "15m"
SMC_TF_MS = 15 * 60_000
SMC_SYMBOL = "BTC-USDT-SWAP"
SMC_HISTORY_BARS = 400        # ~4 days of 15m (ICT needs previous day + Asia range)
SMC_MIN_BARS = 80
SMC_SWING = 3
SMC_RR = 1.75
SMC_MIN_SL_ATR = 0.35
SMC_MAX_SL_ATR = 2.50
SMC_DISP_BODY_MIN = 0.55      # displacement candle body / range
SMC_DISP_ATR_MIN = 0.80       # displacement range vs ATR
SMC_OB_LOOKBACK = 12          # bars to search for order block after sweep
SMC_SWEEP_TOL_ATR = 0.15      # wick must pierce swing by this many ATR
SMC_CONFIRM_BARS = 1          # confirmation must be the latest candle (entry = its close)
SMC_COOLDOWN_HOURS = 4        # shorter cooldown for scalp

# ICT Scalp (BTC only, 15m) - session times are New York local time
ICT_ENABLED = os.getenv("ICT_ENABLED", "1") == "1"
ICT_USE_KILLZONE = os.getenv("ICT_USE_KILLZONE", "1") == "1"
ICT_KILLZONES = [
    ("London", 2.0, 5.0),
    ("NY AM", 7.0, 11.0),
    ("NY PM", 13.5, 16.0),
]
ICT_SILVER_BULLET = [(3.0, 4.0), (10.0, 11.0), (14.0, 15.0)]
ICT_MIN_BARS = 300
ICT_MIN_PD_BARS = 80          # candles needed to trust previous-day H/L
ICT_SWING = 2
ICT_RAID_LOOKBACK = 24        # bars back to look for the raid candle
ICT_RAID_TOL_ATR = 0.10       # wick must pierce the level by this many ATR
ICT_MSS_MAX = 8               # bars after the raid to print the MSS
ICT_RETEST_MAX = 12           # bars after the MSS to retest the FVG
ICT_DISP_BODY_MIN = 0.55
ICT_DISP_ATR_MIN = 0.80
ICT_FVG_MIN_ATR = 0.10
ICT_MAX_PD = 0.50             # entry must be in discount (long) / premium (short)
ICT_OTE = (0.21, 0.38)        # 62-79% retracement, expressed from the leg low
ICT_SL_BUFFER_ATR = 0.15
ICT_MIN_SL_ATR = 0.50
ICT_MAX_SL_ATR = 2.50
ICT_MIN_SL_PCT = 0.0015       # SL must be >= 0.15% of price (round-trip fee ~0.10%)
ICT_MIN_RR = 2.0
ICT_MAX_RR = 4.0

SCALP_SETUPS = ("SMC_SCALP", "ICT_SCALP")

# Adaptive 15m (regime switching, fee-aware, multi-symbol).
# Backtest-only: NOT wired into the live scan loop until it passes validation.
AD_HISTORY_BARS = 500          # 15m candles (125 hours -> enough for 1H EMA50 / ADX)
AD_MIN_BARS = 300
AD_COOLDOWN_HOURS = 1.0
AD_ADX_TREND = 22.0            # 1H ADX at/above -> trending
AD_ADX_RANGE = 18.0            # 1H ADX at/below -> ranging (18-22 = no trade)
AD_MIN_ATR_PCT = 0.0035        # 15m ATR must be >= 0.35% of price (fees stay small vs R)
AD_MAX_ATR_PCT = 0.0300        # ... and <= 3% (too wild)
AD_SPIKE_MAX = 2.5             # skip when ATR is > 2.5x its 24h median (news / chaos)
AD_PB_LOOKBACK = 5             # bars to look back for the pullback to EMA21
AD_PB_RSI = 45.0               # RSI must have dipped to this (long) / 100-this (short)
AD_BODY_MIN = 0.50             # reclaim candle body / range
AD_SL_BUFFER_ATR = 0.20
AD_MIN_SL_ATR = 0.8
AD_MAX_SL_ATR = 3.0
AD_MIN_RISK_PCT = 0.005        # SL distance >= 0.5% of price -> taker fees <= 0.2R
AD_RR_TREND = 2.0
AD_RSI_LOW = 35.0              # range module: oversold / overbought (RSI(14) rarely hits 30 on a 2-sigma close)
AD_RSI_HIGH = 65.0
AD_MIN_RR_RANGE = 1.5          # range module: target = BB mid, at least 1.5R away

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
log = logging.getLogger("V4.2")

S = requests.Session()
S.headers.update({"User-Agent": "ALPHAQUANT-V4.2"})

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
        # last_scan_candle / last_smc_candle are optional keys preserved as-is
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
    "SMC_SCALP": "SMC Scalp",
    "ICT_SCALP": "ICT Scalp",
    "ADAPTIVE": "Adaptive",
    "ALL": "Umum"
}

CUR_SETUP = "ALL"

SMC_STAGES = [
    "Data", "Struktur", "Sweep", "Displacement", "OrderBlock",
    "Retest", "Konfirmasi", "SL/RR", "Diblokir"
]

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

# ================= SMC SCALP (BTC 15m) =================

def _smc_swings(cs, swing=SMC_SWING):
    """Fractal swing highs/lows. Returns lists of (index, price)."""
    highs, lows = [], []
    for i in range(swing, len(cs) - swing):
        h, l = cs[i][2], cs[i][3]
        if all(h >= cs[i - j][2] for j in range(1, swing + 1)) and \
           all(h > cs[i + j][2] for j in range(1, swing + 1)):
            highs.append((i, h))
        if all(l <= cs[i - j][3] for j in range(1, swing + 1)) and \
           all(l < cs[i + j][3] for j in range(1, swing + 1)):
            lows.append((i, l))
    return highs, lows


def _smc_structure(highs, lows):
    """
    Determine last structural bias from swing sequence.
    Returns: bias ('BULL'|'BEAR'|None), event ('BOS'|'CHOCH'|None),
             last_sh, last_sl
    """
    if len(highs) < 2 or len(lows) < 2:
        return None, None, None, None

    sh1, sh0 = highs[-2], highs[-1]
    sl1, sl0 = lows[-2], lows[-1]
    last_sh, last_sl = sh0, sl0

    # Most recent swing event determines bias.
    # Higher high + higher low = bull structure; opposite = bear.
    hh = sh0[1] > sh1[1]
    hl = sl0[1] > sl1[1]
    lh = sh0[1] < sh1[1]
    ll = sl0[1] < sl1[1]

    if hh and hl:
        return "BULL", "BOS", last_sh, last_sl
    if lh and ll:
        return "BEAR", "BOS", last_sh, last_sl
    # CHOCH: only one side of structure flips
    if hh and ll:
        # conflict – use the more recent swing
        if sh0[0] > sl0[0]:
            return "BULL", "CHOCH", last_sh, last_sl
        return "BEAR", "CHOCH", last_sh, last_sl
    if lh and hl:
        if sl0[0] > sh0[0]:
            return "BEAR", "CHOCH", last_sh, last_sl
        return "BULL", "CHOCH", last_sh, last_sl
    return None, None, last_sh, last_sl


def _find_order_block(cs, side, start_i, end_i):
    """
    Order block = last opposing candle before the impulse that caused the
    structure break / sweep recovery.
    LONG  → last bearish candle (close < open) in [start_i, end_i)
    SHORT → last bullish candle
    Returns (index, high, low) or None.
    """
    if start_i < 0:
        start_i = 0
    end_i = min(end_i, len(cs))
    for i in range(end_i - 1, start_i - 1, -1):
        o, cl = cs[i][1], cs[i][4]
        if side == "LONG" and cl < o:
            return i, cs[i][2], cs[i][3]
        if side == "SHORT" and cl > o:
            return i, cs[i][2], cs[i][3]
    return None


def _is_displacement(c, atr_v, side):
    """Strong impulse candle in the trade direction."""
    o, hi, lo, cl = c[1], c[2], c[3], c[4]
    rng = hi - lo
    if rng <= 0 or not atr_v:
        return False
    body = abs(cl - o) / rng
    atr_mult = rng / atr_v
    if body < SMC_DISP_BODY_MIN or atr_mult < SMC_DISP_ATR_MIN:
        return False
    if side == "LONG":
        return cl > o
    return cl < o


def _smc_attempt(inst, cs, meta, a, rs, highs, lows, side, sweep_idx, swept_level):
    """
    Run steps 2-6 for ONE sweep candidate.
    Returns a signal dict, or (stage, detail) describing why it failed.
    """
    # Structure is judged on swings that existed BEFORE the sweep. The sweep
    # candle's own wick later becomes a swing low/high and must not flip the bias.
    pre_h = [x for x in highs if x[0] < sweep_idx]
    pre_l = [x for x in lows if x[0] < sweep_idx]
    bias, event, _, _ = _smc_structure(pre_h, pre_l)
    if bias is None:
        return "Struktur", "bias struktur tidak jelas"

    if bias != ("BULL" if side == "LONG" else "BEAR") and event != "CHOCH":
        return "Struktur", f"sweep {side} tapi bias {bias} (bukan CHOCH)"

    # --- Displacement after the sweep ---
    disp_idx = None
    for i in range(sweep_idx, min(sweep_idx + 6, len(cs))):
        if _is_displacement(cs[i], a, side):
            disp_idx = i
            break
    if disp_idx is None:
        return "Displacement", f"{side} tidak ada displacement setelah sweep"

    # --- Order block: last opposing candle before displacement ---
    ob = _find_order_block(cs, side, max(0, disp_idx - SMC_OB_LOOKBACK), disp_idx)
    if ob is None:
        return "OrderBlock", f"{side} order block tidak ditemukan"
    ob_i, ob_hi, ob_lo = ob

    # --- Retest of the order block AFTER the displacement candle ---
    confirm_idx = None
    mid_ob = (ob_hi + ob_lo) / 2
    for i in range(max(ob_i + 1, disp_idx + 1, len(cs) - 8), len(cs)):
        c = cs[i]
        if side == "LONG" and c[4] < ob_lo:
            return "Retest", "LONG order block ditembus (close di bawah OB)"
        if side == "SHORT" and c[4] > ob_hi:
            return "Retest", "SHORT order block ditembus (close di atas OB)"

        tapped = c[3] <= ob_hi and c[2] >= ob_lo
        if not tapped:
            continue
        if side == "LONG" and c[4] > mid_ob and c[4] > c[1]:
            confirm_idx = i
            break
        if side == "SHORT" and c[4] < mid_ob and c[4] < c[1]:
            confirm_idx = i
            break

    if confirm_idx is None:
        return "Retest", f"{side} belum retest order block"

    # Confirmation must be the latest candle (entry = its close)
    if confirm_idx < len(cs) - SMC_CONFIRM_BARS:
        return (
            "Konfirmasi",
            f"{side} konfirmasi terlalu lama ({len(cs) - 1 - confirm_idx} bar lalu)"
        )

    close = cs[-1][4]

    # SL: beyond the OB extreme, the swept level and the sweep wick
    if side == "LONG":
        sweep_ext = cs[sweep_idx][3]
        sl_raw = min(ob_lo, swept_level, sweep_ext) - SL_ATR_BUFFER * a
        risk = close - sl_raw
    else:
        sweep_ext = cs[sweep_idx][2]
        sl_raw = max(ob_hi, swept_level, sweep_ext) + SL_ATR_BUFFER * a
        risk = sl_raw - close

    if risk <= 0:
        return "SL/RR", f"{side} SL tidak valid"

    sl_atr = risk / a
    if not SMC_MIN_SL_ATR <= sl_atr <= SMC_MAX_SL_ATR:
        return (
            "SL/RR",
            f"{side} SL {sl_atr:.2f} ATR (perlu {SMC_MIN_SL_ATR}-{SMC_MAX_SL_ATR})"
        )

    tp_raw = close + SMC_RR * risk if side == "LONG" else close - SMC_RR * risk

    tick = meta.get(inst, {}).get("tick", 0.1)
    entry = tick_round(close, tick)
    sl = tick_round(sl_raw, tick)
    tp = tick_round(tp_raw, tick)

    note = (
        f"SMC {event or 'BOS'} {bias} | "
        f"Sweep {'low' if side == 'LONG' else 'high'} @ {swept_level:.2f} | "
        f"OB [{ob_lo:.2f}-{ob_hi:.2f}] | "
        f"Disp bar {disp_idx} | RSI {rs[-1]:.1f}"
    )

    return {
        "signal_id": f"{inst}|{side}|{cs[-1][0]}|SMC",
        "symbol": inst,
        "direction": side,
        "timeframe": SMC_TF,
        "setup": "SMC_SCALP",
        "note": note,
        "signal_candle_time": cs[-1][0],
        "signal_candle_iso": iso(cs[-1][0]),
        "created_at": now(),
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": SMC_RR,
        "atr": a,
        "sl_atr": sl_atr,
        "ema50": 0.0,
        "ema200": 0.0,
        "rsi": rs[-1],
        "adx": 0.0,
        "volume_ratio": volume_ratio(cs, VOL_PERIOD) or 0.0,
        "regime": bias or "-",
        "structure": event or "-",
        "bos": event or "NONE",
        "pullback": None,
        "score": None,
        "score_reasons": [],
        "risk_usdt": ACCOUNT_EQUITY * RISK_PER_TRADE,
        "status": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "result_r": None,
        "result": None,
        "monitor_tf_ms": SMC_TF_MS,
    }


def build_smc_scalp(inst, cs, meta):
    """
    BTC-only 15m Smart Money Concept scalp (long; short is mirrored):
      1. Liquidity sweep of a recent swing (wick through, close back inside)
      2. Structure BEFORE the sweep agrees with the trade (BOS/CHOCH)
      3. Displacement candle after the sweep
      4. Order block = last opposing candle before the displacement
      5. Price retests the OB AFTER the displacement and prints a
         confirmation candle (must be the latest candle)
      6. Entry at close, SL beyond OB / swept level / sweep wick, TP at SMC_RR
    Both directions are evaluated; the first valid one wins.
    """
    global CUR_SETUP
    CUR_SETUP = "SMC_SCALP"

    if inst != SMC_SYMBOL:
        return _rej(inst, "Data", "bukan BTC")

    if len(cs) < SMC_MIN_BARS:
        return _rej(inst, "Data", f"hanya {len(cs)} candle (min {SMC_MIN_BARS})")

    at = atr(cs, ATR_PERIOD)
    rs = rsi(cs, RSI_PERIOD)
    if at[-1] is None or rs[-1] is None:
        return _rej(inst, "Data", "indikator belum siap")

    a = at[-1]
    if a <= 0:
        return _rej(inst, "Data", "ATR nol")

    highs, lows = _smc_swings(cs, SMC_SWING)
    if len(highs) < 2 or len(lows) < 2:
        return _rej(inst, "Struktur", "swing high/low kurang dari 2")

    # --- Sweep candidates (last 15 bars), newest first, both directions ---
    cands = []
    for side in ("LONG", "SHORT"):
        pool = lows if side == "LONG" else highs
        for abs_i in range(len(cs) - 1, max(0, len(cs) - 15) - 1, -1):
            c = cs[abs_i]
            for si, p in pool:
                if si >= abs_i or abs_i - si > 30:
                    continue
                if side == "LONG":
                    ok = (p - c[3]) / a >= SMC_SWEEP_TOL_ATR and c[4] > p
                else:
                    ok = (c[2] - p) / a >= SMC_SWEEP_TOL_ATR and c[4] < p
                if ok:
                    cands.append((side, abs_i, p))
                    break

    if not cands:
        return _rej(inst, "Sweep", "tidak ada liquidity sweep terkini")

    best = None
    for side, sweep_idx, swept in cands:
        res = _smc_attempt(inst, cs, meta, a, rs, highs, lows, side, sweep_idx, swept)
        if isinstance(res, dict):
            return res
        stage, detail = res
        depth = SMC_STAGES.index(stage)
        if best is None or depth > best[0]:
            best = (depth, stage, detail)

    return _rej(inst, best[1], best[2])


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

# ================= ICT SCALP (BTC 15m) =================

try:
    from zoneinfo import ZoneInfo
    ICT_TZ = ZoneInfo("America/New_York")
except Exception:                                   # pragma: no cover
    ICT_TZ = timezone(timedelta(hours=-4))          # EDT fallback, no DST

ICT_STAGES = [
    "Data", "Sesi", "Raid", "MSS", "FVG", "Retest", "Discount",
    "SL/RR", "Diblokir"
]

_LEVEL_FLIP = {
    "PDL": "PDH", "PDH": "PDL",
    "Asia Low": "Asia High", "Asia High": "Asia Low",
    "London Low": "London High", "London High": "London Low",
    "Swing High": "Swing Low"
}

def _ny(ms):
    return datetime.fromtimestamp(ms / 1000, ICT_TZ)

def _hfrac(dt):
    return dt.hour + dt.minute / 60

def ict_session(close_ms):
    """(killzone name | None, silver-bullet flag) for a candle close time."""
    x = _hfrac(_ny(close_ms))
    kz = next((n for n, a, b in ICT_KILLZONES if a < x <= b), None)
    sb = any(a < x <= b for a, b in ICT_SILVER_BULLET)
    return kz, sb

def _ict_levels(view):
    """
    Key liquidity from a candle view (LONG orientation).
    raid   : lows that can be raided  -> PDL, Asia Low, London Low
    target : highs price can run to   -> PDH, Asia High, London High
    mo     : NY midnight open
    """
    last = _ny(view[-1][0])
    d0 = last.date()
    prev = d0 - timedelta(days=1)

    pdc, asia, lon, today = [], [], [], []
    for v in view:
        t = _ny(v[0])
        if t.date() == prev:
            pdc.append(v)
            if t.hour >= 20:
                asia.append(v)
        elif t.date() == d0:
            today.append(v)
            if 2 <= t.hour < 5:
                lon.append(v)

    raid, target = {}, {}
    if len(pdc) >= ICT_MIN_PD_BARS:
        raid["PDL"] = min(x[3] for x in pdc)
        target["PDH"] = max(x[2] for x in pdc)
    if len(asia) >= 12:
        raid["Asia Low"] = min(x[3] for x in asia)
        target["Asia High"] = max(x[2] for x in asia)
    if len(lon) >= 10 and _hfrac(last) >= 5:
        raid["London Low"] = min(x[3] for x in lon)
        target["London High"] = max(x[2] for x in lon)

    mo = None
    if today:
        t0 = _ny(today[0][0])
        if t0.hour == 0 and t0.minute == 0:
            mo = today[0][1]
    return raid, target, mo

def _pa(x):
    return f"{abs(x):.8g}"

def _ict_seq(view, a, side, j, lvl_name, lvl, tgt_lv, mo, swh, swh3):
    n = len(view)
    r = n - 1
    op = [x[1] for x in view]
    hi = [x[2] for x in view]
    lo = [x[3] for x in view]
    cl = [x[4] for x in view]

    # Short-term high the price must take out to confirm the shift (MSS)
    # (latest swing high within 12 bars before the raid, else the 6-bar high)
    prior = [p for i, p in swh if j - 12 <= i < j]
    sh = prior[-1] if prior else max(hi[max(0, j - 6):j])

    m = None
    for k in range(j + 1, min(j + ICT_MSS_MAX, r - 2) + 1):
        rng = hi[k] - lo[k]
        if rng <= 0:
            continue
        body = cl[k] - op[k]
        if (cl[k] > sh + 0.05 * a and body > 0 and
                body >= ICT_DISP_BODY_MIN * rng and rng >= ICT_DISP_ATR_MIN * a):
            m = k
            break
    if m is None:
        return "MSS", f"{side} belum ada displacement yang close melewati {_pa(sh)}"

    raid_ext = min(lo[j:m + 1])
    if min(lo[m + 1:]) <= raid_ext:
        return "MSS", f"{side} setup batal: ekstrem raid ditembus lagi"

    gap = lo[m + 1] - hi[m - 1]
    if gap < ICT_FVG_MIN_ATR * a:
        return "FVG", f"{side} gap {max(gap, 0) / a:.2f} ATR (min {ICT_FVG_MIN_ATR})"
    fvg_bot, fvg_top = hi[m - 1], lo[m + 1]

    if r > m + ICT_RETEST_MAX:
        return "Retest", f"{side} setup kedaluwarsa (retest lebih dari {ICT_RETEST_MAX} bar)"
    if any(lo[i] <= fvg_top for i in range(m + 2, r)):
        return "Retest", f"{side} FVG sudah pernah disentuh (bukan first touch)"
    if lo[r] > fvg_top:
        return "Retest", f"{side} harga belum kembali ke FVG {_pa(fvg_bot)}-{_pa(fvg_top)}"
    if not (cl[r] > op[r] and cl[r] >= fvg_bot):
        return "Retest", f"{side} tap FVG tanpa candle konfirmasi"

    entry = cl[r]
    leg_hi = max(hi[m:r + 1])
    leg = leg_hi - raid_ext
    if leg <= 0:
        return "Discount", f"{side} leg tidak valid"
    pd_ = (entry - raid_ext) / leg
    if pd_ > ICT_MAX_PD:
        zone = "discount" if side == "LONG" else "premium"
        return "Discount", (
            f"{side} entry di {pd_ * 100:.0f}% leg (perlu maks "
            f"{ICT_MAX_PD * 100:.0f}% = {zone})"
        )
    ote = ICT_OTE[0] <= pd_ <= ICT_OTE[1]

    sl = raid_ext - ICT_SL_BUFFER_ATR * a
    risk = entry - sl
    if risk <= 0:
        return "SL/RR", f"{side} SL tidak valid"
    sl_atr = risk / a
    if not ICT_MIN_SL_ATR <= sl_atr <= ICT_MAX_SL_ATR:
        return "SL/RR", (
            f"{side} SL {sl_atr:.2f} ATR (perlu {ICT_MIN_SL_ATR}-{ICT_MAX_SL_ATR})"
        )
    sl_pct = risk / abs(entry)
    if sl_pct < ICT_MIN_SL_PCT:
        return "SL/RR", (
            f"{side} SL {sl_pct * 100:.2f}% (min {ICT_MIN_SL_PCT * 100:.2f}%, fee memakan R)"
        )

    options = [(pr, nm) for nm, pr in tgt_lv.items() if pr > entry]
    options += [(pr, "Swing High") for i, pr in swh3 if pr > entry and i >= r - 96]
    options.sort()

    chosen, best_rr = None, 0.0
    for pr, nm in options:
        rr_ = (pr - entry) / risk
        best_rr = max(best_rr, rr_)
        if rr_ >= ICT_MIN_RR:
            chosen = (pr, nm)
            break
    if not chosen:
        return "SL/RR", (
            f"{side} target likuiditas terdekat hanya {best_rr:.2f}R (min {ICT_MIN_RR})"
        )

    tgt_price, tgt_name = chosen
    tp = min(tgt_price, entry + ICT_MAX_RR * risk)
    rr = (tp - entry) / risk

    return {
        "entry": entry, "sl": sl, "tp": tp, "rr": rr, "sl_atr": sl_atr,
        "level_name": lvl_name, "level": lvl, "raid_ext": raid_ext,
        "mss": sh, "fvg": (fvg_bot, fvg_top), "pd": pd_, "ote": ote,
        "mo": mo, "mo_ok": (mo is not None and entry < mo),
        "target_name": tgt_name, "target": tgt_price,
        "raid_idx": j, "mss_idx": m
    }

def _ict_long(view, a, side):
    n = len(view)
    r = n - 1
    lo = [x[3] for x in view]
    cl = [x[4] for x in view]

    raid_lv, tgt_lv, mo = _ict_levels(view)
    if not raid_lv:
        return "Data", "level kunci (PDL/Asia/London) belum lengkap"

    swh, _ = _smc_swings(view, ICT_SWING)
    swh3, _ = _smc_swings(view, SMC_SWING)

    cands = []
    for j in range(r - 3, max(1, r - ICT_RAID_LOOKBACK) - 1, -1):
        for nm, p in raid_lv.items():
            if lo[j] < p - ICT_RAID_TOL_ATR * a and cl[j] > p:
                cands.append((j, nm, p))

    if not cands:
        return "Raid", f"{side} tidak ada raid likuiditas (PDL/Asia/London) terkini"

    best = None
    for j, nm, p in cands:
        res = _ict_seq(view, a, side, j, nm, p, tgt_lv, mo, swh, swh3)
        if isinstance(res, dict):
            return res
        depth = ICT_STAGES.index(res[0])
        if best is None or depth > best[0]:
            best = (depth, res[0], res[1])
    return best[1], best[2]

def build_ict_scalp(inst, cs, meta):
    """
    BTC-only 15m ICT model (long; short is mirrored by inverting prices):
      1. Signal candle closes inside a killzone (New York time)
      2. Raid of PDL / Asian low / London low (wick through, close back above)
      3. MSS: displacement candle closes above the short-term high
      4. The displacement leaves a Fair Value Gap
      5. First retest of the FVG prints a confirmation candle, entry in
         discount (<= 50% of the leg); 62-79% is flagged as OTE
      6. SL beyond the raid extreme, TP at the next draw on liquidity (>= 1:2)
    """
    global CUR_SETUP
    CUR_SETUP = "ICT_SCALP"

    if inst != SMC_SYMBOL:
        return _rej(inst, "Data", "bukan BTC")
    if len(cs) < ICT_MIN_BARS:
        return _rej(inst, "Data", f"hanya {len(cs)} candle (min {ICT_MIN_BARS})")

    at = atr(cs, ATR_PERIOD)
    rs = rsi(cs, RSI_PERIOD)
    if at[-1] is None or rs[-1] is None or at[-1] <= 0:
        return _rej(inst, "Data", "indikator belum siap")
    a = at[-1]

    close_ms = cs[-1][0] + SMC_TF_MS
    kz, silver = ict_session(close_ms)
    if ICT_USE_KILLZONE and kz is None:
        return _rej(
            inst, "Sesi",
            f"{_ny(close_ms):%H:%M} NY di luar killzone"
        )

    inv = [[x[0], -x[1], -x[3], -x[2], -x[4], x[5]] for x in cs]

    fails = []
    res, side, sign = None, None, 1
    for sd, view, sg in (("LONG", cs, 1), ("SHORT", inv, -1)):
        out = _ict_long(view, a, sd)
        if isinstance(out, dict):
            res, side, sign = out, sd, sg
            break
        fails.append(out)

    if res is None:
        stage, detail = max(fails, key=lambda f: ICT_STAGES.index(f[0]))
        return _rej(inst, stage, detail)

    def flip(nm):
        return _LEVEL_FLIP.get(nm, nm) if side == "SHORT" else nm

    tick = meta.get(inst, {}).get("tick", 0.1)
    entry = tick_round(sign * res["entry"], tick)
    sl = tick_round(sign * res["sl"], tick)
    tp = tick_round(sign * res["tp"], tick)

    fa, fb = sign * res["fvg"][0], sign * res["fvg"][1]
    mo_px = sign * res["mo"] if res["mo"] is not None else None

    conf = sum([
        bool(res["ote"]),
        bool(res["mo_ok"]),
        bool(silver),
        flip(res["level_name"]) in ("PDH", "PDL"),
    ])

    ict = {
        "kz": kz,
        "silver": silver,
        "level": flip(res["level_name"]),
        "level_price": sign * res["level"],
        "raid_extreme": sign * res["raid_ext"],
        "mss": sign * res["mss"],
        "fvg": [min(fa, fb), max(fa, fb)],
        "pd": res["pd"],
        "ote": res["ote"],
        "mo": mo_px,
        "mo_ok": res["mo_ok"],
        "target": flip(res["target_name"]),
        "target_price": sign * res["target"],
        "conf": conf,
    }

    note = (
        f"ICT {kz or 'off-KZ'} | Raid {ict['level']} @ {ict['level_price']:.2f} | "
        f"MSS @ {ict['mss']:.2f} | FVG {ict['fvg'][0]:.2f}-{ict['fvg'][1]:.2f}"
    )

    return {
        "signal_id": f"{inst}|{side}|{cs[-1][0]}|ICT",
        "symbol": inst,
        "direction": side,
        "timeframe": SMC_TF,
        "setup": "ICT_SCALP",
        "note": note,
        "ict": ict,
        "signal_candle_time": cs[-1][0],
        "signal_candle_iso": iso(cs[-1][0]),
        "created_at": now(),
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": round(res["rr"], 2),
        "atr": a,
        "sl_atr": res["sl_atr"],
        "ema50": 0.0,
        "ema200": 0.0,
        "rsi": rs[-1],
        "adx": 0.0,
        "volume_ratio": volume_ratio(cs, VOL_PERIOD) or 0.0,
        "regime": "BULL" if side == "LONG" else "BEAR",
        "structure": "MSS",
        "bos": "NONE",
        "pullback": res["pd"],
        "score": None,
        "score_reasons": [],
        "risk_usdt": ACCOUNT_EQUITY * RISK_PER_TRADE,
        "status": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "result_r": None,
        "result": None,
        "monitor_tf_ms": SMC_TF_MS,
    }

# ================= ADAPTIVE 15m (regime switching) =================

ADAPT_STAGES = [
    "Data", "Vol", "Regime", "Pullback", "Band", "RSI", "Reclaim", "SL/RR"
]

def _median(v):
    t = sorted(v)
    n = len(t)
    if n == 0:
        return 0.0
    return t[n // 2] if n % 2 else (t[n // 2 - 1] + t[n // 2]) / 2

def _resample(cs, bar_ms, base_ms=900_000):
    """
    Aggregate base candles into bar_ms candles (epoch aligned, like OKX 1H/4H).
    Only COMPLETE groups are returned, so there is no look-ahead.
    """
    need = bar_ms // base_ms
    out, cur, cnt = [], None, 0
    for c in cs:
        k = (c[0] // bar_ms) * bar_ms
        if cur is None or cur[0] != k:
            if cur is not None and cnt == need:
                out.append(cur)
            cur, cnt = [k, c[1], c[2], c[3], c[4], c[5]], 1
        else:
            cur[2] = max(cur[2], c[2])
            cur[3] = min(cur[3], c[3])
            cur[4] = c[4]
            cur[5] += c[5]
            cnt += 1
    if cur is not None and cnt == need:
        out.append(cur)
    return out

def build_adaptive(inst, cs, meta):
    """
    Regime-switching 15m model. One rule set per market state, and NO trade
    when the state is unclear or when costs would eat the edge.

      state from 1H:  ADX >= 22 + EMA20/EMA50 aligned -> TREND (up/down)
                      ADX <= 18                         -> RANGE
                      otherwise                         -> skip
      TREND : dip to EMA21 (RSI dipped) then a strong candle that reclaims
              EMA21 in the trend direction. SL beyond the 6-bar swing, TP 2R.
      RANGE : close outside Bollinger(20,2) with extreme RSI, then a candle
              that closes back inside. TP at the Bollinger mid (>= 1.5R).
      GATES : ATR% between 0.35% and 3%, no volatility spike (>2.5x median),
              SL distance >= 0.5% of price (fee drag <= 0.2R).
    """
    S = "ADAPTIVE"

    def rej(stage, detail):
        return _rej(inst, stage, detail, setup=S)

    n = len(cs)
    if n < AD_MIN_BARS:
        return rej("Data", f"hanya {n} candle (min {AD_MIN_BARS})")

    op = [x[1] for x in cs]
    hi = [x[2] for x in cs]
    lo = [x[3] for x in cs]
    cl = [x[4] for x in cs]

    at = atr(cs, ATR_PERIOD)
    rs = rsi(cs, RSI_PERIOD)
    e21 = ema(cl, 21)
    a = at[-1]
    if a is None or a <= 0 or rs[-1] is None or e21[-1] is None:
        return rej("Data", "indikator belum siap")

    close = cl[-1]

    # ---- cost / chaos gates ----
    atr_pct = a / close
    if atr_pct < AD_MIN_ATR_PCT:
        return rej("Vol", f"ATR {atr_pct*100:.2f}% (min {AD_MIN_ATR_PCT*100:.2f}%, fee terlalu besar)")
    if atr_pct > AD_MAX_ATR_PCT:
        return rej("Vol", f"ATR {atr_pct*100:.2f}% terlalu liar (maks {AD_MAX_ATR_PCT*100:.1f}%)")
    med = _median([x for x in at[-96:] if x])
    if med > 0 and a / med > AD_SPIKE_MAX:
        return rej("Vol", f"lonjakan volatilitas {a/med:.1f}x median 24 jam")

    # ---- regime from the 1H series built out of the same candles ----
    h1 = _resample(cs, 3_600_000)
    if len(h1) < 60:
        return rej("Data", f"hanya {len(h1)} candle 1H")
    h1c = [x[4] for x in h1]
    ax1 = adx(h1, ADX_PERIOD)[0][-1]
    e20 = ema(h1c, 20)[-1]
    e50 = ema(h1c, 50)[-1]
    if ax1 is None or e20 is None or e50 is None:
        return rej("Data", "indikator 1H belum siap")
    c1 = h1c[-1]

    if ax1 >= AD_ADX_TREND and e20 > e50 and c1 > e50:
        regime = "UP"
    elif ax1 >= AD_ADX_TREND and e20 < e50 and c1 < e50:
        regime = "DOWN"
    elif ax1 <= AD_ADX_RANGE:
        regime = "RANGE"
    else:
        return rej("Regime", f"ADX 1H {ax1:.1f}: zona abu-abu / tren tidak searah")

    rng = hi[-1] - lo[-1]
    if rng <= 0:
        return rej("Reclaim", "candle tanpa range")
    body = abs(close - op[-1]) / rng

    module = "TREND" if regime in ("UP", "DOWN") else "RANGE"
    tp = None

    if module == "TREND":
        side = "LONG" if regime == "UP" else "SHORT"
        idx = range(n - 1 - AD_PB_LOOKBACK, n - 1)
        if any(e21[i] is None or rs[i] is None for i in idx):
            return rej("Data", "indikator belum siap")

        if side == "LONG":
            touched = any(lo[i] <= e21[i] + 0.15 * a for i in idx)
            dipped = min(rs[i] for i in idx) <= AD_PB_RSI
        else:
            touched = any(hi[i] >= e21[i] - 0.15 * a for i in idx)
            dipped = max(rs[i] for i in idx) >= 100 - AD_PB_RSI
        if not touched:
            return rej("Pullback", f"{side} harga belum menyentuh EMA21 dalam {AD_PB_LOOKBACK} bar")
        if not dipped:
            return rej("Pullback", f"{side} RSI belum terkoreksi (batas {AD_PB_RSI:.0f})")

        if side == "LONG":
            ok = (close > op[-1] and body >= AD_BODY_MIN and close > e21[-1]
                  and cl[-2] <= e21[-2] + 0.10 * a)
        else:
            ok = (close < op[-1] and body >= AD_BODY_MIN and close < e21[-1]
                  and cl[-2] >= e21[-2] - 0.10 * a)
        if not ok:
            return rej("Reclaim", f"{side} belum ada candle kuat yang merebut kembali EMA21")

        sl = (min(lo[-6:]) - AD_SL_BUFFER_ATR * a) if side == "LONG" \
            else (max(hi[-6:]) + AD_SL_BUFFER_ATR * a)

    else:
        mid, up, lb, _ = bollinger(cl, 20, 2.0)
        if None in (mid[-1], up[-1], lb[-1], up[-2], lb[-2], rs[-2]):
            return rej("Data", "Bollinger belum siap")

        out_lo = cl[-2] < lb[-2]
        out_hi = cl[-2] > up[-2]
        if not (out_lo or out_hi):
            d = min(cl[-2] - lb[-2], up[-2] - cl[-2]) / a
            return rej("Band", f"candle sebelumnya {d:.2f} ATR di dalam band")

        side = "LONG" if out_lo else "SHORT"
        if side == "LONG" and rs[-2] > AD_RSI_LOW:
            return rej("RSI", f"LONG RSI {rs[-2]:.1f} (perlu maks {AD_RSI_LOW:.0f})")
        if side == "SHORT" and rs[-2] < AD_RSI_HIGH:
            return rej("RSI", f"SHORT RSI {rs[-2]:.1f} (perlu min {AD_RSI_HIGH:.0f})")

        if side == "LONG":
            ok = close > lb[-1] and close > op[-1]
        else:
            ok = close < up[-1] and close < op[-1]
        if not ok:
            return rej("Reclaim", f"{side} belum menutup kembali di dalam band")

        sl = (min(lo[-3:]) - AD_SL_BUFFER_ATR * a) if side == "LONG" \
            else (max(hi[-3:]) + AD_SL_BUFFER_ATR * a)
        tp = mid[-1]

    # ---- risk gates (shared) ----
    risk = (close - sl) if side == "LONG" else (sl - close)
    if risk <= 0:
        return rej("SL/RR", f"{side} SL tidak valid")
    sl_atr = risk / a
    if not AD_MIN_SL_ATR <= sl_atr <= AD_MAX_SL_ATR:
        return rej("SL/RR", f"{side} SL {sl_atr:.2f} ATR (perlu {AD_MIN_SL_ATR}-{AD_MAX_SL_ATR})")
    risk_pct = risk / close
    if risk_pct < AD_MIN_RISK_PCT:
        return rej("SL/RR", f"{side} SL {risk_pct*100:.2f}% (min {AD_MIN_RISK_PCT*100:.2f}%, fee memakan R)")

    if module == "TREND":
        tp = close + AD_RR_TREND * risk if side == "LONG" else close - AD_RR_TREND * risk
        rr = AD_RR_TREND
    else:
        reward = (tp - close) if side == "LONG" else (close - tp)
        if reward <= 0:
            return rej("SL/RR", f"{side} harga sudah melewati rata-rata band")
        rr = reward / risk
        if rr < AD_MIN_RR_RANGE:
            return rej("SL/RR", f"{side} RR ke rata-rata {rr:.2f} (min {AD_MIN_RR_RANGE})")

    tick = meta.get(inst, {}).get("tick", 0.00000001)
    return {
        "signal_id": f"{inst}|{side}|{cs[-1][0]}|AD",
        "symbol": inst,
        "direction": side,
        "timeframe": "15m",
        "setup": S,
        "note": f"{module} {regime} | ADX1H {ax1:.1f} | ATR {atr_pct*100:.2f}%",
        "module": module,
        "signal_candle_time": cs[-1][0],
        "signal_candle_iso": iso(cs[-1][0]),
        "created_at": now(),
        "entry": tick_round(close, tick),
        "sl": tick_round(sl, tick),
        "tp": tick_round(tp, tick),
        "rr": round(rr, 2),
        "atr": a,
        "sl_atr": sl_atr,
        "ema50": 0.0,
        "ema200": 0.0,
        "rsi": rs[-1],
        "adx": ax1,
        "volume_ratio": volume_ratio(cs, VOL_PERIOD) or 0.0,
        "regime": regime,
        "structure": module,
        "bos": "NONE",
        "pullback": None,
        "score": None,
        "score_reasons": [],
        "risk_usdt": ACCOUNT_EQUITY * RISK_PER_TRADE,
        "status": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "result_r": None,
        "result": None,
        "monitor_tf_ms": 900_000,
    }

# ================= DEDUPE =================

def blocked(h, sig):
    sid = sig["signal_id"]
    if any(x.get("signal_id") == sid for x in h["open"]+h["closed"]):
        return True

    # One open position per symbol within the same book (4H swing vs 15m scalp).
    is_scalp = sig.get("setup") in SCALP_SETUPS
    if any(
        x.get("symbol") == sig["symbol"] and
        (x.get("setup") in SCALP_SETUPS) == is_scalp
        for x in h["open"]
    ):
        return True

    # Scalp uses a shorter cooldown; other setups keep the default.
    cd_h = SMC_COOLDOWN_HOURS if is_scalp else COOLDOWN_HOURS
    cutoff = time.time() - cd_h * 3600
    for x in h["closed"]:
        if x.get("symbol") != sig["symbol"]:
            continue
        # Only apply same-setup cooldown for scalp so 4H and 15m don't block each other
        if (x.get("setup") in SCALP_SETUPS) != is_scalp:
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
    # SMC scalp signals are themselves on 15m → use signal TF length.
    sig_tf_ms = trade.get("monitor_tf_ms") or (
        SMC_TF_MS if trade.get("setup") in SCALP_SETUPS else TF_MS
    )
    start = trade.get("signal_candle_time", 0) + sig_tf_ms

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
        return 0

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

    return len(closed)

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
        "<b>📊 V4.2 PERFORMANCE</b>\n"
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
        "MEAN_REV": "MEAN REVERSION",
        "SMC_SCALP": "SMC SCALP · BTC 15m",
        "ICT_SCALP": "ICT SCALP · BTC 15m",
    }.get(setup, setup)

    if setup == "PULLBACK":
        head = (
            f"{s['timeframe']} | {title} | Score <b>{s['score']}/100</b>\n"
            f"Regime: {s['regime']}\n"
            f"Structure: {s['structure']}\n"
            f"BOS: {s['bos']}\n\n"
        )
    elif setup == "ICT_SCALP":
        x = s.get("ict", {})
        sess = x.get("kz") or "-"
        if x.get("silver"):
            sess += " · Silver Bullet"
        zone = "discount" if s["direction"] == "LONG" else "premium"
        mo_txt = "-"
        if x.get("mo") is not None:
            mo_txt = f"{'✔' if x.get('mo_ok') else '✘'} ({x['mo']:.2f})"
        head = (
            f"{s['timeframe']} | <b>{title}</b>\n"
            f"Sesi: {sess} (NY)\n"
            f"Raid: {x.get('level', '-')} @ {x.get('level_price', 0):.2f}\n"
            f"MSS: close melewati {x.get('mss', 0):.2f}\n"
            f"FVG: {x.get('fvg', [0, 0])[0]:.2f} – {x.get('fvg', [0, 0])[1]:.2f}\n"
            f"Entry di {x.get('pd', 0) * 100:.0f}% leg ({zone}"
            f"{', OTE ✔' if x.get('ote') else ''})\n"
            f"Midnight Open: {mo_txt}\n"
            f"Target: {x.get('target', '-')} @ {x.get('target_price', 0):.2f}\n"
            f"Confluence: <b>{x.get('conf', 0)}/4</b>\n\n"
        )
    elif setup == "SMC_SCALP":
        head = (
            f"{s['timeframe']} | <b>{title}</b>\n"
            f"Structure: {s.get('structure', '-')} · Regime: {s.get('regime', '-')}\n"
            f"{_safe(s.get('note', ''))}\n\n"
        )
    else:
        head = (
            f"{s['timeframe']} | <b>{title}</b>\n"
            f"{_safe(s.get('note', ''))}\n\n"
        )

    filters = (
        f"RSI: {s['rsi']:.2f}\n"
        f"ADX: {s['adx']:.2f}\n"
        f"Volume: {s['volume_ratio']:.2f}x\n"
    )
    if setup not in SCALP_SETUPS:
        filters += (
            f"EMA50: {s['ema50']:.8f}\n"
            f"EMA200: {s['ema200']:.8f}\n"
        )

    return (
        "<b>🚨 ALPHAQUANT V4.2 SIGNAL</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"<b>{s['symbol']}</b> · <b>{s['direction']}</b>\n" +
        head +
        "<b>TRADE PLAN</b>\n"
        f"Entry: <code>{s['entry']}</code>\n"
        f"SL: <code>{s['sl']}</code>\n"
        f"TP: <code>{s['tp']}</code>\n"
        f"RR: <b>1:{float(s.get('rr', RR)):.2f}</b>\n"
        f"SL: {s['sl_atr']:.2f} ATR\n\n" +
        ("" if setup == "ICT_SCALP" else "<b>FILTERS</b>\n" + filters + "\n") +
        f"Risk: {s['risk_usdt']:.2f} USDT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ SIGNAL ONLY — NO AUTO EXECUTION\n"
        f"Candle: {s['signal_candle_iso']}"
    )

def n_swing_open(h):
    return sum(1 for x in h["open"] if x.get("setup") not in SCALP_SETUPS)

def scan(h):
    """Returns True when the scan completed (or was deliberately skipped)."""
    REJECTS.clear()

    if n_swing_open(h) >= MAX_OPEN:
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
        if n_swing_open(h) >= MAX_OPEN:
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

    tg(reject_summary(scanned, created, last_ts) + smc_tally_text(h))
    return True


SMC_RUN = {"evaluated": set(), "signal": None}

SCALP_STAGES = {"SMC_SCALP": SMC_STAGES, "ICT_SCALP": ICT_STAGES}

def _smc_flush(h):
    """Move scalp rejections out of REJECTS into a persistent per-setup tally."""
    rows = {k: REJECTS.pop(k) for k in [k for k in REJECTS if k[0] in SCALP_SETUPS]}

    if not SMC_RUN["evaluated"]:
        return

    root = h.get("smc_rej") or {}
    if "scans" in root:                      # old single-setup format
        root = {"SMC_SCALP": root}

    for setup in SMC_RUN["evaluated"]:
        d = root.get(setup) or {"scans": 0, "signals": 0, "stages": {}, "best": None}
        d["scans"] += 1
        if SMC_RUN["signal"] == setup:
            d["signals"] += 1

        order = SCALP_STAGES[setup]
        for (st_setup, st), v in rows.items():
            if st_setup != setup:
                continue
            d["stages"][st] = d["stages"].get(st, 0) + len(v)
            if st in order and st not in ("Data", "Sesi", "Error"):
                depth = order.index(st)
                if d["best"] is None or depth >= d["best"]["depth"]:
                    d["best"] = {"depth": depth, "stage": st, "detail": v[-1][1]}
        root[setup] = d

    h["smc_rej"] = root

def smc_tally_text(h):
    root = h.get("smc_rej")
    if not root:
        return ""
    if "scans" in root:
        root = {"SMC_SCALP": root}

    blocks = []
    for setup in ("ICT_SCALP", "SMC_SCALP"):
        d = root.get(setup)
        if not d or not d.get("scans"):
            continue
        order = SCALP_STAGES[setup] + ["Error"]
        parts = [f"{st} {d['stages'][st]}" for st in order if d["stages"].get(st)]
        text = (
            f"<b>⚡ {SETUP_NAME[setup]} · BTC 15m</b>\n"
            f"Scan {d['scans']} | Sinyal {d['signals']}\n"
            "Gugur di: " + (" · ".join(parts) if parts else "-")
        )
        if d.get("best"):
            text += f"\nPaling dekat: {d['best']['stage']} — {d['best']['detail']}"
        blocks.append(text)

    h["smc_rej"] = None
    return ("\n\n" + "\n\n".join(blocks)) if blocks else ""

def scan_smc(h):
    SMC_RUN["evaluated"] = set()
    SMC_RUN["signal"] = None
    try:
        return _scan_smc(h)
    finally:
        _smc_flush(h)

def _scan_smc(h):
    """
    BTC-only 15m Smart Money Concept scalp.
    Runs every engine cycle (independent of the 4H candle gate).
    Returns number of new signals created.
    """
    global CUR_SETUP
    # Avoid stacking: one open SMC scalp at a time (4H BTC trades don't block it)
    if any(x.get("setup") in SCALP_SETUPS for x in h["open"]):
        log.info("SMC scalp skipped: a scalp position is already open.")
        return 0

    log.info("SMC scalp scan %s on %s...", SMC_SYMBOL, SMC_TF)

    try:
        cs = candles(SMC_SYMBOL, SMC_TF, SMC_HISTORY_BARS)
        if len(cs) < SMC_MIN_BARS:
            log.info(
                "SMC SKIP %s | only %s confirmed candles (need %s)",
                SMC_SYMBOL, len(cs), SMC_MIN_BARS
            )
            _rej(SMC_SYMBOL, "Data", f"hanya {len(cs)} candle", setup="SMC_SCALP")
            return 0

        # Gate: only act on a new 15m candle (avoid re-firing same bar)
        last_bar = cs[-1][0]
        if h.get("last_smc_candle") == last_bar:
            log.info("SMC: no new 15m candle since %s — skipped.", iso(last_bar))
            return 0

        meta = instruments()   # fetched only when there is a new candle

        # ICT is evaluated first; SMC only if ICT finds nothing this candle.
        s = None
        if ICT_ENABLED:
            SMC_RUN["evaluated"].add("ICT_SCALP")
            s = build_ict_scalp(SMC_SYMBOL, cs, meta)
        if not s:
            SMC_RUN["evaluated"].add("SMC_SCALP")
            s = build_smc_scalp(SMC_SYMBOL, cs, meta)
        CUR_SETUP = "ALL"

        if not s:
            log.info("SMC: no valid setup on this candle.")
            h["last_smc_candle"] = last_bar
            return 0

        if blocked(h, s):
            _rej(
                SMC_SYMBOL, "Diblokir",
                f"{s['direction']} {SETUP_NAME.get(s['setup'], '')} duplikat/cooldown/posisi open",
                setup=s["setup"]
            )
            h["last_smc_candle"] = last_bar
            return 0

        h["open"].append(s)
        SMC_RUN["signal"] = s["setup"]
        h["last_smc_candle"] = last_bar
        save_history(h)

        log.info(
            "NEW %s SIGNAL %s %s rr=%s",
            s["setup"], s["symbol"], s["direction"], s["rr"]
        )
        tg(signal_message(s))
        return 1

    except Exception as e:
        log.exception("SMC scan error: %s", e)
        _rej(SMC_SYMBOL, "Error", str(e)[:60], setup="SMC_SCALP")
        return 0

# ================= MAIN =================

def main():
    global TELEGRAM

    log.info("==========================================")
    log.info("ALPHAQUANT V4.2 STARTING")
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
        "SMC=%s@%s RR=1:%.2f | MinHistory=%s | History=%s | "
        "Telegram=%s | RunForever=%s",
        TIMEFRAME, MONITOR_TF, RR,
        SMC_SYMBOL, SMC_TF, SMC_RR,
        MIN_HISTORY_BARS, HISTORY_FILE,
        "ON" if TELEGRAM else "OFF", RUN_FOREVER
    )

    today = datetime.now(timezone.utc).date().isoformat()
    if TELEGRAM and h.get("last_online_day") != today:
        h["last_online_day"] = today
        tg(
            "<b>🟢 ALPHAQUANT V4.2 ONLINE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "4H Multi-Setup + BTC 15m Scalp (SMC + ICT)\n"
            "Pullback • Breakout • Mean Reversion • SMC Scalp • ICT Scalp\n"
            "EMA • Structure • BB • RSI • ADX • ATR • Volume\n"
            "SMC: Sweep · Order Block · Displacement | ICT: Killzone · Raid · MSS · FVG\n"
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
            closed_n = check_open(h)

            ts = latest_candle_ts()
            new_4h = ts is None or h.get("last_scan_candle") != ts

            # Periodic reports only on a new 4H candle (or when a trade closed),
            # so a 15-minute schedule does not flood Telegram.
            if new_4h:
                running_report(h)
                stats(h)
            elif closed_n:
                stats(h)

            # --- BTC 15m SMC scalp (every cycle, gated on new 15m bar) ---
            scan_smc(h)

            # --- 4H multi-setup (gated on new 4H candle) ---
            if not new_4h:
                log.info(
                    "No new %s candle since %s - 4H scan skipped.",
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
