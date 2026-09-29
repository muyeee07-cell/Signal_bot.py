"""
===============================================================
ALPHAQUANT V3
QUANT MOMENTUM–STRUCTURE SIGNAL ENGINE
===============================================================
Purpose:
- 1H quantitative crypto futures signal engine
- Signal only — NO live trading
- Market Structure + EMA Regime + Momentum + Volume
- Structural ATR Stop Loss
- Fixed RR 1:2
- Deterministic scoring
- Telegram notifications
- Persistent trade history
- 5m TP/SL monitoring
- Position sizing based on fixed account risk
Architecture:
1H MARKET DATA
      ↓
EMA 50 / EMA 200
      ↓
MARKET REGIME
      ↓
SWING STRUCTURE
      ↓
BOS
      ↓
MOMENTUM
      ↓
VOLUME
      ↓
PULLBACK
      ↓
CONFIRMATION
      ↓
QUALITY SCORE
      ↓
SL / TP
      ↓
POSITION SIZE
      ↓
TELEGRAM SIGNAL
      ↓
5M MONITOR
      ↓
TRADE LOG / STATS
IMPORTANT:
This is a research/forward-testing engine.
It does NOT guarantee profitability.
"""
from __future__ import annotations
import os
import json
import time
import math
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple
import requests
# ============================================================
# CONFIGURATION
# ============================================================
OKX_BASE_URL = "https://www.okx.com"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# ------------------------------------------------------------
# Market
# ------------------------------------------------------------
TIMEFRAME = "1H"
MONITOR_TF = "5m"
TOP_PAIRS = 30
MIN_VOLUME_USDT = 3_000_000
KLINE_LIMIT = 300
MONITOR_LIMIT = 300
# ------------------------------------------------------------
# Indicators
# ------------------------------------------------------------
EMA_FAST = 50
EMA_SLOW = 200
RSI_PERIOD = 14
ADX_PERIOD = 14
ATR_PERIOD = 14
VOLUME_PERIOD = 20
# Swing detection
SWING_LEFT = 2
SWING_RIGHT = 2
# ------------------------------------------------------------
# Structure
# ------------------------------------------------------------
BOS_ATR_BUFFER = 0.10
# ------------------------------------------------------------
# Risk
# ------------------------------------------------------------
ACCOUNT_EQUITY = float(os.getenv("ACCOUNT_EQUITY", "1000"))
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.004"))
RR = 2.0
SL_ATR_BUFFER = 0.20
MIN_SL_ATR = 0.30
MAX_SL_ATR = 2.50
# ------------------------------------------------------------
# Filters
# ------------------------------------------------------------
ADX_MIN = 20.0
ADX_STRONG = 25.0
VOLUME_HARD_MIN = 0.80
VOLUME_NORMAL = 1.00
VOLUME_STRONG = 1.30
MIN_SCORE = 75
# ------------------------------------------------------------
# Pullback
# ------------------------------------------------------------
PULLBACK_MIN = 0.30
PULLBACK_MAX = 0.70
MAX_DISTANCE_EMA50_ATR = 0.75
# ------------------------------------------------------------
# Confirmation
# ------------------------------------------------------------
MIN_BODY_RATIO = 0.50
# ------------------------------------------------------------
# Risk / Portfolio
# ------------------------------------------------------------
MAX_OPEN_POSITIONS = 12
COOLDOWN_HOURS = 3
# Prevent duplicate signal on same symbol/candle
SIGNAL_DEDUPE_HOURS = 24
# ------------------------------------------------------------
# Runtime
# ------------------------------------------------------------
SCAN_INTERVAL_SECONDS = 300
HISTORY_FILE = "v3_history.json"
REQUEST_TIMEOUT = 15
LOG_LEVEL = logging.INFO
# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("ALPHAQUANT_V3")
# ============================================================
# HTTP SESSION
# ============================================================
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ALPHAQUANT-V3/1.0"
})
# ============================================================
# TIME HELPERS
# ============================================================
def now_ms() -> int:
    return int(time.time() * 1000)
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(
        ms / 1000,
        tz=timezone.utc
    ).isoformat()
# ============================================================
# JSON HISTORY
# ============================================================
def load_history() -> Dict:
    if not os.path.exists(HISTORY_FILE):
        return {
            "closed": [],
            "open": []
        }
    try:
        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Invalid history format")
        data.setdefault("closed", [])
        data.setdefault("open", [])
        return data
    except Exception as e:
        logger.exception(
            "History load failed: %s",
            e
        )
        return {
            "closed": [],
            "open": []
        }
def save_history(history: Dict):
    temp_file = HISTORY_FILE + ".tmp"
    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            history,
            f,
            indent=2,
            ensure_ascii=False
        )
    os.replace(
        temp_file,
        HISTORY_FILE
    )
# ============================================================
# TELEGRAM
# ============================================================
def telegram_send(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "Telegram credentials missing."
        )
        return False
    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = SESSION.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(
            "Telegram error: %s",
            e
        )
        return False
# ============================================================
# OKX API
# ============================================================
def okx_get(
    endpoint: str,
    params: Optional[Dict] = None
) -> Optional[Dict]:
    url = OKX_BASE_URL + endpoint
    try:
        response = SESSION.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != "0":
            logger.warning(
                "OKX API error: %s",
                data
            )
            return None
        return data
    except Exception as e:
        logger.error(
            "OKX request failed: %s",
            e
        )
        return None
# ============================================================
# INSTRUMENTS
# ============================================================
def get_instruments() -> Dict[str, Dict]:
    data = okx_get(
        "/api/v5/public/instruments",
        {
            "instType": "SWAP"
        }
    )
    if not data:
        return {}
    result = {}
    for item in data.get("data", []):
        inst_id = item.get("instId", "")
        if not inst_id.endswith("-USDT-SWAP"):
            continue
        result[inst_id] = {
            "tickSz": float(item.get("tickSz", "0.00000001")),
            "lotSz": float(item.get("lotSz", "1")),
            "minSz": float(item.get("minSz", "1"))
        }
    return result
# ============================================================
# TICKER / UNIVERSE
# ============================================================
def get_top_pairs() -> List[str]:
    data = okx_get(
        "/api/v5/market/tickers",
        {
            "instType": "SWAP"
        }
    )
    if not data:
        return []
    candidates = []
    for item in data.get("data", []):
        inst_id = item.get("instId", "")
        if not inst_id.endswith("-USDT-SWAP"):
            continue
        try:
            volume = float(
                item.get("volCcy24h", "0")
            )
        except Exception:
            continue
        if volume < MIN_VOLUME_USDT:
            continue
        candidates.append(
            (
                inst_id,
                volume
            )
        )
    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )
    return [
        x[0]
        for x in candidates[:TOP_PAIRS]
    ]
def get_current_price(inst_id: str) -> Optional[float]:
    data = okx_get(
        "/api/v5/market/ticker",
        {
            "instId": inst_id
        }
    )
    if not data:
        return None
    try:
        return float(
            data["data"][0]["last"]
        )
    except Exception:
        return None
# ============================================================
# KLINES
# ============================================================
def get_klines(
    inst_id: str,
    bar: str = TIMEFRAME,
    limit: int = KLINE_LIMIT
) -> List[List]:
    data = okx_get(
        "/api/v5/market/candles",
        {
            "instId": inst_id,
            "bar": bar,
            "limit": str(limit)
        }
    )
    if not data:
        return []
    candles = []
    for row in data.get("data", []):
        try:
            candles.append([
                int(row[0]),      # timestamp
                float(row[1]),    # open
                float(row[2]),    # high
                float(row[3]),    # low
                float(row[4]),    # close
                float(row[5]),    # volume
                int(row[8])       # confirm
            ])
        except Exception:
            continue
    candles.sort(
        key=lambda x: x[0]
    )
    # ONLY CLOSED CANDLES
    candles = [
        c for c in candles
        if c[6] == 1
    ]
    return candles
# ============================================================
# INDICATORS
# ============================================================
def ema(
    values: List[float],
    period: int
) -> List[Optional[float]]:
    result = [None] * len(values)
    if len(values) < period:
        return result
    multiplier = 2 / (period + 1)
    initial = sum(
        values[:period]
    ) / period
    result[period - 1] = initial
    previous = initial
    for i in range(
        period,
        len(values)
    ):
        current = (
            values[i] * multiplier
            + previous * (1 - multiplier)
        )
        result[i] = current
        previous = current
    return result
def true_ranges(
    candles: List[List]
) -> List[float]:
    tr = []
    for i, candle in enumerate(candles):
        high = candle[2]
        low = candle[3]
        if i == 0:
            tr.append(
                high - low
            )
            continue
        previous_close = candles[i - 1][4]
        value = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )
        tr.append(value)
    return tr
def rma(
    values: List[float],
    period: int
) -> List[Optional[float]]:
    result = [None] * len(values)
    if len(values) < period:
        return result
    initial = sum(
        values[:period]
    ) / period
    result[period - 1] = initial
    previous = initial
    for i in range(
        period,
        len(values)
    ):
        previous = (
            (previous * (period - 1))
            + values[i]
        ) / period
        result[i] = previous
    return result
def calculate_atr(
    candles: List[List],
    period: int = ATR_PERIOD
) -> List[Optional[float]]:
    return rma(
        true_ranges(candles),
        period
    )
def calculate_rsi(
    candles: List[List],
    period: int = RSI_PERIOD
) -> List[Optional[float]]:
    closes = [
        c[4]
        for c in candles
    ]
    gains = [0.0]
    losses = [0.0]
    for i in range(
        1,
        len(closes)
    ):
        change = (
            closes[i] -
            closes[i - 1]
        )
        gains.append(
            max(change, 0)
        )
        losses.append(
            max(-change, 0)
        )
    avg_gain = rma(
        gains,
        period
    )
    avg_loss = rma(
        losses,
        period
    )
    result = [None] * len(candles)
    for i in range(
        len(candles)
    ):
        if (
            avg_gain[i] is None
            or avg_loss[i] is None
        ):
            continue
        if avg_loss[i] == 0:
            result[i] = 100.0
        else:
            rs = (
                avg_gain[i] /
                avg_loss[i]
            )
            result[i] = (
                100 -
                (100 / (1 + rs))
            )
    return result
def calculate_adx(
    candles: List[List],
    period: int = ADX_PERIOD
) -> Tuple[
    List[Optional[float]],
    List[Optional[float]],
    List[Optional[float]]
]:
    trs = true_ranges(candles)
    plus_dm = [0.0]
    minus_dm = [0.0]
    for i in range(
        1,
        len(candles)
    ):
        high = candles[i][2]
        low = candles[i][3]
        prev_high = candles[i - 1][2]
        prev_low = candles[i - 1][3]
        up_move = (
            high - prev_high
        )
        down_move = (
            prev_low - low
        )
        if (
            up_move > down_move
            and up_move > 0
        ):
            plus_dm.append(
                up_move
            )
        else:
            plus_dm.append(0.0)
        if (
            down_move > up_move
            and down_move > 0
        ):
            minus_dm.append(
                down_move
            )
        else:
            minus_dm.append(0.0)
    atr = rma(
        trs,
        period
    )
    plus_smoothed = rma(
        plus_dm,
        period
    )
    minus_smoothed = rma(
        minus_dm,
        period
    )
    plus_di = [None] * len(candles)
    minus_di = [None] * len(candles)
    dx = [None] * len(candles)
    for i in range(
        len(candles)
    ):
        if (
            atr[i] is None
            or plus_smoothed[i] is None
            or minus_smoothed[i] is None
        ):
            continue
        if atr[i] == 0:
            continue
        plus_di[i] = (
            100 *
            plus_smoothed[i] /
            atr[i]
        )
        minus_di[i] = (
            100 *
            minus_smoothed[i] /
            atr[i]
        )
        denominator = (
            plus_di[i] +
            minus_di[i]
        )
        if denominator != 0:
            dx[i] = (
                100 *
                abs(
                    plus_di[i] -
                    minus_di[i]
                ) /
                denominator
            )
    valid_dx = [
        x if x is not None else 0
        for x in dx
    ]
    adx = rma(
        valid_dx,
        period
    )
    return (
        adx,
        plus_di,
        minus_di
    )
# ============================================================
# SWING DETECTION
# ============================================================
def detect_swings(
    candles: List[List]
) -> Tuple[List[Dict], List[Dict]]:
    highs = []
    lows = []
    n = len(candles)
    for i in range(
        SWING_LEFT,
        n - SWING_RIGHT
    ):
        high = candles[i][2]
        low = candles[i][3]
        is_high = True
        is_low = True
        for j in range(
            1,
            SWING_LEFT + 1
        ):
            if high <= candles[i - j][2]:
                is_high = False
            if low >= candles[i - j][3]:
                is_low = False
        for j in range(
            1,
            SWING_RIGHT + 1
        ):
            if high <= candles[i + j][2]:
                is_high = False
            if low >= candles[i + j][3]:
                is_low = False
        if is_high:
            highs.append({
                "index": i,
                "time": candles[i][0],
                "price": high
            })
        if is_low:
            lows.append({
                "index": i,
                "time": candles[i][0],
                "price": low
            })
    return highs, lows
# ============================================================
# STRUCTURE
# ============================================================
def get_structure(
    highs: List[Dict],
    lows: List[Dict]
) -> Dict:
    structure = {
        "bullish": False,
        "bearish": False,
        "hh_hl": False,
        "lh_ll": False,
        "latest_high": None,
        "previous_high": None,
        "latest_low": None,
        "previous_low": None
    }
    if len(highs) >= 2:
        latest_high = highs[-1]
        previous_high = highs[-2]
        structure["latest_high"] = latest_high
        structure["previous_high"] = previous_high
    if len(lows) >= 2:
        latest_low = lows[-1]
        previous_low = lows[-2]
        structure["latest_low"] = latest_low
        structure["previous_low"] = previous_low
    if (
        structure["latest_high"]
        and structure["previous_high"]
        and structure["latest_low"]
        and structure["previous_low"]
    ):
        h1 = structure["latest_high"]["price"]
        h2 = structure["previous_high"]["price"]
        l1 = structure["latest_low"]["price"]
        l2 = structure["previous_low"]["price"]
        if h1 > h2 and l1 > l2:
            structure["hh_hl"] = True
            structure["bullish"] = True
        elif h1 < h2 and l1 < l2:
            structure["lh_ll"] = True
            structure["bearish"] = True
    return structure
# ============================================================
# BOS
# ============================================================
def detect_bos(
    candles: List[List],
    atr: List[Optional[float]],
    highs: List[Dict],
    lows: List[Dict]
) -> Dict:
    result = {
        "bullish": False,
        "bearish": False,
        "price": None,
        "time": None
    }
    if not candles:
        return result
    current_index = len(candles) - 1
    current_close = candles[-1][4]
    current_atr = atr[-1]
    if current_atr is None:
        return result
    buffer = (
        current_atr *
        BOS_ATR_BUFFER
    )
    # Most recent confirmed swing high
    if highs:
        latest_high = highs[-1]
        # Swing must occur before current candle
        if latest_high["index"] < current_index:
            if (
                current_close >
                latest_high["price"] + buffer
            ):
                result.update({
                    "bullish": True,
                    "price": current_close,
                    "time": candles[-1][0]
                })
                return result
    # Most recent confirmed swing low
    if lows:
        latest_low = lows[-1]
        if latest_low["index"] < current_index:
            if (
                current_close <
                latest_low["price"] - buffer
            ):
                result.update({
                    "bearish": True,
                    "price": current_close,
                    "time": candles[-1][0]
                })
    return result
# ============================================================
# EMA SLOPE
# ============================================================
def get_ema_slope(
    values: List[Optional[float]],
    lookback: int = 5
) -> Optional[float]:
    if len(values) <= lookback:
        return None
    current = values[-1]
    previous = values[-1 - lookback]
    if (
        current is None
        or previous is None
    ):
        return None
    return current - previous
# ============================================================
# REGIME
# ============================================================
def determine_regime(
    close: float,
    ema50: float,
    ema200: float,
    ema50_slope: float
) -> str:
    if (
        close > ema200
        and ema50 > ema200
        and ema50_slope > 0
    ):
        return "BULL"
    if (
        close < ema200
        and ema50 < ema200
        and ema50_slope < 0
    ):
        return "BEAR"
    return "NEUTRAL"
# ============================================================
# VOLUME
# ============================================================
def calculate_volume_ratio(
    candles: List[List]
) -> Optional[float]:
    if len(candles) < VOLUME_PERIOD:
        return None
    volumes = [
        c[5]
        for c in candles
    ]
    average = sum(
        volumes[-VOLUME_PERIOD:]
    ) / VOLUME_PERIOD
    if average <= 0:
        return None
    return (
        volumes[-1] /
        average
    )
# ============================================================
# PULLBACK
# ============================================================
def detect_pullback(
    candles: List[List],
    atr: List[Optional[float]],
    ema50: List[Optional[float]],
    bos: Dict,
    direction: str
) -> Dict:
    result = {
        "valid": False,
        "retracement": None,
        "distance_atr": None
    }
    if len(candles) < 10:
        return result
    if not bos.get("bullish") and not bos.get("bearish"):
        return result
    current_atr = atr[-1]
    current_ema50 = ema50[-1]
    if (
        current_atr is None
        or current_ema50 is None
    ):
        return result
    # --------------------------------------------------------
    # Find impulse before BOS
    # --------------------------------------------------------
    bos_index = len(candles) - 1
    lookback_start = max(
        0,
        bos_index - 30
    )
    window = candles[
        lookback_start:
        bos_index + 1
    ]
    if not window:
        return result
    if direction == "LONG":
        impulse_low = min(
            c[3]
            for c in window
        )
        impulse_high = candles[-1][2]
        impulse_range = (
            impulse_high -
            impulse_low
        )
        if impulse_range <= 0:
            return result
        current_low = candles[-1][3]
        retracement = (
            impulse_high -
            current_low
        ) / impulse_range
        distance = abs(
            candles[-1][4] -
            current_ema50
        )
        distance_atr = (
            distance /
            current_atr
        )
    else:
        impulse_high = max(
            c[2]
            for c in window
        )
        impulse_low = candles[-1][3]
        impulse_range = (
            impulse_high -
            impulse_low
        )
        if impulse_range <= 0:
            return result
        current_high = candles[-1][2]
        retracement = (
            current_high -
            impulse_low
        ) / impulse_range
        distance = abs(
            candles[-1][4] -
            current_ema50
        )
        distance_atr = (
            distance /
            current_atr
        )
    valid_retracement = (
        PULLBACK_MIN <=
        retracement <=
        PULLBACK_MAX
    )
    near_ema = (
        distance_atr <=
        MAX_DISTANCE_EMA50_ATR
    )
    result.update({
        "valid": (
            valid_retracement
            and near_ema
        ),
        "retracement": retracement,
        "distance_atr": distance_atr
    })
    return result
# ============================================================
# CONFIRMATION CANDLE
# ============================================================
def confirmation_candle(
    candles: List[List],
    direction: str
) -> bool:
    if len(candles) < 2:
        return False
    current = candles[-1]
    previous = candles[-2]
    open_price = current[1]
    high = current[2]
    low = current[3]
    close = current[4]
    candle_range = (
        high - low
    )
    if candle_range <= 0:
        return False
    body = abs(
        close - open_price
    )
    body_ratio = (
        body /
        candle_range
    )
    if body_ratio < MIN_BODY_RATIO:
        return False
    if direction == "LONG":
        return (
            close > open_price
            and close > previous[2]
        )
    return (
        close < open_price
        and close < previous[3]
    )
# ============================================================
# SCORE
# ============================================================
def calculate_score(
    direction: str,
    regime: str,
    structure: Dict,
    bos: Dict,
    rsi: float,
    adx: float,
    volume_ratio: float,
    pullback_valid: bool,
    confirmation: bool,
    ema_slope: float
) -> Tuple[int, Dict]:
    score = 0
    details = {}
    # --------------------------------------------------------
    # REGIME = 25
    # --------------------------------------------------------
    if direction == "LONG":
        if regime == "BULL":
            score += 10
            details["EMA200"] = 10
            details["EMA200"] = 10
        if structure.get("hh_hl"):
            score += 15
            details["HH_HL"] = 15
    else:
        if regime == "BEAR":
            score += 10
            details["EMA200"] = 10
        if structure.get("lh_ll"):
            score += 15
            details["LH_LL"] = 15
    # --------------------------------------------------------
    # EMA alignment extra component
    # --------------------------------------------------------
    # We need the full 25-point regime block:
    # 10 = price vs EMA200
    # 10 = EMA50 alignment
    # 5  = slope
    #
    # Structure is separately scored below.
    # Rebuild score cleanly below.
    score = 0
    details = {}
    # --------------------------------------------------------
    # REGIME 25
    # --------------------------------------------------------
    if direction == "LONG":
        if regime == "BULL":
            score += 10
            details["Price>EMA200"] = 10
        # EMA50 alignment
        if regime == "BULL":
            score += 10
            details["EMA50>EMA200"] = 10
        if ema_slope > 0:
            score += 5
            details["EMA50Slope"] = 5
    else:
        if regime == "BEAR":
            score += 10
            details["Price<EMA200"] = 10
        if regime == "BEAR":
            score += 10
            details["EMA50<EMA200"] = 10
        if ema_slope < 0:
            score += 5
            details["EMA50Slope"] = 5
    # --------------------------------------------------------
    # STRUCTURE 25
    # --------------------------------------------------------
    if direction == "LONG":
        if structure.get("hh_hl"):
            score += 15
            details["HH_HL"] = 15
        if bos.get("bullish"):
            score += 10
            details["BullishBOS"] = 10
    else:
        if structure.get("lh_ll"):
            score += 15
            details["LH_LL"] = 15
        if bos.get("bearish"):
            score += 10
            details["BearishBOS"] = 10
    # --------------------------------------------------------
    # MOMENTUM 20
    # --------------------------------------------------------
    if direction == "LONG":
        if 60 <= rsi < 70:
            score += 10
            details["RSI"] = 10
        elif 50 < rsi < 60:
            score += 5
            details["RSI"] = 5
    else:
        if 30 < rsi <= 40:
            score += 10
            details["RSI"] = 10
        elif 40 < rsi < 50:
            score += 5
            details["RSI"] = 5
    if adx >= ADX_STRONG:
        score += 10
        details["ADX"] = 10
    elif adx >= ADX_MIN:
        score += 5
        details["ADX"] = 5
    # --------------------------------------------------------
    # VOLUME 10
    # --------------------------------------------------------
    if volume_ratio >= VOLUME_STRONG:
        score += 10
        details["Volume"] = 10
    elif volume_ratio >= VOLUME_NORMAL:
        score += 5
        details["Volume"] = 5
    # --------------------------------------------------------
    # ENTRY QUALITY 20
    # --------------------------------------------------------
    if pullback_valid:
        score += 10
        details["Pullback"] = 10
    if confirmation:
        score += 10
        details["Confirmation"] = 10
    return score, details
# ============================================================
# PRICE ROUNDING
# ============================================================
def decimals_from_step(
    step: float
) -> int:
    if step <= 0:
        return 8
    text = f"{step:.12f}".rstrip("0")
    if "." not in text:
        return 0
    return len(
        text.split(".")[1]
    )
def round_to_tick(
    value: float,
    tick: float
) -> float:
    if tick <= 0:
        return value
    decimals = decimals_from_step(tick)
    return round(
        round(value / tick) * tick,
        decimals
    )
# ============================================================
# POSITION SIZE
# ============================================================
def calculate_position_size(
    entry: float,
    stop: float
) -> Dict:
    risk_distance = abs(
        entry - stop
    )
    if risk_distance <= 0:
        return {
            "risk_usdt": 0,
            "position_size": 0,
            "notional": 0
        }
    risk_usdt = (
        ACCOUNT_EQUITY *
        RISK_PER_TRADE
    )
    position_size = (
        risk_usdt /
        risk_distance
    )
    notional = (
        position_size *
        entry
    )
    return {
        "risk_usdt": risk_usdt,
        "position_size": position_size,
        "notional": notional
    }
# ============================================================
# SIGNAL CREATION
# ============================================================
def build_signal(
    inst_id: str,
    candles: List[List],
    instruments: Dict[str, Dict]
) -> Optional[Dict]:
    minimum = max(
        EMA_SLOW + 20,
        230
    )
    if len(candles) < minimum:
        logger.warning(
            "%s insufficient candles: %s",
            inst_id,
            len(candles)
        )
        return None
    closes = [
        c[4]
        for c in candles
    ]
    ema50 = ema(
        closes,
        EMA_FAST
    )
    ema200 = ema(
        closes,
        EMA_SLOW
    )
    atr = calculate_atr(
        candles,
        ATR_PERIOD
    )
    rsi = calculate_rsi(
        candles,
        RSI_PERIOD
    )
    adx, plus_di, minus_di = calculate_adx(
        candles,
        ADX_PERIOD
    )
    volume_ratio = calculate_volume_ratio(
        candles
    )
    if (
        ema50[-1] is None
        or ema200[-1] is None
        or atr[-1] is None
        or rsi[-1] is None
        or adx[-1] is None
        or volume_ratio is None
    ):
        return None
    close = candles[-1][4]
    current_atr = atr[-1]
    slope = get_ema_slope(
        ema50,
        5
    )
    if slope is None:
        return None
    regime = determine_regime(
        close,
        ema50[-1],
        ema200[-1],
        slope
    )
    if regime == "NEUTRAL":
        return None
    # --------------------------------------------------------
    # Swings / Structure
    # --------------------------------------------------------
    highs, lows = detect_swings(
        candles
    )
    structure = get_structure(
        highs,
        lows
    )
    # --------------------------------------------------------
    # BOS
    # --------------------------------------------------------
    bos = detect_bos(
        candles,
        atr,
        highs,
        lows
    )
    # --------------------------------------------------------
    # Direction
    # --------------------------------------------------------
    if regime == "BULL":
        direction = "LONG"
        if not (
            structure["hh_hl"]
            or bos["bullish"]
        ):
            return None
    elif regime == "BEAR":
        direction = "SHORT"
        if not (
            structure["lh_ll"]
            or bos["bearish"]
        ):
            return None
    else:
        return None
    # --------------------------------------------------------
    # Momentum
    # --------------------------------------------------------
    current_rsi = rsi[-1]
    current_adx = adx[-1]
    if current_adx < ADX_MIN:
        return None
    if direction == "LONG":
        if not (
            current_rsi > 50
            and current_rsi < 70
        ):
            return None
    else:
        if not (
            current_rsi < 50
            and current_rsi > 30
        ):
            return None
    # --------------------------------------------------------
    # Volume hard filter
    # --------------------------------------------------------
    if volume_ratio < VOLUME_HARD_MIN:
        return None
    # --------------------------------------------------------
    # Pullback
    # --------------------------------------------------------
    pullback = detect_pullback(
        candles,
        atr,
        ema50,
        bos,
        direction
    )
    if not pullback["valid"]:
        return None
    # --------------------------------------------------------
    # Confirmation
    # --------------------------------------------------------
    confirmation = confirmation_candle(
        candles,
        direction
    )
    if not confirmation:
        return None
    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------
    score, score_details = calculate_score(
        direction=direction,
        regime=regime,
        structure=structure,
        bos=bos,
        rsi=current_rsi,
        adx=current_adx,
        volume_ratio=volume_ratio,
        pullback_valid=pullback["valid"],
        confirmation=confirmation,
        ema_slope=slope
    )
    if score < MIN_SCORE:
        return None
    # --------------------------------------------------------
    # Entry
    # --------------------------------------------------------
    entry = close
    # --------------------------------------------------------
    # Structural SL
    # --------------------------------------------------------
    if direction == "LONG":
        if not structure["latest_low"]:
            return None
        swing_low = (
            structure["latest_low"]["price"]
        )
        stop = (
            swing_low -
            (SL_ATR_BUFFER * current_atr)
        )
        risk_distance = (
            entry - stop
        )
        if risk_distance <= 0:
            return None
        tp = (
            entry +
            risk_distance * RR
        )
    else:
        if not structure["latest_high"]:
            return None
        swing_high = (
            structure["latest_high"]["price"]
        )
        stop = (
            swing_high +
            (SL_ATR_BUFFER * current_atr)
        )
        risk_distance = (
            stop - entry
        )
        if risk_distance <= 0:
            return None
        tp = (
            entry -
            risk_distance * RR
        )
    # --------------------------------------------------------
    # SL distance validation
    # --------------------------------------------------------
    sl_atr = (
        risk_distance /
        current_atr
    )
    if sl_atr < MIN_SL_ATR:
        return None
    if sl_atr > MAX_SL_ATR:
        return None
    # --------------------------------------------------------
    # Tick rounding
    # --------------------------------------------------------
    instrument = instruments.get(
        inst_id,
        {}
    )
    tick = instrument.get(
        "tickSz",
        0.00000001
    )
    entry = round_to_tick(
        entry,
        tick
    )
    stop = round_to_tick(
        stop,
        tick
    )
    tp = round_to_tick(
        tp,
        tick
    )
    # Recalculate exact risk after rounding
    risk_distance = abs(
        entry - stop
    )
    if risk_distance <= 0:
        return None
    # --------------------------------------------------------
    # Position sizing
    # --------------------------------------------------------
    sizing = calculate_position_size(
        entry,
        stop
    )
    if sizing["position_size"] <= 0:
        return None
    # --------------------------------------------------------
    # Signal ID
    # --------------------------------------------------------
    candle_time = candles[-1][0]
    signal_id = (
        f"{inst_id}|"
        f"{direction}|"
        f"{candle_time}"
    )
    return {
        "signal_id": signal_id,
        "symbol": inst_id,
        "direction": direction,
        "timeframe": TIMEFRAME,
        "signal_candle_time": candle_time,
        "signal_candle_iso": ms_to_iso(
            candle_time
        ),
        "created_at": now_iso(),
        "entry": entry,
        "sl": stop,
        "tp": tp,
        "rr": RR,
        "atr": current_atr,
        "sl_atr": sl_atr,
        "ema50": ema50[-1],
        "ema200": ema200[-1],
        "rsi": current_rsi,
        "adx": current_adx,
        "plus_di": plus_di[-1],
        "minus_di": minus_di[-1],
        "volume_ratio": volume_ratio,
        "regime": regime,
        "structure": (
            "HH-HL"
            if direction == "LONG"
            else "LH-LL"
        ),
        "bos": (
            "BULLISH"
            if bos["bullish"]
            else "BEARISH"
            if bos["bearish"]
            else "NONE"
        ),
        "pullback": pullback["retracement"],
        "score": score,
        "score_details": score_details,
        "risk_usdt": sizing["risk_usdt"],
        "position_size": sizing["position_size"],
        "notional": sizing["notional"],
        "status": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "result_r": None,
        "result": None
    }
# ============================================================
# DUPLICATE / COOLDOWN
# ============================================================
def has_duplicate_signal(
    history: Dict,
    signal: Dict
) -> bool:
    signal_id = signal["signal_id"]
    for trade in history["open"]:
        if trade.get("signal_id") == signal_id:
            return True
    for trade in history["closed"]:
        if trade.get("signal_id") == signal_id:
            return True
    # Symbol cooldown
    cutoff = (
        time.time() -
        COOLDOWN_HOURS * 3600
    )
    for trade in history["closed"]:
        if trade.get("symbol") != signal["symbol"]:
            continue
        created = trade.get(
            "exit_time"
        )
        if not created:
            continue
        try:
            dt = datetime.fromisoformat(
                created
            )
            if dt.timestamp() > cutoff:
                return True
        except Exception:
            continue
    return False
# ============================================================
# OPEN POSITION COUNT
# ============================================================
def open_position_count(
    history: Dict
) -> int:
    return len(
        history["open"]
    )
# ============================================================
# SIGNAL TELEGRAM
# ============================================================
def format_signal(
    signal: Dict
) -> str:
    side = (
        "🟢 LONG"
        if signal["direction"] == "LONG"
        else "🔴 SHORT"
    )
    details = signal["score_details"]
    score_lines = []
    for name, value in details.items():
        score_lines.append(
            f"• {name}: +{value}"
        )
    score_text = "\n".join(
        score_lines
    )
    return f"""
<b>🚨 ALPHAQUANT V3 SIGNAL</b>
━━━━━━━━━━━━━━━━━━
<b>{signal["symbol"]}</b>
{side}
🕐 Timeframe: 1H
📊 Score: <b>{signal["score"]}/100</b>
🌐 Regime: {signal["regime"]}
🏗 Structure: {signal["structure"]}
💥 BOS: {signal["bos"]}
━━━━━━━━━━━━━━━━━━
<b>ENTRY</b>
Entry: <code>{signal["entry"]}</code>
SL: <code>{signal["sl"]}</code>
TP: <code>{signal["tp"]}</code>
RR: <b>1:{signal["rr"]:.1f}</b>
SL Distance: {signal["sl_atr"]:.2f} ATR
━━━━━━━━━━━━━━━━━━
<b>MOMENTUM</b>
RSI: {signal["rsi"]:.2f}
ADX: {signal["adx"]:.2f}
Volume Ratio: {signal["volume_ratio"]:.2f}x
EMA50: {signal["ema50"]:.8f}
EMA200: {signal["ema200"]:.8f}
━━━━━━━━━━━━━━━━━━
<b>RISK</b>
Risk: {signal["risk_usdt"]:.2f} USDT
Position Size: {signal["position_size"]:.8f}
Notional: {signal["notional"]:.2f} USDT
━━━━━━━━━━━━━━━━━━
<b>SCORE BREAKDOWN</b>
{score_text}
━━━━━━━━━━━━━━━━━━
⚠️ Signal only
❌ No automatic execution
Signal candle:
{signal["signal_candle_iso"]}
""".strip()
# ============================================================
# MONITOR OPEN TRADE
# ============================================================
def monitor_trade(
    trade: Dict
) -> Optional[Dict]:
    candles = get_klines(
        trade["symbol"],
        MONITOR_TF,
        MONITOR_LIMIT
    )
    if not candles:
        return None
    entry = trade["entry"]
    sl = trade["sl"]
    tp = trade["tp"]
    direction = trade["direction"]
    # --------------------------------------------------------
    # IMPORTANT:
    # We need to monitor candles after signal candle.
    # --------------------------------------------------------
    signal_time = trade.get(
        "signal_candle_time",
        0
    )
    relevant = [
        c for c in candles
        if c[0] >= signal_time
    ]
    if not relevant:
        return None
    for candle in relevant:
        high = candle[2]
        low = candle[3]
        hit_sl = False
        hit_tp = False
        if direction == "LONG":
            if low <= sl:
                hit_sl = True
            if high >= tp:
                hit_tp = True
        else:
            if high >= sl:
                hit_sl = True
            if low <= tp:
                hit_tp = True
        # ----------------------------------------------------
        # Same candle TP + SL:
        # Conservative assumption = SL first.
        # ----------------------------------------------------
        if hit_sl and hit_tp:
            result_r = -1.0
            return close_trade(
                trade,
                sl,
                candle[0],
                result_r,
                "LOSS"
            )
        if hit_tp:
            result_r = RR
            return close_trade(
                trade,
                tp,
                candle[0],
                result_r,
                "WIN"
            )
        if hit_sl:
            result_r = -1.0
            return close_trade(
                trade,
                sl,
                candle[0],
                result_r,
                "LOSS"
            )
    return None
# ============================================================
# CLOSE TRADE
# ============================================================
def close_trade(
    trade: Dict,
    exit_price: float,
    exit_time_ms: int,
    result_r: float,
    result: str
) -> Dict:
    closed = dict(trade)
    closed["status"] = "CLOSED"
    closed["exit_price"] = exit_price
    closed["exit_time"] = ms_to_iso(
        exit_time_ms
    )
    closed["result_r"] = result_r
    closed["result"] = result
    return closed
# ============================================================
# CHECK ALL OPEN TRADES
# ============================================================
def check_open_trades(
    history: Dict
):
    if not history["open"]:
        return
    remaining = []
    closed_now = []
    for trade in history["open"]:
        try:
            result = monitor_trade(
                trade
            )
            if result is None:
                remaining.append(
                    trade
                )
                continue
            closed_now.append(
                result
            )
        except Exception as e:
            logger.exception(
                "Monitor error %s: %s",
                trade["symbol"],
                e
            )
            remaining.append(
                trade
            )
    history["open"] = remaining
    history["closed"].extend(
        closed_now
    )
    if closed_now:
        save_history(
            history
        )
    for trade in closed_now:
        emoji = (
            "✅"
            if trade["result"] == "WIN"
            else "❌"
        )
        telegram_send(
            f"""
<b>{emoji} TRADE CLOSED</b>
━━━━━━━━━━━━━━━━━━
<b>{trade["symbol"]}</b>
{trade["direction"]}
Entry: <code>{trade["entry"]}</code>
Exit: <code>{trade["exit_price"]}</code>
Result:
<b>{trade["result_r"]:+.2f}R</b>
Score:
{trade["score"]}/100
Regime:
{trade["regime"]}
Closed:
{trade["exit_time"]}
""".strip()
        )
# ============================================================
# RUNNING POSITIONS REPORT
# ============================================================
def calculate_floating_r(
    trade: Dict,
    current_price: float
) -> float:
    entry = trade["entry"]
    sl = trade["sl"]
    risk = abs(
        entry - sl
    )
    if risk <= 0:
        return 0.0
    if trade["direction"] == "LONG":
        return (
            current_price -
            entry
        ) / risk
    return (
        entry -
        current_price
    ) / risk
def send_running_report(
    history: Dict
):
    if not history["open"]:
        telegram_send(
            """
<b>📡 RUNNING POSITIONS</b>
━━━━━━━━━━━━━━━━━━
No open positions.
System is waiting for
the next qualified setup.
""".strip()
        )
        return
    lines = []
    floating_values = []
    profitable = 0
    negative = 0
    for trade in history["open"]:
        price = get_current_price(
            trade["symbol"]
        )
        if price is None:
            continue
        floating_r = calculate_floating_r(
            trade,
            price
        )
        floating_values.append(
            floating_r
        )
        if floating_r > 0:
            profitable += 1
        elif floating_r < 0:
            negative += 1
        emoji = (
            "🟢"
            if floating_r > 0
            else "🔴"
            if floating_r < 0
            else "⚪"
        )
        lines.append(
            f"{emoji} "
            f"<b>{trade['symbol']}</b> · "
            f"{trade['direction']}\n"
            f"Entry <code>{trade['entry']}</code>\n"
            f"Now   <code>{price}</code>\n"
            f"SL    <code>{trade['sl']}</code>\n"
            f"TP    <code>{trade['tp']}</code>\n"
            f"Float <b>{floating_r:+.2f}R</b>\n"
        )
    if not floating_values:
        return
    total_float = sum(
        floating_values
    )
    average_float = (
        total_float /
        len(floating_values)
    )
    best = max(
        floating_values
    )
    worst = min(
        floating_values
    )
    theoretical_tp = (
        len(history["open"]) *
        RR
    )
    sl_exposure = -len(
        history["open"]
    )
    report = f"""
<b>📡 RUNNING POSITIONS</b>
━━━━━━━━━━━━━━━━━━
<b>{len(history["open"])} OPEN POSITIONS</b>
{chr(10).join(lines)}
━━━━━━━━━━━━━━━━━━
<b>OPEN SUMMARY</b>
Open Positions : {len(history["open"])}
Profitable     : {profitable}
Negative       : {negative}
Floating R     : <b>{total_float:+.2f}R</b>
Average Float  : {average_float:+.2f}R
Best           : +{best:.2f}R
Worst          : {worst:+.2f}R
━━━━━━━━━━━━━━━━━━
Target RR      : 1:{RR:.1f}
TP Potential   : +{theoretical_tp:.2f}R
SL Exposure    : {sl_exposure:.2f}R
⚠️ Floating R is unrealized.
TP Potential is theoretical.
"""
    telegram_send(
        report.strip()
    )
# ============================================================
# PERFORMANCE
# ============================================================
def calculate_statistics(
    history: Dict
) -> Dict:
    trades = history["closed"]
    if not trades:
        return {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "wr": 0,
            "total_r": 0,
            "avg_r": 0,
            "profit_factor": 0,
            "max_drawdown": 0
        }
    wins = [
        t["result_r"]
        for t in trades
        if t["result"] == "WIN"
    ]
    losses = [
        t["result_r"]
        for t in trades
        if t["result"] == "LOSS"
    ]
    total_r = sum(
        t["result_r"]
        for t in trades
    )
    gross_profit = sum(
        max(t["result_r"], 0)
        for t in trades
    )
    gross_loss = abs(
        sum(
            min(t["result_r"], 0)
            for t in trades
        )
    )
    if gross_loss > 0:
        profit_factor = (
            gross_profit /
            gross_loss
        )
    else:
        profit_factor = float("inf")
    # --------------------------------------------------------
    # Max drawdown
    # --------------------------------------------------------
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        equity += trade["result_r"]
        peak = max(
            peak,
            equity
        )
        drawdown = (
            peak -
            equity
        )
        max_drawdown = max(
            max_drawdown,
            drawdown
        )
    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "wr": (
            len(wins) /
            len(trades) *
            100
        ),
        "total_r": total_r,
        "avg_r": (
            total_r /
            len(trades)
        ),
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown
    }
def send_statistics(
    history: Dict
):
    stats = calculate_statistics(
        history
    )
    if stats["total"] == 0:
        return
    pf = stats["profit_factor"]
    if math.isinf(pf):
        pf_text = "∞"
    else:
        pf_text = f"{pf:.2f}"
    telegram_send(
        f"""
<b>📊 V3 PERFORMANCE</b>
━━━━━━━━━━━━━━━━━━
Trades        : {stats["total"]}
Wins          : {stats["wins"]}
Losses        : {stats["losses"]}
Win Rate      : <b>{stats["wr"]:.2f}%</b>
Total R       : <b>{stats["total_r"]:+.2f}R</b>
Avg R/Trade   : {stats["avg_r"]:+.3f}R
Profit Factor : {pf_text}
Max Drawdown  : -{stats["max_drawdown"]:.2f}R
RR Target     : 1:{RR:.1f}
━━━━━━━━━━━━━━━━━━
BEP WR @ 1:2:
<b>33.33%</b>
⚠️ Before fees,
slippage and funding.
""".strip()
    )
# ============================================================
# SCAN ONE SYMBOL
# ============================================================
def scan_symbol(
    inst_id: str,
    instruments: Dict[str, Dict],
    history: Dict
) -> Optional[Dict]:
    candles = get_klines(
        inst_id,
        TIMEFRAME,
        KLINE_LIMIT
    )
    if not candles:
        return None
    signal = build_signal(
        inst_id,
        candles,
        instruments
    )
    if signal is None:
        return None
    if has_duplicate_signal(
        history,
        signal
    ):
        logger.info(
            "Duplicate/cooldown: %s",
            inst_id
        )
        return None
    return signal
# ============================================================
# MAIN SCANNER
# ============================================================
def scan_market(
    history: Dict
):
    current_open = (
        len(history["open"])
    )
    if current_open >= MAX_OPEN_POSITIONS:
        logger.info(
            "Maximum open positions reached: %s",
            current_open
        )
        return
    pairs = get_top_pairs()
    if not pairs:
        logger.warning(
            "No pairs found."
        )
        return
    instruments = get_instruments()
    logger.info(
        "Scanning %s pairs...",
        len(pairs)
    )
    signals_created = 0
    for inst_id in pairs:
        if (
            len(history["open"])
            >= MAX_OPEN_POSITIONS
        ):
            break
        try:
            signal = scan_symbol(
                inst_id,
                instruments,
                history
            )
            if signal is None:
                continue
            history["open"].append(
                signal
            )
            save_history(
                history
            )
            telegram_send(
                format_signal(
                    signal
                )
            )
            signals_created += 1
            logger.info(
                "NEW SIGNAL: %s %s score=%s",
                signal["symbol"],
                signal["direction"],
                signal["score"]
            )
            # Small delay to avoid
            # hammering API
            time.sleep(0.5)
        except Exception as e:
            logger.exception(
                "Scan error %s: %s",
                inst_id,
                e
            )
    logger.info(
        "Scan complete. New signals: %s",
        signals_created
    )
# ============================================================
# SYSTEM STATUS
# ============================================================
def send_system_status(
    history: Dict
):
    stats = calculate_statistics(
        history
    )
    telegram_send(
        f"""
<b>🧠 ALPHAQUANT V3 STATUS</b>
━━━━━━━━━━━━━━━━━━
Mode:
<b>QUANT MOMENTUM–STRUCTURE</b>
Timeframe:
1H
Open Positions:
{len(history["open"])}
Closed Trades:
{stats["total"]}
Minimum Score:
{MIN_SCORE}/100
RR:
1:{RR:.1f}
Risk/Trade:
{RISK_PER_TRADE * 100:.2f}%
Regime:
EMA50 / EMA200
Structure:
HH-HL / LH-LL / BOS
Momentum:
RSI + ADX
Activity:
Volume Ratio
Risk:
ATR Structural SL
━━━━━━━━━━━━━━━━━━
System is running.
""".strip()
    )
# ============================================================
# MAIN LOOP
# ============================================================
def main():
    logger.info(
        "=================================================="
    )
    logger.info(
        "ALPHAQUANT V3 STARTING"
    )
    logger.info(
        "=================================================="
    )
    history = load_history()
    logger.info(
        "Open trades: %s",
        len(history["open"])
    )
    logger.info(
        "Closed trades: %s",
        len(history["closed"])
    )
    telegram_send(
        """
<b>🟢 ALPHAQUANT V3 ONLINE</b>
Quant Momentum–Structure
Signal Engine
1H
EMA50 / EMA200
Market Structure
BOS
RSI
ADX
ATR
Volume
RR 1:2
Signal-only mode
Waiting for A+ setups...
""".strip()
    )
    while True:
        cycle_start = time.time()
        try:
            logger.info(
                "Starting engine cycle..."
            )
            # ------------------------------------------------
            # 1. Monitor existing positions
            # ------------------------------------------------
            check_open_trades(
                history
            )
            # ------------------------------------------------
            # 2. Running report
            # ------------------------------------------------
            send_running_report(
                history
            )
            # ------------------------------------------------
            # 3. Performance
            # ------------------------------------------------
            send_statistics(
                history
            )
            # ------------------------------------------------
            # 4. Scan new setups
            # ------------------------------------------------
            scan_market(
                history
            )
            # ------------------------------------------------
            # 5. Save
            # ------------------------------------------------
            save_history(
                history
            )
        except KeyboardInterrupt:
            logger.info(
                "Engine stopped manually."
            )
            break
        except Exception as e:
            logger.exception(
                "MAIN LOOP ERROR: %s",
                e
            )
            telegram_send(
                f"""
<b>⚠️ V3 ENGINE ERROR</b>
<code>{str(e)[:500]}</code>
Engine will continue.
""".strip()
            )
        elapsed = (
            time.time() -
            cycle_start
        )
        sleep_time = max(
            10,
            SCAN_INTERVAL_SECONDS -
            elapsed
        )
        logger.info(
            "Cycle finished. Sleeping %.1f seconds.",
            sleep_time
        )
        time.sleep(
            sleep_time
        )
# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    main()


