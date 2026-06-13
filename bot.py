"""
🚀 Crypto Analysis Bot v6 - FUTURES FOCUS
- 25x Leverage futures analysis
- Real-time Binance futures data
- Broader market analysis (BTC dominance, Fear & Greed)
- Latest news via Groq AI research
- Complete futures trade setup
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

SPOT = "https://api.binance.com"
FUT  = "https://fapi.binance.com"
CG   = "https://api.coingecko.com/api/v3"
GROQ = "https://api.groq.com/openai/v1/chat/completions"

CG_IDS = {
    "BTC":"bitcoin","ETH":"ethereum","SOL":"solana","BNB":"binancecoin",
    "XRP":"ripple","ADA":"cardano","DOGE":"dogecoin","AVAX":"avalanche-2",
    "DOT":"polkadot","MATIC":"matic-network","LINK":"chainlink","UNI":"uniswap",
    "ATOM":"cosmos","LTC":"litecoin","NEAR":"near","APT":"aptos","ARB":"arbitrum",
    "OP":"optimism","SUI":"sui","PEPE":"pepe","SHIB":"shiba-inu","FLOKI":"floki",
    "BONK":"bonk","WIF":"dogwifcoin","TRX":"tron","TON":"the-open-network",
    "NOT":"notcoin","STG":"stargate-finance","INJ":"injective-protocol",
    "FET":"fetch-ai","SEI":"sei-network","RENDER":"render-token",
    "HBAR":"hedera-hashgraph","VET":"vechain","ALGO":"algorand",
    "ICP":"internet-computer","FHE":"fhenix","JUP":"jupiter",
    "PYTH":"pyth-network","JTO":"jito","ONDO":"ondo-finance",
}

# ─── HTTP ─────────────────────────────────────────────────────────────────────
async def fetch(session, url, params=None, headers=None, json_body=None, method="GET", timeout=12):
    try:
        if method == "POST":
            async with session.post(url, headers=headers, json=json_body,
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status == 200: return await r.json()
        else:
            async with session.get(url, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status == 200: return await r.json()
    except Exception as e:
        logger.warning(f"Fetch {url[:40]}: {e}")
    return None

# ─── INDICATORS ───────────────────────────────────────────────────────────────
def ema(closes, p):
    if not closes or len(closes) < p: return None
    k = 2/(p+1); v = sum(closes[:p])/p
    for x in closes[p:]: v = x*k + v*(1-k)
    return round(v, 10)

def rsi(closes, p=14):
    if not closes or len(closes) < p+1: return None
    d = [closes[i+1]-closes[i] for i in range(len(closes)-1)]
    ag = sum(x if x>0 else 0 for x in d[-p:])/p
    al = sum(-x if x<0 else 0 for x in d[-p:])/p
    if al == 0: return 100.0
    return round(100-(100/(1+ag/al)), 2)

def macd(closes):
    if not closes or len(closes) < 35: return None, None, None
    e12=ema(closes,12); e26=ema(closes,26)
    if not e12 or not e26: return None, None, None
    ml=e12-e26; snaps=[]; c=closes.copy()
    for _ in range(9):
        if len(c)>=26:
            a=ema(c,12); b=ema(c,26)
            if a and b: snaps.insert(0,a-b)
        c=c[:-1]
    sig=sum(snaps)/len(snaps) if snaps else ml
    return round(ml,10), round(sig,10), round(ml-sig,10)

def bb(closes, p=20):
    if not closes or len(closes)<p: return None,None,None
    w=closes[-p:]; m=sum(w)/p
    s=(sum((x-m)**2 for x in w)/p)**0.5
    return round(m-2*s,10), round(m,10), round(m+2*s,10)

def atr(klines, p=14):
    if not klines or len(klines)<p+1: return None
    trs=[]
    for i in range(1,len(klines)):
        h=float(klines[i][2]); l=float(klines[i][3]); pc=float(klines[i-1][4])
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs[-p:])/p if trs else None

def vwap(klines):
    if not klines: return None
    tv=0; tpv=0
    for k in klines:
        tp=(float(k[2])+float(k[3])+float(k[4]))/3
        v=float(k[5])
        tpv+=tp*v; tv+=v
    return round(tpv/tv,10) if tv else None

def compute(klines):
    if not klines or len(klines)<20: return {}
    closes=[float(k[4]) for k in klines]
    highs=[float(k[2]) for k in klines]
    lows=[float(k[3]) for k in klines]
    vols=[float(k[5]) for k in klines]
    cur=closes[-1]
    rv=rsi(closes); e9=ema(closes,9); e21=ema(closes,21)
    e50=ema(closes,50); e200=ema(closes,200)
    mv,sv,hv=macd(closes); bl,bm,bu=bb(closes)
    at=atr(klines); vw=vwap(klines[-24:] if len(klines)>=24 else klines)
    av=sum(vols[-20:])/20 if vols else 0
    vr=vols[-1]/av if av>0 else 1
    # Higher high / Lower low detection
    recent_highs=highs[-5:]
    recent_lows=lows[-5:]
    hh=recent_highs[-1]>max(recent_highs[:-1]) if len(recent_highs)>1 else False
    ll=recent_lows[-1]<min(recent_lows[:-1]) if len(recent_lows)>1 else False
    return {
        "cur":cur,"rsi":rv,"e9":e9,"e21":e21,"e50":e50,"e200":e200,
        "macd":mv,"hist":hv,"bl":bl,"bm":bm,"bu":bu,
        "atr":at,"vwap":vw,"vr":vr,"hh":hh,"ll":ll,
        "high":max(highs),"low":min(lows),
    }

def score(ind):
    if not ind: return 0
    s=0; cur=ind.get("cur",0)
    rv=ind.get("rsi")
    if rv:
        if rv<25: s+=3
        elif rv<35: s+=2
        elif rv>75: s-=3
        elif rv>65: s-=2
        elif rv>55: s+=1
        elif rv<45: s-=1
    e9=ind.get("e9"); e21=ind.get("e21"); e50=ind.get("e50"); e200=ind.get("e200")
    if e9 and e21:
        if cur>e9>e21: s+=2
        elif cur<e9<e21: s-=2
    if e50: s+=1 if cur>e50 else -1
    if e200: s+=1 if cur>e200 else -1
    hv=ind.get("hist"); mv=ind.get("macd")
    if hv is not None:
        if hv>0 and (mv or 0)>0: s+=2
        elif hv>0: s+=1
        elif hv<0 and (mv or 0)<0: s-=2
        else: s-=1
    bl=ind.get("bl"); bu=ind.get("bu")
    if bl and bu:
        rng=bu-bl; pos=(cur-bl)/rng if rng else 0.5
        if pos<=0.05: s+=3
        elif pos<=0.15: s+=2
        elif pos>=0.95: s-=3
        elif pos>=0.85: s-=2
        elif pos>0.6: s+=1
        elif pos<0.4: s-=1
    vw=ind.get("vwap")
    if vw: s+=1 if cur>vw else -1
    if ind.get("hh"): s+=1
    if ind.get("ll"): s-=1
    return s

def sig(s):
    if s>=6: return "🟢 STRONG BUY"
    elif s>=3: return "🟩 BUY"
    elif s<=-6: return "🔴 STRONG SELL"
    elif s<=-3: return "🟥 SELL"
    return "🟡 NEUTRAL"

def trend(ind):
    if not ind: return "⚪ No Data"
    cur=ind.get("cur",0); e9=ind.get("e9"); e21=ind.get("e21")
    e50=ind.get("e50"); rv=ind.get("rsi",50) or 50
    if e9 and e21 and e50:
        if cur>e9>e21>e50 and rv>60: return "🚀 Strong Uptrend"
        elif cur>e9>e21 and rv>52: return "📈 Uptrend"
        elif cur<e9<e21<e50 and rv<40: return "💀 Strong Downtrend"
        elif cur<e9<e21 and rv<48: return "📉 Downtrend"
    return "↔️ Sideways/Consolidation"

def fmt(n, d=4):
    if n is None: return "N/A"
    try:
        n=float(n)
        if abs(n)>=1e9: return f"{n/1e9:.2f}B"
        if abs(n)>=1e6: return f"{n/1e6:.2f}M"
        if abs(n)>=1e3: return f"{n/1e3:.2f}K"
        return f"{n:.{d}f}"
    except: return str(n)

def prange(label, klines, price):
    if not klines or not isinstance(klines,list) or len(klines)==0: return ""
    hs=[float(k[2]) for k in klines]; ls=[float(k[3]) for k in klines]
    os=float(klines[0][1]); cs=float(klines[-1][4])
    h=max(hs); l=min(ls)
    chg=((cs-os)/os*100) if os else 0
    em="📈" if chg>=0 else "📉"
    pos=((price-l)/(h-l)*100) if h!=l else 50
    bar="█"*int(pos/10)+"░"*(10-int(pos/10))
    return f"  `{label:3}` {em}`{chg:+.2f}%` H:`${fmt(h,4)}` L:`${fmt(l,4)}` [{bar}]`{pos:.0f}%`"

def ind_section(label, ind):
    if not ind: return f"\n📐 *{label}* — Insufficient data"
    cur=ind.get("cur",0); lines=[f"\n📐 *{label} Technical*"]
    rv=ind.get("rsi")
    if rv:
        e="🔴" if rv>70 else ("🟢" if rv<30 else "🟡")
        zone="Overbought ⚠️" if rv>70 else ("Oversold 💡" if rv<30 else "Normal")
        lines.append(f"  RSI(14): {e} `{rv}` — {zone}")
    for nm,ky in [("EMA9","e9"),("EMA21","e21"),("EMA50","e50"),("EMA200","e200")]:
        v=ind.get(ky)
        if v:
            diff=((cur-v)/v*100) if v else 0
            lines.append(f"  {nm}: {'🟢' if cur>v else '🔴'} `{fmt(v,6)}` ({diff:+.2f}%)")
    mv=ind.get("macd"); hv=ind.get("hist")
    if mv is not None:
        cross="Bullish Cross 📈" if (hv or 0)>0 else "Bearish Cross 📉"
        lines.append(f"  MACD: {'🟢' if (hv or 0)>0 else '🔴'} {cross} Hist:`{fmt(hv,8)}`")
    bl=ind.get("bl"); bu=ind.get("bu"); bm=ind.get("bm")
    if bl and bu:
        rng=bu-bl; pos=((cur-bl)/rng*100) if rng else 50
        tag=" 🔵LOWER" if cur<=bl else (" 🔴UPPER" if cur>=bu else f" mid:{pos:.0f}%")
        lines.append(f"  BB: `{fmt(bl,6)}`/`{fmt(bm,6)}`/`{fmt(bu,6)}`{tag}")
    at=ind.get("atr"); vw=ind.get("vwap")
    if at: lines.append(f"  ATR(14): `{fmt(at,6)}` (volatility)")
    if vw:
        lines.append(f"  VWAP: {'🟢' if cur>vw else '🔴'} `{fmt(vw,6)}`")
    vr=ind.get("vr")
    if vr: lines.append(f"  Volume: {'🔥 SPIKE' if vr>2 else ('📊' if vr>1 else '😴 Low')} `{vr:.2f}x` avg")
    if ind.get("hh"): lines.append("  📊 Higher High detected → bullish structure")
    if ind.get("ll"): lines.append("  📊 Lower Low detected → bearish structure")
    sc=score(ind)
    lines.append(f"  Signal: *{sig(sc)}* (score: {sc:+d})")
    lines.append(f"  Trend:  {trend(ind)}")
    return "\n".join(lines)

# ─── FUTURES CALC ─────────────────────────────────────────────────────────────
def futures_levels(price, direction, atr_val, leverage=25):
    """Calculate futures entry/SL/TP for 25x leverage"""
    if not price or not atr_val: return {}
    # With 25x leverage, 1% move = 25% PnL
    # Risk max 2% of position (= 0.08% price move at 25x for safe trade)
    if direction == "LONG":
        entry = price
        sl    = round(price - atr_val * 1.5, 8)          # 1.5 ATR below
        liq   = round(price * (1 - 1/leverage * 0.9), 8) # ~90% of margin
        tp1   = round(price + atr_val * 1.0, 8)
        tp2   = round(price + atr_val * 2.0, 8)
        tp3   = round(price + atr_val * 3.5, 8)
        sl_pct  = abs((sl-price)/price*100)
        tp1_pct = abs((tp1-price)/price*100)
        rr    = round(tp1_pct/sl_pct, 2) if sl_pct else 0
        pnl_sl  = round(-sl_pct*leverage, 1)
        pnl_tp1 = round(tp1_pct*leverage, 1)
        pnl_tp2 = round(abs((tp2-price)/price*100)*leverage, 1)
    else:
        entry = price
        sl    = round(price + atr_val * 1.5, 8)
        liq   = round(price * (1 + 1/leverage * 0.9), 8)
        tp1   = round(price - atr_val * 1.0, 8)
        tp2   = round(price - atr_val * 2.0, 8)
        tp3   = round(price - atr_val * 3.5, 8)
        sl_pct  = abs((sl-price)/price*100)
        tp1_pct = abs((tp1-price)/price*100)
        rr    = round(tp1_pct/sl_pct, 2) if sl_pct else 0
        pnl_sl  = round(-sl_pct*leverage, 1)
        pnl_tp1 = round(tp1_pct*leverage, 1)
        pnl_tp2 = round(abs((tp2-price)/price*100)*leverage, 1)
    return {
        "direction":direction,"entry":entry,"sl":sl,"liq":liq,
        "tp1":tp1,"tp2":tp2,"tp3":tp3,"rr":rr,
        "sl_pct":sl_pct,"tp1_pct":tp1_pct,
        "pnl_sl":pnl_sl,"pnl_tp1":pnl_tp1,"pnl_tp2":pnl_tp2
    }

# ─── GROQ AI ──────────────────────────────────────────────────────────────────
async def groq_ai(session, coin, data_ctx):
    prompt = f"""You are a professional crypto futures trader with 10 years experience. You have deep knowledge of all crypto news, market events, and on-chain data.

REAL-TIME DATA FOR {coin}/USDT:
{data_ctx}

Provide COMPLETE analysis. Use SPECIFIC numbers from the data. Be precise.

📰 LATEST NEWS & RESEARCH ({coin})
[Research and provide 4-5 REAL recent news items about {coin}. Include:
- Recent protocol updates or upgrades
- Partnership announcements
- Exchange listings or delistings
- Regulatory news affecting {coin}
- Whale wallet movements if known
- Community/social sentiment
Format: "• [Date approx] [News headline] — [1 line impact]"]

🌍 BROADER MARKET CONDITIONS
[3-4 lines: BTC trend impact on {coin}, overall crypto market sentiment, DeFi/altcoin season indicator, institutional flows]

📊 MARKET SENTIMENT SCORE: X/10
[Bull case vs Bear case in 2 lines each]

⏱ SHORT TERM FORECAST (Next 24-72 hours)
Direction: BULLISH / BEARISH / NEUTRAL
Confidence: X%
Price Target: $X.XXXX — $X.XXXX
Key Levels to Watch: $X (support), $X (resistance)
• [Specific reason with data]
• [Specific reason with data]
• [Specific reason with data]

📅 MEDIUM TERM FORECAST (1-4 weeks)
Direction: BULLISH / BEARISH / NEUTRAL
Confidence: X%
Price Target: $X — $X
• [reason]
• [reason]
• [reason]

🚀 PUMP CATALYSTS (Ranked by probability)
1. [Most likely - specific trigger + price target]
2. [Second likely - specific event]
3. [Third - specific catalyst]
4. [Fourth - macro factor]

💥 DUMP RISKS (Ranked by severity)
1. [Highest risk - specific level to watch]
2. [Second risk]
3. [Third risk]
4. [Stop-loss invalidation level]

📈 SPOT TRADE SETUP
Recommendation: BUY / SELL / WAIT
Entry Zone: $X — $X
Stop Loss: $X (X% below entry)
TP1: $X (+X%) — Take 30% profit
TP2: $X (+X%) — Take 50% profit
TP3: $X (+X%) — Let rest run
Risk/Reward: X:1
Position Size: MAX 5% of portfolio

🔮 FUTURES TRADE SETUP (25x Leverage)
⚠️ HIGH RISK — 25x leverage
Direction: LONG / SHORT / NO TRADE
Entry: $X
Stop Loss: $X (gets liquidated near $X)
TP1: $X (PnL: +X% on margin)
TP2: $X (PnL: +X% on margin)
Recommended Margin: X% of account
Max Loss if SL hits: -X% of margin used
Key Risk: [specific risk at 25x]
Signal Confidence: X%

⚠️ RISK ASSESSMENT
Overall Risk: LOW / MEDIUM / HIGH / VERY HIGH
Volatility Risk: [assessment]
Liquidity Risk: [assessment]
At 25x leverage: [specific warning]"""

    h={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}
    b={"model":"llama-3.3-70b-versatile",
       "messages":[{"role":"user","content":prompt}],
       "max_tokens":1800,"temperature":0.35}
    r=await fetch(session, GROQ, headers=h, json_body=b, method="POST", timeout=50)
    if r and "choices" in r: return r["choices"][0]["message"]["content"]
    return "⚠️ Groq AI unavailable right now. Try again."

# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def build(raw: str) -> list:
    coin=raw.upper().strip().lstrip("/")
    if coin.endswith("USDT"): coin=coin[:-4]
    sym=coin+"USDT"
    now=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    logger.info(f"=== {sym} ===")

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False),
        headers={"User-Agent":"Mozilla/5.0"}
    ) as s:
        # Symbol check
        sc=await fetch(s, f"{SPOT}/api/v3/ticker/price", {"symbol":sym}, timeout=8)
        fc=await fetch(s, f"{FUT}/fapi/v1/ticker/price",  {"symbol":sym}, timeout=8)
        on_spot=isinstance(sc,dict) and "price" in sc
        on_fut =isinstance(fc,dict) and "price" in fc
        ok=on_spot or on_fut

        # BTC dominance + fear greed (broader market)
        btc_task=fetch(s, f"{SPOT}/api/v3/ticker/24hr", {"symbol":"BTCUSDT"}, timeout=8)
        eth_task=fetch(s, f"{SPOT}/api/v3/ticker/24hr", {"symbol":"ETHUSDT"}, timeout=8)
        fg_task =fetch(s, "https://api.alternative.me/fng/?limit=1", timeout=8)

        price=None; spot_t=None; fut_t=None; prem=None
        oi=None; fund=None; ls=None; oih=None; lstop=None
        i1h=i4h=i1d=i1w={}
        k1h_r=k2h_r=k4h_r=k12h_r=k1d_r=k3d_r=k1w_r=k1M_r=None

        if ok:
            kb=FUT if on_fut else SPOT
            kp="/fapi/v1/klines" if on_fut else "/api/v3/klines"
            res=await asyncio.gather(
                fetch(s,f"{SPOT}/api/v3/ticker/24hr",{"symbol":sym}),
                fetch(s,f"{FUT}/fapi/v1/ticker/24hr",{"symbol":sym}) if on_fut else asyncio.sleep(0),
                fetch(s,f"{FUT}/fapi/v1/premiumIndex",{"symbol":sym}) if on_fut else asyncio.sleep(0),
                fetch(s,f"{FUT}/fapi/v1/openInterest",{"symbol":sym}) if on_fut else asyncio.sleep(0),
                fetch(s,f"{FUT}/fapi/v1/fundingRate",{"symbol":sym,"limit":5}) if on_fut else asyncio.sleep(0),
                fetch(s,f"{FUT}/futures/data/globalLongShortAccountRatio",{"symbol":sym,"period":"5m","limit":1}) if on_fut else asyncio.sleep(0),
                fetch(s,f"{FUT}/fapi/v1/openInterestHist",{"symbol":sym,"period":"1h","limit":12}) if on_fut else asyncio.sleep(0),
                fetch(s,f"{FUT}/futures/data/topLongShortPositionRatio",{"symbol":sym,"period":"1h","limit":1}) if on_fut else asyncio.sleep(0),
                fetch(s,f"{FUT}/futures/data/takerlongshortRatio",{"symbol":sym,"period":"1h","limit":1}) if on_fut else asyncio.sleep(0),
                # Price range klines
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"1h","limit":1}),
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"1h","limit":2}),
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"4h","limit":1}),
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"4h","limit":3}),
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"1d","limit":1}),
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"1d","limit":3}),
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"1w","limit":1}),
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"1M","limit":1}),
                # Indicator klines
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"1h","limit":100}),
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"4h","limit":100}),
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"1d","limit":200}),
                fetch(s,f"{kb}{kp}",{"symbol":sym,"interval":"1w","limit":52}),
                btc_task, eth_task, fg_task,
                return_exceptions=True
            )
            r=[x if not isinstance(x,Exception) else None for x in res]
            spot_t =r[0]  if isinstance(r[0],dict)  else None
            fut_t  =r[1]  if isinstance(r[1],dict)  else None
            prem   =r[2]  if isinstance(r[2],dict)  else None
            oi     =r[3]  if isinstance(r[3],dict)  else None
            fund   =r[4]  if isinstance(r[4],list)  else None
            ls     =r[5]  if isinstance(r[5],list)  else None
            oih    =r[6]  if isinstance(r[6],list)  else None
            lstop  =r[7]  if isinstance(r[7],list)  else None
            taker  =r[8]  if isinstance(r[8],list)  else None
            k1h_r  =r[9]  if isinstance(r[9],list)  else None
            k2h_r  =r[10] if isinstance(r[10],list) else None
            k4h_r  =r[11] if isinstance(r[11],list) else None
            k12h_r =r[12] if isinstance(r[12],list) else None
            k1d_r  =r[13] if isinstance(r[13],list) else None
            k3d_r  =r[14] if isinstance(r[14],list) else None
            k1w_r  =r[15] if isinstance(r[15],list) else None
            k1M_r  =r[16] if isinstance(r[16],list) else None
            ki1h   =r[17] if isinstance(r[17],list) else None
            ki4h   =r[18] if isinstance(r[18],list) else None
            ki1d   =r[19] if isinstance(r[19],list) else None
            ki1w   =r[20] if isinstance(r[20],list) else None
            btc_t  =r[21] if isinstance(r[21],dict) else None
            eth_t  =r[22] if isinstance(r[22],dict) else None
            fg     =r[23] if isinstance(r[23],dict) else None

            if fut_t:    price=float(fut_t.get("lastPrice",0))
            elif spot_t: price=float(spot_t.get("lastPrice",0))
            i1h=compute(ki1h) if ki1h else {}
            i4h=compute(ki4h) if ki4h else {}
            i1d=compute(ki1d) if ki1d else {}
            i1w=compute(ki1w) if ki1w else {}
        else:
            # CoinGecko fallback
            cg_id=CG_IDS.get(coin)
            if not cg_id:
                return [f"❌ *{sym}* not found on Binance or CoinGecko.\nCheck coin name and try again."]
            async with aiohttp.ClientSession() as s2:
                cg=await fetch(s2,f"{CG}/coins/{cg_id}",
                    {"localization":"false","tickers":"false","community_data":"false","developer_data":"false"},timeout=15)
                ohlc=await fetch(s2,f"{CG}/coins/{cg_id}/ohlc",{"vs_currency":"usd","days":"90"},timeout=15)
                btc_t=await fetch(s2,f"{SPOT}/api/v3/ticker/24hr",{"symbol":"BTCUSDT"},timeout=8)
                fg=await fetch(s2,"https://api.alternative.me/fng/?limit=1",timeout=8)
            if not isinstance(cg,dict) or "market_data" not in cg:
                return [f"❌ No data for *{coin}*. Try again later."]
            md=cg["market_data"]; price=md["current_price"]["usd"]
            spot_t={"lastPrice":str(price),"priceChangePercent":str(md.get("price_change_percentage_24h",0)),
                    "highPrice":str(md.get("high_24h",{}).get("usd",price)),
                    "lowPrice":str(md.get("low_24h",{}).get("usd",price)),
                    "quoteVolume":str(md.get("total_volume",{}).get("usd",0))}
            if isinstance(ohlc,list) and ohlc:
                kc=[[0,k[1],k[2],k[3],k[4],0] for k in ohlc]
                i1d=compute(kc); i4h=i1d
            taker=None; eth_t=None

    # ── BUILD MESSAGE ──
    pages=[]
    p1=[]
    p1.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    p1.append(f"🪙 *{coin}/USDT — Full Analysis*")
    p1.append(f"🕐 `{now}`")
    p1.append(f"📡 _{'Binance ✅ Live' if ok else 'CoinGecko ⚠️'}_")
    p1.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # BROADER MARKET
    p1.append("\n🌍 *BROADER MARKET*")
    if btc_t and isinstance(btc_t,dict):
        btc_ch=float(btc_t.get("priceChangePercent",0))
        btc_p=float(btc_t.get("lastPrice",0))
        be="📈" if btc_ch>=0 else "📉"
        p1.append(f"  BTC: {be} `${fmt(btc_p,0)}` ({btc_ch:+.2f}%)")
    if eth_t and isinstance(eth_t,dict):
        eth_ch=float(eth_t.get("priceChangePercent",0))
        eth_p=float(eth_t.get("lastPrice",0))
        ee="📈" if eth_ch>=0 else "📉"
        p1.append(f"  ETH: {ee} `${fmt(eth_p,0)}` ({eth_ch:+.2f}%)")
    if fg and isinstance(fg,dict) and "data" in fg:
        fgd=fg["data"][0]
        fgv=fgd.get("value","N/A")
        fgc=fgd.get("value_classification","N/A")
        fg_e="😱" if int(fgv)<25 else ("😰" if int(fgv)<40 else ("😐" if int(fgv)<60 else ("😊" if int(fgv)<80 else "🤑")))
        p1.append(f"  Fear & Greed: {fg_e} `{fgv}/100` — {fgc}")

    # PRICE
    p1.append("\n💰 *PRICE*")
    p1.append(f"  Current: `${fmt(price,6)}`")
    if spot_t:
        ch=float(spot_t.get("priceChangePercent",0))
        h24=float(spot_t.get("highPrice",price or 0))
        l24=float(spot_t.get("lowPrice",price or 0))
        vol=float(spot_t.get("quoteVolume",0))
        em="📈" if ch>=0 else "📉"
        p1.append(f"  24h:    {em} `{ch:+.2f}%`")
        p1.append(f"  High:   `${fmt(h24,6)}`  Low: `${fmt(l24,6)}`")
        p1.append(f"  Volume: `{fmt(vol,0)} USDT`")

    # PRICE RANGES
    p1.append("\n📊 *PRICE RANGES*")
    for lbl,kd in [("1H",k1h_r),("2H",k2h_r),("4H",k4h_r),("12H",k12h_r),
                    ("1D",k1d_r),("3D",k3d_r),("1W",k1w_r),("1M",k1M_r)]:
        if kd and price:
            ln=prange(lbl,kd,price)
            if ln: p1.append(ln)

    # FUTURES
    if ok and on_fut:
        p1.append("\n🔴 *FUTURES MARKET (LIVE)*")
        if fut_t:
            p1.append(f"  Price: `${fmt(float(fut_t.get('lastPrice',0)),6)}`  ({float(fut_t.get('priceChangePercent',0)):+.2f}%)")
            p1.append(f"  Volume: `{fmt(float(fut_t.get('quoteVolume',0)),0)} USDT`")
        if prem:
            fr=float(prem.get("lastFundingRate",0))*100
            mark=float(prem.get("markPrice",0))
            idx=float(prem.get("indexPrice",0))
            basis=((mark-idx)/idx*100) if idx else 0
            fe="🔴" if fr<0 else "🟢"
            p1.append(f"  Mark:    `${fmt(mark,6)}`  Index: `${fmt(idx,6)}`")
            p1.append(f"  Funding: {fe} `{fr:.4f}%`  Basis: `{basis:+.4f}%`")
            if fr>0.1:     p1.append("   ↳ 🚨 Extreme funding → HEAVY SHORT bias recommended")
            elif fr>0.05:  p1.append("   ↳ ⚠️ High funding → longs overheated → dump risk")
            elif fr<-0.05: p1.append("   ↳ 🚨 Extreme negative → SHORT SQUEEZE coming")
            elif fr<-0.01: p1.append("   ↳ 💡 Negative funding → squeeze possible")
            else:          p1.append("   ↳ ✅ Balanced funding → healthy market")
        if oi:
            oi_v=float(oi.get("openInterest",0))
            p1.append(f"  Open Interest: `{fmt(oi_v,2)} {coin}`")
        if oih and len(oih)>=2:
            ov=[float(x.get("sumOpenInterest",0)) for x in oih]
            oc=((ov[-1]-ov[0])/ov[0]*100) if ov[0] else 0
            oi_e="🔥" if oc>5 else ("📈" if oc>0 else ("📉" if oc>-5 else "💀"))
            p1.append(f"  OI Trend(12h): {oi_e} `{oc:+.2f}%`")
            if oc>10:   p1.append("   ↳ 🔥 OI surging → massive move imminent")
            elif oc>5:  p1.append("   ↳ 📈 OI rising → directional conviction building")
            elif oc<-10:p1.append("   ↳ 💀 OI collapsing → positions unwinding fast")
            elif oc<-5: p1.append("   ↳ ⚠️ OI dropping → reversal risk")
        if ls:
            lp=float(ls[0].get("longAccount",0))*100; sp=100-lp
            le="🟢" if lp>55 else ("🔴" if lp<45 else "🟡")
            p1.append(f"  L/S (Accounts): {le} `{lp:.1f}% Long / {sp:.1f}% Short`")
            if lp>70:   p1.append("   ↳ 🚨 Extreme long bias → short squeeze OR liquidation cascade")
            elif lp>60: p1.append("   ↳ ⚠️ Longs heavy → liquidation risk if price drops")
            elif sp>65: p1.append("   ↳ 💡 Shorts dominant → HIGH squeeze probability")
        if lstop:
            ltp=float(lstop[0].get("longAccount",0))*100; stp=100-ltp
            le2="🟢" if ltp>55 else ("🔴" if ltp<45 else "🟡")
            p1.append(f"  L/S (Top Traders): {le2} `{ltp:.1f}% / {stp:.1f}%`")
        if taker:
            tb=float(taker[0].get("buySell",1)) if taker else 1
            p1.append(f"  Taker Buy/Sell: {'🟢 Buy dominant' if tb>1 else '🔴 Sell dominant'} `{tb:.3f}`")
        if fund and len(fund)>=3:
            rates=[float(f.get("fundingRate",0))*100 for f in fund]
            avg=sum(rates)/len(rates)
            p1.append(f"  Avg Funding(5): `{avg:.4f}%`")
            trend_fr="Rising 📈" if rates[-1]>rates[0] else "Falling 📉"
            p1.append(f"  Funding Trend:  {trend_fr}")

    pages.append("\n".join(p1))

    # PAGE 2 — INDICATORS + FUTURES SETUP
    p2=[]
    # TREND ANALYSIS
    p2.append("🔍 *TREND ANALYSIS*")
    t1h=trend(i1h); t4h=trend(i4h); t1d=trend(i1d)
    p2.append(f"  1H:  {t1h}")
    p2.append(f"  4H:  {t4h}")
    p2.append(f"  1D:  {t1d}")
    sc1h=score(i1h); sc4h=score(i4h); sc1d=score(i1d)
    all_agree=all(x>0 for x in [sc1h,sc4h,sc1d]) or all(x<0 for x in [sc1h,sc4h,sc1d])
    if all(x>0 for x in [sc1h,sc4h,sc1d]):
        p2.append("  ✅ ALL TFs BULLISH — Strong confluence signal!")
    elif all(x<0 for x in [sc1h,sc4h,sc1d]):
        p2.append("  ❌ ALL TFs BEARISH — Strong downside signal!")
    else:
        p2.append("  ⚠️ Mixed TF signals — wait for confluence")

    # INDICATORS
    p2.append(ind_section("1H", i1h))
    p2.append(ind_section("4H", i4h))
    p2.append(ind_section("1D", i1d))
    if i1w: p2.append(ind_section("1W", i1w))

    # KEY LEVELS
    if i1d and i1d.get("bl"):
        sup=i1d.get("bl"); res=i1d.get("bu")
        p2.append("\n🏗 *KEY LEVELS*")
        p2.append(f"  Daily Support:    `${fmt(sup,6)}`")
        p2.append(f"  Daily Resistance: `${fmt(res,6)}`")
        if price and sup and res:
            p2.append(f"  To Resistance: `+{((res-price)/price*100):.2f}%`")
            p2.append(f"  To Support:    `-{((price-sup)/price*100):.2f}%`")
        if i1h.get("vwap"):
            p2.append(f"  VWAP (1H):    `${fmt(i1h.get('vwap'),6)}`")

    # SIGNAL SUMMARY
    p2.append("\n🎯 *SIGNAL SUMMARY*")
    p2.append(f"  Spot Short (1H-4H): *{sig((sc1h*2+sc4h)//3)}*")
    p2.append(f"  Spot Long  (1D-1W): *{sig((sc1d*2+score(i1w))//3 if i1w else sc1d)}*")
    if on_fut:
        overall=(sc1h+sc4h+sc1d)//3
        p2.append(f"  Futures Signal:     *{sig(overall)}*")

    # FUTURES TRADE SETUP 25x
    if price and i4h:
        at4h=i4h.get("atr") or (price*0.02)  # fallback 2%
        overall_score=(sc1h+sc4h+sc1d)//3
        direction="LONG" if overall_score>0 else "SHORT"
        lvl=futures_levels(price, direction, at4h, 25)

        p2.append(f"\n🔴 *FUTURES SETUP — 25x Leverage*")
        p2.append(f"  ⚠️ EXTREME RISK — 25x leverage")
        p2.append(f"  Direction: {'🟢 LONG' if direction=='LONG' else '🔴 SHORT'}")
        p2.append(f"  Entry:    `${fmt(lvl.get('entry'),6)}`")
        p2.append(f"  Stop Loss:`${fmt(lvl.get('sl'),6)}` ({lvl.get('sl_pct',0):.2f}% | PnL: {lvl.get('pnl_sl',0):.0f}% margin)")
        p2.append(f"  Liq Zone: `${fmt(lvl.get('liq'),6)}` ← NEVER let it reach here")
        p2.append(f"  TP1:      `${fmt(lvl.get('tp1'),6)}` ({lvl.get('tp1_pct',0):.2f}% | PnL: +{lvl.get('pnl_tp1',0):.0f}% margin)")
        p2.append(f"  TP2:      `${fmt(lvl.get('tp2'),6)}` (PnL: +{lvl.get('pnl_tp2',0):.0f}% margin)")
        p2.append(f"  TP3:      `${fmt(lvl.get('tp3'),6)}` (let it run)")
        p2.append(f"  R/R Ratio: `{lvl.get('rr',0):.2f}:1`")
        p2.append(f"  Margin Use: MAX 3-5% of account")
        p2.append(f"  Signal Basis: {trend(i4h)}")
        if not all_agree:
            p2.append(f"  ⚠️ Mixed signals — reduce position size by 50%")

    pages.append("\n".join(p2))

    # PAGE 3 — GROQ AI (news + full analysis)
    p3=[]
    p3.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    p3.append("🤖 *GROQ AI — DEEP ANALYSIS*")
    p3.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    fr_val=float(prem.get("lastFundingRate",0))*100 if prem else 0
    oi_str=fmt(float(oi.get("openInterest",0)) if oi else 0,2)
    ls_str=f"{float(ls[0].get('longAccount',0))*100:.1f}% long" if ls else "N/A"
    btc_info=f"BTC ${fmt(float(btc_t.get('lastPrice',0)),0)} ({float(btc_t.get('priceChangePercent',0)):+.2f}%)" if btc_t and isinstance(btc_t,dict) else "N/A"
    fg_info=f"{fg['data'][0]['value']}/100 — {fg['data'][0]['value_classification']}" if fg and isinstance(fg,dict) and "data" in fg else "N/A"
    oi_chg="N/A"
    if oih and len(oih)>=2:
        ov=[float(x.get("sumOpenInterest",0)) for x in oih]
        oi_chg=f"{((ov[-1]-ov[0])/ov[0]*100):+.2f}%" if ov[0] else "N/A"

    ctx=(
        f"Coin: {coin}/USDT | Price: ${fmt(price,6)}\n"
        f"24h Change: {float(spot_t.get('priceChangePercent',0) if spot_t else 0):+.2f}%\n"
        f"24h Vol: {fmt(float(spot_t.get('quoteVolume',0) if spot_t else 0),0)} USDT\n"
        f"BTC Context: {btc_info}\n"
        f"Fear & Greed Index: {fg_info}\n"
        f"Futures Available: {on_fut}\n"
        f"Funding Rate: {fr_val:.4f}%\n"
        f"Open Interest: {oi_str} {coin} (12h change: {oi_chg})\n"
        f"Long/Short: {ls_str}\n"
        f"1H Signal: {sig(sc1h)} | Trend: {trend(i1h)}\n"
        f"4H Signal: {sig(sc4h)} | Trend: {trend(i4h)}\n"
        f"1D Signal: {sig(sc1d)} | Trend: {trend(i1d)}\n"
        f"RSI 1H: {i1h.get('rsi','N/A')} | 4H: {i4h.get('rsi','N/A')} | 1D: {i1d.get('rsi','N/A')}\n"
        f"ATR 4H: {fmt(i4h.get('atr'),6)}\n"
        f"BB Position 4H: {'Lower' if i4h.get('cur',0)<=i4h.get('bl',0) else ('Upper' if i4h.get('cur',0)>=i4h.get('bu',0) else 'Middle')}"
    )

    async with aiohttp.ClientSession() as s2:
        ai=await groq_ai(s2, coin, ctx)

    p3.append(ai)
    p3.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    p3.append("⚠️ _Not financial advice. 25x = extreme risk. DYOR._")
    pages.append("\n".join(p3))
    return pages

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT: return
    text=update.message.text or ""
    cmd=text.split()[0].lstrip("/").split("@")[0].strip()
    if cmd.lower() in ("start","help"):
        await update.message.reply_text(
            "👋 *Crypto Analysis Bot v6*\n\n"
            "Type `/` + coin: `/BTC` `/ETH` `/SOL`\n\n"
            "📊 *What you get:*\n"
            "• BTC market + Fear & Greed Index\n"
            "• Price ranges: 1H/2H/4H/12H/1D/3D/1W/1M\n"
            "• Futures: OI, Funding, L/S, Taker ratio\n"
            "• RSI, EMA, MACD, BB, ATR, VWAP\n"
            "• Trend analysis (1H/4H/1D/1W)\n"
            "• 🔴 *25x Futures setup* with SL/TP/Liq\n"
            "• 🤖 Groq AI: News + pump/dump + signals",
            parse_mode="Markdown")
        return
    if not cmd: return
    msg=await update.message.reply_text(
        f"⏳ *Deep Analysis: {cmd.upper()}/USDT*\n"
        f"_Fetching Binance + Fear&Greed + Groq AI..._\n"
        f"_Takes 20-30 seconds_",
        parse_mode="Markdown")
    try:
        pages=await build(cmd)
        await msg.delete()
        for i,page in enumerate(pages):
            if page.strip():
                await update.message.reply_text(page.strip(), parse_mode="Markdown")
                if i < len(pages)-1: await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        try: await msg.edit_text(f"❌ Error: `{str(e)[:200]}`", parse_mode="Markdown")
        except: pass

def main():
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", handler))
    app.add_handler(CommandHandler("help", handler))
    app.add_handler(MessageHandler(filters.COMMAND, handler))
    logger.info("🚀 Cryptoo Bot v6 started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
