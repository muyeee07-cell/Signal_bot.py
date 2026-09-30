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
ALL_SETUPS = list(SWING_SETUPS) + list(SCALP_SETUPS)

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


def get_series(inst, bar, since_ms, end_ms, cache_dir):
    key = (inst, bar)
    if key not in _DATA:
        _DATA[key] = fetch_series(inst, bar, since_ms, cache_dir)
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
        if not s:
            continue

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

    return trades, unfinished, errors


# ---------------------------------------------------------------- statistics

def wilson(w, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d, (c + m) / d


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
        "by_dir": by_dir, "by_month": by_month,
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


def report_text(setup, st, meta, full=True):
    head = f"{setup}"
    if st["n"] == 0:
        return (f"{head}: 0 trade"
                f" (pair {meta['symbols']}, hari {meta['days']}, "
                f"belum selesai {meta['unfinished']}, error {meta['errors']})")

    t = "n/a" if st["tstat"] is None else f"{st['tstat']:.2f}"
    lines = [
        f"{head}",
        f"Trade      : {st['n']}  ({st['per_week']:.1f}/minggu, rata-rata {st['avg_hours']:.1f} jam)",
        f"Win rate   : {st['wr']*100:.1f}%  (95% CI {st['ci'][0]*100:.0f}-{st['ci'][1]*100:.0f}%)",
        f"Break-even : {st['bep_gross']*100:.1f}% gross | {st['bep_net']*100:.1f}% setelah fee",
        f"Total R    : {st['r_gross']:+.2f}R gross | {st['r_net']:+.2f}R net",
        f"Expectancy : {st['exp_net']:+.3f}R/trade net | PF {fmt_pf(st['pf_net'])} | t={t}",
        f"Max DD     : {st['max_dd']:.2f}R | kalah beruntun terpanjang {st['longest_loss']}",
    ]
    if full:
        for d, (n, w, r) in sorted(st["by_dir"].items()):
            lines.append(f"  {d}: {n} trade, WR {w/n*100:.0f}%, {r:+.2f}R")
        for m, (n, r) in sorted(st["by_month"].items()):
            lines.append(f"  {m}: {n} trade, {r:+.2f}R")
    lines.append(f"-> {verdict(st)}")
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
    start_ms = end_ms - args.days * DAY_MS

    setups = ALL_SETUPS if args.setup == "ALL" else [args.setup]
    need_swing = any(s in SWING_SETUPS for s in setups)

    symbols_swing = []
    if need_swing:
        if args.symbols:
            symbols_swing = [s.strip() for s in args.symbols.split(",") if s.strip()]
        else:
            bot.TOP_PAIRS = args.pairs
            symbols_swing = bot.top_pairs()
            if not symbols_swing:
                print("Gagal mengambil daftar pair dari OKX.", flush=True)

    results, all_trades = {}, []

    for setup in setups:
        p = setup_params(setup, args, start_ms)
        symbols = symbols_swing if setup in SWING_SETUPS else [bot.SMC_SYMBOL]

        trades, unfinished, errors, used = [], 0, 0, 0
        for inst in symbols:
            sig = get_series(
                inst, p["sig_bar"],
                start_ms - p["hist"] * p["sig_ms"], end_ms, args.cache
            )
            ex = get_series(inst, p["ex_bar"], start_ms, end_ms, args.cache)
            if len(sig) < p["min_bars"] or not ex:
                print(f"[{setup}] {inst}: data tidak cukup, dilewati", flush=True)
                continue

            tr, un, er = run_symbol(setup, inst, sig, ex, p)
            trades += tr
            unfinished += un
            errors += er
            used += 1
            print(f"[{setup}] {inst}: {len(tr)} trade", flush=True)

        meta = {"symbols": used, "days": args.days,
                "unfinished": unfinished, "errors": errors}
        st = summarize(trades, args.days)
        results[setup] = (st, meta)
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
    lines = [f"<b>📈 BACKTEST · {days} hari</b>", "━━━━━━━━━━━━━━━━━━"]
    for setup, (st, meta) in results.items():
        if st["n"] == 0:
            lines.append(f"<b>{setup}</b>: 0 trade")
            continue
        t = "n/a" if st["tstat"] is None else f"{st['tstat']:.1f}"
        lines.append(
            f"<b>{setup}</b>: {st['n']} trade · WR {st['wr']*100:.0f}% "
            f"(BEP {st['bep_net']*100:.0f}%)\n"
            f"{st['r_net']:+.1f}R net · {st['exp_net']:+.2f}R/trade · "
            f"DD {st['max_dd']:.1f}R · t={t}\n"
            f"{verdict(st)}"
        )
    lines.append("\nFee 0.05%/sisi sudah dihitung. Tanpa slippage.")
    return "\n".join(lines)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="ALPHAQUANT backtest")
    ap.add_argument("--setup", default="ALL", choices=["ALL"] + ALL_SETUPS)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--pairs", type=int, default=20,
                    help="top-volume pairs for the 4H setups")
    ap.add_argument("--symbols", default="",
                    help="comma separated override, e.g. ETH-USDT-SWAP,SOL-USDT-SWAP")
    ap.add_argument("--fee", type=float, default=0.0005, help="per side, 0.0005 = 0.05%%")
    ap.add_argument("--exec", default="auto",
                    help="execution candle bar: auto | same | 1m | 5m | 15m | 1H")
    ap.add_argument("--end", default="", help="end date YYYY-MM-DD (UTC), default now")
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
    t0 = time.time()
    results, trades = backtest(args)
    text = write_outputs(results, trades, args.out)

    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)
    print(f"Selesai dalam {time.time() - t0:.0f} detik. File: {args.out}/trades.csv, summary.txt")

    if args.telegram and bot.TELEGRAM:
        bot.tg(telegram_summary(results, args.days))


if __name__ == "__main__":
    sys.exit(main())
