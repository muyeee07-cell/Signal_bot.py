#!/usr/bin/env python3
"""
ALPHAQUANT backtest

Replays the LIVE strategy code from signal_bot.py on OKX history, so the
backtest can never drift from what the bot actually does.

  python backtest.py --setup ALL --days 90 --pairs 20
  python backtest.py --setup ICT_SCALP --days 180
  python backtest.py --setup MEAN_REV --days 120 --pairs 30 --fee 0.0005

Method (same rules as the live bot)
- Signal is evaluated on every CONFIRMED candle using the same window length
  the bot uses (HISTORY_BARS / SMC_HISTORY_BARS).
- Entry = close of the signal candle; SL / TP exactly as the strategy returns.
- Exit is simulated on finer candles (1H for 4H setups, 5m for scalps).
  If SL and TP are both touched inside one execution candle -> SL first.
- One open position per symbol per setup, plus the bot's cooldown after a close.
- Each setup is tested on its own (no priority order between setups).

Extra realism
- Fees: --fee is charged per side (default 0.05% taker) and is reported as
  "net R" next to the bot's own gross R.

Known limits
- No slippage / latency: entry is at the signal candle close.
- MAX_OPEN (12) portfolio cap is not applied.
- Pairs are today's top-volume pairs -> survivorship bias for the 4H setups.
- Past performance is not a guarantee.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
import time
from bisect import bisect_left
from datetime import datetime, timezone

import signal_bot as bot

DAY_MS = 86_400_000
BAR_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1H": 3_600_000, "4H": 14_400_000,
}

SWING_SETUPS = {
    "PULLBACK": bot.build_pullback,
    "BREAKOUT": bot.build_breakout,
    "MEAN_REV": bot.build_meanrev,
}
SCALP_SETUPS = {
    "SMC_SCALP": bot.build_smc_scalp,
    "ICT_SCALP": bot.build_ict_scalp,
}
MULTI_SETUPS = {"ADAPTIVE": bot.build_adaptive}      # 15m, many symbols
ALL_SETUPS = list(SWING_SETUPS) + list(SCALP_SETUPS)  # "ALL" excludes ADAPTIVE (heavy)
CHOICES = ["ALL"] + ALL_SETUPS + list(MULTI_SETUPS)

_DATA = {}          # (inst, bar) -> candles, shared between setups in one run


# ---------------------------------------------------------------- data

def fetch_series(inst, bar, since_ms, cache_dir="bt_cache"):
    """Confirmed candles (oldest -> newest) from OKX history-candles."""
    path = os.path.join(cache_dir, f"{inst}_{bar}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 6 * 3600:
        try:
            with open(path) as f:
                data = json.load(f)
            if data and data[0][0] <= since_ms:
                return [c for c in data if c[0] >= since_ms]
        except Exception:
            pass

    found, cursor = {}, None
    while True:
        params = {"instId": inst, "bar": bar, "limit": "100"}
        if cursor is not None:
            params["after"] = str(cursor)

        d = bot.api("/api/v5/market/history-candles", params)
        if not d or not d.get("data"):
            break

        oldest = None
        for x in d["data"]:
            try:
                ts = int(x[0])
                oldest = ts if oldest is None else min(oldest, ts)
                if int(x[8]) != 1:
                    continue
                found[ts] = [ts, float(x[1]), float(x[2]),
                             float(x[3]), float(x[4]), float(x[5])]
            except Exception:
                continue

        if oldest is None or oldest == cursor or oldest <= since_ms:
            break
        cursor = oldest
        time.sleep(0.12)              # OKX limit: 20 requests / 2 s per IP

    out = sorted(found.values(), key=lambda c: c[0])
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "w") as f:
            json.dump(out, f)
    except Exception:
        pass
    return [c for c in out if c[0] >= since_ms]


def get_series(inst, bar, since_ms, end_ms, cache_dir, fetch_since=None):
    key = (inst, bar)
    if key not in _DATA:
        _DATA[key] = fetch_series(inst, bar, fetch_since or since_ms, cache_dir)
    ms = BAR_MS[bar]
    return [c for c in _DATA[key] if c[0] >= since_ms and c[0] + ms <= end_ms]


# ---------------------------------------------------------------- simulation

def simulate(trade, ex, ex_ts, start_ms):
    """
    Walk execution candles from the signal-candle close.
    Returns (result, exit_candle_open_ms, exit_price) or None if still open.
    """
    sl, tp = trade["sl"], trade["tp"]
    long_ = trade["direction"] == "LONG"

    for c in ex[bisect_left(ex_ts, start_ms):]:
        hi, lo = c[2], c[3]
        hit_sl = lo <= sl if long_ else hi >= sl
        hit_tp = hi >= tp if long_ else lo <= tp

        if hit_sl and hit_tp:                    # same candle -> SL first
            return "LOSS", c[0], sl
        if hit_tp:
            return "WIN", c[0], tp
        if hit_sl:
            return "LOSS", c[0], sl
    return None


def run_symbol(setup, inst, sig, ex, p):
    """Sequentially replay one setup on one symbol. Returns (trades, unfinished, errors)."""
    builder = p["builder"]
    sig_ms, hist, cd_ms = p["sig_ms"], p["hist"], p["cd_ms"]
    ex_ts = [c[0] for c in ex]

    trades, unfinished, errors = [], 0, 0
    busy_until = 0
    funnel = {"_evaluated": 0, "_signal": 0}
    examples = {}

    for i in range(len(sig)):
        if sig[i][0] < p["start_ms"]:
            continue

        t_close = sig[i][0] + sig_ms
        if t_close < busy_until:                 # position open or cooling down
            continue

        window = sig[max(0, i - hist + 1): i + 1]
        if len(window) < p["min_bars"]:
            continue

        bot.REJECTS.clear()
        try:
            s = builder(inst, window, {})
        except Exception:
            errors += 1
            continue

        funnel["_evaluated"] += 1
        if not s:
            # every rejection is recorded at the FIRST stage that failed
            for (_, stage), rows in bot.REJECTS.items():
                funnel[stage] = funnel.get(stage, 0) + len(rows)
                keep = examples.setdefault(stage, [])
                for _inst, detail in rows[:1]:
                    keep.append(f"{inst} {bot.iso(t_close)[:16]} {detail}")
                del keep[:-5]
            continue
        funnel["_signal"] += 1

        res = simulate(s, ex, ex_ts, t_close)
        if res is None:                          # still open when data ends
            unfinished += 1
            break

        result, exit_ms, exit_px = res
        rr = float(s.get("rr", bot.RR))
        entry, sl = float(s["entry"]), float(s["sl"])
        risk = abs(entry - sl)

        r_gross = rr if result == "WIN" else -1.0
        fee_r = (2 * p["fee"] * entry / risk) if risk > 0 else 0.0

        trades.append({
            "setup": setup,
            "symbol": inst,
            "direction": s["direction"],
            "module": s.get("module", ""),
            "entry_time": bot.iso(t_close),
            "exit_time": bot.iso(exit_ms),
            "entry_ms": t_close,
            "exit_ms": exit_ms,
            "entry": entry,
            "sl": sl,
            "tp": float(s["tp"]),
            "rr": rr,
            "result": result,
            "r_gross": r_gross,
            "fee_r": round(fee_r, 4),
            "r_net": round(r_gross - fee_r, 4),
            "hours_held": round((exit_ms - t_close) / 3_600_000, 2),
        })
        busy_until = exit_ms + cd_ms

    return trades, unfinished, errors, funnel, examples


# ---------------------------------------------------------------- statistics

def wilson(w, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d, (c + m) / d


def concurrency(trades):
    """Peak and average number of open trades (average measured at each entry)."""
    ev = []
    for t in trades:
        ev.append((t["entry_ms"], 1))
        ev.append((t["exit_ms"], -1))
    ev.sort(key=lambda x: (x[0], x[1]))          # exits before entries at the same ms
    cur = peak = 0
    at_entry = []
    for _, d in ev:
        cur += d
        if d == 1:
            at_entry.append(cur)
        peak = max(peak, cur)
    avg = sum(at_entry) / len(at_entry) if at_entry else 0.0
    return peak, avg


def apply_cap(trades, cap):
    """Portfolio cap: skip a trade if `cap` trades are already open at its entry."""
    if cap <= 0:
        return trades, 0
    kept, open_exits, skipped = [], [], 0
    for t in sorted(trades, key=lambda t: t["entry_ms"]):
        open_exits = [x for x in open_exits if x > t["entry_ms"]]
        if len(open_exits) >= cap:
            skipped += 1
            continue
        kept.append(t)
        open_exits.append(t["exit_ms"])
    return kept, skipped


def summarize(trades, days):
    n = len(trades)
    if n == 0:
        return {"n": 0}

    wins = sum(1 for t in trades if t["result"] == "WIN")
    rn = [t["r_net"] for t in trades]
    rg = [t["r_gross"] for t in trades]
    avg_rr = statistics.mean(t["rr"] for t in trades)
    avg_fee = statistics.mean(t["fee_r"] for t in trades)

    pos = sum(x for x in rn if x > 0)
    neg = -sum(x for x in rn if x < 0)
    pf = (pos / neg) if neg > 0 else math.inf

    eq = peak = dd = 0.0
    streak = longest = 0
    for t in sorted(trades, key=lambda t: t["exit_ms"]):
        eq += t["r_net"]
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
        streak = streak + 1 if t["result"] == "LOSS" else 0
        longest = max(longest, streak)

    mean_n = statistics.mean(rn)
    tstat = None
    if n > 1:
        sd = statistics.stdev(rn)
        if sd > 0:
            tstat = mean_n / (sd / math.sqrt(n))

    lo_ci, hi_ci = wilson(wins, n)
    bep_gross = 1 / (1 + avg_rr)
    bep_net = (1 + avg_fee) / (1 + avg_rr)

    peak_open, avg_open = concurrency(trades)
    by_module = {}
    for t in trades:
        if t.get("module"):
            mm = by_module.setdefault(t["module"], [0, 0, 0.0])
            mm[0] += 1
            mm[1] += t["result"] == "WIN"
            mm[2] += t["r_net"]

    by_dir, by_month = {}, {}
    for t in trades:
        d = by_dir.setdefault(t["direction"], [0, 0, 0.0])
        d[0] += 1
        d[1] += t["result"] == "WIN"
        d[2] += t["r_net"]
        m = by_month.setdefault(t["exit_time"][:7], [0, 0.0])
        m[0] += 1
        m[1] += t["r_net"]

    return {
        "n": n, "wins": wins, "losses": n - wins,
        "wr": wins / n, "ci": (lo_ci, hi_ci),
        "avg_rr": avg_rr, "avg_fee_r": avg_fee,
        "bep_gross": bep_gross, "bep_net": bep_net,
        "r_gross": sum(rg), "r_net": sum(rn),
        "exp_net": mean_n, "pf_net": pf, "max_dd": dd,
        "longest_loss": longest,
        "avg_hours": statistics.mean(t["hours_held"] for t in trades),
        "per_week": n / max(days / 7, 1e-9),
        "tstat": tstat,
        "by_dir": by_dir, "by_month": by_month, "by_module": by_module,
        "peak_open": peak_open, "avg_open": avg_open,
    }


def verdict(st):
    if st["n"] < 30:
        return "Sampel terlalu kecil (<30 trade): abaikan angka di atas."
    if st["tstat"] is not None and st["tstat"] >= 2 and st["exp_net"] > 0:
        return "Ada indikasi edge positif setelah fee (t>=2). Tetap uji lagi di data live."
    if st["ci"][1] < st["bep_net"]:
        return "Win rate hampir pasti di bawah break-even setelah fee."
    return "Belum bisa dibedakan dari acak. Butuh lebih banyak trade."


def fmt_pf(x):
    return "inf" if math.isinf(x) else f"{x:.2f}"


def stage_order(setup):
    if setup == "ADAPTIVE":
        return list(bot.ADAPT_STAGES)
    if setup in SWING_SETUPS:
        return list(bot.SETUP_STAGES.get(setup, []))
    return list(bot.SCALP_STAGES.get(setup, []))


def funnel_line(setup, meta, top=None):
    fn = meta.get("funnel") or {}
    ev = fn.get("_evaluated", 0)
    if not ev:
        return ""
    order = stage_order(setup)
    stages = [k for k in fn if not k.startswith("_")]
    stages.sort(key=lambda k: (order.index(k) if k in order else 99, k))
    parts = [f"{k} {fn[k]}" for k in stages]
    if top:
        parts = sorted(parts, key=lambda x: -int(x.rsplit(" ", 1)[1]))[:top]
    return (f"Corong: {ev} candle dicek, {fn.get('_signal', 0)} sinyal | "
            f"gugur di: " + " · ".join(parts))


def window_lines(meta):
    ws = meta.get("windows") or []
    if not ws:
        return []
    pos = sum(1 for w in ws if w["r_net"] > 0)
    out = [f"Jendela ({len(ws)} periode, untung di {pos}/{len(ws)}):"]
    for w in ws:
        wr = (w["wins"] / w["n"] * 100) if w["n"] else 0
        out.append(f"  {w['start']}..{w['end']}: {w['n']} trade, WR {wr:.0f}%, {w['r_net']:+.1f}R net")
    worst = min(w["r_net"] for w in ws)
    out.append(f"  jendela terburuk: {worst:+.1f}R")
    return out


def example_lines(setup, meta, stages=2, per=4):
    ex = meta.get("examples") or {}
    fn = meta.get("funnel") or {}
    order = [k for k in stage_order(setup) if fn.get(k) and ex.get(k)
             and k not in ("Data", "Diblokir", "Error")]
    lines = []
    for k in order[-stages:]:
        lines.append(f"Contoh gugur di {k}:")
        lines += [f"  {x}" for x in ex[k][-per:]]
    return lines


def report_text(setup, st, meta, full=True):
    head = f"{setup}"
    if st["n"] == 0:
        txt = (f"{head}: 0 trade"
               f" (pair {meta['symbols']}, hari {meta['days']}, "
               f"belum selesai {meta['unfinished']}, error {meta['errors']})")
        fl = funnel_line(setup, meta)
        return "\n".join([txt] + ([fl] if fl else []) + example_lines(setup, meta))

    t = "n/a" if st["tstat"] is None else f"{st['tstat']:.2f}"
    lines = [
        f"{head}",
        f"Trade      : {st['n']}  ({st['per_week']:.1f}/minggu, rata-rata {st['avg_hours']:.1f} jam)",
        f"Win rate   : {st['wr']*100:.1f}%  (95% CI {st['ci'][0]*100:.0f}-{st['ci'][1]*100:.0f}%)",
        f"Break-even : {st['bep_gross']*100:.1f}% gross | {st['bep_net']*100:.1f}% setelah fee",
        f"Total R    : {st['r_gross']:+.2f}R gross | {st['r_net']:+.2f}R net",
        f"Expectancy : {st['exp_net']:+.3f}R/trade net | PF {fmt_pf(st['pf_net'])} | t={t}",
        f"Max DD     : {st['max_dd']:.2f}R | kalah beruntun terpanjang {st['longest_loss']}",
        f"Posisi bersamaan: maks {st['peak_open']}, rata-rata {st['avg_open']:.1f}"
        + (f" | dilewati karena batas {meta['cap']}: {meta['capped']}" if meta.get("cap") else ""),
    ]
    for mname, (n, w, r) in sorted(st.get("by_module", {}).items()):
        lines.append(f"  modul {mname}: {n} trade, WR {w/n*100:.0f}%, {r:+.2f}R net")
    if full:
        for d, (n, w, r) in sorted(st["by_dir"].items()):
            lines.append(f"  {d}: {n} trade, WR {w/n*100:.0f}%, {r:+.2f}R")
        for m, (n, r) in sorted(st["by_month"].items()):
            lines.append(f"  {m}: {n} trade, {r:+.2f}R")
    lines.append(f"-> {verdict(st)}")
    wl = window_lines(meta)
    lines += wl
    fl = funnel_line(setup, meta)
    if fl:
        lines.append(fl)
    lines += example_lines(setup, meta, stages=1, per=3)
    lines.append(
        f"(pair {meta['symbols']}, {meta['days']} hari, belum selesai {meta['unfinished']},"
        f" error {meta['errors']})"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------- driver

def setup_params(setup, args, start_ms):
    if setup in SWING_SETUPS:
        sig_bar, builder = bot.TIMEFRAME, SWING_SETUPS[setup]
        hist, min_bars, cd_h = bot.HISTORY_BARS, bot.MIN_HISTORY_BARS, bot.COOLDOWN_HOURS
        ex_bar = "1H"
    elif setup in MULTI_SETUPS:
        sig_bar, builder = "15m", MULTI_SETUPS[setup]
        hist, min_bars, cd_h = bot.AD_HISTORY_BARS, bot.AD_MIN_BARS, bot.AD_COOLDOWN_HOURS
        ex_bar = "15m"          # conservative: SL first when both touched in one candle
    else:
        sig_bar, builder = bot.SMC_TF, SCALP_SETUPS[setup]
        hist, min_bars, cd_h = bot.SMC_HISTORY_BARS, 80, bot.SMC_COOLDOWN_HOURS
        ex_bar = "5m"

    if args.exec == "same":
        ex_bar = sig_bar
    elif args.exec != "auto":
        ex_bar = args.exec

    return {
        "builder": builder, "sig_bar": sig_bar, "ex_bar": ex_bar,
        "sig_ms": BAR_MS[sig_bar], "hist": hist, "min_bars": min_bars,
        "cd_ms": int(cd_h * 3_600_000), "fee": args.fee, "start_ms": start_ms,
    }


def backtest(args):
    end_ms = args.end_ms or int(time.time() * 1000)
    K = max(1, getattr(args, "windows", 1))
    earliest = end_ms - K * args.days * DAY_MS

    setups = ALL_SETUPS if args.setup == "ALL" else [args.setup]
    need_pairs = any(x in SWING_SETUPS or x in MULTI_SETUPS for x in setups)

    symbols_multi = []
    if need_pairs:
        if args.symbols:
            symbols_multi = [x.strip() for x in args.symbols.split(",") if x.strip()]
        else:
            bot.TOP_PAIRS = args.pairs
            symbols_multi = bot.top_pairs()
            if not symbols_multi:
                print("Gagal mengambil daftar pair dari OKX.", flush=True)

    results, all_trades = {}, []

    for setup in setups:
        p0 = setup_params(setup, args, earliest)
        symbols = symbols_multi if (setup in SWING_SETUPS or setup in MULTI_SETUPS) \
            else [bot.SMC_SYMBOL]

        trades, windows, used = [], [], set()
        unfinished = errors = 0
        funnel, examples = {}, {}

        for w in range(K):
            w_end = end_ms - w * args.days * DAY_MS
            w_start = w_end - args.days * DAY_MS
            p = dict(p0, start_ms=w_start)
            w_trades = []

            for inst in symbols:
                sig = get_series(
                    inst, p["sig_bar"], w_start - p["hist"] * p["sig_ms"], w_end,
                    args.cache, fetch_since=earliest - p["hist"] * p["sig_ms"]
                )
                ex = get_series(inst, p["ex_bar"], w_start, w_end, args.cache,
                                fetch_since=earliest)
                if len(sig) < p["min_bars"] or not ex:
                    print(f"[{setup}] {inst}: data tidak cukup, dilewati", flush=True)
                    continue

                tr, un, er, fn, exm = run_symbol(setup, inst, sig, ex, p)
                w_trades += tr
                unfinished += un
                errors += er
                used.add(inst)
                for k, v in fn.items():
                    funnel[k] = funnel.get(k, 0) + v
                for k, v in exm.items():
                    examples.setdefault(k, []).extend(v)
                    del examples[k][:-5]

            wins = sum(1 for t in w_trades if t["result"] == "WIN")
            windows.append({
                "start": bot.iso(w_start)[:10], "end": bot.iso(w_end)[:10],
                "n": len(w_trades), "wins": wins,
                "r_net": sum(t["r_net"] for t in w_trades),
                "_lo": w_start, "_hi": w_end,
            })
            trades += w_trades
            print(f"[{setup}] jendela {bot.iso(w_start)[:10]} .. {bot.iso(w_end)[:10]}: "
                  f"{len(w_trades)} trade", flush=True)

        capped = 0
        cap = getattr(args, "max_open", 0)
        if cap > 0:
            trades, capped = apply_cap(trades, cap)
            for w in windows:                   # recompute window totals after the cap
                lo_, hi_ = w["_lo"], w["_hi"]
                wt = [t for t in trades if lo_ <= t["entry_ms"] < hi_]
                w["n"], w["wins"] = len(wt), sum(1 for t in wt if t["result"] == "WIN")
                w["r_net"] = sum(t["r_net"] for t in wt)
        windows.reverse()                       # oldest -> newest
        meta = {"symbols": len(used), "days": args.days * K,
                "unfinished": unfinished, "errors": errors, "funnel": funnel,
                "examples": examples, "windows": windows if K > 1 else [],
                "cap": cap, "capped": capped}
        results[setup] = (summarize(trades, args.days * K), meta)
        all_trades += trades

    return results, all_trades


def write_outputs(results, trades, out_dir):
    os.makedirs(out_dir, exist_ok=True)

    cols = ["setup", "symbol", "direction", "entry_time", "exit_time", "entry",
            "sl", "tp", "rr", "result", "r_gross", "fee_r", "r_net", "hours_held"]
    with open(os.path.join(out_dir, "trades.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for t in sorted(trades, key=lambda t: t["entry_ms"]):
            w.writerow(t)

    text = "\n\n".join(report_text(s, st, meta) for s, (st, meta) in results.items())
    with open(os.path.join(out_dir, "summary.txt"), "w") as f:
        f.write(text + "\n")
    return text


def telegram_summary(results, days):
    label = days if isinstance(days, str) else f"{days} hari"
    lines = [f"<b>📈 BACKTEST · {label}</b>", "━━━━━━━━━━━━━━━━━━"]
    for setup, (st, meta) in results.items():
        if st["n"] == 0:
            fl = funnel_line(setup, meta)
            ex = example_lines(setup, meta, stages=1, per=3)
            lines.append(
                f"<b>{setup}</b>: 0 trade" + ("\n" + fl if fl else "") +
                ("\n" + "\n".join(ex) if ex else "")
            )
            continue
        t = "n/a" if st["tstat"] is None else f"{st['tstat']:.1f}"
        lines.append(
            f"<b>{setup}</b>: {st['n']} trade · WR {st['wr']*100:.0f}% "
            f"(BEP {st['bep_net']*100:.0f}%)\n"
            f"{st['r_net']:+.1f}R net · {st['exp_net']:+.2f}R/trade · "
            f"DD {st['max_dd']:.1f}R · t={t}\n"
            f"{verdict(st)}"
        )
        lines.append(f"Posisi bersamaan: maks {st['peak_open']} | rata-rata {st['avg_open']:.1f}"
                     + (f" (batas {meta['cap']})" if meta.get("cap") else ""))
        if st.get("by_module"):
            lines.append("Modul: " + " | ".join(
                f"{k} {n} trade {r:+.0f}R" for k, (n, w, r) in sorted(st["by_module"].items())))
        ws = meta.get("windows") or []
        if ws:
            pos = sum(1 for w in ws if w["r_net"] > 0)
            lines.append(
                f"Jendela: {pos}/{len(ws)} untung | " +
                " ".join(f"{w['r_net']:+.0f}" for w in ws) + " R"
            )
    lines.append("\nFee 0.05%/sisi sudah dihitung. Tanpa slippage.")
    return "\n".join(lines)


def apply_overrides(items):
    """--set NAME=VALUE ... changes constants of signal_bot for this run only."""
    applied = []
    for item in items:
        if "=" not in item:
            raise SystemExit(f"Format salah: {item!r} (pakai NAMA=NILAI)")
        name, raw = item.split("=", 1)
        if not hasattr(bot, name):
            raise SystemExit(f"Konstanta tidak ada di signal_bot.py: {name}")
        cur = getattr(bot, name)
        if isinstance(cur, bool):
            val = raw.strip().lower() in ("1", "true", "yes", "ya")
        elif isinstance(cur, (int, float)):
            val = type(cur)(float(raw)) if isinstance(cur, int) else float(raw)
        else:
            raise SystemExit(f"Tipe {type(cur).__name__} tidak didukung: {name}")
        setattr(bot, name, val)
        applied.append(f"{name}={val}")
    return applied


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="ALPHAQUANT backtest")
    ap.add_argument("--setup", default="ALL", choices=CHOICES)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--windows", type=int, default=1,
                    help="number of consecutive windows of --days (robustness check)")
    ap.add_argument("--pairs", type=int, default=20,
                    help="top-volume pairs for the 4H setups")
    ap.add_argument("--symbols", default="",
                    help="comma separated override, e.g. ETH-USDT-SWAP,SOL-USDT-SWAP")
    ap.add_argument("--max-open", type=int, default=0, dest="max_open",
                    help="portfolio cap: max simultaneous open trades (0 = no cap)")
    ap.add_argument("--fee", type=float, default=0.0005, help="per side, 0.0005 = 0.05%%")
    ap.add_argument("--exec", default="auto",
                    help="execution candle bar: auto | same | 1m | 5m | 15m | 1H")
    ap.add_argument("--end", default="", help="end date YYYY-MM-DD (UTC), default now")
    ap.add_argument("--set", nargs="*", default=[], dest="overrides",
                    help="override constants, e.g. MIN_SCORE=65 ICT_MAX_PD=0.62")
    ap.add_argument("--out", default="bt_out")
    ap.add_argument("--cache", default="bt_cache")
    ap.add_argument("--telegram", action="store_true")
    a = ap.parse_args(argv)

    a.end_ms = 0
    if a.end:
        a.end_ms = int(datetime.strptime(a.end, "%Y-%m-%d")
                       .replace(tzinfo=timezone.utc).timestamp() * 1000)
    return a


def main(argv=None):
    args = parse_args(argv)
    applied = apply_overrides(args.overrides)
    args.applied = applied
    t0 = time.time()
    results, trades = backtest(args)
    text = write_outputs(results, trades, args.out)
    if applied:
        text = "OVERRIDE: " + " ".join(applied) + "\n\n" + text

    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)
    print(f"Selesai dalam {time.time() - t0:.0f} detik. File: {args.out}/trades.csv, summary.txt")

    if args.telegram and bot.TELEGRAM:
        label = (f"{args.windows} x {args.days} hari" if args.windows > 1
                 else f"{args.days} hari")
        msg = telegram_summary(results, label)
        if applied:
            msg = msg.replace(
                "━━━━━━━━━━━━━━━━━━\n",
                "━━━━━━━━━━━━━━━━━━\n<i>Override: " + " ".join(applied) + "</i>\n", 1)
        bot.tg(msg)


if __name__ == "__main__":
    sys.exit(main())
