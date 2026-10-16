"""
ALPHAQUANT MURPHY x VOLMAN V8.0 FULL (15m)
Rule-based scalper for the top OKX USDT perpetuals (Telegram, signal-only).

Murphy, "Technical Analysis of the Financial Markets":
  4H / 1H / 15m trend (MA 9 and 18), RSI guard, 33-66% retracement (Dow thirds, Fibonacci 38/62),
  swing support / resistance, flag and pennant with the measuring rule, breakout volume,
  Bollinger room to the opposite band, candlestick patterns filtered by the Stochastic presignal area.
Volman, "Understanding Price Action" (applied to the 15m chart):
  25 EMA dominance; setups pullback reversal, pattern break, pattern break pullback, combi;
  technical test / ceiling test; round-number magnets; and the skip rules of chapter 7
  (against dominance, into resistance, ranging market, entry far from the 25 EMA,
  frantic environment, powerbars inside a pullback, front-running without buildup).
Entry is a PENDING stop order 1 tick beyond the signal bar; SL beyond the structure; TP = TARGET_RR x risk.
Cancelled after PENDING_BARS 15m bars or when the stop level trades first; time stop after MAX_HOLD_BARS.

Not implemented (needs a human eye or data the bot does not have): head and shoulders and other
major reversal patterns, trendline construction, Elliott waves and cycles, point and figure charts,
Volman's break-for-failure setup, manual exits and news handling.

Modes
  python signal_bot_mv_full.py                       live scan (cron every 15 min)
  python signal_bot_mv_full.py selftest              offline check on synthetic candles
  python signal_bot_mv_full.py backtest BTC-USDT-SWAP ETH-USDT-SWAP --bars 8000
  python signal_bot_mv_full.py ablation [PAIR ...] --bars 6000

Backtest uses the exact same engine as live. Treat every signal as unproven until a backtest on
the pairs you scan shows an edge after fees.
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

# --- Murphy x Volman FULL scalp (15m) ---
# Murphy ("Technical Analysis of the Financial Markets"):
#   1H (+4H) trend with MA 9/18, 15m trend, 33-66% retracements (38/50/62), swing support/resistance,
#   flag/pennant with measuring rule, volume confirmation, Bollinger room, RSI guard,
#   candlestick patterns filtered by the Stochastic presignal area.
# Volman ("Understanding Price Action"), applied to the 15m chart:
#   25 EMA dominance, pullback reversal, pattern break, pattern break pullback, combi,
#   round-number magnets, ceiling/technical tests, and the seven "skip" rules of chapter 7.
# Entry = stop order 1 tick beyond the signal bar.
SETUP_ID = "MURPHY_VOLMAN15"


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


TF = "15m"                             # signal candle
TF_MS = 15 * 60_000
MONITOR_TF = "5m"                      # finer candles to resolve pending fills and TP/SL
MONITOR_MS = 5 * 60_000
REF_SYMBOL = "BTC-USDT-SWAP"           # reference symbol for the "new candle" gate
HISTORY_BARS = env_num(420, "HISTORY_BARS")   # 15m bars: ~4.4 days (needs 19 complete 4H bars)
MIN_BARS = 330

# ---- CORE ----
TARGET_RR = env_num(1.75, "TARGET_RR")        # Volman's standard bracket is 1:2

# ---- Murphy: trend context ----
MA_MID, MA_SLOW = 9, 18
HTF_FILTER = env_first("HTF_FILTER") != "0"     # 1H trend must agree (always on in DEFENSIVE mode)
HTF4_FILTER = env_first("HTF4_FILTER") != "0"   # 4H trend must agree too ("combine weeklies and dailies")
RSI15_MAX_LONG = env_num(72.0, "RSI15_MAX_LONG")
RSI15_MIN_SHORT = env_num(28.0, "RSI15_MIN_SHORT")
BB_N, BB_K = 20, 2.0
BB_MIN_R = env_num(0.5, "BB_MIN_R")             # opposite Bollinger band >= this many R away (0 = off)
ST_N, ST_SMOOTH, ST_D = 14, 3, 3
ST_PRESIGNAL = 30.0                              # Murphy candle filter: %D <= 30 (long) / >= 70 (short)
VOL_N = 20
BREAKOUT_VOL_MULT = env_num(1.0, "BREAKOUT_VOL_MULT")   # breakouts need volume >= this x average (Murphy)

# ---- Volman: dominance and skip rules ----
EMA_N = 25
DOM_SLOPE_BARS = 12
DOM_MIN_SLOPE_ATR = env_num(0.3, "DOM_MIN_SLOPE_ATR")   # flat EMA = ranging market (error 3)
RANGE_MAX_CROSSES = 3                                    # price crossing the EMA more often = choppy
EXT_MAX_ATR = env_num(2.5, "EXT_MAX_ATR")                # entry further than this from the EMA (error 4)
FRANTIC_BARS = 10
FRANTIC_MULT = 1.3                                       # error 5: most bars exceed their average span
FRANTIC_SHARE = 0.6

# ---- pullback reversal: Murphy 33-66% retracement + Volman technical test ----
LEG_LOOKBACK = 36
LEG_MIN_ATR = env_num(2.5, "LEG_MIN_ATR")
PB_MIN_BARS, PB_MAX_BARS = 3, 24
PB_MIN_RETR = env_num(0.33, "PB_MIN_RETR")
PB_MAX_RETR = env_num(0.66, "PB_MAX_RETR")      # beyond 2/3 the odds favour a reversal (Murphy)
PB_EMA_TOUCH_ATR = 0.10
TECH_TOL_ATR = 0.30                             # pullback low near a swing level / round number
POWER_ATR = env_num(1.0, "POWER_ATR")

# ---- pattern break / pattern break pullback / combi ----
CLUSTER_BARS = env_num(6, "CLUSTER_BARS")
CLUSTER_MAX_ATR = env_num(2.2, "CLUSTER_MAX_ATR")
BARRIER_TOUCHES = 2
BARRIER_TOL_ATR = 0.15
PBP_LOOKBACK = 10                               # a break within the last N bars, then a retest

# ---- Murphy flag / pennant ----
FLAG_POLE_BARS = 6
FLAG_POLE_MIN_ATR = env_num(3.0, "FLAG_POLE_MIN_ATR")
FLAG_SIZES = (4, 6, 8, 10)

# ---- support / resistance, round numbers, obstruction ----
PIVOT_N = 3                                      # swing high/low = extreme of 3 bars each side
SR_LOOKBACK = 150
OBSTR_R = env_num(0.8, "OBSTR_R")               # a level closer than this many R ahead = obstruction

# ---- stop / cost gates (Volman: tight stop, "no hope-and-pray") ----
SL_MIN_ATR = env_num(0.8, "SL_MIN_ATR")
MAX_SL_ATR = env_num(2.0, "MAX_SL_ATR")
MAX_RISK_PCT = env_num(0.02, "MAX_RISK_PCT")
MIN_RISK_PCT = env_num(0.004, "MIN_RISK_PCT", "SMC_MIN_RISK_PCT")      # 0 disables the cost gate
# Separate cost gate for BTC only. Negative = use MIN_RISK_PCT.
MIN_RISK_PCT_BTC = env_num(-1.0, "MIN_RISK_PCT_BTC", "SMC_MIN_RISK_PCT_BTC")
MAX_OPEN = env_num(15, "MAX_OPEN", "SMC_MAX_OPEN")
COOLDOWN_HOURS = env_num(2.0, "COOLDOWN_HOURS")

# ---- pending stop order / holding time ----
PENDING_BARS = env_num(2, "PENDING_BARS")     # cancel when not triggered within this many 15m bars
MAX_HOLD_BARS = env_num(24, "MAX_HOLD_BARS")  # time stop after filling (24 x 15m = 6 h); 0 = off

# ---- POSITION CROWDING (0 = no limit) ----
MAX_ACTIVE_PER_DIRECTION = env_num(3, "MAX_ACTIVE_PER_DIRECTION", "MAX_ACTIVE_SMC_PER_DIRECTION")
MAX_NEW_PER_CANDLE = env_num(1, "MAX_NEW_PER_CANDLE", "MAX_NEW_SMC_PER_CANDLE")

# ---- session gate: UTC hours of the signal candle to skip (default none) ----
BLOCK_HOURS = parse_hours(env_first("BLOCK_HOURS", "SMC_BLOCK_HOURS"))

# ---- adaptive gate: rolling win rate of the last ADAPT_WINDOW closed trades ----
ADAPT_WINDOW = env_num(30, "ADAPT_WINDOW")
ADAPT_MIN_TRADES = env_num(20, "ADAPT_MIN_TRADES")
ADAPT_MIN_WR = env_num(0.40, "ADAPT_MIN_WR")
DEFENSIVE = [False]      # DEFENSIVE: 1H filter forced on and the Bollinger room doubled
OFF = set()   # filters switched off (ablation only; live = empty)

# --- universe ---
TOP_PAIRS = int(os.getenv("TOP_PAIRS", "150"))
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

SETUP_NAME = {"MURPHY_VOLMAN15": "Murphy × Volman 15m", "MURPHY_VOLMAN": "Murphy × Volman 5m (lama)", "MURPHY_PULLBACK": "Murphy Pullback (lama)", "SMC_SCALP": "SMC Scalp (lama)"}

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
    "Data", "Candle sedikit", "Candle telat", "Murphy 4H", "Murphy 1H", "Murphy 15m", "RSI15",
    "Dominasi", "Ranging", "Frantic", "Setup", "Extended", "SL/RR", "Obstruksi", "Volume",
    "Bollinger", "Diblokir"
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

# ================= MURPHY x VOLMAN FULL SCALP (15m) =================

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

def aggregate(cs, tf_ms, per):
    """Resample candles to a higher frame. Only COMPLETE groups are returned (no lookahead)."""
    groups = {}
    for x in cs:
        groups.setdefault(x[0] // tf_ms, []).append(x)
    out = []
    for k in sorted(groups):
        g = groups[k]
        if len(g) == per:
            out.append([k * tf_ms, g[0][1], max(x[2] for x in g), min(x[3] for x in g),
                        g[-1][4], sum(x[5] for x in g)])
    return out

def _mirror(cs):
    """Flip prices so a SHORT can be evaluated with the LONG rules (and vice versa)."""
    return [[x[0], -x[1], -x[3], -x[2], -x[4], x[5]] for x in cs]

def stoch_d(cs):
    """Stochastic %D (14,3,3) of the last bar."""
    n = len(cs)
    raw = []
    for i in range(n - (ST_SMOOTH + ST_D - 2) - 1, n):
        win = cs[i - ST_N + 1:i + 1]
        hh, ll = max(x[2] for x in win), min(x[3] for x in win)
        raw.append(100 * (cs[i][4] - ll) / (hh - ll) if hh > ll else 50.0)
    k = [sum(raw[j - ST_SMOOTH + 1:j + 1]) / ST_SMOOTH for j in range(ST_SMOOTH - 1, len(raw))]
    return sum(k[-ST_D:]) / ST_D

def round_step(a):
    """Round-number spacing: the {1,2,5}x10^k step that is at least 3 ATR wide (Volman 00/50 levels)."""
    target = 3 * a
    k = math.floor(math.log10(target))
    for m in (1, 2, 5, 10):
        if m * 10 ** k >= target:
            return m * 10 ** k
    return 10 ** (k + 1)

def swing_levels(v, i):
    """Confirmed swing highs / lows (extreme of PIVOT_N bars each side) inside SR_LOOKBACK."""
    hi, lo = [], []
    for j in range(max(PIVOT_N, i - SR_LOOKBACK), i - PIVOT_N + 1):
        win = v[j - PIVOT_N:j + PIVOT_N + 1]
        if v[j][2] == max(x[2] for x in win):
            hi.append((j, v[j][2]))
        if v[j][3] == min(x[3] for x in win):
            lo.append((j, v[j][3]))
    return hi, lo

# ---------- Murphy layer: trend context ----------

def _trend_of(bars):
    if len(bars) < MA_SLOW + 1:
        return None
    c = [x[4] for x in bars]
    m, s = sum(c[-MA_MID:]) / MA_MID, sum(c[-MA_SLOW:]) / MA_SLOW
    return "UP" if (m > s and c[-1] > s) else "DOWN" if (m < s and c[-1] < s) else None

def murphy_context(cs):
    """1H / 4H trend (from complete bars), 15m trend, 15m RSI, Bollinger bands, Stochastic %D."""
    ctx = {"ok": False, "h1": None, "h4": None, "m15": None, "rsi15": None,
           "bb_up": None, "bb_lo": None, "d": None}
    h1 = aggregate(cs, 3_600_000, 4)
    h4 = aggregate(cs, 14_400_000, 16)
    if len(h1) < MA_SLOW + 1 or len(cs) < 60:
        return ctx
    ctx["h1"], ctx["h4"] = _trend_of(h1), _trend_of(h4)

    c = [x[4] for x in cs]
    ma_m, ma_s = sma_list(c, MA_MID), sma_list(c, MA_SLOW)
    if ma_m[-1] > ma_s[-1] and ma_s[-1] > ma_s[-4] and c[-1] > ma_s[-1]:
        ctx["m15"] = "UP"
    elif ma_m[-1] < ma_s[-1] and ma_s[-1] < ma_s[-4] and c[-1] < ma_s[-1]:
        ctx["m15"] = "DOWN"

    ctx["rsi15"] = rsi(cs, RSI_PERIOD)[-1]
    mid, sd = sma_list(c, BB_N)[-1], std_list(c, BB_N)[-1]
    if ctx["rsi15"] is None or mid is None:
        return ctx
    ctx["bb_up"], ctx["bb_lo"] = mid + BB_K * sd, mid - BB_K * sd
    ctx["d"] = stoch_d(cs)
    ctx["ok"] = True
    return ctx

# ---------- Volman layer: setups (long form) ----------
# fn(v, ev, a, i, piv) -> (tag, structural_stop, detail, extra) or (None, reason)

def _vol_avg(v, lo, hi):
    seg = v[lo:hi]
    return sum(x[5] for x in seg) / max(1, len(seg))

def _tech_test(v, ev, a, piv, H, i, P):
    """Volman: never turn on a retracement alone; need a technical element at the pullback low."""
    if min(v[j][3] - ev[j] for j in range(H + 1, i + 1)) <= PB_EMA_TOUCH_ATR * a:
        return f"EMA{EMA_N}"
    tol = TECH_TOL_ATR * a
    for j, p in piv[1]:                      # old swing lows = support
        if j < H and abs(P - p) <= tol:
            return "support"
    for j, p in piv[0]:                      # old swing highs = resistance turned support (ceiling test)
        if j < H and abs(P - p) <= tol:
            return "ceiling test"
    if "ROUND" not in OFF:
        step = round_step(a)
        if abs(P - round(P / step) * step) <= tol:
            return "level bulat"
    return None

def _setup_pullback(v, ev, a, i, piv):
    """Pullback reversal: 33-66% retracement (Murphy), technical test + harmony (Volman)."""
    lo_i = max(0, i - LEG_LOOKBACK)
    last_h = i - PB_MIN_BARS
    if last_h <= lo_i + 3:
        return None, "data kurang"
    H = max(range(lo_i, last_h + 1), key=lambda j: v[j][2])
    if i - H > PB_MAX_BARS:
        return None, "pullback terlalu panjang"
    if H - lo_i < 3:
        return None, "tidak ada leg sebelum swing high"
    S = min(range(lo_i, H + 1), key=lambda j: v[j][3])
    leg = v[H][2] - v[S][3]
    if leg < LEG_MIN_ATR * a:
        return None, f"leg {leg / a:.1f} ATR terlalu kecil"
    P = min(v[j][3] for j in range(H + 1, i + 1))
    retr = (v[H][2] - P) / leg
    if retr < PB_MIN_RETR:
        return None, f"retrace {retr * 100:.0f}% (min {PB_MIN_RETR * 100:.0f}%)"
    if retr > PB_MAX_RETR:
        return None, f"retrace {retr * 100:.0f}% > {PB_MAX_RETR * 100:.0f}% (peluang reversal)"
    tech = _tech_test(v, ev, a, piv, H, i, P)
    if "TECHTEST" not in OFF and not tech:
        return None, "tanpa technical test (EMA / S-R / level bulat)"
    pb_avg = sum(v[j][2] - v[j][3] for j in range(H + 1, i + 1)) / (i - H)
    lo_leg = max(S, H - 9)                  # the impulse itself, not the quiet base before it
    leg_avg = sum(v[j][2] - v[j][3] for j in range(lo_leg, H + 1)) / (H - lo_leg + 1)
    if pb_avg > leg_avg:
        return None, "pullback tidak harmonis"
    for j in range(H + 1, i):                # error 6: aggressive powerbar inside the pullback
        b = v[j]
        if b[4] < b[1] and (b[2] - b[3]) >= 1.5 * POWER_ATR * a:
            return None, "ada powerbar agresif di dalam pullback"
    sg = v[i]
    if not sg[4] > sg[1]:
        return None, "signal bar tidak searah"
    return "PB", P - SL_ATR_BUFFER * a, f"retrace {retr * 100:.0f}% di {tech or '-'}", {"breakout": False}

def _setup_pattern(v, ev, a, i, piv):
    """Pattern break: tight buildup under a barrier, squeezed against the 25 EMA."""
    B = CLUSTER_BARS
    seg = v[i - B + 1:i + 1]
    top, bot = max(x[2] for x in seg), min(x[3] for x in seg)
    height = top - bot
    if height > CLUSTER_MAX_ATR * a:
        return None, f"cluster {height / a:.1f} ATR (maks {CLUSTER_MAX_ATR:g})"
    touches = sum(1 for x in seg if x[2] >= top - BARRIER_TOL_ATR * a)
    if touches < BARRIER_TOUCHES:
        return None, f"barrier baru {touches}x tersentuh"
    sg = v[i]
    if not sg[4] > sg[1]:
        return None, "signal bar tidak searah"
    if sg[2] < top - BARRIER_TOL_ATR * a:
        return None, "signal bar tidak di barrier"
    if sg[4] < bot + 0.7 * height:
        return None, "close signal bar jauh dari barrier"
    above = sum(1 for j in range(i - B + 1, i + 1) if v[j][4] > ev[j])
    if above < 0.7 * B:
        return None, f"hanya {above}/{B} close di atas EMA{EMA_N}"
    return "PATTERN", sg[3] - SL_ATR_BUFFER * a, f"cluster {height / a:.1f} ATR, barrier {touches}x", {"breakout": True}

def _setup_pbp(v, ev, a, i, piv):
    """Pattern break pullback: a break of a buildup, then a retest of the broken barrier."""
    B = CLUSTER_BARS
    for j in range(i - 2, max(i - PBP_LOOKBACK, B + 1) - 1, -1):
        barrier = max(x[2] for x in v[j - B:j])
        base = min(x[3] for x in v[j - B:j])
        if barrier - base > CLUSTER_MAX_ATR * a:
            continue
        if not v[j][4] > barrier:            # bar j closes through the barrier
            continue
        pb = v[j + 1:i + 1]
        if min(x[3] for x in pb) > barrier + TECH_TOL_ATR * a:
            return None, "break belum di-retest"
        if min(x[4] for x in pb) < barrier - 0.5 * a:
            return None, "retest gagal (close kembali ke dalam pattern)"
        sg = v[i]
        if not sg[4] > sg[1]:
            return None, "signal bar tidak searah"
        if sg[4] < ev[i]:
            return None, f"close di bawah EMA{EMA_N}"
        return "PBP", min(x[3] for x in pb) - SL_ATR_BUFFER * a, f"retest barrier setelah break {i - j} bar lalu", {"breakout": True}
    return None, "tidak ada break + retest"

def _setup_combi(v, ev, a, i, piv):
    """Pattern break combi: powerbar followed by an inside bar (the inside bar is the signal bar)."""
    p, s = v[i - 1], v[i]
    rng = p[2] - p[3]
    if rng < POWER_ATR * a:
        return None, "tidak ada powerbar"
    body = p[4] - p[1]
    if not (body > 0 and body >= 0.6 * rng and p[4] >= p[3] + 0.7 * rng):
        return None, "powerbar tidak kuat searah"
    if not (s[2] <= p[2] and s[3] >= p[3]):
        return None, "bar sesudah powerbar bukan inside bar"
    prior_high = max(x[2] for x in v[i - 9:i - 1])
    if not (p[4] > prior_high or p[3] <= ev[i - 1] + 0.3 * a):
        return None, "combi tanpa lokasi (bukan breakout / bukan di EMA)"
    return "COMBI", s[3] - SL_ATR_BUFFER * a, "powerbar + inside bar", {"breakout": False}

def _setup_flag(v, ev, a, i, piv):
    """Murphy flag / pennant: sharp pole on heavy volume, quiet pause in the upper half, burst out."""
    reasons = []
    for F in FLAG_SIZES:
        s = i - F + 1
        if s - FLAG_POLE_BARS < 0:
            continue
        pole = v[s - FLAG_POLE_BARS:s]
        cons = v[s:i]                         # consolidation before the breakout bar
        sg = v[i]
        p_lo, p_hi = min(x[3] for x in pole), max(x[2] for x in pole)
        height = p_hi - p_lo
        if height < FLAG_POLE_MIN_ATR * a:
            reasons.append("pole kecil")
            continue
        if pole[-1][4] < p_lo + 0.7 * height:
            reasons.append("pole tidak berakhir di atas")
            continue
        c_top, c_bot = max(x[2] for x in cons), min(x[3] for x in cons)
        if c_top - c_bot > 0.5 * height:
            reasons.append("flag terlalu lebar")
            continue
        if c_bot < p_lo + 0.5 * height:
            reasons.append("flag turun melewati setengah pole")
            continue
        half = len(cons) // 2
        first = sum(x[4] for x in cons[:half]) / half
        second = sum(x[4] for x in cons[half:]) / (len(cons) - half)
        if second > first + 0.3 * a:
            reasons.append("flag miring searah tren")
            continue
        if _vol_avg(v, s, i) > 0.85 * _vol_avg(v, s - FLAG_POLE_BARS, s):
            reasons.append("volume flag tidak mengering")
            continue
        if not (sg[4] > c_top and sg[4] > sg[1]):
            reasons.append("belum close di atas flag")
            continue
        return ("FLAG", sg[3] - SL_ATR_BUFFER * a, f"pole {height / a:.1f} ATR, flag {F} bar",
                {"breakout": True, "measured": height})
    return None, reasons[0] if reasons else "tidak ada flag"

VOLMAN_SETUPS = [("PB", _setup_pullback), ("PBP", _setup_pbp), ("FLAG", _setup_flag),
                 ("PATTERN", _setup_pattern), ("COMBI", _setup_combi)]
STRUCT_NAME = {"PB": "PULLBACK_REVERSAL", "PBP": "PATTERN_BREAK_PULLBACK", "FLAG": "FLAG_BREAK",
               "PATTERN": "PATTERN_BREAK", "COMBI": "PATTERN_BREAK_COMBI"}
SETUP_PRIORITY = {"PB": 1.5, "FLAG": 1.4, "PBP": 1.3, "PATTERN": 1.0, "COMBI": 0.8}

def _candle_bonus(v, i, d_view):
    """Murphy ch.12: reversal candles only count inside the Stochastic presignal area."""
    if d_view > ST_PRESIGNAL:
        return None
    p, s = v[i - 1], v[i]
    body = abs(s[4] - s[1])
    rng = s[2] - s[3]
    if p[4] < p[1] and s[4] > s[1] and s[1] <= p[4] and s[4] >= p[1]:
        return "engulfing"
    lower = min(s[1], s[4]) - s[3]
    if rng > 0 and body > 0 and lower >= 2 * body and s[4] >= s[3] + 0.65 * rng:
        return "hammer"
    return None

def _attempt(inst, cs, meta, ctx, ema, a, side):
    """
    Evaluate ONE direction on the latest 15m bar.
    Returns a signal dict, or (stage, detail) of the first filter that failed.
    """
    n = len(cs)
    i = n - 1
    up = side == "LONG"
    want = "UP" if up else "DOWN"

    # ---- Murphy: trend context ----
    if "HTF4" not in OFF and HTF4_FILTER and ctx["h4"] != want:
        return "Murphy 4H", f"{side} tren 4H {ctx['h4'] or 'netral'} (perlu {want})"
    if "HTF" not in OFF and (HTF_FILTER or DEFENSIVE[0]) and ctx["h1"] != want:
        return "Murphy 1H", f"{side} tren 1H {ctx['h1'] or 'netral'} (perlu {want})"
    if "M15" not in OFF and ctx["m15"] != want:
        return "Murphy 15m", f"{side} tren 15m {ctx['m15'] or 'netral'} (perlu {want})"
    r15 = ctx["rsi15"]
    if "RSI15" not in OFF:
        if up and r15 > RSI15_MAX_LONG:
            return "RSI15", f"LONG RSI {r15:.0f} overbought (maks {RSI15_MAX_LONG:g})"
        if not up and r15 < RSI15_MIN_SHORT:
            return "RSI15", f"SHORT RSI {r15:.0f} oversold (min {RSI15_MIN_SHORT:g})"

    # ---- evaluate with the long rules; SHORT = mirrored prices ----
    v = cs if up else _mirror(cs)
    ev = ema if up else [None if x is None else -x for x in ema]
    d_view = ctx["d"] if up else 100 - ctx["d"]

    # ---- Volman: dominance (error 1) and ranging market (error 3) ----
    slope = ev[i] - ev[i - DOM_SLOPE_BARS]
    dom = slope >= DOM_MIN_SLOPE_ATR * a and v[i][4] > ev[i]
    if "DOMINANCE" not in OFF and not dom:
        return "Dominasi", f"{side} EMA{EMA_N} slope {slope / a:+.2f} ATR (min {DOM_MIN_SLOPE_ATR:g}) / harga di sisi salah"
    crosses = sum(1 for j in range(i - 19, i + 1)
                  if (v[j][4] - ev[j]) * (v[j - 1][4] - ev[j - 1]) < 0)
    if "RANGE" not in OFF and crosses > RANGE_MAX_CROSSES:
        return "Ranging", f"{side} harga memotong EMA{EMA_N} {crosses}x dalam 20 bar (choppy)"
    # ---- Volman error 5: frantic environment ----
    avg50 = sum(x[2] - x[3] for x in v[i - 50:i]) / 50
    fr = sum(1 for j in range(i - FRANTIC_BARS + 1, i + 1) if (v[j][2] - v[j][3]) > FRANTIC_MULT * avg50)
    if "FRANTIC" not in OFF and fr >= FRANTIC_SHARE * FRANTIC_BARS:
        return "Frantic", f"{side} {fr}/{FRANTIC_BARS} bar melebihi rentang rata-rata"

    # ---- Volman + Murphy setups ----
    piv = swing_levels(v, i)
    found, reasons = None, []
    for tag, fn in VOLMAN_SETUPS:
        if f"SETUP_{tag}" in OFF:
            continue
        r = fn(v, ev, a, i, piv)
        if r[0]:
            found = r
            break
        reasons.append(f"{tag}: {r[1]}")
    if not found:
        return "Setup", f"{side} " + " | ".join(reasons)
    tag, sl_struct_v, extra_txt, extra = found

    sig_hour = datetime.fromisoformat(iso(cs[i][0])).hour
    if sig_hour in BLOCK_HOURS:
        return "Diblokir", f"{side} jam UTC {sig_hour} diblokir (BLOCK_HOURS)"

    tick = meta.get(inst, {}).get("tick", 0.00000001)
    entry_v = v[i][2] + tick
    # ---- Volman error 4: entry too far from the 25 EMA ----
    if "EXTENDED" not in OFF and entry_v - ev[i] > EXT_MAX_ATR * a:
        return "Extended", f"{side} entry {(entry_v - ev[i]) / a:.1f} ATR dari EMA{EMA_N} (maks {EXT_MAX_ATR:g})"

    # ---- stop order 1 tick beyond the signal bar; stop beyond the structure ----
    risk = max(entry_v - sl_struct_v, SL_MIN_ATR * a)
    if risk > MAX_SL_ATR * a:
        return "SL/RR", f"{side} stop struktur {risk / a:.2f} ATR (maks {MAX_SL_ATR:g}), terlalu lebar"
    if extra.get("measured") and extra["measured"] < TARGET_RR * risk:
        return "SL/RR", f"{side} measured move flag {extra['measured'] / risk:.2f}R < RR {TARGET_RR:g}"
    sl_v, tp_v = entry_v - risk, entry_v + TARGET_RR * risk
    if up:
        entry, sl, tp = entry_v, sl_v, tp_v
    else:
        entry, sl, tp = -entry_v, -sl_v, -tp_v
    entry, sl, tp = tick_round(entry, tick), tick_round(sl, tick), tick_round(tp, tick)
    risk = abs(entry - sl)
    if risk <= 0:
        return "SL/RR", f"{side} SL tidak valid"
    risk_pct = risk / entry
    min_risk = MIN_RISK_PCT_BTC if (inst == REF_SYMBOL and MIN_RISK_PCT_BTC >= 0) else MIN_RISK_PCT
    if "MINRISK" not in OFF and risk_pct < min_risk:
        return "SL/RR", f"{side} SL {risk_pct * 100:.2f}% (min {min_risk * 100:.2f}%, fee memakan R)"
    if MAX_RISK_PCT > 0 and risk_pct > MAX_RISK_PCT:
        return "SL/RR", f"{side} SL {risk_pct * 100:.2f}% terlalu jauh (maks {MAX_RISK_PCT * 100:.2f}%)"

    # ---- Volman error 2 + Murphy S/R: do not break straight into a level ----
    if "OBSTRUCTION" not in OFF:
        cands = [(p - entry_v, "swing high") for _, p in piv[0] if p > entry_v]
        if "ROUND" not in OFF:
            step = round_step(a)
            cands.append((math.floor(entry_v / step) * step + step - entry_v, "level bulat"))
        if cands:
            d, what = min(cands)
            if d < OBSTR_R * risk:
                return "Obstruksi", f"{side} {what} hanya {d / risk:.2f}R di depan entry"

    # ---- Murphy: a breakout needs volume ----
    vr = volume_ratio(cs, VOL_N) or 0.0
    if "VOLUME" not in OFF and extra.get("breakout") and vr < BREAKOUT_VOL_MULT:
        return "Volume", f"{side} breakout {tag} volume {vr:.2f}x (min {BREAKOUT_VOL_MULT:g}x)"

    # ---- Murphy: room to the opposite Bollinger band ----
    room_r = ((ctx["bb_up"] - entry) if up else (entry - ctx["bb_lo"])) / risk
    need_room = BB_MIN_R * (2.0 if DEFENSIVE[0] else 1.0)
    if "BBROOM" not in OFF and BB_MIN_R > 0 and room_r < need_room:
        return "Bollinger", f"{side} band hanya {room_r:.2f}R dari entry (min {need_room:g}R)"

    candle = _candle_bonus(v, i, d_view)
    note = (f"{STRUCT_NAME[tag]} ({extra_txt}) | 4H {ctx['h4'] or '-'} · 1H {ctx['h1'] or '-'} · 15m {ctx['m15'] or '-'} | "
            f"RSI {r15:.0f} · Vol {vr:.1f}x | Band {room_r:.2f}R" + (f" | candle {candle}" if candle else ""))

    return {
        "signal_id": f"{inst}|{side}|{cs[i][0]}|{tag}",
        "symbol": inst,
        "direction": side,
        "timeframe": TF,
        "setup": SETUP_ID,
        "setup_tag": tag,
        "note": note,
        "signal_candle_time": cs[i][0],
        "signal_candle_iso": iso(cs[i][0]),
        "created_at": now(),
        "order_type": "BUY STOP" if up else "SELL STOP",
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": TARGET_RR,
        "atr": a,
        "sl_atr": risk / a,
        "ema50": 0.0,
        "ema200": 0.0,
        "rsi": r15,
        "adx": 0.0,
        "volume_ratio": vr,
        "band_room_r": round(room_r, 2),
        "htf": ctx["h1"],
        "htf4": ctx["h4"],
        "rsi_deadzone": False,
        "quality": round(SETUP_PRIORITY[tag] + (0.5 if candle else 0.0) + 0.5 * min(room_r, 3.0)
                         + (1.0 if ctx["h1"] == want else 0.0), 2),
        "mode": "DEFENSIVE" if DEFENSIVE[0] else "NORMAL",
        "regime": "UPTREND" if up else "DOWNTREND",
        "structure": STRUCT_NAME[tag],
        "bos": "NONE",
        "pullback": 0.0,
        "score": None,
        "score_reasons": [],
        "risk_usdt": ACCOUNT_EQUITY * RISK_PER_TRADE,
        "status": "PENDING",
        "exit_price": None,
        "exit_time": None,
        "result_r": None,
        "result": None,
        "monitor_tf_ms": TF_MS,
    }

def build_signal(inst, cs, meta):
    """
    Murphy x Volman FULL on the LAST closed 15m bar of `cs` (both directions).
      Murphy: 4H/1H/15m trend, RSI guard, S/R + round-number obstruction, retracement 33-66%,
              flag measuring rule, breakout volume, Bollinger room, filtered candle patterns.
      Volman: 25 EMA dominance, ranging/frantic/extended skips, then pullback reversal,
              pattern break pullback, flag, pattern break or combi.
    Output is a PENDING stop order 1 tick beyond the signal bar.
    """
    global CUR_SETUP
    CUR_SETUP = SETUP_ID

    if len(cs) < MIN_BARS:
        return _rej(inst, "Candle sedikit", f"hanya {len(cs)} candle (min {MIN_BARS})")

    ctx = murphy_context(cs)
    a = atr(cs, ATR_PERIOD)[-1]
    if not ctx["ok"] or a is None or a <= 0:
        return _rej(inst, "Data", "konteks 1H/4H atau ATR belum siap")
    ema = ema_list([x[4] for x in cs], EMA_N)

    best = None
    for side in ("LONG", "SHORT"):
        res = _attempt(inst, cs, meta, ctx, ema, a, side)
        if isinstance(res, dict):
            return res
        stage, detail = res
        depth = STAGES.index(stage)
        if best is None or depth > best[0]:
            best = (depth, stage, detail)
    return _rej(inst, best[1], best[2])

# ================= BACKTEST (same engine as live) =================

BT = {"signals": 0, "cancel": 0}

def _simulate(cs, k, s):
    """
    Mirror of monitor() on 5m bars. Returns (end_index, kind, r) with kind in
    WIN / LOSS / TIME / CANCEL, or None when the data ends before the trade resolves.
    Conservative: a bar that triggers the entry AND touches the stop = loss; the TP is
    never counted on the trigger bar; SL first when a bar touches both.
    """
    entry, sl, tp = s["entry"], s["sl"], s["tp"]
    long_ = s["direction"] == "LONG"
    n = len(cs)
    if k + PENDING_BARS >= n:
        return None
    fill = None
    for j in range(k + 1, k + 1 + PENDING_BARS):
        hi, lo = cs[j][2], cs[j][3]
        trig = hi >= entry if long_ else lo <= entry
        inval = lo <= sl if long_ else hi >= sl
        if trig:
            if inval:
                return j, "LOSS", -1.0
            fill = j
            break
        if inval:
            return j, "CANCEL", 0.0
    if fill is None:
        return k + PENDING_BARS, "CANCEL", 0.0
    end = n if MAX_HOLD_BARS <= 0 else min(n, fill + 1 + MAX_HOLD_BARS)
    for j in range(fill + 1, end):
        hi, lo = cs[j][2], cs[j][3]
        hit_sl = lo <= sl if long_ else hi >= sl
        hit_tp = hi >= tp if long_ else lo <= tp
        if hit_sl:
            return j, "LOSS", -1.0
        if hit_tp:
            return j, "WIN", float(s["rr"])
    if end >= n:
        return None
    r = float_r(s, cs[end - 1][4])
    return end - 1, "TIME", r

def backtest_series(inst, cs, meta=None):
    meta = meta or {}
    trades, k, busy_until = [], MIN_BARS, -1
    cooldown_bars = int(COOLDOWN_HOURS * 3600_000 / TF_MS)
    while k < len(cs) - 1:
        if k <= busy_until:
            k += 1
            continue
        window = cs[max(0, k - HISTORY_BARS + 1):k + 1]
        s = build_signal(inst, window, meta)
        if not s:
            k += 1
            continue
        res = _simulate(cs, k, s)
        if res is None:
            break
        j, kind, r = res
        BT["signals"] += 1
        if kind == "CANCEL":
            BT["cancel"] += 1
            busy_until = j
            k += 1
            continue
        t = dict(s)
        t.update({"status": "CLOSED", "exit_time": iso(cs[j][0]),
                  "result": "WIN" if r > 0 else "LOSS", "result_r": r, "exit_kind": kind})
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
    tags = {}
    for t in trades:
        tags[t["setup_tag"]] = tags.get(t["setup_tag"], 0) + 1
    print(
        f"{name}: {len(trades)} trade ({longs} long / {len(trades) - longs} short) {tags} | "
        f"WR {wins / len(trades) * 100:.1f}% (BEP net {bep_net:.1f}%) | "
        f"R gross {sum(r):+.2f} | net {net:+.2f} | avg net {net / len(trades):+.3f}R | "
        f"PF {gp / gl if gl else float('inf'):.2f} | MaxDD net -{dd:.2f}R"
    )

def synthetic_candles(n=12000, seed=7):
    """OKX-style 15m candles [ts,o,h,l,c,v] with trend / range regimes, for offline selftest."""
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
        BT["signals"] = BT["cancel"] = 0
        t = backtest_series(inst, cs, meta)
        allt += t
        bt_report(f"{inst} [{iso(cs[0][0])[:10]} -> {iso(cs[-1][0])[:10]}]", t)
        print(f"   sinyal {BT['signals']} | pending batal {BT['cancel']} | terisi {len(t)}")
    if len(insts) > 1:
        bt_report("GABUNGAN", allt)

ABLATION_FILTERS = ["HTF4", "HTF", "M15", "RSI15", "DOMINANCE", "RANGE", "FRANTIC", "EXTENDED",
                    "TECHTEST", "OBSTRUCTION", "ROUND", "VOLUME", "BBROOM", "MINRISK",
                    "SETUP_PB", "SETUP_PBP", "SETUP_FLAG", "SETUP_PATTERN", "SETUP_COMBI"]

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
    """Backtest with every filter / setup switched off one at a time (all others stay on)."""
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
    print(f"\nAblation: {len(data)} pair x {bars} candle {TF} | fee {FEE_PER_SIDE * 100:.2f}%/sisi | RR 1:{TARGET_RR}")
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
    print("\nCatatan: baris 'tanpa SETUP_x' = setup itu dimatikan; baris lain = filter dilonggarkan.")
    if not reliable:
        print(f"PERINGATAN: baseline hanya {base[0]} trade (<60). Selisih antar baris masih noise, "
              "jangan ambil keputusan. Tambah pair atau --bars.")
    else:
        print("Tanda di kanan indikatif (ambang selisih 0,05R). Dengan <200 trade, "
              "selisih sekecil itu masih bisa noise.")

def run_selftest():
    QUIET[0] = True
    allt = []
    for seed in (7, 11, 23):
        BT["signals"] = BT["cancel"] = 0
        t = backtest_series("SYNTH-USDT-SWAP", synthetic_candles(12000, seed))
        allt += t
        bt_report(f"synthetic seed {seed}", t)
        print(f"   sinyal {BT['signals']} | pending batal {BT['cancel']} | terisi {len(t)}")
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

FILL_EVENTS = []   # pending orders that became OPEN during this run (announced by check_open)

def monitor(trade):
    """
    Walk 1m candles after the signal bar.
      PENDING : stop order 1 tick beyond the signal bar. Filled when price trades through it;
                cancelled when not filled within PENDING_BARS signal bars, or when price
                reaches the stop level first.
      OPEN    : SL / TP (SL first when one candle touches both), time stop after MAX_HOLD_BARS.
    A candle that fills the order AND touches the stop counts as a loss (conservative);
    the TP is never counted on the fill candle.
    """
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

    long_ = trade["direction"] == "LONG"
    entry, sl, tp = trade["entry"], trade["sl"], trade["tp"]
    pending = trade.get("status") == "PENDING"
    expiry = start + PENDING_BARS * TF_MS

    def finish(c, exit_price, r, result):
        t = dict(trade)
        t.update({"status": "CLOSED", "exit_price": exit_price, "exit_time": iso(c[0]),
                  "result_r": r, "result": result})
        return t

    def cancel(c, why):
        t = dict(trade)
        t.update({"status": "CANCELLED", "exit_price": None, "exit_time": iso(c[0]),
                  "result_r": 0.0, "result": why})
        return t

    for c in [x for x in cs if x[0] >= start]:
        hi, lo = c[2], c[3]

        if pending:
            if c[0] >= expiry:
                return cancel(c, "EXPIRED")
            trig = hi >= entry if long_ else lo <= entry
            inval = lo <= sl if long_ else hi >= sl
            if trig:
                trade["status"] = "OPEN"
                trade["entry_ts"] = c[0]
                trade["entry_time"] = iso(c[0])
                pending = False
                FILL_EVENTS.append(dict(trade))
                if inval:                      # filled and stopped inside the same candle
                    return finish(c, sl, -1.0, "LOSS")
                continue
            if inval:
                return cancel(c, "INVALID")
            continue

        hit_sl = lo <= sl if long_ else hi >= sl
        hit_tp = hi >= tp if long_ else lo <= tp
        if hit_sl and hit_tp:
            return finish(c, sl, -1.0, "LOSS")
        if hit_tp:
            return finish(c, tp, float(trade.get("rr", RR)), "WIN")
        if hit_sl:
            return finish(c, sl, -1.0, "LOSS")

        ets = trade.get("entry_ts")
        if ets and MAX_HOLD_BARS > 0 and c[0] + mon_ms >= ets + MAX_HOLD_BARS * TF_MS:
            r = float_r(trade, c[4])
            return finish(c, c[4], r, "WIN" if r > 0 else "LOSS")
    return None

def check_open(h):
    if not h["open"]:
        return 0

    FILL_EVENTS.clear()
    remain, closed, cancelled = [], [], []

    for t in h["open"]:
        try:
            result = monitor(t)
            if result:
                (cancelled if result.get("status") == "CANCELLED" else closed).append(result)
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
    if cancelled:
        h["cancelled"] = (h.get("cancelled", []) + cancelled)[-300:]
    if closed or cancelled or FILL_EVENTS:
        save_history(h)

    for t in FILL_EVENTS:
        tg(
            f"<b>🔔 ORDER TERISI</b>\n"
            f"<b>{t['symbol']}</b> {t['direction']} @ <code>{t['entry']}</code>\n"
            f"SL <code>{t['sl']}</code> | TP <code>{t['tp']}</code>"
        )

    for t in cancelled:
        why = "tidak terisi dalam batas waktu" if t["result"] == "EXPIRED" else "SL tersentuh sebelum terisi"
        tg(
            f"<b>❎ ORDER BATAL</b>\n"
            f"<b>{t['symbol']}</b> {t['direction']} @ <code>{t['entry']}</code>\n"
            f"Alasan: {why}"
        )

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
    live = [t for t in h["open"] if t.get("status") != "PENDING"]
    n_pend = len(h["open"]) - len(live)
    if not live:
        return

    blocks, rs = [], []

    for t in live:
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
        f"Open Positions : {len(live)} (+{n_pend} pending)\n"
        f"Profitable     : {sum(x > 0 for x in rs)}\n"
        f"Negative       : {sum(x < 0 for x in rs)}\n"
        f"Floating R     : <b>{total:+.2f}R</b>\n"
        f"Average Float  : {avg:+.2f}R\n"
        f"Best           : {max(rs):+.2f}R\n"
        f"Worst          : {min(rs):+.2f}R\n\n"
        f"TP Potential   : +{sum(float(x.get('rr', RR)) for x in live):.2f}R\n"
        f"SL Exposure    : -{len(live):.2f}R\n\n"
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
        f"{s['timeframe']} | <b>{SETUP_NAME.get(setup, setup)}</b> · {s.get('structure', '-')}\n"
        f"{_safe(s.get('note', ''))}\n\n"
    )

    return (
        "<b>🚨 ALPHAQUANT MURPHY x VOLMAN V8.0 FULL SIGNAL</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"<b>{s['symbol']}</b> · <b>{s['direction']}</b>\n" +
        head +
        "<b>TRADE PLAN</b>\n"
        f"Order: <b>{s.get('order_type', 'MARKET')}</b> @ <code>{s['entry']}</code>\n"
        f"SL: <code>{s['sl']}</code>\n"
        f"TP: <code>{s['tp']}</code>\n"
        f"RR: <b>1:{float(s.get('rr', RR)):.2f}</b>\n"
        f"SL: {s['sl_atr']:.2f} ATR · {risk_pct:.2f}% harga\n"
        f"Fee ≈ {fee_r:.2f}R (taker {FEE_PER_SIDE * 100:.2f}%/sisi)\n\n"
        f"Batal bila belum terisi dalam {PENDING_BARS} candle {TF}, atau SL tersentuh lebih dulu.\n"
        f"Time stop {MAX_HOLD_BARS * TF_MS / 3_600_000:g} jam setelah terisi.\n\n"
        f"RSI: {s['rsi']:.0f} | 4H: {s.get('htf4') or '-'} | 1H: {s.get('htf') or '-'} | Vol {s.get('volume_ratio', 0):.1f}x\n"
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
        if stage in STAGES and stage not in ("Data", "Candle sedikit", "Candle telat", "Murphy 4H", "Murphy 1H", "Murphy 15m", "RSI15"):
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
        "<b>⚡ MURPHY x VOLMAN · SCAN REPORT</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Scan         : {d['scans']} candle {TF}\n"
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
    Scan the top pairs for a Murphy x Volman scalp on every NEW 15m candle.
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

            # A slow scan can straddle a candle boundary: pairs fetched after it already have a
            # newer candle. Cut every pair back to the reference candle so all use the same bar.
            if ref is not None:
                cs = [x for x in cs if x[0] <= ref]
            # Stale data (no trades in the latest bar): never signal on an old candle.
            if not cs or (ref is not None and cs[-1][0] != ref):
                _rej(inst, "Candle telat", "candle terakhir tidak sinkron dengan acuan BTC")
                continue

            s = build_signal(inst, cs, meta)
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
    log.info("ALPHAQUANT MURPHY x VOLMAN V8.0 FULL STARTING")
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

    log.info(
        "Build MV-FULL-8.0 | HTF4=%s HTF=%s | PB retr %.0f-%.0f%% | cluster<=%.1fATR | "
        "PENDING_BARS=%s | MAX_HOLD_BARS=%s | MaxSL=%.1fATR | BB_MIN_R=%s | BreakoutVol>=%.1fx",
        "ON" if HTF4_FILTER else "OFF", "ON" if HTF_FILTER else "OFF",
        PB_MIN_RETR * 100, PB_MAX_RETR * 100, CLUSTER_MAX_ATR,
        PENDING_BARS, MAX_HOLD_BARS, MAX_SL_ATR, BB_MIN_R, BREAKOUT_VOL_MULT
    )

    today = datetime.now(timezone.utc).date().isoformat()
    if TELEGRAM and h.get("last_online_day") != today:
        h["last_online_day"] = today
        tg(
            "<b>🟢 ALPHAQUANT MURPHY x VOLMAN V8.0 FULL ONLINE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Murphy x Volman FULL 15m · top {TOP_PAIRS} pair\n"
            "4H/1H trend · S/R · retracement · flag (Murphy) · EMA25 · pullback / pattern break / combi (Volman)\n"
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
