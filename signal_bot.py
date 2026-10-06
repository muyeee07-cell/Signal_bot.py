#!/usr/bin/env python3
"""Bot Scalping PLAYBOOK NONSTOP - TOP 50 pair USDT-SWAP, TF 15m
  Strategi rule-based sesuai 'High Probability Scalping Playbook':
    #4 RSI+WMA | #5 MFI+HMA | Ch1 SMA500+HMA30+StochRSI | #ma", "side3 BB+RSI
  Regime switch via ADX14": side,
                "sl: >=20 strategi trend, <25 strategi mean-reversion
  MODE TANPA REM: tanpa cooldown, tanpa max posisi, tanpa kuota harian,
  tanpa pause/stop, tanpa guard volatilitas, tanpa kunci duplikat pair.
  Setiap scan menyapu seluruh universe dan membuka semua sinyal yang lolos.
  Yang tersisa BUKAN rem tapi aturan strategi & kewarasan sizing:
  risk 0.4%/trade, lantai SL 0.10%, exit indikator per buku, TO 24 jam
  AI Gate: Gemini (conf min 65, double-check, sizing, review harian)
Mode: scan | daily | stats [days] | test | aitest
": sl_from_c"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta

CFG = {
    "top_n_pairs": 50,
    "min_vol_24h_usdt": 10_000_000,
    "tf": "15m",
    "candles": 600,
    "adx_trend_min": 20,
    "adx_range_max": 25,
    "sl_buffer_atr": 0.10,
    "sl_min_pct": 0.10,
    "lookback_touch": 5,
    "strats": ["rsi_wma", "mfi_hma", "hma_stoch", "bb_rsi"],
    "running_update_every_checks": 4,
    "max_hold_hours": 24,
    "heartbeat": True,
    "risk_pct": 0.4,
    "ai_enabled": True,
    "ai_fail_open": True,
    "ai_notify_reject": False,
    "ai_model_gh": "gpt-4o-mini",
    "ai_min_conf": 65,
    "ai_double_check": True,
    "ai_conf_sandle(side, sizing": True,
    "ai_daily_review": True,
}
FALLBACK_PAIRS = ["BTCUSDT",, i),
                "why": "S "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
                  "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
                  "LTCUSDT", "UNIUSDT", "ATOMUSDT", "NEARUSDT", "APTUSDT",
                  "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT", "PEPEUSDT"]
STRAT_TITLE = {
    "rsi_wma": "RSI+WMA (#4)",
    "mfi_hma": "MFI+HMA (#5)",
    "hma_stoch": "SMA500+HMA30+StochRSI (Ch1)",
    "bb_rsi": "BB+RSI (#3)",
}
EXIT_DESC = {
    "rsi_wma": "exit saat close lintas balik HMA50",
    "mfi_hma": "exit saat closeMA200 lintas balik HMA ok, MFI21 cross SMA18 di zona ekstrem, "
                       "close break65",
    "hma_stoch": "exit saat close lintas balik HMA30",
    "bb_rsi": "exit saat HMA65"}
    return harga sentuh band None

def st_hma_stoch BB berlawanan",(s, i):
    c =
}
OKX = s["c"]
    for side "https://www.okx.com"
STATE_FILE = os.path.join(os.getcwd(), "state.json")
W in ("LONG", "SHORT"):
        if side == "LONG":
            if s["sma500"][i] is None or c[i] <= s["sma500"][i]:
                continue
            if not stoch_cross("LONG", s, i, IB = timezone(timedelta(hours=7))

# ---------------- util ----------------
def http_get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "gha3):
                continue
            if not xabove(c, s["hma30"], i):
                continue
        else:
            if s["sma500"][-scalper/1.0"})
    with urllib.request.urlopen(req, timeout=15) asi] is None or c[i] >= s["s r:
        return json.loads(r.read())

def okx(path, params=None):ma500"][i]:
                continue
           
    time.sleep(0.12)
    if not stoch_cross("SHORT", s, i, 3):
                continue
 r = http_get(OKX + path, params)
    if r.get("code") != "0":
        raise RuntimeError("OKX " + str(r.get("code")) + ": " + str            if not xbelow(c, s["hma30"], i):
                continue
       (r.get("msg return {"strat": "hma_st")))
    return r["data"]

def inst_id(sym):
    return sym.replaceoch", "side": side,
                "sl": sl_from_candle(side, s, i),("USDT",
                "why "-USDT-SWAP", 1)

def now_ms():
    return int(time.time() * 100": "SMA500 ok, StochRSI cross "
                       f"{'up <50' if side=='LONG' else '0)

down >50def wib_now():
    return datetime.now(timezone'}, "
                       "close break HMA30"}
    return None

def st_bb.utc).astime_rsi(s,zone(WIB)

def wib i):
   _date():
    for side in ("LONG", "SHORT return wib_now().date().isoformat()

def week_key():"):
        if
    return w not bb_touch(side, s, iib_now().is, CFG["lookocalendar()[:2]

def fmt(x):
    if xback_touch"]):
            continue
        if not rsi5_extreme_then_exit(side, s, i, CFG["lookback_touch"]):
            continue
        >= 10 return {"strat00:
        return f"{x:,.1f}"
    if x >= ": "bb_r1:
       si", "side": side,
                "sl": sl_from_swing(side, return f"{x:,.2f}"
    return f"{x:,.4f}" s, i),
                "why

def esc(s):
    return": f"ADX (str(s).replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", sideways, harga tembus band "
                       f"{'bawah' if side=='LONG' else 'atas'} BB40, " "&gt;"))

def tg(text):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
                       f"RSI5 keluar zona "
                       f"{'overs
    chat =old' if side=='LONG' else 'overbought'}"}
    return None

STRAT_FNS = {
    "rsi_wma os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("[tg] secrets belum diset, skip:", text[:60])
        return": st_rsi_wma,
    "mfi
    data =_hma": st_mfi_hma,
    "hma_stoch": st_hma_stoch,
    "bb_rsi": urllib.parse.urlencode(
        {"chat_id": chat, "text": text, "parse_mode": "HTML",
         "disable_web_page_preview": "true"}). st_bb_rsiencode()
   ,
}

def exit_hit(strat, side, s, j):
    c for _ in range(3):
        try:
            urllib.request.urlopen(urllib.request.Request = s["c"]
    if(
                " j < 1:
        return False
    if strat == "rshttps://api.telegram.org/bot" + tok + "/sendMessage",
                data=data),i_wma": timeout=15
        hv = s["hma)
            return50"][j]
        if hv is None:
            return False
        return
        except Exception as e:
            print("[tg] retry:", e)
            time c[j] <.sleep(2) hv if side
    print("[tg] GAG == "LONG"AL kirim")

def tg_long(text else c[j] > hv):
    if len(text) <= 4000:
        tg(text); return
    chunks, cur = [], ""
    for line in text.split("\
    if strat == "mfi_hma":
        hv = s["hma65"][j]
        if hv is None:
            return False
        return c[j] < hv if side == "LONG" else c[j]n"):
        if len(cur) + len(line) + 1 > 3900:
            chunks.append(cur); cur = line + "\n"
 > hv
    if strat == "hma_stoch":
        hv = s["hma30"][j]
        if hv is None:
            return False
        return c[j] < hv if side        else:
            cur += line + "\n"
    if cur:
        chunks.append(cur)
    for i, == "LONG" else c[j] > hv
    if strat == "bb_rsi":
        if s["bb_u"][j] is None or s["bb_l"][j] is None:
            return False
        return s["h"][j] >= s["bb_u"][j] if side == "LONG" \
            else s c in enumerate(chunks):
        if i > 0:
            time.sleep(0["l"][j] <= s.3)
        tg(c.rstrip())

# ---------------- data OKX ----------------
def get_universe():
    try:
        tickers = okx("/api/v5/market/tickers", {"instType": "SWAP"})
        cands = []
        for t in tickers:
            iid = t.get("instId", "")
            if not iid.endswith("-USDT-SWAP"):
                continue
            try:
                vol = float(t.get("volCcy24h", 0))
                last = float(t.get("last", 0))
                if last <= 0:
                    continue
                vu = vol * last
["bb_l"][j]
    return False

def compute_signal(sym, funnel=None):
    def hit(key):
        if funnel is not None:
            funnel[key] = funnel.get(key, 0) + 1
    try:
        k = fetch_klines(sym, CFG["tf"], CFG["candles"])
    except Exception as e:
        print                if vu < CFG["min_vol_24h_usdt"]:(f"[pb-{sym}] fetch error: {e
                    continue
}")
        return                cands.append None
    s = build_series(k((vu, iid)
    i = len(s["c"]) - 1
    if i < 520 or not s["atr"][i]:
        return None
    adxv = s["adx"][.replace("-USDT-SWAP", "USDT")))
            except (ValueError, TypeError):
                continue
        cands.sort(reverse=True)
        out = [s for _, s in ci]ands[:CFG["top_n_pairs"]
    if ad]]
        ifxv is None:
        return None
    if adxv >= CFG["adx_trend_min"]:
        hit("regime_trend")
    if adxv < CFG["adx_range_max"]:
        hit("regime not out:
            raise RuntimeError("empty universe")
        print(f"[pairs] universe top{CFG['top_n_pairs']}: {len(out)} pair")
        return out
    except Exception as e:
        print(f"[pairs] fetch gagal ({e}), pakai fallback")
        return list(FALLBACK_PAIRS)

def fetch_klines(sym, iv, limit=400, include_live=False):
    inst = inst_id(sym)
    bar = iv if iv[-1_range")
    for name in CFG["strats"]:
        if name in ("rsi_wma", "mfi_hma", "hma_stoch") \
           and adxv < CFG["adx_trend_min"]:
            continue
] in ("m        if name == "bb_rsi" and adxv > CFG["adx_range_max"]:
            continue
        res = STRAT_FNS[name](s, i)
        if not res:
            continue
        hit("sig_" + name)
        entry = s", "M") else iv.upper()
    rows = okx("/api/v5/market/candles",
               {"instId": inst, "bar": bar, "limit": "300"})["c"][
    while leni]
        side = res["side"](rows) < limit:
        oldest = rows[-1][0]
        d = okx("/api/v5/market/history-candles",

        sl =                {"instId res["sl"]
        d =": inst, "bar": bar, "after": oldest, "limit": "100 abs(entry - sl)
        if d <= 0"})
        if:
            continue
        min_d = CFG[" not d:
            break
        rows += d
sl_min_pct"]        if len(d / 10) < 10 * entry
00:
            break
    seen, out = set(), []
    for r in rows:
        if r[0] in seen:
            continue
        if not include_live and r[8] != "1":
            continue
        seen        if d < min_d:
            d = min_d
            sl = entry - d if side == "LONG" else entry + d
        reason = (f"Playbook {STRAT_TITLE[name]} @15m, ADX {.add(r[0adxv:.0])
        tsf}: " = int(r[0])
        out.append([ts, float(r[
                  f"{res['why']}1]),")
        return {"symbol": sym, "side": side, "entry": entry,
                "sl": sl, "tp": None, "tp1": None, "tp2": None,
                " float(r[2]), float(r[3]),
                    float(r[4]), float(r[5]), ts + 1, r[8]])
    out.sortreason": reason,(key=lambda x: x[0])
    return out[-limit:]

def fetch_price(sym):
    d = okx("/api/v5/market/ticker", {"instId": inst_id(sym)}) "layer": "PB", "strat": name,
                "stage": 0, "legacy": False, "adx": adxv,
                "market_type": "trend" if
    return float adxv >=(d[0]["last"]) CFG["adx_t

def parse(krend_min"]
):
    return                else "range ([x[0",
                "rr": 0.0, "zone_type": STR] for x in k], [x[1] forAT_TITLE[name], x in k],
                "tf": CFG["tf"], "filled": True, "fill_ms": 0,
                "be_r": 0.0, "trail": False [x[4] for x in k],
            [x[2] for x in k], [x[3] for x in k], [x[5] for x in,
                " k])

# ---------------- indikatorrisk_pct_base": CFG["risk_pct"]}
    return ----------------
def ema None

# ================================================================
# ========== AI GATE ==============================================
(v, n):
    k = 2 / (# ================================================================
n + 1AI_PROMPT = (
    "Kamu adalah risk manager scalping crypto)
    out = [v[0]]
    for x in v[1:]:
        out.append yang ketat(x * k +.\n"
    "Tugas: menilai apakah sinyal indikator berikut layak dieksekusi. "
    "TOLAK jika:\n"
    out[-1] * (1 - k))
    return out

def sma(v, n):
    out = [None] * len(v "- candle terakhir menunjukkan)
    for rejection kuat BERLAWANAN arah sinyal\n"
    "- sinyal lahir tepat di zona support/resistance besar berlawanan\n"
 i in range(n - 1, len(v)):
        out[i] = sum(v[i-n+1:i+1])    "- / n
    volatilitas terlalu ekstrem sehingga stop candle-entry tidak masuk akal\n"
    "- return out

def wma(v, n):
    out = [None] * len(v)
    denom = kondisi market (ADX n * (n) tidak cocok dengan + 1) jenis strateg / 2.0
    for i in range(n - 1, len(v)):
        acc = 0.0inya\n"

        for j    "Data sinyal:\n{dossier}\n"
    "Balas HANYA dengan JSON: "
    '{"approve": true/false, "confidence":  in range(n):
            acc += v[i-n+1+j0-10] * (j + 1)
        out[i] = acc / denom
    return out

def hma(v, n0, '
    '"risk_multiplier": 0.5 atau 0.75 atau 1.0, '
   ):
    '"reason": "<maksimal 20 kata dalam n2 = max(1, n // 2) bahasa indonesia>"}
    ns =\n'
    "Aturan risk_multiplier max(1, int(round(n ** 0.5: 1.)))
    a0 = setup sangat layak; 0.75 = layak dengan "
    "keraguan kecil; 0.5 = marginal tapi = wma(v, n2)
    b = wma(v, n)
    xs = [None] * len(v)
    for i in range(len masih bisa diterima."(v)):
)

AI_REVIEW_PROM
        if a[i] is notPT = (
 None and b[i] is not None:
            xs[i] = 2 * a[i] - b[i]
    idx0 = next    "Kamu analis trading profesional yang objektif.\n"
    "Berikut jurnal trade crypto futures terakhir sistem kami:\n{journal}\n"
   ((i for i "Tugas:, x in enumerate(xs) (1) ring if x is notkas pola kemenangan/kerugian dalam  None),1-2 kalimat, "
    "(2) sebut pair atau strategi yang perlu diwaspadai, "
    "(3) beri maksimal None)
    if idx0 is None:
        return [None] * len(v)
    w = wma(xs[idx0:], ns)
    return [None] * idx0 + w

def rsi(v, n=14):
    g = [0 3 saran perbaikan parameter yang spesifik dan aman.\n"
    "Jawab dalam bahasa indonesia, maksimal 150 kata, teks.0] + biasa tanpa JSON." [max(v[i] - v[i-1], 0) for i in range(1, len(v))]
    l = [0.0] + [max(v[i-1] - v[i], 0) for
)

def _ai_http_json(url, body, headers):
    req = urllib.request.Request(url, i in range( data=json.dumps(body).encode(),
                                 headers=headers)
    try:
        with urllib.request.urlopen1, len(v(req, timeout=))]
    ag = [0.0] * len(v)
    al = [0.0] * len(v)
    out =30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = ""
        try [50.:
            detail = e.read().0] * lendecode()[:(v)
    ag[n] = sum(g[1:n+1]) / n
    al[n] = sum(l[1:n+1])300]
        except Exception:
            pass
        print("[ai] HTTP", e.code, "-> / n
   ", detail)
 for i in range(n+1, len(v)):
        ag[i] = (ag[i-1] * (n-        raise

def _ai_http_get_json(url):
    req = urllib.request.Request(url, headers={"Content-Type": "1) + gapplication/json"})
    try:
        with urllib.request.urlopen(req, timeout=30)[i]) / n
        al[i] = (al[i-1] * (n-1) + l[i]) / n
    for i in range(n, len(v as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:300]
        except Exception:
            pass
        print("[ai)):
        out[i] = 100.0 if al[i] == 0] HTTP", e.code, "->", detail)
        raise

_GEM_MODEL_CACHE = {}

def _gemini_pick_model(key):
    try:
        d = else 100 - 100 / (1 + ag[i] / al[i])
    return out

def atr(h, l, c, n=14):
    tr = [h[0] - l[0]]
    for i in range(1, len(c)): _ai_http_get_json(
            "https://generativelanguage.googleapis.com/v1beta/models?key=" +
        tr.append(max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])))
    a = [None] * len(tr)
    a[n-1] = sum(tr[:n]) / n
    for i in range(n, len(tr)):
        a[i] = (a[i-1] * (n-1) + tr[i]) / n
    return a

def adx(h, l, c, n=14):
    if len(c) < n + 1:
        return [ key)
    except Exception as e:
        print("[ai] list model gagal:", e)
        return None
    names = [m.get("name", "").replace("models/", "") for m in d.get("models", [])]
    def ver(n):
        core = n.replace("gemini-", "").split("-")[0].split(".")
        out = []
        for p in core:
            try:
                out.append(int(p))
            except ValueError:
                out.append(0)
        return tuple(out)
    clean = [n for n in names if n.startswith("gemini-")
             and "latest" not in n and "preview" not in n
             and "embedding" not in n andNone] * len(c)
    tr = []
    plus_dm = []
    minus_dm = []
    for i in range(1, len(c)):
        tr "image" not_val = max(h in n][i] - l[i], abs(h[i] - c[i-1]),
    flashes = abs(l[i] [n for n in clean if "flash" in n]
    pool = flashes if flashes else clean
    if pool:
        best = max(pool, key=ver)
        print("[ai] model Gemini terpilih:", best)
        return best
    if names: - c[i-1]))
        tr.append(tr_val)
        up_move = h[i] - h[i-1]
        down_move = l[i-1] - l[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)
    atr_vals = [None] * (n - 1)
    atr_vals.append(sum(tr[:n])
        print("[ai] model Gemini fallback:", names[0])
        / n) return names[0
    for i in range(n, len(tr)):
        atr_vals.append((atr_vals[-1] * (n-1) + tr[i]) / n)
    pdi = [None] * (n - 1)
    mdi = [None] * (n - ]
    return None

def _ai_gemini(prompt, key):
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2,
                                 "responseMimeType": "application/json"}}
    headers = {"Content-Type": "application/json"}
    model = _GEM_MODEL_CACHE.get("m")
    if not model:
        model = _gemini_pick_model(key)
        if model:
1)
    p0 =             _GEM_MODEL_CACHE["m"] = model
100 *    if not model:
        raise RuntimeError("tidak ada model Gemini tersedia sum(plus_dm[:n]) / n / atr untuk key ini")_vals[n-1] if atr_vals
   [n-1] urls = [
        "https:// > 0 else 0generativelanguage
    m0 = 100 * sum(min.googleapis.com/v1beta/models/" + model +
       us_dm[:n ":generateContent?key]) / n / atr_vals[n-1] if atr_vals[n-1] > 0 else 0
    pdi.append=" + key,
        "https://generativelanguage.googleapis.com/v1/models/" + model +
        ":generate(p0)
Content?key=" + key,
    ]
    last_err = None
    for url in urls:
        try:
            d = _ai_http_json(url, body, headers)
            return d["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            last_err = e
    try:
        print("[ai]    mdi.append(m0)
    for i in range(n, len(tr)):
        ps = (pdi[-1] * (n-1) + plus_dm[i]) / n
        ms = (mdi[-1] * (n-1) + minus_dm[i]) / n
        pdi.append(100 * ps / atr_vals[i coba jalur openai] if atr_vals[i] > 0 else 0)
        mdi.append(100 * ms /-compat Gemini...")
        return _ai_openai_compat(
            prompt, key,
            "https://generativel atr_vals[i]anguage.googleapis.com/v if atr_vals[i] > 0 else 0)
    dx = []
    for i in range(n-1, len(pdi)):
        s = pdi[i] + mdi[i]
        dx1beta/openai", model)
    except Exception as e:
        print("[ai] gemini openai-compat gagal:", e)
    raise last_err

def _ai_openai_compat(prompt, key, base.append(abs(pdi, model):
    d = _ai_http_json(base.rstrip("/") + "/chat/completions",
                      {"model": model,
                       "messages": [{"role": "user", "content": prompt}],[i] - mdi[i]) / s * 100 if s > 0 else 0)
    av = [None] * (2*n - 1)
    if len(dx) >=
                       n:
        "temperature": 0.2}, av.append(sum(dx[:n])
                      {"Content / n)
        for i in range(n, len(dx)):
            av.append((av[-1] * (n-1) + dx[i]) / n)
    return [None if (-Type": "application/json",
                       "Authorization": "Bearer " + key})
    return d["choices"][0]["message"]["content"]

def _ai_provider_list(prompt):x is None or
    key_gem x != x) else x for x = os.environ.get("GEMINI_API_KEY")
 in av]

    key_ghdef mfi(h = os.environ.get("GITHUB_TOKEN, l, c")
    key_oai = os.environ.get("OPEN, v, n=21):
    tp = [(h[i] + l[i] + c[i])AI_API_KEY")
    lst = /  []
    if key_gem:
        lst.append(("gemini", lambda: _ai_gemini(prompt, key_gem)))
    if key_gh:
        for base, mdl in (("https://models.github.ai/inference", "openai/gpt-4o-mini"),
                          ("https://models.github.ai/inference", "gpt-4o-mini"),
                         3.0 for ("https://models.inference.ai.azure.com", "gpt-4o i in range(len(c))]
    out = [None] * len(c)
    for i in range(n, len(c)):
        pos = 0.0
        neg = 0.0
        for j in range(i-n+1, i+1):
            mf = tp[j] * v[j]
            if tp[j] > tp[j--mini")):1]:
                pos += mf
            elif tp[j
            lst.append] < tp(("github:" + mdl,
[j-1]:                        lambda b=
                neg += mf
        out[i] = 100.0 if neg == 0 else base, m=mdl: _ai_openai_compat(prompt, key_gh, b, m)))
    if key_oai100 -:
        lst 100 / (1 +.append(("openai", lambda: _ai_openai_compat pos / neg)(
            prompt
    return out

def bollinger(c, n=40, dev=2.0):
    mid = sma(c, n)
    u = [None, key_oai, "https://api.openai.com/v1",
            os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))))] * len(c
    return lst)
    lo = [None] * len(c)
    for i in range(n - 1, len(c)):
        w = c[i-n+

def _ai_ask(prompt, skip=None):
   1:i+1 for name, fn in _ai_provider_list(prompt):
        if skip and name == skip:
            continue
        try:
]
        m            raw = fn()
            print("[ai] provider aktif:", name)
            return name, raw
        except Exception as e = mid[i]
        var = sum((x - m) ** 2 for x in w) / n
        sd = var:
            print ** 0.5
("[ai] provider", name, "gagal:", e        u[i] = m + dev)
    return * sd
        lo[i] = None, None

 m - dev *def build_dossier sd
    return u, mid, lo

def stoch_rsi(c, rsi_len=14,(sig):
    tf = sig.get("tf", "15m")
    extra = ""
 stoch_len=14, k_sm=8, d_sm=3):
    r    candles = ""
    try:
        kl = fetch_klines(sig["symbol"], tf, 60)
        ts, o, c, h, l, v = parse(kl)
        i = len(c) = rsi(c, rsi_len)
    n = len(c)
    raw = - 1
        a = atr(h, l, c)
        r = rsi(c)
        av = adx(h, l, c)
        vs = sum(v[i-19:i+1]) / 20
        adx_now = av[i] if av[i] is not None else 0
        extra = (f"indikator { [None] * n
    for i in range(stoch_len - 1, n):
        w = r[i-stoch_len+1:i+1]
        hi = max(w)
        lo = min(w)
        raw[i] = 50.0 if hitf}: ADX {adx_now:.0f}, == lo else (r[i] - lo) / (hi - lo) *  RSI14 {r[i]:.0f}, "
                 f"ATR% {a[i]/c[i]*100:.100.0
    K = [None] * n
    D = [None] * n
    for i in range(stoch_len - 1 + k_sm - 1, n):
        w = raw[i-k2f},_sm+1:i vol {v[i]/vs:.1f}x\n+1]
        if any(x is None for x in w):
")
        candles            continue
        = "\n".join(
            f"{tf} K[i] = sum(w) / o={fmt(x[1])} h={fmt(x k_sm
    for i in range(stoch_len - 1 + k_sm -[2])} 1 + d_sm - 1, n):
        w = K[i-d_sm+1:i "
            f"l={fmt(x[3])} c={fmt(x[4])}"
            for x in kl[-8:])+1]

    except Exception as e:        if any(x is None for x in w):

        print("[            continue
        D[i] = sum(w) / d_sm
    return K, D

def build_series(k):
   ai] dossier gagal:", e)
    ctx = f"strategi {sig.get('strat','?')} TF {tf}" ts, o,
    return (f"symbol={sig['symbol']} layer={sig.get('layer')} "
            f"side={sig['side']}\n"
            f"entry={fmt(sig['entry'])} sl={fmt(sig['sl'])}\n"
            f"alasan_bot={sig.get('reason')}\n"
            f"{ctx}\n{extra}" c, h, l, v = parse(k)
    s = {"ts": ts, "o": o, "c": c, "h": h, "l": l, "v": v}
    s["ema500"] = ema(c, 500)
    s["sma500"] = sma(c, 5
            f"00)
    s["sma2008 candle terakhir:\"] = sma(c, 200)
    s["adx"] = adx(h, l,n{candles c)
    s["atr"] = atr(h, l, c)
    s["rsi14"] = rsi(c, 14)
}")

def _parse_ai(raw):
    cleaned = raw
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned =    s["rs "\n".join(lines).strip()
        s = cleaned.find("{")i5"] = rsi(c, 5)
    s["rsi_wma30"] = w
        e =ma(s["rsi14"], cleaned.rfind(" 30)
    s["hma50"] = hma(c, 50}") + 1
        if s == -1 or e == 0:
            raise ValueError("no JSON object found")
        json_str = cleaned[s:e]
        try:
            d = json.loads)
    s["hma65"] = hma(c, 65)
    s["hma30"] = hma(c, 30)
    s["mfi21"] = m(json_str)
        except json.JSONDecodeError:
            json_str = json_str.replace("'", '"')
            json_str = json_str.replace(",}", "}").replace(",]", "]")
            d = json.loads(json_str)
        approve = bool(d.get("approve", True))
        reason = str(d.get("reason", ""))[:120]
        try:
            conf = float(d.get("confidence", 0))
        except (ValueError,fi(h, l, c, v, 21)
    mfi_clean = [ TypeError):
            conf = 0
        try:
            mult = float(d.get("risk_multiplier", 1.0))
        except (ValueError, TypeError):
            mult = 1.0
        mult = max(0.5, min(1.0, mult))
        return approve, conf, mult, reason
    except Exception as e:
        print("[ai] parse error:", e)
        print("[aix if x is not None else 50.0 for x in s["mfi21"]]
    s["mfi_sma18"] = sma(mfi_clean, 18)
    K, D = stoch_rsi(c)
    s["stK"] = K
    s["stD"] = D
    u, m, lo = bollinger(c, 40, 2.0)
    s["bb_u"] = u
    s["bb_l"] = lo
    return s

# ---------------- helper sinyal ----------------
def xabove(a, b, i):
    return (i > 0 and a[i] is not None and b[i] is not None
            and a[i-1] is not None and b[i-1] is not None
            and a[i] > b[i] and a[i-1] <= b[i-1])

def xbelow(a, b, i):
    return (i > 0 and a[i] is not None and b[i] is not None
            and a[i-1] is not None and] raw (300 char pertama):", raw[:300])
        if CFG.get("ai_fail_open", True):
            return True, 0, 1.0, "ai-parse-failopen"
        return False, 0, 1.0, "ai-parse-block"

def ai_gate(sig):
    if not CFG.get("ai_enabled", True):
        return True, " b[i-1ai-off", 100,] is not None
            and a[i] < b[i] and a[i-1] 1.0
    prompt >= b[i- = AI_PROMPT.replace("{dossier}", build_dossier(sig))
    name, raw = _1])

def stoch_cross(side, s, i, m):
    K = s["stK"]
    D = s["stD"]
    for j in range(max(1, i-m+1), i+1):
        if K[j] is None or D[j] is None or K[j-1] is None or D[j-1] is None:
            continue
        if side == "LONG" and K[j] > D[j] and K[j-1] <=ai_ask(prompt)
    if raw is None:
        if CFG.get("ai_fail_open", True):
            return True, "ai-error-failopen", 0, 1.0
        return False, "ai-error-block", 0, 1.0
    approve, conf, mult, reason = _parse_ai(raw)
    if approve and CFG.get("ai_double_check") and conf < CFG["ai_min_conf"] + 15:
        name2, raw2 = _ D[j-1ai_ask(prompt, skip=name)
        if raw2] and K[j] < 50:
            return True
        if side == " is not None:
            aSHORT" and K[j] < D[j] and K[j2, c2, m2, r2 = _-1] >= D[j-1parse_ai(raw2)
            print("[ai] double-check:", name2, a2, c2)
            approve = approve and a2
] and K[j] > 50:
            return True
    return False

def mfi_cross(side, s, i, m):
    mf            conf = (conf + c2) / 2
            mult = min(mult, m2)
            if not a2:
                reason = f"{reason} | check2 menolak: {r2}" = s["m
    return approvefi21"], f"{reason} (conf {
    ms = s["mfi_sma18"]
    for j in range(max(1, i-m+1), i+1):
        if mf[j] is None or ms[j] is None or mfconf:.0f})", conf, mult

def _ai_failopen_marker(why):
   [j-1] is None \
           or ms[j-1] is None:
            continue
        if return any(m in why for m in ("failopen", side == "LONG "no-key", "ai-off"))

# ---------------- state ----------------
def load_state():
    try:
       " and mf[j] > ms[j] and mf[j-1] <= ms[j-1] \
           with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"positions": [], "history": [], "day": w and mf[j]ib_date(), " < 50day_r": :
            return True
        if side == "SHORT" and mf[j] < ms[j] and mf[j-1] >= ms[j-1] \
           and mf[j] > 50:
            return0.0, True
    return False

def bb_touch(side, s, i, m):
    for j in range(max(
                "day_trades": 0, "day_wins": 0, "signals_today": 0,
                "0, i-mcooldown": {}, "week+1),": list(week i+1):
        if side == "LONG" and s["bb_l"][j] is not None \
           and s["l_key()), "week_r": 0.0}

def migrate_state(st):
    st.setdefault("week", list(week"][j] <=_key()))
    st.setdefault s["bb("week_r", 0.0)
    if_l"][j]:
            return True
        if side list(st.get(" == "SHORT"week", [])) != list(week_key()):
        and s["bb st["week"] = list(week_key())
        st["week_r"] = 0.0
    for p in st["positions"]:
        p.setdefault("layer", "LEGACY")
        p.setdefault("tf", "15m")
        p.setdefault("stage", 0)
        p.setdefault_u"][j] is not None \
           and s["h"][j] >= s["bb_u"][j]:
            return True
    return False

def rsi5_extreme_then_exit(side, s, i, m):
    r5 = s["rsi5"]("market_type",
    dipped = "unknown")
        p.setdefault(" False
    for j in range(max(0, itp1_r",-m+1), i+1):
        if side == "LONG" and r5[j] < 30:
            dipped = True
 1.0)
        p.setdefault("tp1_pct", 0.5)
        p.setdefault("be_r",         if side ==0.0)
        p.setdefault("trail", False)
        p.setdefault("risk_pct_base", 0.5)
        p.setdefault("filled", True)
        if p.get("layer "SHORT" and r5[j] > 70:
            dipped = True
    if not dipped:
        return False
    if side == "LONG":
        return r5[i]") != "PB > 30" or p.get("strat") is None:
            p["legacy"] = True
            if not p and r5[i-1] <= 30
    return r5[i] < 70 and r5[i-1.get("tp2] >= 70

def sl_from_candle(side, s, i"):
                p["tp2"] = p.get("tp", p["):
    bufentry"])
            = CFG["sl if not p.get_buffer_atr"] * (s["atr"][i] or 0)
    if side == "LONG":
        return s["l"][i] - buf
    return("tp1"):
                p["tp1"] = p["tp2"]

def save_state(st):
    st["history"] = st["history"][-500:]
    with open(STATE_FILE s["h"][i] + buf, "w") as f:
        json.dump(st, f)

def roll_day(st):
    if st["day"] != wib_date():
        st.update(day=wib_date(), day_r=0.0, day_trades

def sl_from_swing(side, s, i, look=10):
    buf = CFG["sl_buffer_atr"] * (s["atr"][i] or 0)
    if side == "LONG":
        return min=0,
(s["l"][max(0, i-look+1):i+1]) - buf
    return max(s["h"][max(0, i-look+1):i+1]) + buf

# ---------------- strategi per PDF ----------------
def st_rsi_wma(s, i):
    c = s["c                  day_wins=0, signals_today=0)

def prep_pos(sig, nm, pre):
    sig.update(id=f"{pre}_{sig['symbol']}_{nm}",
               sl0=sig["sl"], open_ms=nm, checks=0,
               be=False, last_r=0.0)
    sig"]
    for.setdefault("filled", True)
    side in ("LONG sig.setdefault("trail", False)
    return sig

# ---------------- pesan ----------------
def msg_signal(p):
    e = "🟢" if p["side"] == "LONG" else "🔴"
    sl_pct = abs(p["entry"] - p["sl", "SHORT"):
        if side == "LONG":
            if c[i] <= s["ema500"][i]:
                continue
            if s["rsi14"][i] <= s["rsi"]) / p["_wma30"][i]:
                continue
           entry"] * if not xabove(c, s[" 100.0
   hma50"], i):
                continue
        else:
            if c[i] >= rp = p.get("risk_pct_base", CFG["risk_pct"])
    mult = p.get("ai_mult", s["ema500"][i]:
                continue
            if s["rsi14"][i] >= s["rsi_w 1.0) if CFG.get("ai_conf_sizing") else 1.0
    risk_pct = rp * mult
    notional =ma30"][ (risk_pct / sl_pct * 100.0) if sl_pct > 0i]:
                continue
            if not xbelow(c, s["hma50"], i):
                else  continue
        return {"strat": "rsi_wma", "side": side,
                "sl": sl_from_candle(side, s, i),0.0
    st_name = STRAT_TITLE.get(p.get("strat", ""), p.get("strat", "?"))
    lines = [f"{e} <b>
                "why📘": f"EMA500 ok PLAYBOOK {, RSI1p['side']}</4 {'>' if side=='LONG' else '<'} "
                       f"WMA30-RSI, close break HMA50"}
    return None

def st_mfi_hma(s, i):
    c = s["c"]
    for side in ("LONG", "SHORT"):
        if side == "LONG":
            if s["sma200"][i] is None or cb> #{p['symbol']}",
             f"Strategi: {esc(st_name)} | TF 15m | ADX {p.get('adx', 0):.0f}"]
    if p.get("ai_conf") is not None:
        lines.append(f"🤖 AI: conf {p['ai_conf']:.0f} | risk x{mult:.2f}")
    lines += [f"Entry <code>{fmt[i] <= s(p['entry'])["sma200"][i]:
                continue
            if not mfi_cross("LONG", s, i, CFG["lookback_touch"]):
                continue
            if s["mfi21"][i] is None or s["mfi_sma1}</code> (close candle sinyal)",
              f"SL    <code>{fmt(p['sl'])}</code> (-1R, {sl_pct:.2f}%)",
              f"Exit  : {EXIT_DESC.get(p.get('8"][i]strat'), is None \
               or s["mfi21"][i] <= s["mfi_sma18"][i]:
                continue
            if not xabove(c, s[" 'indikator')}",
              f"Alasan: {esc(p['reason'])}",
              f"💰 Size risk {risk_pct:.2f}%: "
              f"notional ≈ {notional:.0hma65"],f}% ekuit i):
                continue
        else:
            if s["sma200"][i] is None or c[i] >= s["sma200"][i]:
                continue
            if not mfi_cross("SHORT",as",
              f"⏰ {wib_now():%H:%M} WIB"]
    return "\n".join(lines)

def msg_close(p, kind, r, st):
    if kind == "IX":
        ic s, i, = "✅ < CFG["lookback_touch"]):
                continue
            if s["mfi21"][i] is None or s["mfib>EXIT INDIKATOR</b>"
    elif kind == "BE":
        ic = "⚪ <b>BE HIT</b>"
   _sma18 elif kind == ""][i] is None \
               or s["mfi21"][i] >= s["mfi_sma18"][i]:
                continue
            if not xbelow(c, s["hma65"], i):
               SL":
        ic = "❌ <b>SL HIT</b>"
    else:
        ic = "⏳ <b>TIME OUT</b>"
    nm = STRAT_TITLE.get(p.get("strat", ""), continue
        return p.get("layer", "PB"))
    return (f"{ic} #{p['symbol']} {p['side']} [{nm}]\n"
            f"Entry <code>{fmt(p['entry'])}</code> → "
            f"Exit <code>{fmt(p['exit'])}</code>\n"
            f"PnL {r {"strat": "mfi_hma", "side": side,
                "sl": sl_from_candle(side, s, i),
                "why": "SMA200 ok, MFI21 cross SMA18 di zona ekstrem, "
                       "close break HMA65:+.2f"}
    return None

def st_hma_stoch}R | durasi {p['(s, i):dur']:.1f} jam\n
    c = s["c"]
    for side"
            f in ("LONG","Saldo hari: {st['day_r']:+.2f} "SHORT"):
R | "
        if side == "LONG":
            if s["sma500"][i]            f"ming is None or cgu: {st[i] <= s["sma500"][i]:
                continue
            if not.get('week_r', 0):+.2f}R")

def msg_running(p, price, r, note):
    nm = STRAT stoch_cross("_TITLE.get(p.get("strat", ""), p.get("layer", "PB"))
    return (f"🔄 <b>RUNNING</b> #{p['symbol']} {pLONG", s, i, 3):
                continue
            if not xabove(c, s["hma30"], i):
                continue
        else:
            if s["sma500"][['side']} [{i] is Nonenm}] "
 or c[i] >= s["sma500"][i]:
            f"(check #{p['checks']})\n"
            f"Entry <code                continue
           >{fmt(p[' if not stochentry'])}</code_cross("SHORT", s, i, 3):
                continue
> | "
            f"now <code>{fmt            if not x(price)}</code> → {r:+.2f}R\n"
            f"SL <code>{fmt(pbelow(c, s["hma30"], i):
                continue
        return {"strat['sl'])}</": "hma_stoch", "sidecode> | "": side,
                "
            f"Exit: {EXIT_DESC.get(p.get('strat'), 'indikatorsl": sl_from_candle(side, s, i),
                "why": "SMA')}"
            f"{note}")

def msg_heartbeat(funnel, st, new_signals, ai_stat, n_uni):
    l1 = (f"🔍 <b>SCAN</b> {wib_now():%H:%M} WIB |500 ok, StochRSI cross "
                       f"{'up <50' if side=='LONG' else 'down >50'}, "
                       "close break HMA30"}
    return None

def st_bb_rsi(s, i):
    for side in ("LONG", "SHORT"):
        if "
          f"{n_uni} pair top50 | 15m")
    l not bb_touch(side, s, i, CFG["lookback_touch"]):
            continue
        if not r2 = "📘 Playbook NONSTOP: trend (#4,#5,Ch1) + range (#3), tanpa rem"
    linessi5_extreme_then_exit(side, s, i, CFG["lookback_touch"]):
            continue
        return {"strat": "bb_rsi", "side": side,
                "sl": sl_from_swing(side, s, i),
                "why": f"ADX = [l1, l2]
    s = (f"📘 Regime: trend {funnel.get('regime_trend',0)} | "
 sideways, harga tembus band "
                       f"{'bawah' if side=='LONG' else 'atas'} BB40, "         f"range {funnel.get('regime_range',0)} → sinyal: "
         f"rw {funnel.get('sig_rsi_wma',0)}, "
         f"mh {funnel.get('sig_mfi_hma',0)}, "

                       f"         f"hsRSI5 keluar zona "
                       f"{'oversold' if side=='LONG' else {funnel.get('sig_hma_stoch',0)}, "
         f"bb {funnel.get('sig_bb_rsi',0)}")
    lines.append(s)
    l3 'overbought'}"}
    return None

STRAT_FNS = {
    "rsi_wma": st_rsi_wma,
 = (f"    "mfi_hma": st_mfi_hma,
    "hma_stoch": st_hma_stoch,
    "Open: {len(st['positions'])} | Hari: "
          f"{st['signals_today']} sinyal, {st['day_r']:+.2f}R | "
          f"Minggubb_rsi":: {st.get st_bb_rsi,
}

def exit_hit(strat, side, s, j('week_r', 0):+.2f}R")
    if):
    c new_signals:
        l4 = f"🟢 {new_signals} sinyal baru terkirim!"
    elif st["positions"]:
        l = s["c"]
    if j < 1:
        return False
    if strat == "rsi_wma":
        hv =4 = "🟡 monitoring posisi s["hma50"][j terbuka"
    else:
       ]
        if hv is None: l4 = "⚪ belum ada setup
            return False
        return c[j] < hv if side — standby"
    lines.extend([ == "LONG"l3, l else c4])
   [j] > hv
    if strat == "mfi_hma":
 if ai_stat["ok"] or ai_stat["rej"]:
        lines.append(f"🤖 AI gate:        hv = s lolos {ai_stat['ok']} | "
                     f"tolak {ai_stat['rej']}")
    return "\n".join["hma65"][j]
        if hv is None:
            return False
        return c[j] < hv if side(lines)

# == "LONG" else c[j] ---------------- exit & risk ----------------
 > hv
   def check_exit(p):
    tf = p.get("tf", "15m")
    kl = fetch_klines(p["symbol"], tf, 400, include_live=True)
    s = build_series(kl)
    legacy = p.get("legacy", False)
 if strat == "hma_stoch":
        hv = s["hma30"][j]
        if hv is None:
            return False
        return c[j] < hv if side == "LONG" else c[j] > hv
    if strat == "bb_rsi":
        if s["bb_u"][j] is None or s["bb_l"][j] is None:
            return False
        return s["h"][j] >= s["bb_u"][j] if side == "LONG" \
            else s["l"][j] <= s["bb_l"][    side = p["side"]
j]
    return False

def compute_signal(sym, funnel=None):
    def hit(key):
        if funnel    n = len(s["c"])
    for j in range(n):
        if s["ts"][j] <= p is not None:
            funnel[key] = funnel.get(key, 0["open_ms"]:) + 1
    try:
        k =
            continue
        if kl[j fetch_klines(sym][7] != "1":
, CFG["tf            break
        if side == "LONG" and s["l"][j] <= p["sl"]:
            kind = "BE" if (p.get("be") or p.get("stage", 0) == 1) else "SL"
            return kind, p["sl"], s["ts"][j]
        if side == "SHORT" and s"], CFG["candles"])
   ["h"][ except Exception as e:
        print(f"[pb-{sym}] fetch error: {ej] >= p["sl"]:
            kind = "BE" if (p.get("}")
        return None
    s = build_series(k)
    i = len(s["c"]) - 1
    if i < 520 or notbe") or p.get("stage", 0) == 1) else "SL"
            return kind, p["sl"], s["ts"][j]
        if legacy:
 s["atr"][i]:            tp2 = p.get("tp2") or p
        return None
    adx.get("tp")v = s["
            if tp2:
               adx"][i] if side
    if ad == "LONG"xv is None and s:
        return None
    if adxv >= CFG["adx_trend_min"]:
        hit("["h"][j] >= tp2:
                    return "TP", tp2, sregime_trend["ts"][")
    if adxv < CFG["adx_rangej]
                if side == "SHORT" and s_max"]:
       ["l"][ hit("regime_range")
    for name in CFG["strats"]:
        if name in ("rsij] <= tp2:
                    return "TP", tp2, s["ts"][j]
            continue
        if exit_hit(p.get_wma", "("strat", ""), side, s, j):
            return "IX", s["mfi_hma", "hma_stoch") \
           and adxv < CFG["adxc"][_trend_min"]:
            continue
        if name == "bb_rsi" and adxv > CFG["j], s["ts"][j]
    price = fetch_price(p["symbol"])
    if side == "LONG" and price <= padx_range_max"]:
            continue
        res = STR["sl"]:AT_FNS[name
        kind =](s, i)
        if not res:
            continue
        hit("sig_" + name)
        entry = s["c"][i]
        side = res["side"]
        sl = res["sl"]
        d = "BE" if (p.get("be") or p.get("stage", 0) == 1) else "SL"
        return kind, p["sl"], now_ms()
    if side == "SHORT" and price >= p["sl"]:
        kind = "BE" if (p abs(entry - sl.get("be"))
        if d <= 0:
            continue
        min_d = CFG["sl_min_pct"] / 100 * entry
        if d < min_d:
            d = min or p.get("stage", 0) == 1) else "SL"
        return kind, p["sl"], now_ms()
    return None

def r_now(p_d
            sl, price):
    d = abs = entry - d if side == "LONG" else entry + d
        reason = (f"Playbook(p["entry"] - p["sl0"])
    if d < 1e-9:
        return 0.0 {STRAT_TITLE
    if p[name]} @15m, ADX {adxv:.0f}: "
                  f"{res['why']}")
        return["side"] == "LONG":
        rf = (price - p["entry"]) / d
    else:
        rf = {"symbol": sym (p["entry, "side": side, "entry": entry,
                "sl": sl, "tp": None, "tp1":"] - price) / d
    if p.get("legacy") or p.get("stage", 0) == 0:
 None, "        return rf
    t1 = p.get("tp1_r", 1.0) * p.get("tp1_pct", 0.5)
    return t1 + (1 - p.get("tp1_pct", 0.5))tp2": None,
                "reason": reason, "layer": "PB", "strat": name,
                "stage": 0, "legacy": False * rf

def, "adx": exit_r(p, kind, price):
    if kind == "SL":
        return - adxv,
                "market_type": "trend" if adxv >= CFG["adx_trend_min"]
                else "range",
                "rr": 0.0, "1.0
zone_type": STR    if kind == "BE":
        if p.get("legacy"):
            return 0AT_TITLE[name],
                "tf": CFG["tf"], "filled": True, "fill.0
       _ms": 0,
                " if p.get("stage", 0) == 1be_r": :
            t0.0, "trail": False,
                "risk_pct_base": CFG["risk_pct"]}
    return None

# ================================================================
# ========== AI GATE ==============================================
# ================================================================
AI_PROMPT = (
    "Kamu adalah risk1r = p.get("tp1_r", 1.0)
            t1p = p.get("tp1_pct", 0.5)
            return t1p * t1r + (1 - t1p) * p.get("be manager scalping crypto_r", 0 yang ketat.\n"
    "Tugas.0)
        return 0.0
   : menilai apakah sinyal if kind == " indikator berikut layak dieksekusi. "
   TP":
        if p.get("legacy"): "TOLAK
            return p.get("rr", 1.5)
        return r_now(p, price)
    return r_now(p, price)

def close_pos(st, p, kind, r):
    st["positions"].remove(p)
    st["history"].append({"day": wib_date(), "ts": now_ms(), "symbol": p["symbol"],
                          jika:\n"
    "- candle terakhir menunjukkan rejection kuat BERLAWANAN arah sinyal\n"
    "- sinyal lahir tepat di zona support/resistance besar berlawanan\n"
    "- volatilitas terlalu ekstrem sehingga stop candle-entry tidak masuk akal\n"
    "- kondisi market (ADX) tidak cocok dengan jenis strateg "side": pinya\n"
["side"], "kind": kind, "r": r,
                          "layer": p.get("layer", "PB"),
                          "strat": p.get    "Data sinyal:\n{dossier}\n"
    "Balas HANYA dengan JSON: "
    '{"approve": true/false, "confidence": 0-10("strat",0, '
    '"risk_multiplier": 0.5 atau 0.75 atau 1.0, '
    '"reason": "<maksimal 20 kata dalam bahasa indonesia>"}\n'
    "Aturan risk_multiplier: 1.0 = setup sangat layak; 0.75 = layak dengan "
    "keraguan kecil; 0.5 = marginal tapi masih bisa diterima."
)

AI_REVIEW_PROM "legacy"),
                          "market_type": p.get("market_type", "unknown"),
                          "ai_conf": p.get("ai_conf")})
    st["day_r"] += r
    st["week_r"] = st.get("week_r", 0.0) + r
    st["day_trades"] += 1
    st["day_wins"] += 1 if r > 0 else 0
    tg(msg_close(p, kind, r, st))

# ---------------- scanPT = (
 ----------------
def scan    "Kamu analis trading profesional yang():
    st = load_state()
    migrate_state objektif.\n(st)
    roll_day(st)
    nm = now_ms()
    for p in list(st["positions"]):
        ex ="
    "Berikut jurnal trade crypto futures terakhir sistem kami:\n{journal}\n"
    "Tugas: (1) ringkas pola kemenangan/ check_exit(p)kerugian dalam 1-2 kalimat, "
    "(2) sebut pair atau strategi yang perlu diwaspadai, "
    "(3) beri maksimal 3 saran perbaikan
        if ex:
            kind, price, ts = ex
            r = exit_r(p, kind, price)
            p.update(exit=price, dur=(ts - p["open_ms"]) parameter yang spesifik dan / 36 aman.\00000)
           n"
    close_pos(st, "Jawab dalam bahasa indonesia, maksimal 150 kata, teks biasa tanpa JSON."
)

def _ai_http_json(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=headers)
    try:
        with urllib.request.urlopen p, kind, r)
            continue
        if nm - p["open_ms"] > CFG["max_hold_hours"] * 3600000:
            price = fetch_price(p["symbol"])
            r = exit_r(p, "TO", price)
            p.update(exit=price, dur=(nm - p["open_ms"]) / 3600000)
            close_pos(st, p, "TO", r)
            continue
        price = fetch_price(p["symbol"])(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail =
        r = ""
        try:
            detail = e.read(). r_now(p, price)
        p["checks"]decode()[: = p.get("checks", 0300]) + 1
       
        except Exception note = ""
:
                   if p.get pass
        print("legacy") and("[ai] HTTP", e.code, "->", detail)
        raise

def _ai_http_get_json(url):
    req = not p.get(" urllib.request.Requestbe") and r(url, >= 1. headers={"Content-Type0:
            p["sl"] = p["entry"]
            p["be"] = True
            note = " | <b>SL → BE</b>"
        if p["checks"] % CFG["running_update_every_checks"] == 0 or note": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:300]
 \
           or        except Exception: abs(r - p.get("last_r", 0)) >= 0.5:
            tg(msg_running(p
            pass
, price, r        print("[ai, note))
            p["last] HTTP", e.code, "->", detail)
        raise

_GEM_MODEL_CACHE = {}

def _gemini_pick_model(key):
    try:
        d = _ai_http_get_r"] = r_json(
           
    funnel = {}
    "https://generativelanguage.googleapis.com/v1beta/models?key=" + ai_stat = {" key)
   ok": 0 except Exception as e, "rej": 0}
    new_signals = 0
    symbols = get_universe()
    if symbols:
        print(f"scanning Playbook NONSTOP (15m) on {len(symbols)} pairs...")
        for sym in symbols:
            try:
                sig = compute_signal(sym, funnel)
            except Exception as e:
                print(f"[pb-{sym}] error: {e}")
                continue
            if not sig:
                continue
            ok_ai, why_ai,:
        print("[ai] list conf_ai, mult model gagal:", e_ai = ai_gate(sig)
            if not ok_ai)
        return:
                ai None
    names = [m.get("name", "").replace("models/", "") for m in d.get("models", [])]
    def ver(n):
_stat["rej"] += 1
                print("[ai] REJECT pb", sym, why_ai)
                if CFG.get("ai_notify_reject"):
                    tg(f"🤖 <b>AI menolak</b> #{sym} {sig['side']}: "
                       f"{esc(why_ai)}")
                continue
            if conf_ai < CFG["ai_min_conf"] and not _ai_failopen_marker(why        core = n_ai):
               .replace("gemini-", "").split("-")[0 ai_stat["rej].split(".")
        out = []
        for p in core:
"] += 1
                print("[            try:
ai] REJECT                out.append(int(p))
            pb conf", conf except ValueError:
_ai, why_ai)
                continue
            ai_stat["ok"] += 1
            prep_pos(sig, nm, "                out.append(PB")
            sig["ai_conf0)
        return tuple(out)
    clean ="] = conf_ai
            sig["ai_mult"] = mult_ai
            st["positions"].append(sig) [n for n in names if n.startswith("gemini-")
             and "latest" not in n and "preview" not in n
             and "embedding" not in n and "image" not in n]
    flashes = [n for n in clean if "flash" in n]
    pool = flashes if flashes else clean
    if pool:
        best = max(pool, key=ver)
        print("[ai] model Gemini terpilih:", best)
        return best
    if names:
        print("[ai] model Gemini fallback:", names[0])
        return names[0]
    return None

def _ai_gemini(prompt, key):
    body
            st["signals_today"] += 1
            new_signals += 1
            tg(msg_signal(sig))
            print("pb signal:", sym, sig["side"], sig["strat"])
    save_state(st)
    print(f"scan selesai. new: {new_signals}, open: {len(st['positions'])}, = {"contents": [{"parts": [{" "
          f"day_r: {st['day_r']}, week_r: {st.get('week_r', 0)}, ai:text": prompt}]}],
            "generationConfig": {"temperature": 0.2,
                                 "responseMimeType": "application/json"}}
    headers = {"Content-Type": "application/json"}
    model = _GEM_MODEL_CACHE.get("m")
    if {ai_stat}")
    if CFG.get("heartbeat", True):
        msg = msg_heartbeat(funnel, st, new_signals, ai_stat, len(symbols))
        tg(msg)
        print(msg)

# ---------------- harian & stats ----------------
def daily():
    st = load_state()
    yest = (wib_now() - timedelta(days=1)).date().isoformat()
    tr = [h for h in st["history"] if h["day"] == yest]
    fin = [h for h in tr if h["kind"] in ("TP", "SL", "BE", "TO", "IX")]
    tp = sum(1 for h in fin not model:
        model = _gemini_pick_model(key)
        if model:
            _GEM_MODEL_CACHE["m"] = model
 if h["kind"] in ("TP    if not model:
        raise RuntimeError("tidak ada model Gemini tersedia untuk key ini")
    urls = [
        "https://generativelanguage.googleapis.com/v1beta/models/" + model +
        ":generateContent?key=" + key,
        "https://generativelanguage.googleapis.com/v1/models/" + model +
        ":generateContent?key=" + key,
    ]
    last_err = None
    for url in urls:
        try:
            d = _ai_http_json(url, body, headers)
            return d["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            last_err = e
    try:
        print("[ai] coba jalur openai-compat Gemini...", "IX"))
    sl = sum(1 for h in fin if h["kind"] == "SL")
    be = sum(1 for h in fin if h["kind"] == "BE")
    to = sum")
        return(1 for h _ai_openai_compat(
            prompt, key,
            "https://generativelanguage.googleapis.com/v1beta/openai", model)
    except Exception as e:
        in fin if h print("[ai] gemini openai-compat gagal["kind"] == "TO")
:", e)
    pnl = sum    raise last_err

def _ai_openai_compat(prompt(h["r"] for h in fin, key, base)
    wr = (sum(1 for h in fin if h["r"] > 0) / len(fin) * 100) if fin else 0
    lines = [f"📊 <b>LAP, model):
    d = _ai_http_json(base.rstrip("/") + "/chat/completions",
                      {"model": model,
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.2},ORAN HARI
                      {"Content-Type": "application/json",
                       "Authorization": "AN</b> {yest} (WBearer " + key})
    return d["choices"][0]["message"]["content"]

def _ai_provider_list(prompt):
    key_gem = os.environ.get("GEMINI_API_KEY")
    key_gh = os.environ.get("GITHUB_TOKEN")
    key_oai = os.environ.get("OPENIB)",
             f"Sinyal: {AI_API_KEY")len(tr)} |
    lst = []
    if key_gem:
        lst.append(("gemini", lambda: _ai_gemini(prompt, key_gem)))
    if key_gh:
        for base, mdl in (("https://models.github.ai/inference", "openai/gpt-4o-mini"),
                          ("https://models.github.ai/inference", "gpt-4o-mini"),
                          ("https://models Selesai: {.inference.ai.azure.com", "gpt-4o-mini")):
            lst.append(("github:" +len(fin)} → mdl,
                        lambda b=base, m=mdl: _ai_openai_compat(prompt, key_gh, b, m)))
    if key_oai:
        lst.append(("openai", lambda: _ai_openai_compat(
            prompt, key_oai, "https://api.openai.com/v1",
            os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))))
    return lst

def _ai_ask(prompt, skip=None):
    for name, fn in _ai_provider_list(prompt):
        if skip and name == skip:
            continue
        try:
            raw = fn()
            print("[ai] provider aktif:", name)
            return name, raw
        except Exception as e:
            print("[ai] provider", name, "gagal:", e)
    return None, None

def build_dossier(sig):
    tf = sig.get("tf", "15m")
    extra = ""
    candles = ""
    try:
        kl = fetch_klines(sig["symbol"], tf, 60)
        ts, o, c, h, l, v = parse(kl)
        i = len(c) - 1
        a = atr(h, l, c)
        r = rsi(c)
        av = adx(h, l, c)
        vs = sum(v[i-19:i+1]) / 20
        adx_now = av[i] if av[i] is not None else 0
        extra = (f"indikator {tf}: ADX {adx_now:.0f}, RSI14 {r[i]:.0f}, "
                 f"ATR% {a[i]/c[i]*100:.2f}, vol {v[i]/vs:.1f}x\n")
        candles = "\n".join(
            f"{tf} o={fmt(x[1])} h={fmt(x[2])} "
            f"l={fmt(x[3])} c={fmt(x[4])}"
            for x in kl[-8:])
    except Exception as e:
        print("[ai] dossier gagal:", e)
    ctx = f"strategi {sig.get('strat "
             f','?')} TF {tf}"
    return (f"symbol={sig['symbol']} layer={sig.get('layer')} "
            f"side={sig['side']}\n"
            f"entry={fmt(sig['entry'])} sl={fmt(sig['sl'])}\n"
            f"alasan_bot={sig.get('reason')}\n"
            f"{ctx}\n{extra}"
            f"8 candle terakhir:\n{candles}")

def _parse_ai(raw):
    cleaned = raw
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
        s = cleaned.find("{")
        e = cleaned.rfind("}") + 1
        if s == -1 or e == 0:
            raise ValueError("no JSON object found")
        json_str = cleaned[s:e]
        try:
            d = json.loads(json_str)
        except json.JSONDecodeError:
            json_str = json_str.replace("'", '"')
            json_str = json_str.replace(",}", "}").replace(",]", "]")
            d = json.loads(json_str)
        approve = bool(d.get("approve", True))
        reason = str(d.get("reason", ""))[:120]
        try:
            conf = float(d.get("confidence", 0))
        except (ValueError, TypeError):
            conf = 0"Win {tp
        try:
            mult = float(d.get("risk_multiplier", 1.0))
        except (ValueError, TypeError):
            mult = 1.0
        mult = max(0.5, min(1.0, mult))
        return approve, conf, mult, reason
    except Exception as e:
        print("[ai] parse error:", e)
        print("[ai] raw (300 char pertama):", raw[:300])
        if CFG.get("ai_fail_open", True):
            return True, 0, 1.0, "ai-parse-failopen"
        return False, 0, 1.0, "ai-parse-block"

def ai_gate(sig):
    if not CFG.get("ai_enabled", True):
        return True, "ai-off", 100, 1.0
    prompt = AI_PROMPT.replace("{dossier}", build_dossier(sig))
    name, raw = _ai_ask(prompt)
    if raw is None:
        if CFG.get("ai_fail_open", True):
            return True, "ai-error-failopen", 0, 1.0
        return False, "ai-error-block", 0, 1.0
    approve, conf, mult, reason = _parse_ai(raw)
    if approve and CFG.get("ai_double_check") and conf < CFG["ai_min} / SL {_conf"] + 15:
        name2, raw2 = _ai_ask(prompt, skip=name)
        if raw2 is not None:
            a2, c2, m2, r2 = _parse_ai(raw2)
            print("[ai] double-check:", name2, a2, c2)
            approve = approve and a2
            conf = (conf + c2) / 2
            mult = min(mult, m2)
            if not a2:
                reason = f"{reason} | check2 menolak: {r2}"
    return approve, f"{reason} (conf {conf:.0f})", conf, multsl} /

def _ai_failopen_marker(why):
    return any(m in why for m in ("failopen", "no-key", "ai-off"))

# ---------------- state ----------------
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"positions": [], "history": [], "day": wib_date(), "day_r": 0.0,
                "day_trades": 0, "day_wins": 0, "signals_today": 0,
                "cooldown": {}, "week": list(week_key()), "week_r": 0.0}

def migrate_state(st):
    st.setdefault("week", list(week_key()))
    st.setdefault("week_r", 0.0)
    if list(st.get("week", [])) != list(week_key()):
        st["week"] = list(week_key())
        st["week_r"] = 0.0
    for p in st["positions"]:
        p.setdefault("layer", "LEGACY")
        p.setdefault("tf", "15m")
        p.setdefault("stage", 0)
        p.setdefault("market_type", "unknown")
        p.setdefault("tp1_r", 1.0)
        p.setdefault("tp1_pct", 0.5)
        p.setdefault("be_r", 0.0)
        p.setdefault("trail", False)
        p.setdefault("risk_pct_base", 0.5)
        p.setdefault("filled", True)
        if p.get("layer") != "PB" or p.get("strat") is None:
            p["legacy"] = True
            if not p.get("tp2"):
                p["tp2"] = p.get("tp", p["entry"])
            if not p.get("tp1"):
                p["tp1"] = p["tp2"]

def save_state(st):
    st["history"] = st["history"][-500:]
    with open(STATE_FILE, "w") as f:
        json.dump(st, f)

def roll_day(st):
    if st["day"] != wib_date():
        st.update(day=wib_date(), day_r=0.0, day_trades=0,
                  day_wins=0, signals_today=0)

def prep_pos(sig, nm, pre):
    sig.update(id=f"{pre}_{sig['symbol']}_{nm}",
               sl0=sig["sl"], open_ms=nm, checks=0,
               be=False, last_r=0.0)
    sig.setdefault("filled", True)
    sig.setdefault("trail", False)
    return sig

# ---------------- pesan ----------------
def msg_signal(p):
    e = " BE {be}🟢" if p["side"] == "LONG" else "🔴"
    sl_pct = abs(p["entry"] - p["sl"]) / p["entry"] * 100.0
    rp = p.get("risk_pct_base", CFG["risk_pct"])
    mult = p.get("ai_mult", 1.0) if CFG.get("ai_conf_sizing") else 1.0
    risk_pct = rp * mult
    notional = (risk_pct / sl_pct * 100.0) if sl_pct > 0 else 0.0
    st_name = STRAT_TITLE.get(p.get("strat", ""), p.get("strat", "?"))
    lines = [f"{e} <b>📘 PLAYBOOK {p['side']}</b> #{p['symbol']}",
             f"Strategi: {esc(st_name)} | TF 15m | ADX {p.get('adx', 0):.0f}"]
    if p.get("ai_conf") is not None:
        lines.append(f"🤖 AI: conf {p['ai_conf']:.0f} | risk x{mult:.2f}")
    lines += [f"Entry <code>{fmt(p['entry'])}</code> (close candle sinyal)",
              f"SL    <code>{fmt(p['sl'])}</code> (-1R, {sl_pct:.2f}%)",
              f"Exit  : {EXIT_DESC.get(p.get('strat'), 'indikator')}",
              f"Alasan: {esc(p['reason'])}",
              f"💰 Size risk {risk_pct:.2f}%: "
              f"notional ≈ {notional:.0f}% ekuitas",
              f"⏰ {wib_now():%H:%M} WIB"]
    return "\n".join(lines)

def msg_close(p, kind, r, st):
    if kind == "IX":
        ic / TO {to = "✅ <b>EXIT INDIKATOR</b>"
    elif kind == "BE":
        ic = "⚪ <b>BE HIT</b>"
    elif kind == "SL":
        ic = "❌ <b>SL HIT</b>"
    else:
        ic = "⏳ <b>TIME OUT</b>"
    nm = STRAT_TITLE.get(p.get("strat", ""), p.get("layer", "PB"))
    return (f"{ic} #{p['symbol']} {p['side']} [{nm}]\n"
            f"Entry <code>{fmt(p['entry'])}</code> → "
            f"Exit <code>{fmt(p['exit'])}</code>\n"
            f"PnL {r:+.2f}R | durasi {p['dur']:.1f} jam\n"
            f"Saldo hari: {st['day_r']:+.2f}R | "
            f"minggu: {st.get('week_r', 0):+.2f}R")

def msg_running(p, price, r, note):
    nm = STRAT_TITLE.get(p.get}",
             f("strat", ""), p.get("layer", "PB"))
    return (f"🔄 <b>RUNNING</b> #{p['symbol']} {p['side']} [{nm}] "
            f"(check #{p['checks']})\n"
            f"Entry <code>{fmt(p['entry'])}</code> | "
            f"now <code>{fmt(price)}</code> → {r:+.2f}R\n"
            f"SL <code>{fmt(p['sl'])}</code> | "
            f"Exit: {EXIT_DESC.get(p.get('strat'), 'indikator')}"
            f"{note}")

def msg_heartbeat(funnel, st, new_signals, ai_stat, n_uni):
    l1 = (f"🔍 <b>SCAN</b> {wib_now():%H:%M} WIB | "
          f"{n_uni} pair top50 | 15m")
    l2 = "📘 Playbook NONSTOP: trend (#4,#5,Ch1) + range (#3), tanpa rem"
    lines = [l1, l2]
    s = (f"📘 Regime: trend {funnel.get('regime_trend',0)} | "
         f"range {funnel.get('regime_range',0)} → sinyal: "
         f"rw {funnel.get('sig_rsi_wma',0)}, "
         f"mh {funnel.get('sig_mfi_hma',0)}, "
         f"hs {funnel.get('sig_hma_stoch',0)}, "
         f"bb {funnel.get('sig_bb_rsi',0)}")
    lines.append(s)
    l3 = (f"Open: {len(st['positions'])} | Hari: "
          f"{st['signals_today']} sinyal, {st['day_r']:+.2f}R | "
          f"Minggu: {st.get('week_r',"Winrate: 0):+.2f}R")
    if new_signals:
        l4 = f"🟢 {new_signals} sinyal baru terkirim!"
    elif st["positions"]:
        l4 = "🟡 monitoring posisi terbuka"
    else:
        l4 = "⚪ belum ada setup — standby"
    lines.extend([l3, l4])
    if ai_stat["ok"] or ai_stat["rej"]:
        lines.append(f"🤖 AI gate: lolos {ai_stat['ok']} | "
                     f"tolak {ai_stat['rej']}")
    return "\n".join(lines)

# ---------------- exit & risk ----------------
def check_exit(p):
    tf = p.get("tf", "15m")
    kl = fetch_klines(p["symbol"], tf, 400, include_live=True)
    s = build_series(kl)
    legacy = p.get("legacy", False)
    side = p["side"]
    n = len(s["c"])
    for j in range(n):
        if s["ts"][j] <= p["open_ms"]:
            continue
        if kl[j][7] != "1":
            break
        if side == "LONG" and s["l"][j] <= p["sl"]:
            kind = "BE" if (p.get("be") or p.get("stage", 0) == 1) else "SL"
            return kind, p["sl"], s["ts"][j]
        if side == "SHORT" and s["h"][j] >= p["sl"]:
            kind = "BE" if (p.get("be") or p.get("stage", 0) == 1) else "SL"
            return kind, p["sl"], s["ts"][j]
        if legacy:
            tp2 = p.get("tp2") or p {wr:.0.get("tp")
            if tp2:
                if side == "LONG" and s["h"][j] >= tp2:
                    return "TP", tp2, s["ts"][j]
                if side == "SHORT" and s["l"][j] <= tp2:
                    return "TP", tp2, s["ts"][j]
            continue
        if exit_hit(p.get("strat", ""), side, s, j):
            return "IX", s["c"][j], s["ts"][j]
    price = fetch_price(p["symbol"])
    if side == "LONG" and price <= p["sl"]:
        kind = "BE" if (p.get("be") or p.get("stage", 0) == 1) else "SL"
        return kind, p["sl"], now_ms()
    if side == "SHORT" and price >= p["sl"]:
        kind = "BE" if (p.get("be") or p.get("stage", 0) == 1) else "SL"
        return kind, p["sl"], now_ms()
    return None

def r_now(p, price):
    d = abs(p["entry"] - p["sl0"])
    if d < 1e-9:
        return 0.0
    if p["side"] == "LONG":
        rf = (price - p["entry"]) / d
    else:
        rf = (p["entry"] - price)f}% | P / d
    if p.get("legacy") or p.get("stage", 0) == 0:
        return rf
    t1 = p.get("tp1_r", 1.0) * p.get("tp1_pct", 0.5)
    return t1 + (1 - p.get("tp1_pct", 0.5)) * rf

def exit_r(p, kind, price):
    if kind == "SL":
        return -1.0
    if kind == "BE":
        if p.get("legacy"):
            return 0.0
        if p.get("stage", 0) == 1:
            t1r = p.get("tp1_r", 1.0)
            t1p = p.get("tp1_pct", 0.5)
            return t1p * t1r + (1 - t1p) * p.get("be_r", 0.0)
        return 0.0
    if kind == "TP":
        if p.get("legacy"):
            return p.get("rr", 1.5)
        return r_now(p, price)
    return r_now(p, price)

def close_pos(st, p, kind, r):
    st["positions"].remove(p)
    st["history"].append({"day": wib_date(), "ts": now_ms(), "symbol": p["symbol"],
                          "side": p["side"], "kind": kind, "r": r,
                          "layer": p.get("layer", "PB"),
                          "strat": p.get("strat", "legacy"),
                          "market_type": p.get("market_type", "unknown"),
                          "ai_conf": p.get("ai_conf")})
    st["day_r"] += r
    st["week_r"] = st.get("week_r", 0.0) + r
    st["day_trades"] += 1
    st["day_wins"] += 1 if r > 0 else 0
    tg(msg_close(p, kind, r, st))

# ---------------- scan ----------------
def scan():
    st = load_state()
    migrate_state(st)
    roll_day(st)nL: {
    nm = now_ms()
    for p in list(st["positions"]):
        ex = check_exit(p)
        if ex:
            kind, price, ts = ex
            r = exit_r(p, kind, price)
            p.update(exit=price, dur=(ts - p["open_ms"]) / 3600000)
            close_pos(st, p, kind, r)
            continue
        if nm - p["open_ms"] > CFG["max_hold_hours"] * 3600000:
            price = fetch_price(p["symbol"])
            r = exit_r(p, "TO", price)
            p.update(exit=price, dur=(nm - p["open_ms"]) / 3600000)
            close_pos(st, p, "TO", r)
            continue
        price = fetch_price(p["symbol"])
        r = r_now(p, price)
        p["checks"] = p.get("checks", 0) + 1
        note = ""
        if p.get("legacy") and not p.get("be") and r >= 1.0:
            p["sl"]pnl:+. = p["entry"]
            p["be"] = True
            note = " | <b>SL → BE</b>"
        if p["checks"] % CFG["running_update_every_checks"] == 0 or note \
           or abs(r - p.get("last_r", 0)) >= 0.5:
            tg(msg_running(p, price, r, note))
            p["last_r"] = r
    funnel = {}
    ai_stat = {"ok": 0, "rej": 0}
    new_signals = 0
    symbols = get_universe()
    if symbols:
        print(f"scanning Playbook NONSTOP (15m) on {len(symbols)} pairs...")
        for sym in symbols:
            try:
                sig = compute_signal(sym, funnel)
            except Exception as e:
                print(f"[pb-{sym}] error: {e}")
                continue
            if not sig:
                continue
            ok_ai, why_ai, conf_ai, mult_ai = ai_gate(sig)
            if not ok_ai:
                ai_stat["rej"] += 1
                print("[ai] REJECT pb", sym, why_ai)
                if CFG.get("ai_notify_reject"):
                    tg(f"🤖 <b>AI menolak</b> #{sym} {sig['side']}: "
                       f"{esc(why_ai2f}R)}")
                continue
            if conf_ai < CFG["ai_min_conf"] and not _ai_failopen_marker(why_ai):
                ai_stat["rej"] += 1
                print("[ai] REJECT pb conf", conf_ai, why_ai)
                continue
            ai_stat["ok"] += 1
            prep_pos(sig, nm, "PB")
            sig["ai_conf"] = conf_ai
            sig["ai_mult"] = mult_ai
            st["positions"].append(sig)
            st["signals_today"] += 1
            new_signals += 1
            tg(msg_signal(sig))
            print("pb signal:", sym, sig["side"], sig["strat"])
    save_state(st)
    print(f"scan selesai. new: {new_signals}, open: {len(st['positions'])}, "
          f"day_r: {st['day_r']}, week_r: {st.get('week_r', 0)}, ai: {ai_stat}")
    if CFG.get("heartbeat", True):
        msg = msg_heartbeat(funnel, st, new_signals, ai_stat, len(symbols))
        tg(msg)
        print(msg)

# ---------------- harian & stats ----------------
def daily():
    st = load_state()
    yest = (wib_now() - timedelta(days=1)).date().isoformat()
    tr = [h for h in st["history"] if h["day"] =="]
    ops yest]
    fin = [h for h in tr if h["kind"] in ("TP", "SL", "BE", "TO", "IX")]
    tp = sum(1 for h in fin if h["kind"] in ("TP", "IX"))
    sl = sum(1 for h in fin if h["kind"] == "SL")
    be = sum(1 for h in fin if h["kind"] == "BE")
    to = sum(1 for h in fin if h["kind"] == "TO")
    pnl = sum(h["r"] for h in fin)
    wr = (sum(1 for h in fin if h["r"] > 0) / len(fin) * 100) if fin else 0
    lines = [f"📊 <b>LAP = []
   ORAN HARIAN</b> {yest} (WIB)",
             f"Sinyal: {len(tr)} | Selesai: {len(fin)} → "
             f"Win {tp} / SL {sl} / BE {be} / TO {to}",
             f"Winrate: {wr:.0f}% | PnL: {pnl:+.2f}R"]
    ops = []
    for p in st for p in st["positions"]:
["positions"]:
        price = fetch        price = fetch_price(p["symbol_price(p["symbol"])
        nm"])
        nm = STRAT_TITLE = STRAT_TITLE.get(p.get(".get(p.get("strat", ""),strat", ""), p.get("layer p.get("layer", "PB"))", "PB"))
        ops
        ops.append(f".append(f"#{p['symbol#{p['symbol']} {p['']} {p['side']} [{side']} [{nm}]nm}] "
 "
                   f"({                   f"({r_now(p,r_now(p, price):+.2 price):+.2f}R)")f}R)")
    lines.append
    lines.append("Open: "("Open: " + (", ". + (", ".join(ops)join(ops) if ops else "- if ops else "-"))
    msg"))
    msg = "\ = "\n".join(linesn".join(lines)
    tg)
    tg(msg)
   (msg)
    print(msg)
 print(msg)
    if CFG.get    if CFG.get("ai_daily_review("ai_daily_review") and fin:") and fin:
        jl =
        jl = [f"{h [f"{h['day']} {['day']} {h['symbol']}h['symbol']} [{h [{h.get('strat.get('strat','?')}]','?')}] "
 "
              f"{h              f"{h.get('side','.get('side','?')} {h?')} {h['kind']} {['kind']} {h['r']h['r']:+.2f:+.2f}R"
}R"
              for h in              for h in fin[-10 fin[-10:]]
       :]]
        journal = "\n journal = "\n".join(jl".join(jl)
        journal)
        journal += f"\n += f"\nTotal: {pTotal: {pnl:+.2nl:+.2f}R,f}R, winrate {wr winrate {wr:.0f}:.0f}%"
        name%"
        name, raw = _, raw = _ai_ask(AIai_ask(AI_REVIEW_PROMPT_REVIEW_PROMPT.replace("{journal}",.replace("{journal}", journal)) journal))
        if raw
        if raw:
            tg:
            tg("🤖("🤖 <b>AI <b>AI REVIEW HARIAN REVIEW HARIAN</b>\</b>\n" +n" + esc(raw[:1 esc(raw[:1500]))500]))
            print("[
            print("[ai] review harianai] review harian terkirim")

 terkirim")

def stats(days=Nonedef stats(days=None):
    st):
    st = load_state() = load_state()
    hist =
    hist = list(st.get(" list(st.get("history", []))history", []))
    period_label
    period_label = "ALL-T = "ALL-TIME"
   IME"
    if days:
 if days:
        cutoff = (        cutoff = (wib_now()wib_now() - timedelta(days= - timedelta(days=days)).date().days)).date().isoformat()
        hist = [isoformat()
        hist = [h for h in hist if h.geth for h in hist if h.get("day", "")("day", "") >= cutoff]
        period_label = f"{days >= cutoff]
        period_label = f"{days}H TER}H TERAKHIR"
AKHIR"
    if not hist    if not hist:
        msg:
        msg = (f" = (f"📈 <b>📈 <b>STATS {periodSTATS {period_label}</b>\_label}</b>\n"
              n"
               f"Belum f"Belum ada trade tercatat.")
        tg(msg ada trade tercatat.")
        tg(msg); print(msg);); print(msg); return
    fin = [h for h in hist if return
    fin = [h for h in hist if h.get("kind h.get("kind") in ("TP", "SL",") in ("TP", "SL", "BE", " "BE", "TO", "IXTO", "IX")]
    if")]
    if not fin:
        msg = ( not fin:
        msg = (f"📈 <b>f"📈 <b>STATS {periodSTATS {period_label}</b>\_label}</b>\n"
              n"
               f"Belum f"Belum ada trade selesai.") ada trade selesai.")
        tg(msg
        tg(msg); print(msg);); print(msg); return
    n return
    n = len(fin) = len(fin)
    tp =
    tp = sum(1 for sum(1 for h in fin if h in fin if h["kind"] h["kind"] in ("TP", in ("TP", "IX"))
 "IX"))
    sl = sum    sl = sum(1 for(1 for h in fin if h in fin if h["kind"] h["kind"] == " == "SL")
   SL")
    be = be = sum(1 for sum(1 for h in fin if h in fin if h["kind"] h["kind"] == " == "BE")
   BE")
    to = sum( to = sum(1 for h in1 for h in fin if h[" fin if h["kind"] == "kind"] == "TO")
   TO")
    pnl = sum(h pnl = sum(h["r"]["r"] for h in fin for h in fin)
    wins = [h["r"] for h in fin if h)
    wins["r"] > = [h["r"] for h in fin if h["r"] > 0] 0]
    losses =
    losses = [h["r [h["r"] for h in"] for h in fin if h[" fin if h["r"] < r"] < 0]
    flats = [h0]
    flats = [h for h in fin for h in fin if h["r if h["r"] == 0"] == 0]
    n]
    n_wl = len_wl = len(wins) +(wins) + len(losses) len(losses)
    wr =
    wr = (len(wins (len(wins) / n_w) / n_wl * 1l * 100) if00) if n_wl else n_wl else 0
    0
    avg_win = sum avg_win = sum(wins) /(wins) / len(wins len(wins) if wins else) if wins else 0
    0
    avg_loss = sum avg_loss = sum(losses) /(losses) / len(losses) len(losses) if losses else  if losses else 0
    sum0
    sum_loss = abs(sum_loss = abs(sum(losses))(losses)) if losses else  if losses else 0
    pf0
    pf = (sum(w = (sum(wins) / sumins) / sum_loss) if_loss) if sum_loss >  sum_loss > 0 else0 else float("inf") float("inf")
    expectancy =
    expectancy = pnl / n
 pnl / n
    running =     running = 0; peak =0; peak = 0; max 0; max_dd = _dd = 0
    for0
    for h in fin: h in fin:
        running +=
        running += h["r"] h["r"]
        peak =
        peak = max( max(peak, running)
        max_ddpeak, running)
        max_dd = max(max_dd = max(max_dd, peak - running, peak - running)
    max)
    max_ws = max_ls_ws = max_ls = cur_w = = cur_w = cur_l cur_l =  = 0
    for0
    for h in fin: h in fin:
        if h
        if h["r"] >["r"] > 0: 0:
            cur_w
            cur_w += 1; += 1; cur_l cur_l = 0; = 0; max_ws = max max_ws = max(max_ws(max_ws, cur_w), cur_w)
        elif h
        elif h["r"] <["r"] < 0:
 0:
            cur_l +=            cur_l += 1; cur 1; cur_w = 0_w = 0; max_ls =; max_ls = max(max_ls, max(max_ls, cur_l)
 cur_l)
        else:
        else:
            cur_w =            cur_w = 0; cur 0; cur_l = 0_l = 0
    by
    by_pair = {}
    for h in_pair = {}
    for h in fin:
        fin:
        p = by_pair p = by_pair.setdefault(h["symbol.setdefault(h["symbol"], {"w":"], {"w": 0, " 0, "l": 0l": 0, "r":, "r": 0.0 0.0})
        if h["r"]})
        if h["r"] > 0: > 0: p["w"] p["w"] += 1
 += 1
        elif h["        elif h["r"] < r"] < 0: p["0: p["l"] += l"] += 1
        p1
        p["r"] +=["r"] += h["r"] h["r"]
    by_side
    by_side = {}
    = {}
    for h in fin for h in fin:
        sd:
        sd = h.get(" = h.get("side", "?")side", "?")
        p =
        p = by_side.setdefault(sd by_side.setdefault(sd, {"w":, {"w": 0, " 0, "l": 0l": 0, "r":, "r": 0.0 0.0})
        if})
        if h["r"] h["r"] > 0: > 0: p["w"] p["w"] += 1
 += 1
        elif h["        elif h["r"] < r"] < 0: p["0: p["l"] +=l"] += 1
        1
        p["r"] p["r"] += h["r += h["r"]
    by"]
    by_strat = {}_strat = {}
    for h
    for h in fin:
 in fin:
        ly = h        ly = h.get("strat.get("strat", "legacy")", "legacy")
        p =
        p = by_strat.setdefault by_strat.setdefault(ly, {"(ly, {"n": 0n": 0, "w":, "w": 0, " 0, "l": 0l": 0, "r":, "r": 0.0 0.0})
        p})
        p["n"] +=["n"] += 1; p 1; p["r"] +=["r"] += h["r"] h["r"]
        if h
        if h["r"] >["r"] > 0: p 0: p["w"] +=["w"] += 1
        1
        elif h["r elif h["r"] < 0"] < 0: p["l: p["l"] += 1"] += 1
   
    by_day = {} by_day = {}
    for h
    for h in fin:
 in fin:
        d = by        d = by_day.setdefault(h["_day.setdefault(h["day"], {"nday"], {"n": 0,": 0, "r": 0.0}) "r": 0.0})
        d["
        d["n"] += n"] += 1; d["1; d["r"] += hr"] += h["r"]["r"]
    green_days
    green_days = sum(1 = sum(1 for d for d in by_day.values in by_day.values() if() if d["r"] d["r"] >  > 0)
   0)
    red_days = sum red_days = sum(1 for d(1 for d in by_day.values in by_day.values() if d["() if d["r"] < r"] < 0)
   0)
    lines = [f lines = [f"📈"📈 <b>STAT <b>STATS {period_labelS {period_label}</b>",}</b>",
             f"<
             f"<i>Update {i>Update {wib_now():wib_now():%Y-%m%Y-%m-%d %H-%d %H:%M} WIB:%M} WIB</i>", "",</i>", "",
             "🎯 <
             "🎯 <b>OVERALLb>OVERALL</b>",</b>",
             f"
             f"Trades: <Trades: <b>{n}</b>{n}</b> →b> → Win Win {tp} | {tp} | SL {sl} SL {sl} | BE {be | BE {be} | TO {} | TO {to}",
            to}",
             f"Winrate f"Winrate: <b>{: <b>{wr:.1fwr:.1f}%</b>}%</b> "
             f "
             f"(W {len"(W {len(wins)} /(wins)} / L {len(loss L {len(losses)} /es)} / F {len(fl F {len(flats)})",
ats)})",
             f"Total             f"Total PnL: PnL: <b>{p <b>{pnl:+.2nl:+.2f}R</f}R</b>",
            b>",
             f"Avg win f"Avg win {avg_win:+ {avg_win:+.2f}.2f}R | Avg lossR | Avg loss {avg_loss:+ {avg_loss:+.2f}.2f}R",
            R",
             ("Profit factor: ("Profit factor: ∞ ∞" if pf ==" if pf == float("inf") float("inf")
              else f
              else f"Profit factor:"Profit factor: {pf:.2 {pf:.2f}"),
f}"),
             f"Expect             f"Expectancy: {expectancy: {expectancy:+.2ancy:+.2f}R/trf}R/trade",
            ade",
             f"Max draw f"Max drawdown: {maxdown: {max_dd:.2f_dd:.2f}R | St}R | Streak 🟢reak 🟢{max_ws}{max_ws} / 🔴{ / 🔴{max_ls}",
max_ls}",
             "", "🧩             "", "🧩 <b>PER <b>PER STRATEGI</ STRATEGI</b>"]
b>"]
    for ly,    for ly, v in by_str v in by_strat.items():
at.items():
        wrp =        wrp = (v["w (v["w"] / max(v"] / max(v["w"]["w"] + v["l + v["l"], 1)"], 1) * 10 * 100)
       0)
        title = STRAT title = STRAT_TITLE.get(ly_TITLE.get(ly, ly)
, ly)
        lines.append(f        lines.append(f"• {title"• {title}: {v['}: {v['n']}t ({n']}t ({v['v['w']}W/{w']}W/{v['l']}v['l']}L)L) → "
                     → "
                     f"<b>{ f"<b>{v['v['r']:+.r']:+.2f}R2f}R</b> ({</b> ({wrp:.0wrp:.0f}%)")f}%)")
    lines +=
    lines += ["", "↕️ < ["", "↕️ <b>PER SIDEb>PER SIDE</b>"]</b>"]
    for sd
    for sd, v in sorted, v in sorted(by_side(by_side.items()):
       .items()):
        ns = v[" ns = v["w"] + vw"] + v["l"]
["l"]
        wrs =        wrs = (v["w (v["w"] / ns *"] / ns * 100 100) if ns else) if ns else 0
        0
        lines.append(f" lines.append(f"• {• {sd}: {vsd}: {v['w']}['w']}W/{v['W/{v['l']}l']}L → "
L → "
                     f"<b                     f"<b>{v['r>{v['r']:+.2']:+.2f}R</f}R</b> ({wb> ({wrs:.rs:.0f}%)0f}%)")
    lines")
    lines += ["", " += ["", "📊 <b>📊 <b>TOP 10TOP 10 PAIR PAIR</b>"]</b>"]
    top =
    top = sorted(by_pair.items sorted(by_pair.items(), key=lambda x(), key=lambda x: -x[: -x[1]["r"])1]["r"])[:10][:10]
    for sym
    for sym, v in top, v in top:
        np:
        np_ = v_ = v["w"] +["w"] + v["l"] v["l"]
        wrp
        wrp = (v[" = (v["w"] / npw"] / np_ * _ * 100)100) if np_ else if np_ else 0
        0
        lines.append(f" lines.append(f"• <code>{• <code>{sym}</sym}</code>:code>: {v['w {v['w']}W/{v']}W/{v['l']}['l']}L → "
L → "
                     f"<b                     f"<b>{v['r>{v['r']:+.2']:+.2f}R</f}R</b> ({wrb> ({wrp:.0fp:.0f}%)")
}%)")
    lines += ["    lines += ["", f"📅 <b", f"📅 <b>PER DAY</>PER DAY</b> ({lenb> ({len(by_day(by_day)} hari)} hari aktif)",
              aktif)",
              f" f"• 🟢• 🟢 {green_days} {green_days} profit | 🔴 {red_days profit | 🔴 {red_days} loss"]
} loss"]
    if by_day    if by_day:
        best:
        best = max(by_day = max(by_day.items(), key=lambda.items(), key=lambda x: x[ x: x[1]["r"])1]["r"])
        worst =
        worst = min(by_day.items min(by_day.items(), key=lambda x(), key=lambda x: x[1: x[1]["r"])]["r"])
        b_txt
        b_txt = "• Best = "• Best <code>" + <code>" + best[0] best[0] + "</ + "</code> "
code> "
        b_txt +=        b_txt += f"{best[ f"{best[1]['r']1]['r']:+.2f:+.2f}R"
}R"
        w_txt =        w_txt = " | Worst < " | Worst <code>" + worstcode>" + worst[0][0] + "</ + "</code> "
code> "
        w_txt +=        w_txt += f"{worst f"{worst[1]['r[1]['r']:+.2']:+.2f}R"f}R"
        lines.append
        lines.append(b_txt + w(b_txt + w_txt)
   _txt)
    last5 = fin last5 = fin[-5:][[-5:][::-1]
::-1]
    if last5    if last5:
        lines:
        lines += ["", " += ["", "🕒 <b>🕒 <b>5 TRADE TERAK5 TRADE TERAKHIR</b>HIR</b>"]
       "]
        for h in last for h in last5:
           5:
            ic = {"TP ic = {"TP": "✅",": "✅", "IX": " "IX": "✅", "SL✅", "SL": "❌": "❌",
                 ",
                  "BE": " "BE": "⚪", "TO⚪", "TO": "⏳"}[h": "⏳"}[h["kind"]]["kind"]]
            cf =
            cf = f" ai{ f" ai{h['h['ai_conf']:.ai_conf']:.0f}" if0f}" if h.get("ai h.get("ai_conf") else_conf") else ""
            ""
            one = (f one = (f"{ic} <"{ic} <code>{h['code>{h['day']}</code>day']}</code> {h['symbol {h['symbol']} "
                  ']} "
                   f"[{STR f"[{STRAT_TITLE.get(hAT_TITLE.get(h.get('strat.get('strat',''), h.get',''), h.get('strat','('strat','?'))}]?'))}] "
                   "
                   f"{h.get f"{h.get('side','-')}('side','-')} → {h[' → {h['r']:+.r']:+.2f}R2f}R{cf}")
{cf}")
            lines.append(one            lines.append(one)
    msg)
    msg = "\n". = "\n".join(linesjoin(lines)
    tg)
    tg_long(msg)
_long(msg)
    print(msg)    print(msg)

# ---------------- main

# ---------------- main ----------------
if __ ----------------
if __name__ == "__main__":
name__ == "__main__":
    mode = sys    mode = sys.argv[1].argv[1] if len(sys.argv if len(sys.argv) > 1) > 1 else "scan" else "scan"
    if mode
    if mode == "scan": == "scan":
        scan()
        scan()
    elif mode
    elif mode == "daily": == "daily":
        daily()
        daily()
    elif mode
    elif mode == "stats": == "stats":
        d =
        d = int(sys.argv[ int(sys.argv[2]) if len2]) if len(sys.argv) >(sys.argv) > 2 else None 2 else None
        stats(d
        stats(d)
    elif)
    elif mode == "ait mode == "aitest":
       est":
        dummy = {"symbol dummy = {"symbol": "BTCUS": "BTCUSDT", "sideDT", "side": "LONG",": "LONG", "layer": "layer": "PB",
 "PB",
                 "strat                 "strat": "rsi": "rsi_wma", "_wma", "entry": 1entry": 100.000.0, "sl":, "sl": 99. 99.5,
                5,
                 "reason": " "reason": "uji coba gate",uji coba gate", "tf": "tf": "15m "15m", "adx":", "adx": 28} 28}
        ok,
        ok, why, conf, why, conf, mult = ai_gate(dummy)
        mult = ai_gate(dummy)
        print("AI approve print("AI approve:", ok, "|:", ok, "| conf:", conf:", conf, "| conf, "| mult:", mult:", mult)
        mult)
        print("alasan:", why)
        tg(f"🤖 <b> print("alasan:", why)
        tg(f"🤖 <b>AI gate test</AI gate test</b>: approve={b>: approve={ok} conf={conf:.0fok} conf={conf:.0f} | "
           f"{esc} | "
           f"{esc(why)}")(why)}")
    elif mode
    elif mode == "test": == "test":
        tg("
        tg("📘📘 Bot Playbook NON Bot Playbook NONSTOP aktifSTOP aktif — test message OK — test message OK ✅")
    ✅")
    else:
        else:
        print("mode tidak print("mode tidak dikenal:", mode) dikenal:", mode)


