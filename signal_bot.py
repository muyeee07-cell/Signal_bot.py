"""
ALPHAQUANT MURPHY V6.0
Murphy Pullback Scalp 15m - Telegram signal engine (signal-only) for the top 50 OKX USDT perpetuals

Strategy source: John J. Murphy, "Technical Analysis of the Financial Markets".
The SMC engine of V5.x was replaced; the infrastructure (OKX data, Telegram, history file,
TP/SL monitor, reports, crowding limits, adaptive mode) is unchanged.

Rules (LONG; SHORT mirrors):
  1. Trend      MA9 > MA18, MA18 rising, price above MA18, and the 1H trend agrees
  2. Pullback   low touches MA9 within PULL_N bars, closes never break MA18
  3. Trigger    bullish candle closes back above a rising MA4 (Murphy "buying alert")
  4. RSI(14)    lowest RSI of the pullback is between 35 and 55
  5. Stoch      (14,3,3) %K crosses above %D (within the last 3 candles) after being <= 40
  6. MACD       (12,26,9) histogram rising
  7. Volume     signal candle >= average volume
  8. Bollinger  (20,2) no squeeze, opposite band at least 0.5R away
  Entry = close of the signal candle, SL beyond the pullback extreme, TP at TARGET_RR (1.75).

Modes
  python signal_bot_murphy.py                      live scan (GitHub Actions: run every 15 min)
  python signal_bot_murphy.py selftest             offline check on synthetic candles
  python signal_bot_murphy.py backtest BTC-USDT-SWAP ETH-USDT-SWAP --bars 5000
  python signal_bot_murphy.py ablation [PAIR ...] --bars 3000   matikan tiap filter bergantian, bandingkan

Backtest uses the exact same engine as live. Treat every signal as unproven until a
backtest on the pairs you actually scan shows an edge after fees.
Old SMC trades that are still open keep being monitored; once closed they go to h["archive"].
"""

from __future__ import annotations

import os, sys, json, time, math, logging
from datetime import datetime, timezone
import requests

# ================= CONFIG =================

OKX = "https://www.okx.com"

def env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""

TOKEN = env_first("TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
CHAT_ID = env_first("CHAT_ID", "TELEGRAM_CHAT_ID", "TELEGRAM_CHAT")

# --- Murphy pullback scalp ---
# Based on John J. Murphy, "Technical Analysis of the Financial Markets":
# MA 4-9-18 trend (ch. 9), Bollinger bands (ch. 9), RSI / Stochastic / MACD (ch. 10),
# volume confirmation (ch. 7), trade with the major trend (ch. 10).
SETUP_ID = "MURPHY_PULLBACK"


def env_num(default, *names):
    """First env var that is set, converted to the type of `default`."""
    v = env_first(*names)
    if not v:
        return default
    try:
        return type(default)(v)
    except ValueError:
        return default


def parse_hours(spec):
    """'8-15,22' -> {8..15, 22}. Empty string = no blocked hours."""
    out = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo = int(a)
        hi = int(b) if b else lo
        out.update(range(lo, hi + 1))
    return out


TF = "15m"
TF_MS = 15 * 60_000
MONITOR_TF = "5m"                      # finer candles to resolve TP/SL of open scalps
MONITOR_MS = 5 * 60_000
REF_SYMBOL = "BTC-USDT-SWAP"           # reference symbol for the "new 15m candle" gate
HISTORY_BARS = env_num(300, "HISTORY_BARS")
MIN_BARS = 150

# ---- CORE ----
TARGET_RR = env_num(1.75, "TARGET_RR")

# ---- 1. trend: MA 4-9-18 (Murphy p.204-206) + 1H filter ----
MA_FAST, MA_MID, MA_SLOW = 4, 9, 18
HTF_FILTER = env_first("HTF_FILTER") != "0"          # 1H trend must agree (needs ~25 h of 15m data)
HOLD_ATR = 0.5                                       # pullback may not close further than 0.5 ATR through MA18

# ---- 2. pullback window / RSI zone (50 acts as support in pullbacks, p.245) ----
PULL_N = env_num(6, "PULL_N")                        # bars in the pullback window
RSI_PULL_HI = env_num(55.0, "RSI_PULL_HI")           # LONG: lowest RSI of the window must be <= this
RSI_FLOOR = env_num(35.0, "RSI_FLOOR")               # ...and >= this (not a collapse). SHORT mirrors (100-x)

# ---- 3. Stochastic (14,3,3) cross from the extreme zone (p.248-249) ----
ST_N, ST_SMOOTH, ST_D = 14, 3, 3
ST_OS = env_num(40.0, "ST_OS")                       # book uses 20/80; looser for pullbacks in a trend
STOCH_LOOKBACK = max(1, env_num(3, "STOCH_LOOKBACK"))  # %K/%D cross may be up to this many candles old (1 = this candle only)

# ---- 4. MACD 12-26-9 histogram turning with the trade (p.252-255) ----
MACD_FAST, MACD_SLOW, MACD_SIG = 12, 26, 9

# ---- 5. volume must confirm (p.174) ----
MIN_VOLUME_RATIO = env_num(1.0, "MIN_VOLUME_RATIO")  # signal-candle volume / average of the last VOL_PERIOD

# ---- 6. Bollinger 20/2: no squeeze, room to the opposite band (p.209-211) ----
BB_N, BB_K = 20, 2.0
BW_LOOKBACK = 100
BW_MIN_PCT = env_num(0.20, "BW_MIN_PCT")             # skip when band width is in the lowest 20%
BB_MIN_R = env_num(0.5, "BB_MIN_R")                  # band must be >= this many R away from entry (0 = off)

# ---- stop / cost gates ----
MIN_SL_ATR = 0.35
MAX_SL_ATR = 2.50
MAX_RISK_PCT = env_num(0.015, "MAX_RISK_PCT")
MIN_RISK_PCT = env_num(0.004, "MIN_RISK_PCT", "SMC_MIN_RISK_PCT")      # 0 disables the cost gate
# Separate cost gate for BTC only. Negative = use MIN_RISK_PCT.
MIN_RISK_PCT_BTC = env_num(-1.0, "MIN_RISK_PCT_BTC", "SMC_MIN_RISK_PCT_BTC")
MAX_OPEN = env_num(5, "MAX_OPEN", "SMC_MAX_OPEN")
COOLDOWN_HOURS = 4

# ---- POSITION CROWDING (0 = no limit) ----
MAX_ACTIVE_PER_DIRECTION = env_num(3, "MAX_ACTIVE_PER_DIRECTION", "MAX_ACTIVE_SMC_PER_DIRECTION")
MAX_NEW_PER_CANDLE = env_num(1, "MAX_NEW_PER_CANDLE", "MAX_NEW_SMC_PER_CANDLE")

# ---- session gate: UTC hours of the signal candle to skip (default none; was 8-15 for SMC) ----
BLOCK_HOURS = parse_hours(env_first("BLOCK_HOURS", "SMC_BLOCK_HOURS"))

# ---- adaptive gate: rolling win rate of the last ADAPT_WINDOW closed trades ----
ADAPT_WINDOW = env_num(30, "ADAPT_WINDOW")
ADAPT_MIN_TRADES = env_num(20, "ADAPT_MIN_TRADES")   # fewer -> stay NORMAL
ADAPT_MIN_WR = env_num(0.40, "ADAPT_MIN_WR")         # below -> DEFENSIVE
DEFENSIVE_EXTRA_VOLUME = env_num(0.25, "DEFENSIVE_EXTRA_VOLUME")  # DEFENSIVE: more volume + 1H filter forced on
DEFENSIVE = [False]                                  # set by scan_murphy each candle

# --- backtest mode ---
BT_MAX_HOLD = 200                                    # bars (50 h); older open trades are closed at the close
OFF = set()   # filters switched off (ablation only; live = empty): HTF PULLBACK MA4 RSI STOCH MACD VOLUME SQUEEZE BANDROOM MINRISK

# --- universe ---
TOP_PAIRS = int(os.getenv("TOP_PAIRS", "50"))
MIN_VOLUME_USDT = float(os.getenv("MIN_VOLUME_USDT", "3000000"))

# --- indicators ---
RSI_PERIOD = 14
ATR_PERIOD = 14
VOL_PERIOD = 20
SL_ATR_BUFFER = env_num(0.10, "SL_ATR_BUFFER")

# --- risk / reporting ---
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.004"))
ACCOUNT_EQUITY = float(os.getenv("ACCOUNT_EQUITY", "1000"))
FEE_PER_SIDE = float(os.getenv("FEE_PER_SIDE", "0.0005"))          # taker 0.05%, for the fee estimate
REPORT_EVERY_HOURS = float(os.getenv("REPORT_EVERY_HOURS", "4"))

MONITOR_MAX_BARS = 1400
RR = 2.0                              # fallback when a stored trade has no "rr"

SCAN_INTERVAL = 300
RUN_FOREVER = os.getenv("RUN_FOREVER", "0").strip() == "1"
HISTORY_FILE = os.getenv("SIGNAL_HISTORY_FILE", "signals_history.json")
TIMEOUT = 15
RETRIES = 3
MIN_REQUEST_GAP = 0.09                # OKX public limit is 20 requests / 2 s per IP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("MURPHY")
S = requests.Session()
S.headers.update({"User-Agent": "ALPHAQUANT-MURPHY"})
TELEGRAM = bool(TOKEN and CHAT_ID)

SETUP_NAME = {"MURPHY_PULLBACK": "Murphy Pullback", "SMC_SCALP": "SMC Scalp (lama)"}

# ================= HELPERS =================


def iso(ms):
    return datetime.fromtimestamp(
        ms / 1000, tz=timezone.utc
    ).isoformat()

def now():
    return datetime.now(timezone.utc).isoformat()

_LAST_REQ = [0.0]

def api(path, params=None):
    for attempt in range(RETRIES):
        wait = MIN_REQUEST_GAP - (time.time() - _LAST_REQ[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_REQ[0] = time.time()
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
        # last_scan_candle / last_scan_candle are optional keys preserved as-is
        return d
    except Exception as e:
        log.error("History load failed: %s", e)
        return {"open": [], "closed": []}

def archive_legacy(h):
    """
    Move CLOSED trades of other strategies (SMC scalp, Breakout, ...) to h["archive"] so
    statistics and the adaptive win rate only cover the Murphy system. Open legacy
    trades are left alone and keep being monitored until they close.
    """
    keep, drop = [], []
    for x in h.get("closed", []):
        (keep if x.get("setup") == SETUP_ID else drop).append(x)
    if drop:
        h["closed"] = keep
        h.setdefault("archive", []).extend(dict(x, archived_from="closed") for x in drop)
    return len(drop)

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
        except Exception:
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

def candles(inst, bar, needed, history=False):
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

        d = api("/api/v5/market/history-candles" if history else "/api/v5/market/candles", p)
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

def latest_candle_ts(bar=TF, inst=REF_SYMBOL):
    """Open time of the newest confirmed candle (BTC as the reference clock)."""
    cs = candles(inst, bar, 3)
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

def volume_ratio(cs, n=20):
    if len(cs) < n:
        return None
    avg = sum(x[5] for x in cs[-n:]) / n
    return cs[-1][5] / avg if avg else None

def tick_round(x, tick):
    if tick <= 0:
        return x
    return round(round(x/tick)*tick, 12)

# ================= REJECT TRACKING =================

STAGES = [
    "Data", "Candle sedikit", "Candle telat", "Tren", "HTF", "Pullback", "MA4", "RSI", "Stochastic",
    "MACD", "Volume", "Bollinger", "SL/RR", "Diblokir"
]

CUR_SETUP = SETUP_ID
QUIET = [False]            # True while backtesting: no reject bookkeeping

# (setup, stage) -> [(pair, detail)], reset at the start of every scan.
REJECTS = {}

def _p(x):
    return f"{x:.8g}"


def _safe(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _rej(inst, stage, detail="", setup=None):
    if QUIET[0]:
        return None
    key = (setup or CUR_SETUP, stage)
    REJECTS.setdefault(key, []).append((inst, _safe(detail)))
    return None

# ================= MURPHY PULLBACK SCALP (15m) =================

def _roll_mean(v, n):
    out = [None] * len(v)
    for i in range(n - 1, len(v)):
        w = v[i - n + 1:i + 1]
        if None in w:
            continue
        out[i] = sum(w) / n
    return out

def sma_list(v, n):
    out = [None] * len(v)
    if len(v) < n:
        return out
    s = sum(v[:n])
    out[n - 1] = s / n
    for i in range(n, len(v)):
        s += v[i] - v[i - n]
        out[i] = s / n
    return out

def ema_list(v, n):
    out = [None] * len(v)
    if not v:
        return out
    k = 2 / (n + 1)
    x = v[0]
    out[0] = x
    for i in range(1, len(v)):
        x = v[i] * k + x * (1 - k)
        out[i] = x
    return out

def std_list(v, n):
    out = [None] * len(v)
    for i in range(n - 1, len(v)):
        w = v[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = math.sqrt(sum((x - m) ** 2 for x in w) / n)
    return out

def _quantile(vals, q):
    v = sorted(vals)
    pos = q * (len(v) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)

def murphy_indicators(cs):
    """All indicators of the strategy as lists aligned with `cs` (None = warm-up)."""
    n = len(cs)
    cl = [x[4] for x in cs]
    ma_f, ma_m, ma_s = (sma_list(cl, p) for p in (MA_FAST, MA_MID, MA_SLOW))

    mid = sma_list(cl, BB_N)
    sd = std_list(cl, BB_N)
    bb_up = [None if m is None else m + BB_K * s for m, s in zip(mid, sd)]
    bb_lo = [None if m is None else m - BB_K * s for m, s in zip(mid, sd)]
    bw = [None if (m is None or not m) else (u - l_) / m
          for m, u, l_ in zip(mid, bb_up, bb_lo)]

    raw = [None] * n
    for i in range(ST_N - 1, n):
        win = cs[i - ST_N + 1:i + 1]
        hh, ll = max(x[2] for x in win), min(x[3] for x in win)
        raw[i] = 100 * (cl[i] - ll) / (hh - ll) if hh > ll else None
    k = _roll_mean(raw, ST_SMOOTH)
    d = _roll_mean(k, ST_D)

    e_f, e_s = ema_list(cl, MACD_FAST), ema_list(cl, MACD_SLOW)
    macd = [a - b for a, b in zip(e_f, e_s)]
    sig = ema_list(macd, MACD_SIG)
    hist = [a - b for a, b in zip(macd, sig)]

    return {
        "ma_f": ma_f, "ma_m": ma_m, "ma_s": ma_s,
        "bb_mid": mid, "bb_up": bb_up, "bb_lo": bb_lo, "bw": bw,
        "rsi": rsi(cs, RSI_PERIOD), "atr": atr(cs, ATR_PERIOD),
        "k": k, "d": d, "hist": hist,
    }

def htf_state(cs):
    """
    1H trend from COMPLETED hourly bars only (the hour of the signal candle is excluded).
    UP   : MA9 > MA18 and last hourly close > MA18
    DOWN : mirror. None : neutral or not enough data.
    """
    last_key = cs[-1][0] // 3_600_000
    groups = {}
    for x in cs:
        groups.setdefault(x[0] // 3_600_000, []).append(x)
    keys = sorted(k for k, g in groups.items() if k < last_key and len(g) == 4)
    closes = [groups[k][-1][4] for k in keys]
    if len(closes) < MA_SLOW + 1:
        return None
    m = sum(closes[-MA_MID:]) / MA_MID
    s = sum(closes[-MA_SLOW:]) / MA_SLOW
    if m > s and closes[-1] > s:
        return "UP"
    if m < s and closes[-1] < s:
        return "DOWN"
    return None

def _murphy_attempt(inst, cs, meta, ind, htf, side):
    """
    Evaluate ONE direction on the latest candle.
    Returns a signal dict, or (stage, detail) describing the first filter that failed.
    """
    n = len(cs)
    i = n - 1
    w = PULL_N
    up = side == "LONG"
    close, opn = cs[i][4], cs[i][1]

    def at(key, j=i):
        return ind[key][j]

    ma_f, ma_m, ma_s, a = at("ma_f"), at("ma_m"), at("ma_s"), at("atr")
    rs, k, d, hist, bb_up, bb_lo, bw = (at(x) for x in ("rsi", "k", "d", "hist", "bb_up", "bb_lo", "bw"))
    ma_s3, ma_f1 = at("ma_s", i - 3), at("ma_f", i - 1)
    k1, d1, hist1 = at("k", i - 1), at("d", i - 1), at("hist", i - 1)
    win = range(i - w + 1, i + 1)
    ma_s_w = [ind["ma_s"][j] for j in win]
    rsi_w = [ind["rsi"][j] for j in win]
    k_w = [ind["k"][j] for j in win]

    need = [ma_f, ma_m, ma_s, a, rs, k, d, hist, bb_up, bb_lo, bw, ma_s3, ma_f1, k1, d1, hist1]
    if any(x is None for x in need) or any(x is None for x in ma_s_w + rsi_w + k_w) or not a or a <= 0:
        return "Data", "indikator belum siap"

    # --- 1. Trend: MA9 > MA18, MA18 rising, price above MA18 (Murphy p.204-206) ---
    if up:
        trend_ok = ma_m > ma_s and ma_s > ma_s3 and close > ma_s
    else:
        trend_ok = ma_m < ma_s and ma_s < ma_s3 and close < ma_s
    if not trend_ok:
        return "Tren", f"{side} MA{MA_MID}/MA{MA_SLOW} tidak searah"

    want = "UP" if up else "DOWN"
    if "HTF" not in OFF and (HTF_FILTER or DEFENSIVE[0]) and htf != want:
        return "HTF", f"{side} tren 1H {htf or 'netral'} (perlu {want})"

    # --- 2. Pullback into MA9 that never breaks MA18 ---
    lows = [cs[j][3] for j in win]
    highs = [cs[j][2] for j in win]
    closes_w = [cs[j][4] for j in win]
    if up:
        touched = min(lows) <= ma_m
        hold = min(c - s for c, s in zip(closes_w, ma_s_w)) > -HOLD_ATR * a
    else:
        touched = max(highs) >= ma_m
        hold = min(s - c for c, s in zip(closes_w, ma_s_w)) > -HOLD_ATR * a
    if "PULLBACK" not in OFF and not touched:
        return "Pullback", f"{side} belum pullback ke MA{MA_MID}"
    if "PULLBACK" not in OFF and not hold:
        return "Pullback", f"{side} close menembus MA{MA_SLOW} saat pullback"

    # --- 3. Trigger candle: MA4 turning back with the trend (Murphy "buying alert", p.205) ---
    if up:
        trig = close > ma_f and ma_f > ma_f1 and close > opn
    else:
        trig = close < ma_f and ma_f < ma_f1 and close < opn
    if "MA4" not in OFF and not trig:
        return "MA4", f"{side} candle pemicu / MA{MA_FAST} belum berbalik searah"

    # --- 4. RSI pulled back into the 35-55 zone (mirror for SHORT) and did not collapse ---
    if up:
        r_ext = min(rsi_w)
        rsi_ok = RSI_FLOOR <= r_ext <= RSI_PULL_HI
    else:
        r_ext = max(rsi_w)
        rsi_ok = 100 - RSI_PULL_HI <= r_ext <= 100 - RSI_FLOOR
    if "RSI" not in OFF and not rsi_ok:
        return "RSI", f"{side} RSI ekstrem pullback {r_ext:.1f} di luar zona"

    # --- 5. Stochastic %K crosses %D out of the oversold/overbought zone, within the last
    #        STOCH_LOOKBACK candles (p.248-249) ---
    def _crossed(j):
        kj, dj, kp, dp = ind["k"][j], ind["d"][j], ind["k"][j - 1], ind["d"][j - 1]
        if None in (kj, dj, kp, dp):
            return False
        return (kj > dj and kp <= dp) if up else (kj < dj and kp >= dp)

    crossed = any(_crossed(j) for j in range(max(1, i - STOCH_LOOKBACK + 1), i + 1))
    still = k > d if up else k < d                      # %K must still be on the trade side of %D
    zone = min(k_w) <= ST_OS if up else max(k_w) >= 100 - ST_OS
    st_ok = crossed and still and zone
    if "STOCH" not in OFF and not st_ok:
        return "Stochastic", (f"{side} K {k:.0f}/D {d:.0f} belum cross dari zona ekstrem "
                              f"(dalam {STOCH_LOOKBACK} candle)")

    # --- 6. MACD histogram turning with the trade (p.255) ---
    if "MACD" not in OFF and ((up and not hist > hist1) or (not up and not hist < hist1)):
        return "MACD", f"{side} histogram MACD belum berbalik searah"

    # --- 7. Volume confirms (p.174) ---
    vr = volume_ratio(cs, VOL_PERIOD) or 0.0
    need_vol = MIN_VOLUME_RATIO + (DEFENSIVE_EXTRA_VOLUME if DEFENSIVE[0] else 0.0)
    if "VOLUME" not in OFF and vr < need_vol:
        return "Volume", f"{side} volume {vr:.2f}x (min {need_vol:.2f}x)"

    # --- 8. Bollinger: not in a squeeze (p.211) ---
    bw_hist = [x for x in ind["bw"][-BW_LOOKBACK:] if x is not None]
    if "SQUEEZE" not in OFF and len(bw_hist) >= 20 and bw < _quantile(bw_hist, BW_MIN_PCT):
        return "Bollinger", f"{side} band menyempit (squeeze), tunggu breakout"

    sig_hour = datetime.fromisoformat(iso(cs[i][0])).hour
    if sig_hour in BLOCK_HOURS:
        return "Diblokir", f"{side} jam UTC {sig_hour} diblokir (BLOCK_HOURS)"

    # --- stop beyond the pullback extreme, cost gates ---
    if up:
        sl_raw = min(lows) - SL_ATR_BUFFER * a
        risk = close - sl_raw
    else:
        sl_raw = max(highs) + SL_ATR_BUFFER * a
        risk = sl_raw - close
    if risk <= 0:
        return "SL/RR", f"{side} SL tidak valid"

    sl_atr = risk / a
    if not MIN_SL_ATR <= sl_atr <= MAX_SL_ATR:
        return "SL/RR", f"{side} SL {sl_atr:.2f} ATR (perlu {MIN_SL_ATR}-{MAX_SL_ATR})"

    risk_pct = risk / close
    min_risk = MIN_RISK_PCT_BTC if (inst == REF_SYMBOL and MIN_RISK_PCT_BTC >= 0) else MIN_RISK_PCT
    if "MINRISK" not in OFF and risk_pct < min_risk:
        return "SL/RR", f"{side} SL {risk_pct * 100:.2f}% (min {min_risk * 100:.2f}%, fee memakan R)"
    if MAX_RISK_PCT > 0 and risk_pct > MAX_RISK_PCT:
        return "SL/RR", f"{side} SL {risk_pct * 100:.2f}% terlalu jauh (maks {MAX_RISK_PCT * 100:.2f}%)"

    # --- Bollinger target: room toward the opposite band (p.210) ---
    room_r = ((bb_up - close) if up else (close - bb_lo)) / risk
    if "BANDROOM" not in OFF and BB_MIN_R > 0 and room_r < BB_MIN_R:
        return "Bollinger", f"{side} band hanya {room_r:.2f}R dari entry (min {BB_MIN_R:g}R)"

    tp_raw = close + TARGET_RR * risk if up else close - TARGET_RR * risk
    tick = meta.get(inst, {}).get("tick", 0.00000001)
    entry = tick_round(close, tick)
    sl = tick_round(sl_raw, tick)
    tp = tick_round(tp_raw, tick)

    note = (
        f"Murphy pullback {'UPTREND' if up else 'DOWNTREND'} | "
        f"MA{MA_MID}/{MA_SLOW} + 1H {htf or '-'} | RSI {rs:.1f} (pullback {r_ext:.1f}) | "
        f"Stoch K{k:.0f}/D{d:.0f} | MACD hist {hist:+.3g} | "
        f"Vol {vr:.2f}x | Band {room_r:.2f}R"
    )

    return {
        "signal_id": f"{inst}|{side}|{cs[i][0]}|MURPHY",
        "symbol": inst,
        "direction": side,
        "timeframe": TF,
        "setup": SETUP_ID,
        "note": note,
        "signal_candle_time": cs[i][0],
        "signal_candle_iso": iso(cs[i][0]),
        "created_at": now(),
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": TARGET_RR,
        "atr": a,
        "sl_atr": sl_atr,
        "ema50": 0.0,
        "ema200": 0.0,
        "rsi": rs,
        "adx": 0.0,
        "volume_ratio": vr,
        "stoch_k": k,
        "stoch_d": d,
        "macd_hist": hist,
        "band_room_r": round(room_r, 2),
        "htf": htf,
        "rsi_deadzone": False,
        "quality": round(min(vr, 3.0) + 0.5 * min(room_r, 3.0) + (1.0 if htf == want else 0.0), 2),
        "mode": "DEFENSIVE" if DEFENSIVE[0] else "NORMAL",
        "regime": "UPTREND" if up else "DOWNTREND",
        "structure": "PULLBACK",
        "bos": "NONE",
        "pullback": round(r_ext, 1),
        "score": None,
        "score_reasons": [],
        "risk_usdt": ACCOUNT_EQUITY * RISK_PER_TRADE,
        "status": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "result_r": None,
        "result": None,
        "monitor_tf_ms": TF_MS,
    }

def build_murphy_pullback(inst, cs, meta):
    """
    15m Murphy pullback scalp on the LAST candle of `cs`, both directions:
      1. Trend      MA9 > MA18, MA18 rising, price above MA18 (+ 1H trend agrees)
      2. Pullback   low touches MA9 within PULL_N bars, closes hold above MA18
      3. Trigger    close back above a rising MA4 on a bullish candle
      4. RSI        pullback low between 35 and 55
      5. Stochastic %K crosses above %D (within STOCH_LOOKBACK candles) after being <= 40
      6. MACD       histogram rising
      7. Volume     >= average
      8. Bollinger  no squeeze; opposite band at least BB_MIN_R away
      Entry = close, SL beyond the pullback extreme, TP at TARGET_RR. SHORT mirrors.
    """
    global CUR_SETUP
    CUR_SETUP = SETUP_ID

    if len(cs) < MIN_BARS:
        return _rej(inst, "Candle sedikit", f"hanya {len(cs)} candle (min {MIN_BARS})")

    ind = murphy_indicators(cs)
    if ind["atr"][-1] is None or ind["rsi"][-1] is None:
        return _rej(inst, "Data", "indikator belum siap")

    htf = htf_state(cs)
    best = None
    for side in ("LONG", "SHORT"):
        res = _murphy_attempt(inst, cs, meta, ind, htf, side)
        if isinstance(res, dict):
            return res
        stage, detail = res
        depth = STAGES.index(stage)
        if best is None or depth > best[0]:
            best = (depth, stage, detail)

    return _rej(inst, best[1], best[2])

# ================= BACKTEST (same engine as live) =================

def _simulate(cs, k, s):
    """Walk forward from candle k+1 exactly like monitor(): SL first when one bar touches both."""
    entry, sl, tp = s["entry"], s["sl"], s["tp"]
    long_ = s["direction"] == "LONG"
    end = min(len(cs), k + 1 + BT_MAX_HOLD)
    for j in range(k + 1, end):
        hi, lo = cs[j][2], cs[j][3]
        hit_sl = lo <= sl if long_ else hi >= sl
        hit_tp = hi >= tp if long_ else lo <= tp
        if hit_sl:
            return j, "LOSS", -1.0
        if hit_tp:
            return j, "WIN", float(s["rr"])
    if end >= len(cs):
        return None                      # still open at the end of the data
    p = cs[end - 1][4]
    return end - 1, ("WIN" if float_r(s, p) > 0 else "LOSS"), float_r(s, p)

def backtest_series(inst, cs, meta=None):
    meta = meta or {}
    trades, k, busy_until = [], MIN_BARS, -1
    cooldown_bars = int(COOLDOWN_HOURS * 3600_000 / TF_MS)
    while k < len(cs) - 1:
        if k <= busy_until:
            k += 1
            continue
        window = cs[max(0, k - HISTORY_BARS + 1):k + 1]
        s = build_murphy_pullback(inst, window, meta)
        if not s:
            k += 1
            continue
        res = _simulate(cs, k, s)
        if res is None:
            break
        j, result, r = res
        t = dict(s)
        t.update({"status": "CLOSED", "exit_time": iso(cs[j][0]), "result": result, "result_r": r})
        trades.append(t)
        busy_until = j + cooldown_bars
        k += 1
    return trades

def bt_report(name, trades):
    if not trades:
        print(f"{name}: 0 trade")
        return
    r = [float(t["result_r"]) for t in trades]
    fees = [fee_r_of(t) for t in trades]
    wins = sum(1 for x in r if x > 0)
    gp = sum(x for x in r if x > 0)
    gl = -sum(x for x in r if x <= 0)
    net = sum(r) - sum(fees)
    eq = peak = dd = 0.0
    for x, f in zip(r, fees):
        eq += x - f
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    avg_rr = sum(float(t["rr"]) for t in trades) / len(trades)
    bep_net = 100 * (1 + sum(fees) / len(trades)) / (1 + avg_rr)
    longs = sum(1 for t in trades if t["direction"] == "LONG")
    print(
        f"{name}: {len(trades)} trade ({longs} long / {len(trades) - longs} short) | "
        f"WR {wins / len(trades) * 100:.1f}% (BEP net {bep_net:.1f}%) | "
        f"R gross {sum(r):+.2f} | net {net:+.2f} | avg net {net / len(trades):+.3f}R | "
        f"PF {gp / gl if gl else float('inf'):.2f} | MaxDD net -{dd:.2f}R"
    )

def synthetic_candles(n=12000, seed=7):
    """OKX-style candles [ts,o,h,l,c,v] with trend / range regimes, for offline selftest."""
    import random
    rng = random.Random(seed)
    ts0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    drift, left, price, out = 0.0, 0, 100.0, []
    for i in range(n):
        if left <= 0:
            left = rng.randint(150, 600)
            drift = rng.choice([-1, 0, 1]) * 0.00025
        left -= 1
        ret = drift + rng.gauss(0, 0.0025)
        o, c = price, price * math.exp(ret)
        hi = max(o, c) + abs(rng.gauss(0, 0.0015)) * c
        lo = min(o, c) - abs(rng.gauss(0, 0.0015)) * c
        vol = rng.lognormvariate(5, 0.5) * (1 + 3 * abs(ret) / 0.0025)
        out.append([ts0 + i * TF_MS, o, hi, lo, c, vol])
        price = c
    return out

def run_backtest(insts, bars):
    QUIET[0] = True
    meta = instruments()
    allt = []
    for inst in insts:
        cs = candles(inst, TF, bars, history=True)
        if len(cs) < MIN_BARS + 10:
            print(f"{inst}: data kurang ({len(cs)} candle)")
            continue
        t = backtest_series(inst, cs, meta)
        allt += t
        bt_report(f"{inst} [{iso(cs[0][0])[:10]} -> {iso(cs[-1][0])[:10]}]", t)
    if len(insts) > 1:
        bt_report("GABUNGAN", allt)

ABLATION_FILTERS = ["HTF", "PULLBACK", "MA4", "RSI", "STOCH", "MACD", "VOLUME", "SQUEEZE", "BANDROOM", "MINRISK"]

def _ablation_job(args):
    name, off, data = args
    QUIET[0] = True
    OFF.clear()
    OFF.update(off)
    rows = []
    for inst, cs in data.items():
        for t in backtest_series(inst, cs):
            rows.append((float(t["result_r"]), fee_r_of(t)))
    return name, rows

def _abl_stats(rows):
    n = len(rows)
    if not n:
        return 0, 0.0, 0.0, 0.0, 0.0
    net = [r - f for r, f in rows]
    wr = sum(1 for r, _ in rows if r > 0) / n * 100
    gp = sum(x for x in net if x > 0)
    gl = -sum(x for x in net if x <= 0)
    return n, wr, sum(net), sum(net) / n, (gp / gl if gl else float("inf"))

def run_ablation(insts, bars, synthetic=False):
    """Backtest with every filter switched off one at a time (all others stay on)."""
    if synthetic:
        data = {f"SYN{sd}": synthetic_candles(bars, sd) for sd in (7, 11, 23)}
    else:
        insts = insts or top_pairs()[:10]
        data = {}
        for inst in insts:
            cs = candles(inst, TF, bars, history=True)
            if len(cs) >= MIN_BARS + 10:
                data[inst] = cs
            else:
                print(f"{inst}: data kurang ({len(cs)} candle), dilewati")
    if not data:
        print("Tidak ada data.")
        return
    jobs = [("BASELINE (semua aktif)", ())] + [(f"tanpa {f}", (f,)) for f in ABLATION_FILTERS]
    payload = [(n, o, data) for n, o in jobs]
    results = {}
    try:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor() as ex:
            for name, rows in ex.map(_ablation_job, payload):
                results[name] = rows
    except Exception as e:
        print(f"Paralel gagal ({e}); jalan berurutan, ini lebih lama...")
        results = dict(_ablation_job(x) for x in payload)

    base = _abl_stats(results[jobs[0][0]])
    print(f"\nAblation: {len(data)} pair x {bars} candle 15m | fee {FEE_PER_SIDE * 100:.2f}%/sisi | RR 1:{TARGET_RR}")
    print(f"{'Konfigurasi':<24}{'Trade':>6}{'WR%':>7}{'Net R':>8}{'Avg R':>8}{'PF':>6}")
    reliable = base[0] >= 60
    for name, _ in jobs:
        n, wr, tot, avg, pf = _abl_stats(results[name])
        pf_t = "inf" if pf == float("inf") else f"{pf:.2f}"
        mark = ""
        if name != jobs[0][0] and reliable:
            if avg >= base[3] + 0.05 and n >= base[0]:
                mark = "  <- kandidat DIBUANG"
            elif avg <= base[3] - 0.05:
                mark = "  <- berguna, pertahankan"
            else:
                mark = "  <- beda tidak jelas"
        print(f"{name:<24}{n:>6}{wr:>7.1f}{tot:>+8.2f}{avg:>+8.3f}{pf_t:>6}{mark}")
    if not reliable:
        print(f"\nPERINGATAN: baseline hanya {base[0]} trade (<60). Selisih antar baris masih noise, "
              "jangan ambil keputusan. Tambah pair atau --bars.")
    else:
        print("\nCatatan: tanda di kanan indikatif (ambang selisih 0,05R). Dengan <200 trade, "
              "selisih sekecil itu masih bisa noise.")

def run_selftest():
    QUIET[0] = True
    allt = []
    for seed in (7, 11, 23):
        t = backtest_series("SYNTH-USDT-SWAP", synthetic_candles(12000, seed))
        allt += t
        bt_report(f"synthetic seed {seed}", t)
    bt_report("TOTAL", allt)
    print("Selftest selesai: kode jalan. Angka di atas dari data acak, BUKAN bukti edge.")

# ================= DEDUPE =================

def symbol_blocked(h, inst):
    """True if `inst` already has an open trade, or is cooling down after a close."""
    if any(x.get("symbol") == inst for x in h["open"]):
        return True
    cutoff = time.time() - COOLDOWN_HOURS * 3600
    for x in h["closed"]:
        if x.get("symbol") != inst:
            continue
        try:
            if datetime.fromisoformat(x["exit_time"]).timestamp() > cutoff:
                return True
        except Exception:
            pass
    return False

def blocked(h, sig):
    sid = sig["signal_id"]
    if any(x.get("signal_id") == sid for x in h["open"] + h["closed"]):
        return True
    return symbol_blocked(h, sig["symbol"])

def n_open(h):
    return len(h["open"])

# ================= MONITOR =================

def monitor(trade):
    # Entry = close of the signal candle: monitoring starts when that candle ENDS.
    start = trade.get("signal_candle_time", 0) + TF_MS
    mon_tf, mon_ms = MONITOR_TF, MONITOR_MS

    age_ms = max(0, int(time.time() * 1000) - start)
    needed = max(60, age_ms // mon_ms + 24)
    if needed > MONITOR_MAX_BARS:
        log.warning(
            "Monitor %s: trade age needs %s %s bars, capped at %s "
            "(older TP/SL hits may be missed)",
            trade["symbol"], needed, mon_tf, MONITOR_MAX_BARS
        )
        needed = MONITOR_MAX_BARS

    cs = candles(trade["symbol"], mon_tf, needed)
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
        h["closed"].extend(x for x in closed if x.get("setup") == SETUP_ID)
        legacy = [x for x in closed if x.get("setup") != SETUP_ID]
        if legacy:
            h.setdefault("archive", []).extend(dict(x, archived_from="open") for x in legacy)
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
            f"{emoji} <b>{t['symbol']}</b> · {t['direction']}\n"
            f"Entry <code>{t['entry']}</code> | Now <code>{p}</code>\n"
            f"SL <code>{t['sl']}</code> | TP <code>{t['tp']}</code>\n"
            f"Float <b>{r:+.2f}R</b>"
        )

    if not rs:
        return

    total = sum(rs)
    avg = total / len(rs)

    tg(
        "<b>📡 RUNNING POSITIONS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n" +
        "\n\n".join(blocks) +
        "\n\n━━━━━━━━━━━━━━━━━━\n"
        f"Open Positions : {len(h['open'])}\n"
        f"Profitable     : {sum(x > 0 for x in rs)}\n"
        f"Negative       : {sum(x < 0 for x in rs)}\n"
        f"Floating R     : <b>{total:+.2f}R</b>\n"
        f"Average Float  : {avg:+.2f}R\n"
        f"Best           : {max(rs):+.2f}R\n"
        f"Worst          : {min(rs):+.2f}R\n\n"
        f"TP Potential   : +{sum(float(x.get('rr', RR)) for x in h['open']):.2f}R\n"
        f"SL Exposure    : -{len(h['open']):.2f}R\n\n"
        "⚠️ Floating R is unrealized."
    )

def fee_r_of(x):
    """Estimated round-trip taker fee of a trade, in R."""
    try:
        entry = float(x["entry"])
        risk = abs(entry - float(x["sl"]))
        return (2 * FEE_PER_SIDE * entry / risk) if risk > 0 else 0.0
    except Exception:
        return 0.0

def stats(h):
    ts = h["closed"]
    if not ts:
        return

    wins = [x for x in ts if x.get("result") == "WIN"]
    losses = [x for x in ts if x.get("result") == "LOSS"]
    total_r = sum(float(x.get("result_r", 0)) for x in ts)
    gp = sum(max(float(x.get("result_r", 0)), 0) for x in ts)
    gl = abs(sum(min(float(x.get("result_r", 0)), 0) for x in ts))
    pf = gp / gl if gl else float("inf")

    eq = peak = dd = 0
    for x in ts:
        eq += float(x.get("result_r", 0))
        peak = max(peak, eq)
        dd = max(dd, peak - eq)

    pf_text = "∞" if math.isinf(pf) else f"{pf:.2f}"

    rrs = [float(x.get("rr", RR)) for x in ts]
    avg_rr = sum(rrs) / len(rrs)
    bep = 100 / (1 + avg_rr)
    fees = [fee_r_of(x) for x in ts]
    net_r = total_r - sum(fees)
    bep_net = 100 * (1 + sum(fees) / len(ts)) / (1 + avg_rr)

    note = ""
    if len(ts) < 30:
        note = "\n\n<i>Kurang dari 30 trade: belum bisa disimpulkan.</i>"

    tg(
        "<b>📊 MURPHY PERFORMANCE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Trades        : {len(ts)}\n"
        f"Wins          : {len(wins)}\n"
        f"Losses        : {len(losses)}\n"
        f"Win Rate      : <b>{len(wins) / len(ts) * 100:.2f}%</b>\n"
        f"Total R       : <b>{total_r:+.2f}R</b> (gross)\n"
        f"Total R net   : <b>{net_r:+.2f}R</b> (setelah fee ≈)\n"
        f"Avg R/Trade   : {total_r / len(ts):+.3f}R gross | {net_r / len(ts):+.3f}R net\n"
        f"Profit Factor : {pf_text}\n"
        f"Max Drawdown  : -{dd:.2f}R\n"
        f"Avg RR Target : 1:{avg_rr:.2f}\n"
        f"BEP WR        : {bep:.2f}% gross | <b>{bep_net:.2f}%</b> net" + note
    )

# ================= SIGNAL MESSAGE =================

def signal_message(s):
    setup = s.get("setup", SETUP_ID)
    risk = abs(s["entry"] - s["sl"])
    fee_r = (2 * FEE_PER_SIDE * s["entry"] / risk) if risk > 0 else 0.0
    risk_pct = (risk / s["entry"] * 100) if s["entry"] else 0.0

    head = (
        f"{s['timeframe']} | <b>{SETUP_NAME.get(setup, setup)}</b>\n"
        f"Structure: {s.get('structure', '-')} · Regime: {s.get('regime', '-')}\n"
        f"{_safe(s.get('note', ''))}\n\n"
    )

    return (
        "<b>🚨 ALPHAQUANT MURPHY V6.0 SIGNAL</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"<b>{s['symbol']}</b> · <b>{s['direction']}</b>\n" +
        head +
        "<b>TRADE PLAN</b>\n"
        f"Entry: <code>{s['entry']}</code>\n"
        f"SL: <code>{s['sl']}</code>\n"
        f"TP: <code>{s['tp']}</code>\n"
        f"RR: <b>1:{float(s.get('rr', RR)):.2f}</b>\n"
        f"SL: {s['sl_atr']:.2f} ATR · {risk_pct:.2f}% harga\n"
        f"Fee ≈ {fee_r:.2f}R (taker {FEE_PER_SIDE * 100:.2f}%/sisi)\n\n"
        f"RSI: {s['rsi']:.2f} | Volume: {s['volume_ratio']:.2f}x\n"
        f"Risk: {s['risk_usdt']:.2f} USDT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ SIGNAL ONLY — NO AUTO EXECUTION\n"
        f"Candle: {s['signal_candle_iso']}"
    )

# ================= SCAN =================

def _tally(h, scanned, created, rows):
    """Accumulate the scan funnel in the history file until the next report."""
    d = h.get("scan_rej")
    if not d or "pairs" not in d:           # empty, or left over from V4.x (different format)
        d = {"scans": 0, "pairs": 0, "signals": 0, "stages": {}, "near": []}
    d["scans"] += 1
    d["pairs"] += scanned
    d["signals"] += created

    for (_, stage), items in rows.items():
        d["stages"][stage] = d["stages"].get(stage, 0) + len(items)
        if stage in STAGES and stage not in ("Data", "Candle sedikit", "Candle telat", "Tren", "HTF"):
            depth = STAGES.index(stage)
            for inst, detail in items:
                d["near"].append({"depth": depth, "text": f"{inst} → {stage}: {detail}"})

    d["near"] = sorted(d["near"], key=lambda x: -x["depth"])[:6]
    h["scan_rej"] = d

def scan_report_text(h):
    d = h.get("scan_rej")
    if not d or "pairs" not in d or not d.get("scans"):
        return ""
    parts_ = [f"{st} {d['stages'][st]}" for st in STAGES + ["Error"] if d["stages"].get(st)]
    text = (
        "<b>⚡ MURPHY PULLBACK · SCAN REPORT</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Scan         : {d['scans']} candle 15m\n"
        f"Pair dicek   : {d['pairs']}\n"
        f"Sinyal baru  : {d['signals']}\n\n"
        "<b>Gugur di filter</b> (filter pertama yang gagal)\n" +
        (" · ".join(parts_) if parts_ else "-")
    )
    if d.get("near"):
        text += "\n\n<b>Paling dekat lolos</b>\n" + "\n".join(x["text"] for x in d["near"][:4])
    return text

def market_mode(h):
    """Rolling win rate of the last ADAPT_WINDOW closed trades -> NORMAL / DEFENSIVE."""
    closed = [x for x in h["closed"] if x.get("exit_time")]
    closed.sort(key=lambda x: x["exit_time"])
    win = closed[-ADAPT_WINDOW:]
    if len(win) < ADAPT_MIN_TRADES:
        return "NORMAL", None, len(win)
    wr = sum(1 for x in win if x.get("result") == "WIN") / len(win)
    return ("DEFENSIVE" if wr < ADAPT_MIN_WR else "NORMAL"), wr, len(win)

def scan_murphy(h):
    """
    Scan the top pairs for a Murphy pullback scalp on every NEW 15m candle.
    Returns the number of new signals.
    """
    global CUR_SETUP

    ref = latest_candle_ts()
    if ref is not None and h.get("last_scan_candle") == ref:
        log.info("No new %s candle since %s - scan skipped.", TF, iso(ref))
        return 0

    if n_open(h) >= MAX_OPEN:
        log.info("Murphy scan skipped: %s open scalps (cap %s).", n_open(h), MAX_OPEN)
        if ref is not None:
            h["last_scan_candle"] = ref
        return 0

    pairs = top_pairs()
    if not pairs:
        log.warning("No pairs returned by OKX; scan aborted.")
        return 0
    meta = instruments()

    log.info("Murphy scan: %s pairs on %s...", len(pairs), TF)
    REJECTS.clear()
    CUR_SETUP = SETUP_ID
    created, scanned = 0, 0
    found = []

    mode, mwr, mn = market_mode(h)
    DEFENSIVE[0] = (mode == "DEFENSIVE")
    log.info("Market mode: %s (rolling WR %s over %s trades)", mode,
             "n/a" if mwr is None else f"{mwr * 100:.0f}%", mn)

    def n_dir(d):
        return sum(1 for x in h["open"] if x.get("direction") == d)

    for inst in pairs:
        if n_open(h) >= MAX_OPEN:
            log.info("Open scalp cap (%s) reached - stopping the scan.", MAX_OPEN)
            break
        if MAX_NEW_PER_CANDLE > 0 and created >= MAX_NEW_PER_CANDLE:
            log.info("New-signal limit per candle (%s) reached - stopping the scan.", MAX_NEW_PER_CANDLE)
            break
        if (MAX_ACTIVE_PER_DIRECTION > 0
                and n_dir("LONG") >= MAX_ACTIVE_PER_DIRECTION
                and n_dir("SHORT") >= MAX_ACTIVE_PER_DIRECTION):
            log.info("Both directions are at the limit (%s) - stopping the scan.", MAX_ACTIVE_PER_DIRECTION)
            break

        # Skip pairs that already have a position / are cooling down BEFORE
        # spending API calls on them.
        if symbol_blocked(h, inst):
            continue

        scanned += 1
        try:
            cs = candles(inst, TF, HISTORY_BARS)
            if len(cs) < MIN_BARS:
                _rej(inst, "Candle sedikit", f"hanya {len(cs)} candle (min {MIN_BARS})")
                continue

            # Stale data (no trades in the latest bar): never signal on an old candle.
            if ref is not None and cs[-1][0] != ref:
                _rej(inst, "Candle telat", "candle terakhir tidak sinkron dengan acuan BTC")
                continue

            s = build_murphy_pullback(inst, cs, meta)
            if not s:
                continue

            if blocked(h, s):
                _rej(inst, "Diblokir", f"{s['direction']} duplikat/cooldown/posisi open")
                continue

            if (MAX_ACTIVE_PER_DIRECTION > 0
                    and n_dir(s["direction"]) >= MAX_ACTIVE_PER_DIRECTION):
                _rej(inst, "Diblokir",
                     f"{s['direction']} sudah {n_dir(s['direction'])} posisi aktif "
                     f"(maks {MAX_ACTIVE_PER_DIRECTION})")
                continue

            found.append(s)

        except Exception as e:
            log.exception("Scan error %s: %s", inst, e)
            _rej(inst, "Error", str(e)[:60])

    # Best-quality setups first (RSI momentum + trend alignment), then the caps.
    found.sort(key=lambda x: x.get("quality", 0), reverse=True)
    for s in found:
        if n_open(h) >= MAX_OPEN:
            break
        if MAX_NEW_PER_CANDLE > 0 and created >= MAX_NEW_PER_CANDLE:
            _rej(s["symbol"], "Diblokir", f"{s['direction']} kalah kualitas (maks {MAX_NEW_PER_CANDLE}/candle)")
            continue
        if (MAX_ACTIVE_PER_DIRECTION > 0
                and n_dir(s["direction"]) >= MAX_ACTIVE_PER_DIRECTION):
            _rej(s["symbol"], "Diblokir", f"{s['direction']} sudah penuh")
            continue
        h["open"].append(s)
        save_history(h)
        created += 1
        log.info("NEW SIGNAL %s %s rr=%s q=%s mode=%s", s["symbol"], s["direction"],
                 s["rr"], s.get("quality"), s.get("mode"))
        tg(signal_message(s))
        time.sleep(0.3)

    log.info("Murphy scan complete. Pairs: %s | New signals: %s", scanned, created)
    _tally(h, scanned, created, dict(REJECTS))
    REJECTS.clear()

    if ref is not None:
        h["last_scan_candle"] = ref
    return created

# ================= MAIN =================

def main():
    global TELEGRAM

    log.info("==========================================")
    log.info("ALPHAQUANT MURPHY V6.0 STARTING")
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
        log.warning("GitHub: Settings > Secrets and variables > Actions")
    else:
        TELEGRAM = True
        log.info("Telegram credentials detected. Notifications ENABLED.")

    h = load_history()
    moved = archive_legacy(h)
    if moved:
        log.info("Archived %s trades of removed strategies (Breakout / Mean Rev / ...).", moved)
        save_history(h)

    log.info("Open trades: %s | Closed trades: %s", len(h["open"]), len(h["closed"]))
    log.info(
        "Config | Murphy@%s RR=1:%.2f | Pairs=%s | MaxOpen=%s | MinRisk=%.2f%% (BTC %s) | "
        "Monitor=%s | History=%s | Telegram=%s | RunForever=%s",
        TF, TARGET_RR, TOP_PAIRS, MAX_OPEN, MIN_RISK_PCT * 100,
        f"{MIN_RISK_PCT_BTC * 100:.2f}%" if MIN_RISK_PCT_BTC >= 0 else "= sama",
        MONITOR_TF, HISTORY_FILE, "ON" if TELEGRAM else "OFF", RUN_FOREVER
    )

    today = datetime.now(timezone.utc).date().isoformat()
    if TELEGRAM and h.get("last_online_day") != today:
        h["last_online_day"] = today
        tg(
            "<b>🟢 ALPHAQUANT MURPHY V6.0 ONLINE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Murphy Pullback 15m · top {TOP_PAIRS} pair\n"
            "MA 4-9-18 · RSI · Stochastic · MACD · Bollinger · Volume\n"
            f"Maks {MAX_OPEN} posisi ({MAX_ACTIVE_PER_DIRECTION} per arah, "
            f"{MAX_NEW_PER_CANDLE} baru per candle) · SL min {MIN_RISK_PCT * 100:.2f}% harga\n"
            "Signal-only"
        )

    while True:
        started = time.time()

        try:
            log.info("Starting engine cycle...")
            closed_n = check_open(h)

            # Periodic report: every REPORT_EVERY_HOURS, or right after a trade closed.
            due = (time.time() - float(h.get("last_report_ts", 0))) >= REPORT_EVERY_HOURS * 3600
            if due:
                running_report(h)
                stats(h)
                text = scan_report_text(h)
                if text:
                    tg(text)
                    h["scan_rej"] = None
                h["last_report_ts"] = time.time()
            elif closed_n:
                stats(h)

            scan_murphy(h)
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
        log.info("Cycle finished. Sleeping %.1f seconds.", sleep_for)
        time.sleep(sleep_for)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        run_selftest()
    elif len(sys.argv) > 1 and sys.argv[1] == "ablation":
        # python signal_bot_murphy.py ablation [PAIR ...] [--bars 3000] [--synthetic]
        args = sys.argv[2:]
        bars, synth = 3000, "--synthetic" in args
        args = [x for x in args if x != "--synthetic"]
        if "--bars" in args:
            p = args.index("--bars")
            bars = int(args[p + 1])
            args = args[:p] + args[p + 2:]
        run_ablation(args, bars, synth)
    elif len(sys.argv) > 1 and sys.argv[1] == "backtest":
        # python signal_bot_murphy.py backtest BTC-USDT-SWAP ETH-USDT-SWAP [--bars 5000]
        args = sys.argv[2:]
        bars = 5000
        if "--bars" in args:
            p = args.index("--bars")
            bars = int(args[p + 1])
            args = args[:p] + args[p + 2:]
        run_backtest(args or [REF_SYMBOL], bars)
    else:
        main()

