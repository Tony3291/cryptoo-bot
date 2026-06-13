"""
Crypto Trading Intelligence Bot - Production
Real-time Spot + Futures analysis with multi-timeframe ranges,
trend detection, signal generation, news sentiment, and market context.
"""

import os
import logging
import asyncio
import aiohttp
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

# ─── CONFIG ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8650706334:AAHJQrBxkw-zOw286H1v-PvtDtUWsM9KFfY")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY",   "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")
ALLOWED_CHAT   = int(os.environ.get("ALLOWED_CHAT", "5214099942"))

OKX_BASE = "https://www.okx.com"
CRYPTOCOMPARE_NEWS = "https://min-api.cryptocompare.com/data/v2/news/"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# OKX kline "bar" codes
INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "4h": "4H", "1d": "1D",
}

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ─── HTTP HELPER ─────────────────────────────────────────────────────────────

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


async def fetch(session, url, params=None, headers=None, json_body=None, method="GET", timeout=12):
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    try:
        if method == "POST":
            async with session.post(url, headers=merged_headers, json=json_body,
                                     timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 200:
                    return await r.json()
                else:
                    text = await r.text()
                    logger.warning(f"POST {url} status {r.status}: {text[:200]}")
        else:
            async with session.get(url, params=params, headers=merged_headers,
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status == 200:
                    return await r.json()
                else:
                    logger.warning(f"GET {url} status {r.status}")
    except Exception as e:
        logger.warning(f"Fetch error {url}: {e}")
    return None


# ─── INDICATORS ──────────────────────────────────────────────────────────────

def ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    val = sum(closes[:period]) / period
    for p in closes[period:]:
        val = p * k + val * (1 - k)
    return val


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0:
        return 100.0
    return round(100 - (100 / (1 + ag / al)), 2)


def atr_calc(klines, period=14):
    if not klines or len(klines) < period + 1:
        return 0.0
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    window = trs[-period:]
    return sum(window) / len(window)


def compute_indicators(klines):
    if not klines or len(klines) < 21:
        return {}
    closes = [float(k[4]) for k in klines]
    cur = closes[-1]
    return {
        "current": cur,
        "rsi": rsi(closes, 14),
        "ema9": ema(closes, 9),
        "ema21": ema(closes, 21),
        "ema50": ema(closes, 50),
        "atr": atr_calc(klines, 14),
    }


def detect_trend(klines):
    """Returns (trend_label, rsi_value) using EMA structure + RSI."""
    ind = compute_indicators(klines)
    if not ind or ind.get("ema21") is None:
        return "SIDEWAYS", ind.get("rsi")

    cur = ind["current"]
    e9 = ind["ema9"]
    e21 = ind["ema21"]
    e50 = ind.get("ema50")
    r = ind.get("rsi") or 50

    if e50:
        if cur > e9 > e21 > e50 and r > 50:
            return "UPTREND", r
        if cur < e9 < e21 < e50 and r < 50:
            return "DOWNTREND", r
    else:
        if cur > e9 > e21 and r > 50:
            return "UPTREND", r
        if cur < e9 < e21 and r < 50:
            return "DOWNTREND", r

    return "SIDEWAYS", r


# ─── MULTI-TIMEFRAME RANGES ──────────────────────────────────────────────────

# label : (interval, number of candles)
TIMEFRAMES = {
    "1H":  ("1m",  60),
    "2H":  ("5m",  24),
    "4H":  ("15m", 16),
    "12H": ("1h",  12),
    "1D":  ("1h",  24),
    "3D":  ("4h",  18),
    "1W":  ("1d",  7),
    "1M":  ("1d",  30),
}


async def fetch_klines(session, instId, interval_label, limit):
    """Fetch candles from OKX. Returns list of [ts, open, high, low, close, vol, ...]
    in ascending (oldest-first) order, or None."""
    bar = INTERVAL_MAP.get(interval_label)
    if not bar:
        return None
    data = await fetch(session, f"{OKX_BASE}/api/v5/market/candles",
                        {"instId": instId, "bar": bar, "limit": limit})
    if not data or data.get("code") != "0":
        return None
    rows = data.get("data", [])
    if not rows:
        return None
    return list(reversed(rows))  # OKX returns newest-first; flip to oldest-first


def calc_range(klines):
    if not klines or len(klines) < 2:
        return None
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    open_first = float(klines[0][1])
    close_last = float(klines[-1][4])
    high = max(highs)
    low = min(lows)
    move_pct = ((close_last - open_first) / open_first) * 100 if open_first else 0
    range_pct = ((high - low) / low) * 100 if low else 0
    return {"high": high, "low": low, "move_pct": move_pct, "range_pct": range_pct}


async def get_multi_timeframe_ranges(session, instId):
    tasks = {
        label: fetch_klines(session, instId, interval, limit)
        for label, (interval, limit) in TIMEFRAMES.items()
    }
    results = await asyncio.gather(*tasks.values())
    ranges = {}
    for label, klines in zip(tasks.keys(), results):
        if klines and len(klines) >= 2:
            ranges[label] = calc_range(klines)
    return ranges


# ─── OKX DATA FETCHERS ────────────────────────────────────────────────────────

async def get_ticker(session, instId):
    """Returns raw OKX ticker dict or None."""
    data = await fetch(session, f"{OKX_BASE}/api/v5/market/ticker", {"instId": instId})
    if not data or data.get("code") != "0":
        return None
    lst = data.get("data", [])
    return lst[0] if lst else None


def normalize_ticker(t):
    """Convert an OKX ticker dict to a common shape used by the report builders."""
    if not t:
        return None
    try:
        last = float(t.get("last", 0))
        open24h = float(t.get("open24h", 0))
        pct = ((last - open24h) / open24h * 100) if open24h else 0
    except (TypeError, ValueError):
        pct = 0
    return {
        "lastPrice": t.get("last"),
        "priceChangePercent": str(pct),
        "highPrice": t.get("high24h"),
        "lowPrice": t.get("low24h"),
        "quoteVolume": t.get("volCcy24h"),
    }


async def get_market_snapshot(session, coin):
    """Fetch tickers, futures extras and trend klines in parallel."""
    spot_inst = f"{coin}-USDT"
    swap_inst = f"{coin}-USDT-SWAP"

    spot_raw, fut_raw = await asyncio.gather(
        get_ticker(session, spot_inst),
        get_ticker(session, swap_inst),
    )

    on_fut = fut_raw is not None
    primary_inst = swap_inst if on_fut else spot_inst

    extra_tasks = [
        fetch_klines(session, primary_inst, "4h", 100),  # 0 4H klines
        fetch_klines(session, primary_inst, "1h", 100),  # 1 1H klines
    ]
    if on_fut:
        extra_tasks.append(fetch(session, f"{OKX_BASE}/api/v5/public/funding-rate",
                                  {"instId": swap_inst}))                       # 2 funding
        extra_tasks.append(fetch(session, f"{OKX_BASE}/api/v5/public/open-interest",
                                  {"instId": swap_inst}))                       # 3 open interest
        extra_tasks.append(fetch(session, f"{OKX_BASE}/api/v5/rubik-stat/contracts/long-short-account-ratio",
                                  {"ccy": coin, "period": "5m"}))               # 4 L/S ratio

    extra_results = await asyncio.gather(*extra_tasks, return_exceptions=True)
    extra_results = [r if not isinstance(r, Exception) else None for r in extra_results]

    k4h = extra_results[0]
    k1h = extra_results[1]
    funding_data = extra_results[2] if on_fut else None
    oi_data = extra_results[3] if on_fut else None
    ls_data = extra_results[4] if on_fut else None

    return spot_raw, fut_raw, funding_data, oi_data, ls_data, k4h, k1h, on_fut, primary_inst


# ─── SIGNAL GENERATION ───────────────────────────────────────────────────────

def fmt(n, dec=4):
    if n is None:
        return "N/A"
    try:
        if abs(n) >= 1000:
            return f"{n:,.2f}"
        if abs(n) >= 1:
            return f"{n:.4f}"
        return f"{n:.8f}".rstrip("0").rstrip(".")
    except Exception:
        return str(n)


def score_market(price, trend_4h, trend_24h, rsi_4h, ind_4h):
    """Composite score: positive = bullish, negative = bearish."""
    score = 0
    notes = []

    if trend_4h == "UPTREND":
        score += 2
        notes.append("4H trend: UPTREND")
    elif trend_4h == "DOWNTREND":
        score -= 2
        notes.append("4H trend: DOWNTREND")
    else:
        notes.append("4H trend: SIDEWAYS")

    if trend_24h == trend_4h and trend_4h != "SIDEWAYS":
        score += 1 if trend_4h == "UPTREND" else -1
        notes.append("4H & 24H trend aligned")
    elif trend_24h != trend_4h:
        notes.append("4H & 24H trend conflict → caution")

    if rsi_4h is not None:
        if rsi_4h < 30:
            score += 2
            notes.append(f"RSI oversold ({rsi_4h})")
        elif rsi_4h > 70:
            score -= 2
            notes.append(f"RSI overbought ({rsi_4h})")
        elif rsi_4h > 55:
            score += 1
        elif rsi_4h < 45:
            score -= 1

    e9 = ind_4h.get("ema9")
    e21 = ind_4h.get("ema21")
    if e9 and e21:
        if e9 > e21:
            score += 1
            notes.append("EMA9 > EMA21 (bullish cross)")
        else:
            score -= 1
            notes.append("EMA9 < EMA21 (bearish cross)")

    return score, notes


def generate_spot_signal(price, score, atr):
    if score >= 3:
        signal = "BUY"
        entry = price
        sl = price - 1.5 * atr
        tp1 = price + 1.0 * atr
        tp2 = price + 2.0 * atr
        tp3 = price + 3.0 * atr
    elif score <= -3:
        signal = "SELL"
        entry = price
        sl = price + 1.5 * atr
        tp1 = price - 1.0 * atr
        tp2 = price - 2.0 * atr
        tp3 = price - 3.0 * atr
    else:
        return {"signal": "HOLD", "entry": None, "sl": None, "tp": []}

    return {"signal": signal, "entry": entry, "sl": sl, "tp": [tp1, tp2, tp3]}


def generate_futures_signal(price, score, atr):
    if score >= 4:
        direction = "LONG"
        entry = price
        sl = price - 1.2 * atr
        tp1 = price + 1.0 * atr
        tp2 = price + 2.0 * atr
        tp3 = price + 3.5 * atr
    elif score <= -4:
        direction = "SHORT"
        entry = price
        sl = price + 1.2 * atr
        tp1 = price - 1.0 * atr
        tp2 = price - 2.0 * atr
        tp3 = price - 3.5 * atr
    else:
        return {"signal": "NO TRADE", "entry": None, "sl": None, "tp": [], "liq": None}

    # Approx liquidation distance at 25x (isolated, ~ -1/leverage from entry, before fees)
    liq_pct = 100 / 25  # 4%
    if direction == "LONG":
        liq_price = entry * (1 - liq_pct / 100)
    else:
        liq_price = entry * (1 + liq_pct / 100)

    return {"signal": direction, "entry": entry, "sl": sl, "tp": [tp1, tp2, tp3], "liq": liq_price}


# ─── NEWS & SENTIMENT ────────────────────────────────────────────────────────

async def get_news(session, coin):
    data = await fetch(session, CRYPTOCOMPARE_NEWS,
                        {"lang": "EN", "categories": coin, "sortOrder": "latest"})
    if not data or "Data" not in data:
        return []
    items = data["Data"][:5]
    return [{"title": it.get("title", ""), "source": it.get("source_info", {}).get("name", ""),
             "url": it.get("url", "")} for it in items]


async def groq_sentiment(session, coin, news_items, market_summary):
    if not news_items:
        headlines = "No recent news found."
    else:
        headlines = "\n".join(f"- {n['title']} ({n['source']})" for n in news_items)

    prompt = f"""You are a crypto market analyst. Based on the latest news headlines and market data for {coin}, classify overall sentiment.

NEWS HEADLINES:
{headlines}

MARKET DATA:
{market_summary}

Respond in this EXACT format:
SENTIMENT: <Bullish/Bearish/Neutral>
SUMMARY:
- point 1
- point 2
- point 3
(max 5 points, short and factual, based only on the headlines and data given)"""

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 400,
    }
    result = await fetch(session, GROQ_URL, headers=headers, json_body=body, method="POST")
    if result and "choices" in result:
        return result["choices"][0]["message"]["content"].strip()
    return "SENTIMENT: Neutral\nSUMMARY:\n- AI summary unavailable right now."


# ─── REPORT BUILDERS ─────────────────────────────────────────────────────────

def build_price_section(symbol, coin, spot_t, fut_t, ranges_spot, ranges_fut):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🪙 {coin}/USDT — Trading Intelligence")
    lines.append(f"🕐 {now}")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if spot_t:
        price = float(spot_t.get("lastPrice", 0))
        ch = float(spot_t.get("priceChangePercent", 0))
        h24 = float(spot_t.get("highPrice", 0))
        l24 = float(spot_t.get("lowPrice", 0))
        vol = float(spot_t.get("quoteVolume", 0))
        em = "📈" if ch >= 0 else "📉"
        lines.append(f"\n💰 SPOT PRICE")
        lines.append(f"  Price:       ${fmt(price)}")
        lines.append(f"  24h Change:  {em} {ch:+.2f}%")
        lines.append(f"  24h High:    ${fmt(h24)}")
        lines.append(f"  24h Low:     ${fmt(l24)}")
        lines.append(f"  24h Volume:  {fmt(vol, 0)} USDT")

    if fut_t:
        fp = float(fut_t.get("lastPrice", 0))
        fch = float(fut_t.get("priceChangePercent", 0))
        fv = float(fut_t.get("quoteVolume", 0))
        lines.append(f"\n📊 FUTURES (USDT-M)")
        lines.append(f"  Price:       ${fmt(fp)}")
        lines.append(f"  24h Change:  {fch:+.2f}%")
        lines.append(f"  24h Volume:  {fmt(fv, 0)} USDT")

    # Multi-timeframe ranges
    lines.append(f"\n📐 MULTI-TIMEFRAME RANGES (Futures)")
    for label in TIMEFRAMES.keys():
        r = ranges_fut.get(label) or ranges_spot.get(label)
        if r:
            arrow = "▲" if r["move_pct"] >= 0 else "▼"
            lines.append(
                f"  {label:>3}: H ${fmt(r['high'])}  L ${fmt(r['low'])}  "
                f"Range {r['range_pct']:.2f}%  Move {arrow}{r['move_pct']:+.2f}%"
            )
        else:
            lines.append(f"  {label:>3}: data unavailable")

    return "\n".join(lines)


def build_trend_signal_section(coin, price, trend_4h, rsi_4h, trend_24h, rsi_24h,
                                score, notes, atr_4h, ch24, on_fut):
    lines = []
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📡 TREND & SIGNALS — {coin}")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")

    lines.append(f"\n🧭 TREND DETECTION")
    lines.append(f"  4H Trend:   {trend_4h}  (RSI {rsi_4h if rsi_4h is not None else 'N/A'})")
    lines.append(f"  24H Trend:  {trend_24h}  (RSI {rsi_24h if rsi_24h is not None else 'N/A'})")
    trending_today = "YES" if abs(ch24) > 3 else "NO"
    lines.append(f"  Trending Today: {trending_today}  (24h move {ch24:+.2f}%)")

    lines.append(f"\n📝 ANALYSIS NOTES")
    for n in notes:
        lines.append(f"  • {n}")
    lines.append(f"  Composite Score: {score:+d}")

    # SPOT signal
    spot_sig = generate_spot_signal(price, score, atr_4h)
    lines.append(f"\n🟢 SPOT SIGNAL")
    lines.append(f"  Action: {spot_sig['signal']}")
    if spot_sig["signal"] != "HOLD":
        lines.append(f"  Entry:  ${fmt(spot_sig['entry'])}")
        lines.append(f"  Stop Loss: ${fmt(spot_sig['sl'])}")
        tps = spot_sig["tp"]
        lines.append(f"  TP1: ${fmt(tps[0])}  TP2: ${fmt(tps[1])}  TP3: ${fmt(tps[2])}")
    else:
        lines.append("  No clear edge — wait for better setup.")

    # FUTURES signal
    lines.append(f"\n🔴 FUTURES SIGNAL")
    if not on_fut:
        lines.append("  Futures market not available for this symbol.")
    else:
        fut_sig = generate_futures_signal(price, score, atr_4h)
        lines.append(f"  Action: {fut_sig['signal']}")
        if fut_sig["signal"] != "NO TRADE":
            lines.append(f"  Entry:  ${fmt(fut_sig['entry'])}")
            lines.append(f"  Stop Loss: ${fmt(fut_sig['sl'])}")
            tps = fut_sig["tp"]
            lines.append(f"  TP1: ${fmt(tps[0])}  TP2: ${fmt(tps[1])}  TP3: ${fmt(tps[2])}")
            lines.append(f"  Suggested Leverage: 25x (isolated)")
            lines.append(f"  ⚠️ Approx. Liquidation: ${fmt(fut_sig['liq'])}")
            lines.append(f"  ⚠️ HIGH RISK: 25x leverage can liquidate on a ~4% adverse move. "
                          f"Use proper position sizing.")
        else:
            lines.append("  No clear directional edge — avoid leveraged trade.")

    return "\n".join(lines)


def build_context_news_section(coin, atr_4h, price, score, trend_4h, trend_24h, sentiment_text,
                                 news_items, oi, ls_ratio, funding):
    lines = []
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🌐 MARKET CONTEXT & NEWS — {coin}")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Volatility
    atr_pct = (atr_4h / price * 100) if price else 0
    if atr_pct > 3:
        vol_label = "HIGH"
    elif atr_pct > 1:
        vol_label = "MEDIUM"
    else:
        vol_label = "LOW"

    condition = "TRENDING" if (trend_4h == trend_24h and trend_4h != "SIDEWAYS") else "RANGING"
    strength = "STRONG" if abs(score) >= 4 else ("MODERATE" if abs(score) >= 2 else "WEAK")

    lines.append(f"\n📊 MARKET CONDITION")
    lines.append(f"  Volatility (4H ATR): {vol_label}  ({atr_pct:.2f}% of price)")
    lines.append(f"  Trend Strength: {strength}")
    lines.append(f"  Condition: {condition}")

    if funding is not None:
        lines.append(f"\n💹 FUTURES METRICS")
        lines.append(f"  Funding Rate: {funding*100:.4f}%")
        if oi is not None:
            lines.append(f"  Open Interest: {fmt(oi, 0)} {coin}")
        if ls_ratio is not None:
            lines.append(f"  Long/Short Ratio: {ls_ratio:.2f}")

    lines.append(f"\n📰 NEWS & SENTIMENT")
    lines.append(sentiment_text)

    if news_items:
        lines.append(f"\n🔗 SOURCES")
        for n in news_items[:5]:
            lines.append(f"  • {n['title']} — {n['source']}")
    else:
        lines.append(f"\n  No recent headlines found for {coin}.")

    return "\n".join(lines)


# ─── MAIN ANALYSIS BUILDER ───────────────────────────────────────────────────

async def build_full_report(symbol_input: str):
    raw = symbol_input.upper().strip().lstrip("/")
    coin = raw[:-4] if raw.endswith("USDT") else raw
    symbol = coin + "USDT"

    async with aiohttp.ClientSession() as session:
        spot_raw, fut_raw, funding_data, oi_data, ls_data, k4h, k1h, on_fut, primary_inst = \
            await get_market_snapshot(session, coin)

    on_spot = spot_raw is not None

    if not on_spot and not on_fut:
        return [f"❌ {symbol} not found on OKX.\nTry: /BTC /ETH /SOL /PEPE"]

    spot_t = normalize_ticker(spot_raw)
    fut_t = normalize_ticker(fut_raw)

    primary_raw = fut_raw if on_fut else spot_raw
    norm_primary = normalize_ticker(primary_raw)
    price = float(norm_primary["lastPrice"])
    try:
        ch24 = float(norm_primary["priceChangePercent"])
    except (TypeError, ValueError):
        ch24 = 0

    async with aiohttp.ClientSession() as session:
        # Multi-timeframe ranges (primary instrument)
        ranges_primary = await get_multi_timeframe_ranges(session, primary_inst)
        ranges_fut = ranges_primary if on_fut else {}
        ranges_spot = ranges_primary if not on_fut else {}

        # Trend detection
        trend_4h, rsi_4h = detect_trend(k4h) if k4h else ("SIDEWAYS", None)
        trend_24h, rsi_24h = detect_trend(k1h) if k1h else ("SIDEWAYS", None)

        ind_4h = compute_indicators(k4h) if k4h else {}
        atr_4h = ind_4h.get("atr", price * 0.01) or (price * 0.01)

        score, notes = score_market(price, trend_4h, trend_24h, rsi_4h, ind_4h)

        # Futures extras
        funding = None
        oi = None
        ls_ratio = None
        if on_fut:
            if isinstance(funding_data, dict) and funding_data.get("code") == "0":
                lst = funding_data.get("data", [])
                if lst:
                    try:
                        funding = float(lst[0].get("fundingRate", 0))
                    except (TypeError, ValueError):
                        funding = None
            if isinstance(oi_data, dict) and oi_data.get("code") == "0":
                lst = oi_data.get("data", [])
                if lst:
                    try:
                        oi = float(lst[0].get("oiCcy", lst[0].get("oi", 0)))
                    except (TypeError, ValueError):
                        oi = None
            if isinstance(ls_data, dict) and ls_data.get("code") == "0":
                lst = ls_data.get("data", [])
                if lst:
                    try:
                        ls_ratio = float(lst[0][1])
                    except (TypeError, ValueError, IndexError):
                        ls_ratio = None

        # News + sentiment
        news_items = await get_news(session, coin)
        market_summary = (f"Price: ${fmt(price)}, 24h change: {ch24:+.2f}%, "
                           f"4H trend: {trend_4h}, 24H trend: {trend_24h}")
        sentiment_text = await groq_sentiment(session, coin, news_items, market_summary)

    msg1 = build_price_section(symbol, coin, spot_t, fut_t, ranges_spot, ranges_fut)
    msg2 = build_trend_signal_section(coin, price, trend_4h, rsi_4h, trend_24h, rsi_24h,
                                       score, notes, atr_4h, ch24, on_fut)
    msg3 = build_context_news_section(coin, atr_4h, price, score, trend_4h, trend_24h,
                                       sentiment_text, news_items, oi, ls_ratio, funding)

    return [msg1, msg2, msg3]


# ─── TELEGRAM HANDLERS ───────────────────────────────────────────────────────

async def coin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT:
        return

    text = update.message.text.strip()
    if text.startswith("/start") or text.startswith("/help"):
        await update.message.reply_text(
            "👋 Crypto Trading Intelligence Bot\n\n"
            "Type / + coin name, e.g.:\n"
            "/BTC  /ETH  /SOL  /PEPE  /DOGE  /XRP\n\n"
            "You'll get:\n"
            "📐 Multi-timeframe ranges (1H → 1M)\n"
            "🧭 4H & 24H trend detection\n"
            "🟢 Spot signal (BUY/SELL/HOLD + SL/TP)\n"
            "🔴 Futures signal (LONG/SHORT + 25x leverage)\n"
            "📰 News sentiment via Groq AI\n"
            "🌐 Volatility & market condition\n\n"
            "⚠️ Not financial advice. High leverage = high risk."
        )
        return

    symbol = text.lstrip("/").upper()
    msg = await update.message.reply_text(f"⏳ Fetching live data for {symbol}...")

    try:
        sections = await build_full_report(symbol)
        await msg.delete()
        for section in sections:
            # Telegram hard limit 4096 chars per message
            for i in range(0, len(section), 4000):
                await update.message.reply_text(section[i:i + 4000])
            await asyncio.sleep(0.3)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        try:
            await msg.edit_text(f"❌ Error: {str(e)[:200]}")
        except Exception:
            await update.message.reply_text(f"❌ Error: {str(e)[:200]}")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", coin_command_handler))
    app.add_handler(CommandHandler("help", coin_command_handler))
    app.add_handler(MessageHandler(filters.COMMAND, coin_command_handler))
    logger.info("🚀 Crypto Trading Intelligence Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
