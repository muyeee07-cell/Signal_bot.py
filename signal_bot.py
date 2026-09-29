"""
ALPHAQUANT V3.1
1H Quant Momentum-Structure Telegram Signal Engine
Signal-only / OKX USDT perpetuals / RR 1:2

V3.1 fixes:
- Paginated OKX 1H candles (EMA200 gets enough history)
- Paginated 5m monitoring
- Real-time OKX ticker price for running reports
- Telegram credentials checked at startup
- Instrument tick-size rounding
- Signal ID deduplication
- Monitoring starts from signal candle
- Atomic history writes
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

TIMEFRAME = "1H"
MONITOR_TF = "5m"

TOP_PAIRS = 100
MIN_VOLUME_USDT = 4_000_000

HISTORY_BARS = 350
MONITOR_BARS = 500
# Upper cap for 5m monitoring history (~4.8 days). OKX /market/candles
# only serves a limited recent window.
MONITOR_MAX_BARS = 1400

# Minimum confirmed 1H candles required for EMA200 + structure.
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
SL_ATR_BUFFER = 0.20

ADX_MIN = 20.0
ADX_STRONG = 25.0
VOL_MIN = 0.80

MIN_SCORE = 75
MIN_SL_ATR = 0.30
MAX_SL_ATR = 2.50

RR = 2.0
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.004"))
ACCOUNT_EQUITY = float(os.getenv("ACCOUNT_EQUITY", "1000"))

MAX_OPEN = 12
COOLDOWN_HOURS = 3
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
log = logging.getLogger("V3.1")

S = requests.Session()
S.headers.update({"User-Agent": "ALPHAQUANT-V3.1"})

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

def build_signal(inst, cs, meta):
    if len(cs) < MIN_HISTORY_BARS:
        log.info(
            "SKIP %s | only %s confirmed 1H candles "
            "(need %s for EMA200/structure)",
            inst, len(cs), MIN_HISTORY_BARS
        )
        return None

    closes = [x[4] for x in cs]
    e50 = ema(closes, EMA_FAST)
    e200 = ema(closes, EMA_SLOW)
    at = atr(cs, ATR_PERIOD)
    rs = rsi(cs, RSI_PERIOD)
    ax, pdi, mdi = adx(cs, ADX_PERIOD)
    vr = volume_ratio(cs, VOL_PERIOD)

    vals = [e50[-1], e200[-1], at[-1], rs[-1], ax[-1], vr]
    if any(x is None for x in vals):
        return None

    slope = e50[-1] - e50[-6]
    close = cs[-1][4]

    bull_regime = close > e200[-1] and e50[-1] > e200[-1] and slope > 0
    bear_regime = close < e200[-1] and e50[-1] < e200[-1] and slope < 0

    if not bull_regime and not bear_regime:
        return None

    hs, ls = swings(cs)
    hhhl, lhll = structure(hs, ls)
    bull_bos, bear_bos = bos(cs, hs, ls, at)

    if bull_regime:
        side = "LONG"
        if not (hhhl or bull_bos):
            return None
        if not 50 < rs[-1] < 70:
            return None
        if pdi[-1] is not None and mdi[-1] is not None and pdi[-1] <= mdi[-1]:
            return None
    else:
        side = "SHORT"
        if not (lhll or bear_bos):
            return None
        if not 30 < rs[-1] < 50:
            return None
        if pdi[-1] is not None and mdi[-1] is not None and mdi[-1] <= pdi[-1]:
            return None

    if ax[-1] < ADX_MIN or vr < VOL_MIN:
        return None

    # Pullback to EMA50/value zone.
    distance_atr = abs(close-e50[-1]) / at[-1]
    if distance_atr > 0.75:
        return None

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

    if not 0.30 <= retr <= 0.70 or not confirm:
        return None

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
        return None

    if side == "LONG":
        if not ls:
            return None
        sl = ls[-1][1] - SL_ATR_BUFFER*at[-1]
        risk = close - sl
        if risk <= 0:
            return None
        tp = close + RR*risk
    else:
        if not hs:
            return None
        sl = hs[-1][1] + SL_ATR_BUFFER*at[-1]
        risk = sl - close
        if risk <= 0:
            return None
        tp = close - RR*risk

    sl_atr = risk/at[-1]
    if not MIN_SL_ATR <= sl_atr <= MAX_SL_ATR:
        return None

    tick = meta.get(inst, {}).get("tick", 0.00000001)
    entry = tick_round(close, tick)
    sl = tick_round(sl, tick)
    tp = tick_round(tp, tick)

    signal_id = f"{inst}|{side}|{cs[-1][0]}"

    return {
        "signal_id": signal_id,
        "symbol": inst,
        "direction": side,
        "timeframe": "1H",
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
    # Entry = close of the signal 1H candle, so monitoring must begin
    # when that candle ENDS (open time + 1H), not when it opened.
    start = trade.get("signal_candle_time", 0) + 3_600_000

    # Fetch enough 5m candles to cover the full trade age (not a fixed 500).
    age_ms = max(0, int(time.time() * 1000) - start)
    needed = max(60, age_ms // 300_000 + 24)
    if needed > MONITOR_MAX_BARS:
        log.warning(
            "Monitor %s: trade age needs %s 5m bars, capped at %s "
            "(older TP/SL hits may be missed)",
            trade["symbol"], needed, MONITOR_MAX_BARS
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

        # Same 5m candle touches both: conservative SL first.
        if hit_sl and hit_tp:
            exit_price, r, result = sl, -1.0, "LOSS"
        elif hit_tp:
            exit_price, r, result = tp, RR, "WIN"
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
            f"Score: {t['score']}/100\n"
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
            f"{emoji} <b>{t['symbol']}</b> · {t['direction']}\n"
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
        f"Target RR      : 1:{RR:.1f}\n"
        f"TP Potential   : +{len(h['open'])*RR:.2f}R\n"
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

    tg(
        "<b>📊 V3.1 PERFORMANCE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Trades        : {len(ts)}\n"
        f"Wins          : {len(wins)}\n"
        f"Losses        : {len(losses)}\n"
        f"Win Rate      : <b>{len(wins)/len(ts)*100:.2f}%</b>\n"
        f"Total R       : <b>{total_r:+.2f}R</b>\n"
        f"Avg R/Trade   : {total_r/len(ts):+.3f}R\n"
        f"Profit Factor : {pf_text}\n"
        f"Max Drawdown  : -{dd:.2f}R\n"
        f"RR Target     : 1:{RR:.1f}\n"
        "BEP WR @ 1:2  : <b>33.33%</b>"
    )

# ================= SCAN =================

def signal_message(s):
    return (
        "<b>🚨 ALPHAQUANT V3.1 SIGNAL</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"<b>{s['symbol']}</b> · <b>{s['direction']}</b>\n"
        f"1H | Score <b>{s['score']}/100</b>\n"
        f"Regime: {s['regime']}\n"
        f"Structure: {s['structure']}\n"
        f"BOS: {s['bos']}\n\n"
        "<b>TRADE PLAN</b>\n"
        f"Entry: <code>{s['entry']}</code>\n"
        f"SL: <code>{s['sl']}</code>\n"
        f"TP: <code>{s['tp']}</code>\n"
        f"RR: <b>1:{RR:.1f}</b>\n"
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
    if len(h["open"]) >= MAX_OPEN:
        log.info("Max open positions reached.")
        return

    pairs = top_pairs()
    meta = instruments()

    log.info("Scanning %s pairs...", len(pairs))
    created = 0

    for inst in pairs:
        if len(h["open"]) >= MAX_OPEN:
            break

        try:
            cs = candles(inst, TIMEFRAME, HISTORY_BARS)
            if len(cs) < MIN_HISTORY_BARS:
                log.info(
                    "SKIP %s | only %s confirmed 1H candles "
                    "(need %s for EMA200/structure)",
                    inst, len(cs), MIN_HISTORY_BARS
                )
                continue

            s = build_signal(inst, cs, meta)
            if not s or blocked(h, s):
                continue

            h["open"].append(s)
            save_history(h)

            tg(signal_message(s))
            log.info(
                "NEW SIGNAL %s %s score=%s",
                s["symbol"], s["direction"], s["score"]
            )
            created += 1
            time.sleep(0.3)

        except Exception as e:
            log.exception("Scan error %s: %s", inst, e)

    log.info("Scan complete. New signals: %s", created)

# ================= MAIN =================

def main():
    global TELEGRAM

    log.info("==========================================")
    log.info("ALPHAQUANT V3.1 STARTING")
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
            "<b>🟢 ALPHAQUANT V3.1 ONLINE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "1H Quant Momentum–Structure\n"
            "EMA50/200 • Structure • BOS\n"
            "RSI • ADX • ATR • Volume\n"
            "RR 1:2 • Signal-only\n"
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
            scan(h)
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
