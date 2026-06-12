"""
🚀 Crypto Analysis Bot v4 - India Fix
"""

import logging
import asyncio
import aiohttp
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

TELEGRAM_TOKEN = "8650706334:AAHJQrBxkw-zOw286H1v-PvtDtUWsM9KFfY"
GROQ_API_KEY   = "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"
ALLOWED_CHAT   = 5214099942

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUT  = "https://fapi.binance.com"
BINANCE_ALT1 = "https://api1.binance.com"
BINANCE_ALT2 = "https://api2.binance.com"
BINANCE_ALT3 = "https://api3.binance.com"
COINGECKO    = "https://api.coingecko.com/api/v3"
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
    "DOGE": "dogecoin", "AVAX": "avalanche-2", "DOT": "polkadot",
    "MATIC": "matic-network", "LINK": "chainlink", "UNI": "uniswap",
    "ATOM": "cosmos", "LTC": "litecoin", "BCH": "bitcoin-cash",
    "NEAR": "near", "APT": "aptos", "ARB": "arbitrum",
    "OP": "optimism", "SUI": "sui", "PEPE": "pepe",
    "SHIB": "shiba-inu", "FLOKI": "floki", "BONK": "bonk",
    "WIF": "dogwifcoin", "TRX": "tron", "TON": "the-open-network",
    "NOT": "notcoin", "STG": "stargate-finance", "INJ": "injective-protocol",
    "FET": "fetch-ai", "RENDER": "render-token", "SEI": "sei-network",
}

async def fetch(session, url, params=None, headers=None, json_body=None, method="GET", timeout=15):
    try:
        if method == "POST":
            async with session.post(url, headers=headers, json=json_body,
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status == 200:
                    return await r.json()
        else:
            async with session.get(url, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        logger.warning(f"Fetch error {url}: {e}")
    return None

async def fetch_with_fallback(session, path, params=None):
    for base in [BINANCE_SPOT, BINANCE_ALT1, BINANCE_ALT2, BINANCE_ALT3]:
        result = await fetch(session, f"{base}{path}", params=params, timeout=8)
        if result is not None:
            return result
    return None

async def check_symbol(session, symbol):
    spot_r = await fetch_with_fallback(session, "/api/v3/ticker/price", {"symbol": symbol})
    fut_r  = await fetch(session, f"{BINANCE_FUT}/fapi/v1/ticker/price", {"symbol": symbol}, timeout=8)
    on_spot = isinstance(spot_r, dict) and "price" in spot_r
    on_fut  = isinstance(fut_r,  dict) and "price" in fut_r
    logger.info(f"Symbol {symbol}: spot={on_spot}, fut={on_fut}")
    return on_spot, on_fut

async def get_coingecko_data(session, coin):
    cg_id = COINGECKO_IDS.get(coin.upper())
    if not cg_id:
        search = await fetch(session, f"{COINGECKO}/search", {"query": coin}, timeout=10)
        if search and "coins" in search and search["coins"]:
            cg_id = search["coins"][0]["id"]
    if not cg_id:
        return None, None
    data = await fetch(session, f"{COINGECKO}/coins/{cg_id}",
                       {"localization": "false", "tickers": "false",
                        "community_data": "false", "developer_data": "false"}, timeout=15)
    ohlc = await fetch(session, f"{COINGECKO}/coins/{cg_id}/ohlc",
                       {"vs_currency": "usd", "days": "90"}, timeout=15)
    return data, ohlc

def ema(closes, period):
    if not closes or len(closes) < period:
        return None
    k = 2 / (period + 1)
    val = sum(closes[:period]) / period
    for p in closes[period:]:
        val = p * k + val * (1 - k)
    return round(val, 8)

def rsi(closes, period=14):
    if not closes or len(closes) < period + 1:
        return None
    deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
    gains  = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0: return 100.0
    return round(100 - (100 / (1 + ag/al)), 2)

def macd_calc(closes):
    if not closes or len(closes) < 35:
        return None, None, None
    e12 = ema(closes, 12)
    e26 = ema(closes, 26)
    if not e12 or not e26: return None, None, None
    macd_line = e12 - e26
    snapshots = []
    c = closes.copy()
    for _ in range(9):
        if len(c) >= 26:
            _e12 = ema(c, 12)
            _e26 = ema(c, 26)
            if _e12 and _e26:
                snapshots.insert(0, _e12 - _e26)
            c = c[:-1]
    signal = sum(snapshots)/len(snapshots) if snapshots else macd_line
    return round(macd_line, 8), round(signal, 8), round(macd_line - signal, 8)

def bollinger(closes, period=20):
    if not closes or len(closes) < period:
        return None, None, None
    w = closes[-period:]
    mid = sum(w) / period
    std = (sum((x - mid)**2 for x in w) / period) ** 0.5
    return round(mid - 2*std, 8), round(mid, 8), round(mid + 2*std, 8)

def compute_indicators(klines):
    if not klines or len(klines) < 20:
        return {}
    closes  = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines] if len(klines[0]) > 5 else [0]*len(klines)
    current = closes[-1]
    rsi_v               = rsi(closes, 14)
    ema9_v              = ema(closes, 9)
    ema21_v             = ema(closes, 21)
    ema50_v             = ema(closes, 50)
    ema200_v            = ema(closes, 200)
    macd_v, sig_v, hist_v = macd_calc(closes)
    bb_l, bb_m, bb_u    = bollinger(closes, 20)
    avg_vol   = sum(volumes[-20:]) / 20 if any(volumes) else 0
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
    return {
        "current": current,
        "rsi": rsi_v, "ema9": ema9_v, "ema21": ema21_v,
        "ema50": ema50_v, "ema200": ema200_v,
        "macd": macd_v, "macd_signal": sig_v, "macd_hist": hist_v,
        "bb_lower": bb_l, "bb_mid": bb_m, "bb_upper": bb_u,
        "vol_ratio": vol_ratio,
    }

def score_indicators(ind):
    if not ind: return 0, []
    score = 0; signals = []
    cur = ind.get("current", 0)
    rsi_v = ind.get("rsi")
    if rsi_v:
        if rsi_v < 30:   score += 2; signals.append(f"RSI oversold ({rsi_v})")
        elif rsi_v > 70: score -= 2; signals.append(f"RSI overbought ({rsi_v})")
        elif rsi_v > 55: score += 1
        elif rsi_v < 45: score -= 1
    e9 = ind.get("ema9"); e21 = ind.get("ema21"); e50 = ind.get("ema50")
    if e9 and e21:
        if cur > e9 > e21:   score += 2; signals.append("Uptrend EMA")
        elif cur < e9 < e21: score -= 2; signals.append("Downtrend EMA")
    if e50:
        score += 1 if cur > e50 else -1
    hist = ind.get("macd_hist"); macd_v = ind.get("macd")
    if hist is not None:
        if hist > 0 and (macd_v or 0) > 0:   score += 2
        elif hist > 0:                         score += 1
        elif hist < 0 and (macd_v or 0) < 0:  score -= 2
        else:                                  score -= 1
    bb_l = ind.get("bb_lower"); bb_u = ind.get("bb_upper")
    if bb_l and bb_u:
        rng = bb_u - bb_l
        pos = (cur - bb_l) / rng if rng else 0.5
        if pos <= 0.1:   score += 2; signals.append("Lower BB bounce zone")
        elif pos >= 0.9: score -= 2; signals.append("Upper BB overbought")
        elif pos > 0.6:  score += 1
        elif pos < 0.4:  score -= 1
    return score, signals

def fmt(n, d=4):
    if n is None: return "N/A"
    try:
        n = float(n)
        if abs(n) >= 1_000_000_000: return f"{n/1_000_000_000:.2f}B"
        if abs(n) >= 1_000_000:     return f"{n/1_000_000:.2f}M"
        if abs(n) >= 1_000:         return f"{n/1_000:.2f}K"
        return f"{n:.{d}f}"
    except: return str(n)

def sig_label(score):
    if score >= 4:    return "🟢 STRONG BUY"
    elif score >= 2:  return "🟩 BUY"
    elif score <= -4: return "🔴 STRONG SELL"
    elif score <= -2: return "🟥 SELL"
    return "🟡 NEUTRAL"

def ind_block(label, ind):
    if not ind: return f"\n📐 *{label}* — No data"
    cur = ind.get("current", 0)
    lines = [f"\n📐 *{label} Indicators*"]
    rsi_v = ind.get("rsi")
    if rsi_v:
        e = "🔴" if rsi_v > 70 else ("🟢" if rsi_v < 30 else "🟡")
        lines.append(f"  RSI(14): {e} `{rsi_v}`")
    for name, key in [("EMA9","ema9"),("EMA21","ema21"),("EMA50","ema50"),("EMA200","ema200")]:
        v = ind.get(key)
        if v:
            lines.append(f"  {name}: {'🟢' if cur>v else '🔴'} `{fmt(v,4)}`")
    macd_v = ind.get("macd"); hist_v = ind.get("macd_hist")
    if macd_v is not None:
        lines.append(f"  MACD: {'🟢' if (hist_v or 0)>0 else '🔴'} `{fmt(macd_v,6)}` Hist:`{fmt(hist_v,6)}`")
    bb_l = ind.get("bb_lower"); bb_u = ind.get("bb_upper"); bb_m = ind.get("bb_mid")
    if bb_l and bb_u:
        tag = " 🔵Lower" if cur<=bb_l else (" 🔴Upper" if cur>=bb_u else "")
        lines.append(f"  BB: `{fmt(bb_l,4)}`/`{fmt(bb_m,4)}`/`{fmt(bb_u,4)}`{tag}")
    vol_r = ind.get("vol_ratio")
    if vol_r: lines.append(f"  Volume: {'🔥' if vol_r>2 else '📊'} `{vol_r:.2f}x` avg")
    score, _ = score_indicators(ind)
    lines.append(f"  Signal: *{sig_label(score)}*")
    return "\n".join(lines)

async def groq_analysis(session, coin, price_data, ind_summary, market_data):
    prompt = f"""You are an expert crypto trader. Analyze {coin}/USDT:

PRICE: {price_data}
INDICATORS: {ind_summary}
MARKET: {market_data}

Reply in this EXACT format:

📊 MARKET SENTIMENT
[2-3 lines]

⏱ SHORT TERM (24-72h)
Direction: BULLISH/BEARISH/NEUTRAL
Target: $X — $Y
• [reason]
• [reason]
• [reason]

📅 LONG TERM (1-4 weeks)
Direction: BULLISH/BEARISH/NEUTRAL
Target: $X — $Y
• [reason]
• [reason]

🚀 PUMP TRIGGERS
• [catalyst]
• [catalyst]
• [catalyst]

💥 DUMP TRIGGERS
• [risk]
• [risk]
• [risk]

⚠️ RISK: LOW/MEDIUM/HIGH — [reason]

📈 TRADE SETUP
Entry: $X | SL: $X | TP1: $X | TP2: $X"""

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {"model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1000, "temperature": 0.3}
    resp = await fetch(session, GROQ_URL, headers=headers, json_body=body, method="POST", timeout=30)
    if resp and "choices" in resp:
        return resp["choices"][0]["message"]["content"]
    return "⚠️ Groq AI unavailable."

async def build_analysis(raw_input: str) -> str:
    coin = raw_input.upper().strip().lstrip("/").strip()
    if coin.endswith("USDT"): coin = coin[:-4]
    symbol = coin + "USDT"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    logger.info(f"=== Analyzing: {symbol} ===")

    connector = aiohttp.TCPConnector(ssl=False)
    headers   = {"User-Agent": "Mozilla/5.0"}

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        on_spot, on_fut = await check_symbol(session, symbol)
        binance_works   = on_spot or on_fut

        price=None; spot_t=None; fut_t=None; premium=None
        oi=None; funding=None; ls_global=None; oi_hist=None
        ind_1h={}; ind_4h={}; ind_1d={}
        source_label=""

        if binance_works:
            source_label = "Binance ✅"
            kline_base = BINANCE_FUT if on_fut else BINANCE_SPOT
            kline_path = "/fapi/v1/klines" if on_fut else "/api/v3/klines"

            results = await asyncio.gather(
                fetch_with_fallback(session, "/api/v3/ticker/24hr", {"symbol": symbol}),
                fetch(session, f"{BINANCE_FUT}/fapi/v1/ticker/24hr", {"symbol": symbol}) if on_fut else asyncio.sleep(0),
                fetch(session, f"{BINANCE_FUT}/fapi/v1/premiumIndex", {"symbol": symbol}) if on_fut else asyncio.sleep(0),
                fetch(session, f"{BINANCE_FUT}/fapi/v1/openInterest", {"symbol": symbol}) if on_fut else asyncio.sleep(0),
                fetch(session, f"{BINANCE_FUT}/fapi/v1/fundingRate", {"symbol": symbol, "limit": 3}) if on_fut else asyncio.sleep(0),
                fetch(session, f"{BINANCE_FUT}/futures/data/globalLongShortAccountRatio", {"symbol": symbol, "period": "5m", "limit": 1}) if on_fut else asyncio.sleep(0),
                fetch(session, f"{BINANCE_FUT}/fapi/v1/openInterestHist", {"symbol": symbol, "period": "1h", "limit": 5}) if on_fut else asyncio.sleep(0),
                fetch(session, f"{kline_base}{kline_path}", {"symbol": symbol, "interval": "1h",  "limit": 100}),
                fetch(session, f"{kline_base}{kline_path}", {"symbol": symbol, "interval": "4h",  "limit": 100}),
                fetch(session, f"{kline_base}{kline_path}", {"symbol": symbol, "interval": "1d",  "limit": 200}),
                return_exceptions=True
            )
            r = [x if not isinstance(x, Exception) else None for x in results]
            spot_t   = r[0]  if isinstance(r[0],  dict) else None
            fut_t    = r[1]  if isinstance(r[1],  dict) else None
            premium  = r[2]  if isinstance(r[2],  dict) else None
            oi       = r[3]  if isinstance(r[3],  dict) else None
            funding  = r[4]  if isinstance(r[4],  list) else None
            ls_global= r[5]  if isinstance(r[5],  list) else None
            oi_hist  = r[6]  if isinstance(r[6],  list) else None
            k1h      = r[7]  if isinstance(r[7],  list) else None
            k4h      = r[8]  if isinstance(r[8],  list) else None
            k1d      = r[9]  if isinstance(r[9],  list) else None

            if fut_t:    price = float(fut_t.get("lastPrice", 0))
            elif spot_t: price = float(spot_t.get("lastPrice", 0))
            ind_1h = compute_indicators(k1h) if k1h else {}
            ind_4h = compute_indicators(k4h) if k4h else {}
            ind_1d = compute_indicators(k1d) if k1d else {}

        else:
            source_label = "CoinGecko (Binance blocked in region)"
            logger.info(f"CoinGecko fallback for {coin}")
            cg_data, ohlc = await get_coingecko_data(session, coin)
            if not isinstance(cg_data, dict) or "market_data" not in cg_data:
                return (f"❌ Data unavailable for *{coin}*\n\n"
                        f"Binance is blocked in India on this network.\n"
                        f"✅ Bot is running on Railway — this means Railway's server\n"
                        f"can access Binance. Check Railway logs for errors.")
            md    = cg_data["market_data"]
            price = md["current_price"]["usd"]
            spot_t = {
                "lastPrice": str(price),
                "priceChangePercent": str(md.get("price_change_percentage_24h", 0)),
                "highPrice": str(md.get("high_24h", {}).get("usd", price)),
                "lowPrice":  str(md.get("low_24h",  {}).get("usd", price)),
                "quoteVolume": str(md.get("total_volume", {}).get("usd", 0)),
            }
            if isinstance(ohlc, list) and ohlc:
                klines_cg = [[0, k[1], k[2], k[3], k[4], 0] for k in ohlc]
                ind_1d = compute_indicators(klines_cg)
                ind_4h = ind_1d

    # Build message
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🪙 *{coin}/USDT — Full Analysis*")
    lines.append(f"🕐 `{now}`")
    lines.append(f"📡 _{source_label}_")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    lines.append("\n💰 *PRICE*")
    lines.append(f"  Price: `${fmt(price, 6)}`")
    if spot_t:
        ch  = float(spot_t.get("priceChangePercent", 0))
        h24 = float(spot_t.get("highPrice", price or 0))
        l24 = float(spot_t.get("lowPrice",  price or 0))
        vol = float(spot_t.get("quoteVolume", 0))
        em  = "📈" if ch >= 0 else "📉"
        lines.append(f"  24h: {em} `{ch:+.2f}%`  High:`${fmt(h24,4)}`  Low:`${fmt(l24,4)}`")
        lines.append(f"  Volume: `{fmt(vol,0)} USDT`")

    if binance_works and on_fut:
        lines.append("\n📊 *FUTURES*")
        if fut_t:
            lines.append(f"  Price: `${fmt(float(fut_t.get('lastPrice',0)),6)}`  ({float(fut_t.get('priceChangePercent',0)):+.2f}%)")
        if premium:
            fr   = float(premium.get("lastFundingRate", 0)) * 100
            mark = float(premium.get("markPrice", 0))
            fr_e = "🔴" if fr < 0 else "🟢"
            lines.append(f"  Mark: `${fmt(mark,6)}`  Funding: {fr_e} `{fr:.4f}%`")
            if fr > 0.05:    lines.append("   ↳ ⚠️ High funding → dump risk")
            elif fr < -0.01: lines.append("   ↳ 💡 Negative funding → squeeze possible")
        if oi:
            lines.append(f"  OI: `{fmt(float(oi.get('openInterest',0)),2)} {coin}`")
        if oi_hist and len(oi_hist) >= 2:
            oi_vals = [float(x.get("sumOpenInterest",0)) for x in oi_hist]
            oi_chg  = ((oi_vals[-1]-oi_vals[0])/oi_vals[0]*100) if oi_vals[0] else 0
            lines.append(f"  OI Trend: {'📈' if oi_chg>0 else '📉'} `{oi_chg:+.2f}%` (5h)")
        if ls_global:
            lp = float(ls_global[0].get("longAccount",0))*100
            sp = 100 - lp
            le = "🟢" if lp>55 else ("🔴" if lp<45 else "🟡")
            lines.append(f"  L/S: {le} `{lp:.1f}% Long / {sp:.1f}% Short`")
            if lp > 65:   lines.append("   ↳ ⚠️ Too many longs → liquidation risk")
            elif sp > 60: lines.append("   ↳ 💡 Short squeeze possible")
        if funding and len(funding) >= 2:
            rates  = [float(f.get("fundingRate",0))*100 for f in funding]
            lines.append(f"  Avg Funding(3): `{sum(rates)/len(rates):.4f}%`")

    lines.append(ind_block("1H",  ind_1h))
    lines.append(ind_block("4H",  ind_4h))
    lines.append(ind_block("1D",  ind_1d))

    if ind_1d and ind_1d.get("bb_lower"):
        lines.append("\n🏗 *KEY LEVELS*")
        sup = ind_1d.get('bb_lower'); res = ind_1d.get('bb_upper')
        lines.append(f"  Support: `${fmt(sup,6)}`  Resistance: `${fmt(res,6)}`")
        if price and sup and res:
            lines.append(f"  To Res: `+{((res-price)/price*100):.2f}%`  To Sup: `-{((price-sup)/price*100):.2f}%`")

    s1h, _ = score_indicators(ind_1h)
    s4h, _ = score_indicators(ind_4h)
    s1d, _ = score_indicators(ind_1d)
    lines.append("\n🎯 *SIGNAL SUMMARY*")
    lines.append(f"  Short (1H-4H): *{sig_label((s1h*2+s4h)//3)}*")
    lines.append(f"  Long  (1D):    *{sig_label(s1d)}*")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🤖 *GROQ AI ANALYSIS*")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    price_summary = (f"Coin:{coin} Price:${fmt(price,6)} "
                     f"24h:{float(spot_t.get('priceChangePercent',0) if spot_t else 0):+.2f}% "
                     f"Vol:{fmt(float(spot_t.get('quoteVolume',0) if spot_t else 0),0)}USDT")
    ind_summary   = (f"1H:RSI={ind_1h.get('rsi','N/A')} MACD={fmt(ind_1h.get('macd_hist'),6)} {sig_label(s1h)}\n"
                     f"4H:RSI={ind_4h.get('rsi','N/A')} MACD={fmt(ind_4h.get('macd_hist'),6)} {sig_label(s4h)}\n"
                     f"1D:RSI={ind_1d.get('rsi','N/A')} MACD={fmt(ind_1d.get('macd_hist'),6)} {sig_label(s1d)}")
    mkt = "Futures available" if on_fut else "Spot/CoinGecko"
    if premium: mkt += f" FR={float(premium.get('lastFundingRate',0))*100:.4f}%"
    if ls_global: mkt += f" Long={float(ls_global[0].get('longAccount',0))*100:.1f}%"

    async with aiohttp.ClientSession() as s2:
        ai_text = await groq_analysis(s2, coin, price_summary, ind_summary, mkt)

    lines.append(ai_text)
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ _Not financial advice. DYOR._")
    return "\n".join(lines)

async def coin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT:
        return
    text = update.message.text or ""
    cmd  = text.split()[0].lstrip("/").split("@")[0].strip()
    if cmd.lower() in ("start", "help"):
        await update.message.reply_text(
            "👋 *Crypto Analysis Bot*\n\nType `/` + coin:\n"
            "• `/BTC` `/ETH` `/SOL` `/PEPE` `/DOGE`\n\n"
            "📊 Price, Futures, RSI, EMA, MACD, BB\n"
            "OI, Funding, L/S + 🤖 Groq AI Analysis",
            parse_mode="Markdown")
        return
    if not cmd: return
    msg = await update.message.reply_text(
        f"⏳ Analyzing *{cmd.upper()}/USDT*... 10-20 sec",
        parse_mode="Markdown")
    try:
        analysis = await build_analysis(cmd)
        if len(analysis) <= 4000:
            await msg.edit_text(analysis, parse_mode="Markdown")
        else:
            await msg.delete()
            chunks = []; cur = ""
            for line in analysis.split("\n"):
                if len(cur)+len(line)+1 > 3800: chunks.append(cur); cur = line
                else: cur += "\n" + line
            if cur: chunks.append(cur)
            for chunk in chunks:
                await update.message.reply_text(chunk.strip(), parse_mode="Markdown")
                await asyncio.sleep(0.3)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error: `{str(e)[:200]}`", parse_mode="Markdown")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", coin_command_handler))
    app.add_handler(CommandHandler("help",  coin_command_handler))
    app.add_handler(MessageHandler(filters.COMMAND, coin_command_handler))
    logger.info("🚀 Cryptoo Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
