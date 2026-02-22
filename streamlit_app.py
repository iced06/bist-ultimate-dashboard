"""
ULTIMATE Turkish Stock Market Technical Analysis Dashboard
Multi-Timeframe Analysis with Sentiment Indicators - 400+ BIST Stocks
"""

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import borsapy as bp
from ta.volatility import BollingerBands
import ta
from datetime import date, datetime, timedelta
import os
import requests
import urllib3
from dotenv import load_dotenv

# Suppress SSL warnings for isyatirim API
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(
    page_title="BIST Technical Analysis",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

load_dotenv()

def get_is_mobile():
    """Detect narrow viewport via CSS class injection and provide responsive defaults."""
    return True  # We apply responsive CSS universally via media queries

st.markdown("""
<style>
    /* ---- Base (Desktop) Styles ---- */
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #2c3e50;
        text-align: center;
        padding: 1rem 0;
    }
    .status-box {
        padding: 1rem;
        border-radius: 0.5rem;
        text-align: center;
        margin: 1rem 0;
        font-weight: bold;
    }
    .status-realtime {
        background-color: #d4edda;
        color: #155724;
        border: 2px solid #c3e6cb;
    }
    .status-delayed {
        background-color: #fff3cd;
        color: #856404;
        border: 2px solid #ffeeba;
    }
    .sentiment-strong-bullish {
        background: linear-gradient(135deg, #00c851 0%, #007E33 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 0.5rem;
        text-align: center;
        font-size: 1.5rem;
        font-weight: bold;
        margin: 1rem 0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .sentiment-bullish {
        background: linear-gradient(135deg, #33b5e5 0%, #0099CC 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 0.5rem;
        text-align: center;
        font-size: 1.5rem;
        font-weight: bold;
        margin: 1rem 0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .sentiment-neutral {
        background: linear-gradient(135deg, #ffbb33 0%, #FF8800 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 0.5rem;
        text-align: center;
        font-size: 1.5rem;
        font-weight: bold;
        margin: 1rem 0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .sentiment-bearish {
        background: linear-gradient(135deg, #ff8800 0%, #CC0000 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 0.5rem;
        text-align: center;
        font-size: 1.5rem;
        font-weight: bold;
        margin: 1rem 0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .sentiment-strong-bearish {
        background: linear-gradient(135deg, #cc0000 0%, #990000 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 0.5rem;
        text-align: center;
        font-size: 1.5rem;
        font-weight: bold;
        margin: 1rem 0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .chosen-stock {
        background-color: #d1ecf1;
        border-left: 4px solid #0c5460;
        padding: 0.5rem;
        margin: 0.5rem 0;
    }
    .filter-info {
        background-color: #fff3cd;
        border-left: 4px solid #856404;
        padding: 1rem;
        margin: 1rem 0;
    }
    /* Mobile compact metric card */
    .mobile-metric {
        background: #f8f9fa;
        border-radius: 0.5rem;
        padding: 0.6rem 0.8rem;
        margin: 0.3rem 0;
        border-left: 3px solid #1f77b4;
    }
    .mobile-metric .label {
        font-size: 0.75rem;
        color: #666;
        margin: 0;
    }
    .mobile-metric .value {
        font-size: 1.1rem;
        font-weight: bold;
        color: #2c3e50;
        margin: 0;
    }
    .mobile-metric .delta {
        font-size: 0.8rem;
        margin: 0;
    }
    .mobile-metric .delta.positive { color: #28a745; }
    .mobile-metric .delta.negative { color: #dc3545; }
    
    /* Mobile score row */
    .mobile-score-row {
        display: flex;
        gap: 0.5rem;
        margin: 0.5rem 0;
    }
    .mobile-score-card {
        flex: 1;
        background: #f8f9fa;
        border-radius: 0.5rem;
        padding: 0.8rem;
        text-align: center;
        border: 1px solid #dee2e6;
    }
    .mobile-score-card .score-label {
        font-size: 0.7rem;
        color: #666;
        margin: 0 0 0.2rem 0;
    }
    .mobile-score-card .score-value {
        font-size: 1.4rem;
        font-weight: bold;
        margin: 0;
    }
    .mobile-score-card .score-max {
        font-size: 0.65rem;
        color: #999;
        margin: 0;
    }
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* ---- Mobile Overrides (iPhone / narrow screens) ---- */
    @media only screen and (max-width: 768px) {
        .main-header {
            font-size: 1.4rem;
            padding: 0.5rem 0;
        }
        .status-box {
            padding: 0.5rem;
            font-size: 0.85rem;
            margin: 0.5rem 0;
        }
        .sentiment-strong-bullish,
        .sentiment-bullish,
        .sentiment-neutral,
        .sentiment-bearish,
        .sentiment-strong-bearish {
            font-size: 1rem;
            padding: 0.8rem;
            margin: 0.5rem 0;
        }
        .sentiment-strong-bullish span,
        .sentiment-bullish span,
        .sentiment-neutral span,
        .sentiment-bearish span,
        .sentiment-strong-bearish span {
            font-size: 0.8rem !important;
        }
        .chosen-stock {
            padding: 0.4rem;
            margin: 0.3rem 0;
        }
        .chosen-stock h4 {
            font-size: 1rem;
            margin: 0.2rem 0;
        }
        /* Force Streamlit columns to stack vertically on mobile */
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
        }
        [data-testid="stHorizontalBlock"] > div {
            flex-basis: 100% !important;
            min-width: 100% !important;
        }
        /* Reduce padding in main content area */
        .block-container {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            padding-top: 1rem !important;
        }
        /* Make dataframes scrollable */
        [data-testid="stDataFrame"] {
            overflow-x: auto;
        }
        /* Compact metric widgets */
        [data-testid="stMetric"] {
            padding: 0.3rem 0;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.75rem !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.1rem !important;
        }
    }
</style>
""", unsafe_allow_html=True)

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'chosen_stocks' not in st.session_state:
    st.session_state.chosen_stocks = {}
if 'filter_chosen_only' not in st.session_state:
    st.session_state.filter_chosen_only = False
if 'current_timeframe' not in st.session_state:
    st.session_state.current_timeframe = "1d"
if 'market_summary' not in st.session_state:
    st.session_state.market_summary = {}

IMKB = [
    "ALBRK", "GARAN", "HALKB", "ISCTR", "SKBNK", "TSKB", "ICBCT", "KLNMA",
    "VAKBN", "YKBNK", "AKGRT", "ANHYT", "ANSGR", "AGESA", "TURSG", "RAYSG", 
    "CRDFA", "GARFA", "ISFIN", "LIDFA", "SEKFK", "ULUFA", "VAKFN", "A1CAP", 
    "GEDIK", "GLBMD", "INFO", "ISMEN", "OSMEN", "OYYAT", "TERA", "ALMAD", 
    "CVKMD",  "PRKME", "ALCAR", "BIENY", "BRSAN", 
    "CUSAN", "DNISI", "DOGUB", "EGSER", "ERBOS", "QUAGR", "INTEM", "KLKIM", 
    "KLSER", "KLMSN", "KUTPO", "PNLSN", "SAFKR", "ERCB", "SISE", "USAK", 
    "YYAPI", "AFYON", "AKCNS", "BTCIM", "BSOKE", "BOBET", "BUCIM", "CMBTN", 
    "CMENT", "CIMSA", "GOLTS", "KONYA", "OYAKC", "NIBAS", "NUHCM", "ARCLK", 
    "ARZUM", "SILVR", "VESBE", "VESTL", "BMSCH", "BMSTL", "EREGL", "IZMDC", 
    "KCAER", "KRDMA", "KRDMB", "KRDMD", "TUCLK", "YKSLN", "AHGAZ", "AKENR", 
    "AKFYE", "AKSEN", "AKSUE", "ALFAS", "ASTOR", "ARASE", "AYDEM", "AYEN",
    "BASGZ", "BIOEN", "CONSE", "CWENE", "CANTE", "EMKEL", "ENJSA", "ENERY", 
    "ESEN", "GWIND", "GEREL", "HUNER", "IZENR", "KARYE", "NATEN", "NTGAZ", 
    "MAGEN", "ODAS", "SMRTG", "TATEN", "ZEDUR", "ZOREN", "ATAKP", "AVOD", 
    "AEFES", "BANVT", "BYDNR", "BIGCH", "CCOLA", "DARDL", "EKIZ", "EKSUN", 
    "ELITE", "ERSU", "FADE", "FRIGO", "GOKNR", "KAYSE", "KENT", "KERVT", 
    "KNFRT", "KRSTL", "KRVGD", "KTSKR", "MERKO", "OFSYM", "ORCAY", "OYLUM", 
    "PENGD", "PETUN", "PINSU", "PNSUT", "SELGD", "SELVA", "SOKE", "TBORG", 
    "TATGD", "TUKAS", "ULKER", "ULUUN", "YYLGD", "BIMAS", "KIMMR", "GMTAS", 
    "SOKM", "BIZIM", "CRFSA", "MGROS", "AKYHO", "ALARK", "MARKA", "ATSYH", 
    "BRYAT", "COSMO", "DOHOL", "DERHL", "ECZYT", "ENKAI", "EUHOL", 
    "GLYHO", "GLRYH", "GSDHO", "HEDEF", "IEYHO", "IHLAS", "INVES", "KERVN", 
    "KLRHO", "KCHOL", "BERA", "MZHLD", "MMCAS", "METRO", "NTHOL", "OSTIM",
    "POLHO", "RALYH", "SAHOL", "TAVHL", "TKFEN", "UFUK", "VERUS", "AGHOL", 
    "YESIL", "UNLU", "ADESE",  "ALCTL", "ARDYZ", "ARENA", "INGRM", 
    "ASELS", "ATATP", "AZTEK", "DGATE", "DESPC", "EDATA", "FORTE", "HTTBT", 
    "KFEIN", "SDTTR", "SMART", "ESCOM", "FONET", "INDES", "KAREL", "KRONT",
    "LINK", "LOGO", "MANAS", "MTRKS", "MIATK", "MOBTL", "NETAS", "OBASE", 
    "PENTA", "TKNSA", "VBTYZ", "ARSAN", "BLCYT", "BRKO", "BRMEN", "BOSSA", 
    "DAGI", "DERIM", "DESA", "DIRIT", "EBEBK", "ENSRI", "HATEK", "ISSEN", 
    "KRTEK", "LUKSK", "MNDRS", "RUBNS", "SKTAS", "SNPAM", "SUNTK", "YATAS", 
    "YUNSA", "ADEL", "ANGEN", "ANELE", "BNTAS", "BRKVY", "BRLSM", "BURCE", 
    "BURVA", "BVSAN", "CEOEM", "DGNMO", "EMNIS", "EUPWR", "ESCAR", "FORMT", 
    "FLAP", "GESAN", "GLCVY", "GENTS", "HKTM", "IHEVA", "IHAAS", "IMASM", 
    "KTLEV", "KLSYN", "KONTR", "MACKO", "MAVI", "MAKIM", "MAKTK", "MEPET", 
    "ORGE", "PARSN", "TGSAS", "PRKAB", "PAPIL", "PCILT", "PKART", "PSDTC", 
    "SANEL", "SNICA", "SANKO", "SARKY", "SNKRN", "KUVVA", "OZSUB", "SONME", 
    "SUMAS", "SUWEN", "TLMAN", "ULUSE", "VAKKO", "YAPRK", "YAYLA", "YEOTK", 
    "AVHOL", "BEYAZ", "DENGE", "IZFAS", "IZINV", "MEGAP", "OZRDN", "PASEU", 
    "PAMEL", "POLTK", "RODRG", "ASUZU", "DOAS", "FROTO", "KARSN", "OTKAR", 
    "TOASO", "TMSN", "TTRAK", "BFREN", "BRISA", "CELHA", "CEMAS", "CEMTS", 
    "DOKTA", "DMSAS", "DITAS", "EGEEN", "FMIZP", "GOODY", "JANTS", "KATMR", 
    "AYGAZ", "CASA", "TUPRS", "TRCAS", "ACSEL", "AKSA", "ALKIM", "BAGFS", 
    "BAYRK", "BRKSN", "DYOBY", "EGGUB", "EGPRO", "EPLAS", "EUREN", "GUBRF", 
    "ISKPL", "KMPUR", "KOPOL", "KORDS", "KRPLS", "MRSHL", "MERCN", "PETKM", 
    "RNPOL", "SANFM", "SASA", "TARKM", "ALKA", "BAKAB", "BARMA", "DURDO", 
    "GEDZA", "GIPTA", "KAPLM", "KARTN", "KONKA", "MNDTR", "PRZMA", "SAMAT", 
    "TEZOL", "VKING", "HUBVC", "GOZDE", "HDFGS", "ISGSY", "PRDGS", "VERTU", 
    "DOBUR", "HURGZ", "IHGZT", "IHYAY", "AYCES", "AVTUR", "ETILR", "MAALT", 
    "METUR", "PKENT", "TEKTU", "ULAS", "CLEBI", "GSDDE", "GRSEL", "GZNMI", 
    "PGSUS", "PLTUR", "RYSAS", "LIDER", "TUREX", "THYAO", "TCELL", "TTKOM", 
    "DEVA", "ECILC", "GENIL", "MEDTR", "MPARK", "EGEPO", "ONCSM", "RTALB", 
    "SELEC", "TNZTP", "TRILC", "ATLAS"
]
IMKB = sorted(list(set(IMKB)))

# BIST 30 Index constituents (Q1 2026 period, updated quarterly by Borsa Istanbul)
BIST_30 = sorted([
    "AKBNK", "ARCLK", "ASELS", "BIMAS", "EKGYO", "ENKAI", "EREGL",
    "FROTO", "GARAN", "GUBRF", "HEKTS", "ISCTR", "KCHOL", "KOZAA",
    "KOZAL", "KRDMD", "MGROS", "ODAS", "PETKM", "PGSUS", "SAHOL",
    "SASA", "SISE", "TAVHL", "TCELL", "THYAO", "TKFEN", "TOASO",
    "TUPRS", "YKBNK",
])

# BIST 100 Index constituents (Q1 2026 period)
BIST_100 = sorted([
    # BIST 30 stocks (all included in BIST 100)
    "AKBNK", "ARCLK", "ASELS", "BIMAS", "EKGYO", "ENKAI", "EREGL",
    "FROTO", "GARAN", "GUBRF", "HEKTS", "ISCTR", "KCHOL", "KOZAA",
    "KOZAL", "KRDMD", "MGROS", "ODAS", "PETKM", "PGSUS", "SAHOL",
    "SASA", "SISE", "TAVHL", "TCELL", "THYAO", "TKFEN", "TOASO",
    "TUPRS", "YKBNK",
    # Additional BIST 50 stocks
    "AEFES", "AGESA", "AKFGY", "AKSA", "AKSEN", "ALFAS", "ASELSA",
    "BERA", "BRSAN", "CCOLA", "CIMSA", "DOAS", "DOHOL", "EGEEN",
    "ENJSA", "GESAN", "HALKB", "KORDS", "KONTR", "MAVI",
    # Additional BIST 100 stocks
    "ADEL", "AGHOL", "AHGAZ", "AKCNS", "ALARK", "ALBRK", "ALKIM",
    "ANSGR", "ASTOR", "AYDEM", "AYGAZ", "BAGFS", "BASGZ", "BTCIM",
    "BUCIM", "CASA", "CWENE", "DEVA", "ECILC", "ECZYT", "EGPRO",
    "ENERY", "EUREN", "FORTE", "GEREL", "GLYHO", "GOODY", "GOZDE",
    "GSDHO", "IEYHO", "INDES", "IPEKE", "ISGYO", "JANTS", "KARTN",
    "KATMR", "KENT", "KERVN", "KLKIM", "KMPUR", "KNFRT", "LOGO",
    "MAGEN", "MPARK", "NETAS", "NTHOL", "NTGAZ", "OTKAR", "OYAKC",
    "OZKGY", "POLHO", "QUAGR", "SELEC", "SOKM", "SUNTK", "TATGD",
    "TMSN", "TRCAS", "TSKB", "TTKOM", "TTRAK", "TURSG", "ULKER",
    "VAKBN", "VESBE", "VESTL", "YEOTK", "ZOREN",
])

# Index filter mapping
INDEX_FILTERS = {
    "🏦 BIST 30": BIST_30,
    "📊 BIST 100": BIST_100,
    "📈 All Stocks": IMKB,
}

TIMEFRAMES = {
    "1m": {"label": "1 Minute", "days": 1, "auth_required": True},
    "5m": {"label": "5 Minutes", "days": 5, "auth_required": True},
    "15m": {"label": "15 Minutes", "days": 7, "auth_required": True},
    "30m": {"label": "30 Minutes", "days": 14, "auth_required": True},
    "1h": {"label": "1 Hour", "days": 30, "auth_required": True},
    "4h": {"label": "4 Hours", "days": 90, "auth_required": True},
    "1d": {"label": "Daily", "days": 365, "auth_required": False},
    "1wk": {"label": "Weekly", "days": 730, "auth_required": False},
}

# Plotly config optimized for mobile touch interaction
PLOTLY_CONFIG = {
    'displayModeBar': False,  # Hide toolbar on mobile (saves space)
    'scrollZoom': False,      # Prevent accidental zoom on touch scroll
    'responsive': True,
}

def calculate_sentiment(ind_score, vol_score, rsi, macd_diff, price_change_pct):
    score = 0
    if ind_score >= 6: score += 4
    elif ind_score >= 4: score += 2
    elif ind_score >= 2: score += 0
    elif ind_score >= 1: score -= 2
    else: score -= 4
    if vol_score > 1.5: score += 2
    elif vol_score > 0.7: score += 1
    elif vol_score < 0.5: score -= 1
    if rsi < 30: score += 2
    elif rsi < 40: score += 1
    elif rsi > 70: score -= 2
    elif rsi > 60: score -= 1
    if macd_diff > 0: score += 1
    else: score -= 1
    if price_change_pct > 5: score += 1
    elif price_change_pct < -5: score -= 1
    confidence = min(100, abs(score) / 10 * 100)
    if score >= 5: return "STRONG BULLISH", "🟢", "sentiment-strong-bullish", confidence
    elif score >= 2: return "BULLISH", "🔵", "sentiment-bullish", confidence
    elif score >= -1: return "NEUTRAL", "🟡", "sentiment-neutral", confidence
    elif score >= -4: return "BEARISH", "🟠", "sentiment-bearish", confidence
    else: return "STRONG BEARISH", "🔴", "sentiment-strong-bearish", confidence

@st.cache_resource
def setup_tradingview_auth():
    try:
        username = os.getenv("TRADINGVIEW_USERNAME")
        password = os.getenv("TRADINGVIEW_PASSWORD")
        if username and password:
            bp.set_tradingview_credentials(username=username, password=password)
            return True, "✅ Real-time"
        return False, "⚠️ 15-min delay"
    except:
        return False, "❌ Auth failed"

@st.cache_data(ttl=300)
def fetch_stock_data(symbol, start_date="2023-01-01", end_date=None, interval="1d"):
    try:
        if end_date is None:
            end_date = date.today().strftime("%Y-%m-%d")
        ticker = bp.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date, interval=interval)
        if df is not None and not df.empty:
            df.columns = [col.title() for col in df.columns]
        return df
    except:
        return None

def calculate_all_indicators(df):
    if df is None or df.empty:
        return None
    try:
        df["Return"] = df["Close"].diff()
        df["Return_pct"] = df["Close"].pct_change()
        df["Target_Cls"] = np.where(df.Return > 0, 1, 0)
        df["Vol_diff"] = df["Volume"].diff()
        df["Vol_change"] = df["Volume"].pct_change()
        indicator_bb = BollingerBands(close=df["Close"], window=20, window_dev=2)
        df["bb_bbm"] = indicator_bb.bollinger_mavg()
        df["bb_bbh"] = indicator_bb.bollinger_hband()
        df["bb_bbl"] = indicator_bb.bollinger_lband()
        df["MACD"] = ta.trend.macd(df["Close"], window_slow=26, window_fast=12, fillna=False)
        df["MACDS"] = ta.trend.macd_signal(df["Close"], window_sign=9, fillna=False)
        df["Diff"] = df["MACD"] - df["MACDS"]
        df["Buy_MACD"] = np.where((df["MACD"] > df["MACDS"]), 1, 0)
        df["Buy_MACDS"] = np.where((df["Buy_MACD"] > df["Buy_MACD"].shift(1)), 1, 0)
        df["Buy_MACDS2"] = np.where((df["Diff"] > 0) & (df["Buy_MACDS"] == 1), 2, df["Buy_MACDS"])
        df['VSMA15'] = ta.trend.sma_indicator(df['Volume'], window=15)
        df['OBV'] = ta.volume.on_balance_volume(df['Close'], df['Volume'])
        df["RSI"] = ta.momentum.rsi(df["Close"], window=14, fillna=False)
        df["Buy_RSI"] = np.where((df["RSI"] > 30), 1, 0)
        df["Buy_RSIS"] = np.where((df["Buy_RSI"] > df["Buy_RSI"].shift(1)), 1, 0)
        df["AO"] = ta.momentum.awesome_oscillator(df["High"], df["Low"], window1=5, window2=34, fillna=True)
        df["Buy_AO"] = np.where((df["AO"] > 0), 1, 0)
        df["Buy_AOS"] = np.where((df["Buy_AO"] > df["Buy_AO"].shift(1)), 1, 0)
        df["CCI"] = ta.trend.cci(df["High"], df["Low"], df["Close"], window=20, fillna=False)
        df["Buy_CCI"] = np.where((df["CCI"] > 0), 1, 0)
        df["Buy_CCIS"] = np.where((df["Buy_CCI"] > df["Buy_CCI"].shift(1)), 1, 0)
        df["EMA10"] = ta.trend.ema_indicator(df["Close"], window=10, fillna=False)
        df["EMA30"] = ta.trend.ema_indicator(df["Close"], window=30, fillna=False)
        df["Buy_EMA10"] = np.where((df["Close"] > df["EMA10"]), 1, 0)
        df["Buy_EMA10S"] = np.where((df["Buy_EMA10"] > df["Buy_EMA10"].shift(1)), 1, 0)
        df["Buy_EMA10_EMA30"] = np.where((df["EMA10"] > df["EMA30"]), 1, 0)
        df["Buy_EMA10_EMA30S"] = np.where((df["Buy_EMA10_EMA30"] > df["Buy_EMA10_EMA30"].shift(1)), 1, 0)
        df["Stochastic"] = ta.momentum.stoch_signal(df["High"], df["Low"], df["Close"], window=3, fillna=False)
        df["Stochastic_Buy"] = np.where((df["Stochastic"] > 20), 1, 0)
        df["Stochastic_BuyS"] = np.where((df["Stochastic_Buy"] > df["Stochastic_Buy"].shift(1)), 1, 0)
        df["KAMA"] = ta.momentum.kama(df["Close"], window=10, pow1=2, pow2=30, fillna=False)
        df["Buy_KAMA"] = np.where((df["Close"] > df["KAMA"]), 1, 0)
        df["Buy_KAMAS"] = np.where((df["Buy_KAMA"] > df["Buy_KAMA"].shift(1)), 1, 0)
        df['SMA5'] = ta.trend.sma_indicator(df['Close'], window=5)
        df['SMA22'] = ta.trend.sma_indicator(df['Close'], window=22)
        df['SMA50'] = ta.trend.sma_indicator(df['Close'], window=50)
        df["Buy_SMA5"] = np.where((df["Close"] > df["SMA5"]), 1, 0)
        df["Buy_SMA22"] = np.where((df["Close"] > df["SMA22"]), 1, 0)
        df["Buy_SMA50"] = np.where((df["Close"] > df["SMA50"]), 1, 0)
        df["Buy_SMA5S"] = np.where((df["Buy_SMA5"] > df["Buy_SMA5"].shift(1)), 1, 0)
        df["Buy_SMA22S"] = np.where((df["Buy_SMA22"] > df["Buy_SMA22"].shift(1)), 1, 0)
        df["Buy_SMA50S"] = np.where((df["Buy_SMA50"] > df["Buy_SMA50"].shift(1)), 1, 0)
        df["CMF"] = ta.volume.chaikin_money_flow(df["High"], df["Low"], df["Close"], df["Volume"], window=20, fillna=False)
        df["Buy_CMF"] = np.where((df["CMF"] > 0), 1, 0)
        df["Buy_CMFS"] = np.where((df["Buy_CMF"] > df["Buy_CMF"].shift(1)), 1, 0)
        return df
    except:
        return df

def calculate_original_scores(df):
    if df is None or df.empty:
        return 0, 0
    try:
        latest = df.iloc[-1]
        indicator_score_2 = (
            latest["Buy_MACDS2"] + latest["Buy_AOS"] + latest["Buy_EMA10_EMA30S"] + 
            latest["Buy_SMA5S"] + latest["Buy_SMA22S"] + latest["Buy_RSIS"] + 
            latest["Stochastic_BuyS"] + latest["Buy_CCIS"] + latest["Buy_KAMAS"] + latest["Buy_CMFS"]
        )
        volume_score_2 = latest["Volume"] / latest["VSMA15"]
        return float(indicator_score_2), float(volume_score_2)
    except:
        return 0, 0

def calculate_simplified_scores(df):
    if df is None or df.empty:
        return 0, 0
    latest = df.iloc[-1]
    score = 0
    if latest['RSI'] < 30: score += 1
    elif latest['RSI'] > 70: score -= 1
    if latest['MACD'] > latest['MACDS']: score += 1
    else: score -= 1
    if latest['Close'] > latest['SMA5'] > latest['SMA22']: score += 1
    elif latest['Close'] < latest['SMA5'] < latest['SMA22']: score -= 1
    score = max(0, min(5, score + 2.5))
    vr = latest["Volume"] / latest["VSMA15"]
    vs = 5 if vr > 2 else 4 if vr > 1.5 else 3 if vr > 1.2 else 2 if vr > 0.8 else 1
    return round(score, 1), round(vs, 1)

def screen_chosen_stocks(stock_list, interval="1d"):
    chosen = []
    prog = st.progress(0)
    stat = st.empty()
    days = TIMEFRAMES[interval]["days"]
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    for i, s in enumerate(stock_list):
        stat.text(f"Screening {s}... ({i+1}/{len(stock_list)})")
        prog.progress((i + 1) / len(stock_list))
        try:
            df = fetch_stock_data(s, start_date=start_date, interval=interval)
            if df is not None and not df.empty:
                df = calculate_all_indicators(df)
                ind, vol = calculate_original_scores(df)
                if ind >= 3 and vol > 0.7:
                    chosen.append({'symbol': s, 'indicator_score_2': round(ind, 2), 'volume_score_2': round(vol, 2)})
        except:
            continue
    prog.empty()
    stat.empty()
    return chosen

def scan_market_summary(stock_list, interval="1d"):
    """Scan all stocks and return sentiment distribution + SMA50 stats."""
    sentiment_counts = {
        "STRONG BULLISH": [], "BULLISH": [], "NEUTRAL": [],
        "BEARISH": [], "STRONG BEARISH": [], "ERROR": []
    }
    above_sma50 = []
    below_sma50 = []
    sma50_na = []
    
    prog = st.progress(0)
    stat = st.empty()
    days = TIMEFRAMES[interval]["days"]
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    for i, s in enumerate(stock_list):
        stat.text(f"Scanning {s}... ({i+1}/{len(stock_list)})")
        prog.progress((i + 1) / len(stock_list))
        try:
            df = fetch_stock_data(s, start_date=start_date, interval=interval)
            if df is None or df.empty:
                sentiment_counts["ERROR"].append(s)
                sma50_na.append(s)
                continue
            df = calculate_all_indicators(df)
            ind2, vol2 = calculate_original_scores(df)
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            price_change_pct = ((latest['Close'] - prev['Close']) / prev['Close']) * 100 if len(df) > 1 else 0
            
            sentiment_text, _, _, confidence = calculate_sentiment(
                ind2, vol2, latest['RSI'], latest['Diff'], price_change_pct
            )
            sentiment_counts[sentiment_text].append(s)
            
            # SMA50 check
            if pd.notna(latest.get('SMA50', np.nan)):
                if latest['Close'] > latest['SMA50']:
                    above_sma50.append(s)
                else:
                    below_sma50.append(s)
            else:
                sma50_na.append(s)
        except:
            sentiment_counts["ERROR"].append(s)
            sma50_na.append(s)
            continue
    
    prog.empty()
    stat.empty()
    return sentiment_counts, above_sma50, below_sma50, sma50_na

def create_gauge(v, t, m=5):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=v, title={'text': t, 'font': {'size': 16}},
        gauge={'axis': {'range': [None, m]}, 'bar': {'color': "#1f77b4"},
               'steps': [{'range': [0, 2], 'color': "#ffcccc"}, 
                        {'range': [2, 3.5], 'color': "#ffffcc"}, 
                        {'range': [3.5, m], 'color': "#ccffcc"}]}
    ))
    fig.update_layout(height=180, margin=dict(l=10, r=10, t=30, b=10))
    return fig

def create_candlestick(df, s):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'))
    fig.add_trace(go.Scatter(x=df.index, y=df['bb_bbh'], mode='lines', line=dict(color='rgba(255,0,0,0.5)', width=1), name='BB Upper'))
    fig.add_trace(go.Scatter(x=df.index, y=df['bb_bbl'], mode='lines', line=dict(color='rgba(0,0,255,0.5)', width=1), name='BB Lower', fill='tonexty', fillcolor='rgba(200,200,200,0.2)'))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA5'], mode='lines', line=dict(color='orange', width=2), name='SMA 5'))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA22'], mode='lines', line=dict(color='green', width=2), name='SMA 22'))
    fig.update_layout(title=f"{s} - Price Chart", height=350, xaxis_rangeslider_visible=False,
                      margin=dict(l=40, r=20, t=40, b=80),
                      legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=10)))
    return fig

def create_volume_chart(df):
    fig = go.Figure()
    colors = ['red' if df['Close'].iloc[i] < df['Open'].iloc[i] else 'green' for i in range(len(df))]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='Volume', marker_color=colors))
    fig.add_trace(go.Scatter(x=df.index, y=df['VSMA15'], mode='lines', line=dict(color='blue', width=2), name='Volume SMA 15'))
    fig.update_layout(title="Volume Analysis", xaxis_title="Date/Time", yaxis_title="Volume", height=250,
                      margin=dict(l=40, r=20, t=40, b=70),
                      legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, font=dict(size=10)))
    return fig

def create_macd_chart(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], mode='lines', line=dict(color='blue', width=2), name='MACD'))
    fig.add_trace(go.Scatter(x=df.index, y=df['MACDS'], mode='lines', line=dict(color='red', width=2), name='Signal'))
    colors = ['green' if val > 0 else 'red' for val in df['Diff']]
    fig.add_trace(go.Bar(x=df.index, y=df['Diff'], name='Histogram', marker_color=colors))
    fig.update_layout(title="MACD Indicator", xaxis_title="Date/Time", yaxis_title="Value", height=250,
                      margin=dict(l=40, r=20, t=40, b=70),
                      legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, font=dict(size=10)))
    return fig

def create_rsi_chart(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], mode='lines', line=dict(color='purple', width=2), name='RSI'))
    fig.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought (70)")
    fig.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold (30)")
    fig.update_layout(title="RSI Indicator", xaxis_title="Date/Time", yaxis_title="RSI", yaxis_range=[0, 100], height=250,
                      margin=dict(l=40, r=20, t=40, b=70),
                      legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, font=dict(size=10)))
    return fig

# =============================================================================
# FUNDAMENTAL DATA - İş Yatırım Balance Sheet API
# =============================================================================

ISYATIRIM_API_URL = 'https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo'

# Key balance sheet items to display — matched by DESCRIPTION keywords (Turkish)
# because İş Yatırım item codes vary by company type (manufacturing, financial, holding, etc.)
# Format: logical_key -> (English label, [Turkish keyword patterns to match itemDescTr])
KEY_ITEMS_BY_DESC = {
    "total_assets":        ("Total Assets",              ["toplam varlıklar", "varlıklar toplamı"]),
    "current_assets":      ("Current Assets",            ["dönen varlıklar"]),
    "noncurrent_assets":   ("Non-Current Assets",        ["duran varlıklar"]),
    "cash":                ("Cash & Equivalents",        ["nakit ve nakit benzerleri"]),
    "trade_recv_short":    ("Trade Receivables (Short)",  ["ticari alacaklar"]),
    "inventories":         ("Inventories",               ["stoklar"]),
    "ppe":                 ("Property, Plant & Equip.",   ["maddi duran varlıklar"]),
    "total_liab_equity":   ("Total Liabilities + Equity", ["kaynaklar toplamı", "toplam kaynaklar"]),
    "current_liabilities": ("Current Liabilities",       ["kısa vadeli yükümlülükler"]),
    "noncurrent_liab":     ("Non-Current Liabilities",   ["uzun vadeli yükümlülükler"]),
    "short_borrowings":    ("Short-term Borrowings",     ["kısa vadeli borçlanmalar"]),
    "long_borrowings":     ("Long-term Borrowings",      ["uzun vadeli borçlanmalar"]),
    "total_equity":        ("Total Equity",              ["özkaynaklar", "özkaynak"]),
    "paid_in_capital":     ("Paid-in Capital",           ["ödenmiş sermaye", "çıkarılmış sermaye"]),
}

KEY_INCOME_BY_DESC = {
    "revenue":             ("Revenue / Sales",           ["hasılat", "satış gelirleri"]),
    "cost_of_sales":       ("Cost of Sales",             ["satışların maliyeti"]),
    "gross_profit":        ("Gross Profit",              ["brüt kar", "brüt kâr", "ticari faaliyetlerden brüt"]),
    "depreciation":        ("Depreciation & Amort.",     ["amortisman"]),
    "operating_profit":    ("Operating Profit / EBIT",   ["esas faaliyet karı", "esas faaliyet kârı", "sürdürülen faaliyetler"]),
    "financial_income":    ("Financial Income",          ["finansman gelirleri", "finansal gelirler"]),
    "financial_expense":   ("Financial Expenses",        ["finansman giderleri", "finansal giderler"]),
    "profit_before_tax":   ("Profit Before Tax",         ["vergi öncesi kar", "vergi öncesi kâr", "sürdürülen faaliyetler vergi öncesi"]),
    "net_profit":          ("Net Profit",                ["dönem karı (zararı)", "dönem net karı", "dönem kârı"]),
    "net_profit_parent":   ("Net Profit (Parent)",       ["ana ortaklık payları", "ana ortaklık net"]),
}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_balance_sheet(symbol, years=None):
    """
    Fetch quarterly balance sheet data from İş Yatırım API.
    Returns a dict of {year: raw_json_response} for each year.
    
    Includes retry logic (2 attempts per year) and does NOT cache empty results
    so a transient API failure doesn't poison the cache for an hour.
    """
    if years is None:
        current_year = datetime.now().year
        years = list(range(current_year, current_year - 5, -1))
    
    all_data = {}
    last_error = None
    
    for y in years:
        params = {
            "companyCode": symbol,
            "exchange": "TRY",
            "financialGroup": "XI_29",
            "year1": y, "period1": "12",
            "year2": y, "period2": "9",
            "year3": y, "period3": "6",
            "year4": y, "period4": "3",
        }
        
        # Retry up to 2 times per year
        for attempt in range(2):
            try:
                resp = requests.get(
                    ISYATIRIM_API_URL, verify=False, params=params,
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
                )
                if resp.status_code == 200:
                    json_data = resp.json()
                    if "value" in json_data and json_data["value"]:
                        all_data[y] = json_data["value"]
                        break  # Success, move to next year
                    else:
                        # API returned 200 but empty data — may be valid (no data for this year)
                        break
                elif resp.status_code == 503 or resp.status_code == 429:
                    # Server overloaded or rate-limited — wait and retry
                    import time
                    time.sleep(2)
                    continue
                else:
                    last_error = f"HTTP {resp.status_code}"
                    break
            except requests.exceptions.Timeout:
                last_error = "Request timeout"
                if attempt == 0:
                    import time
                    time.sleep(1)
                    continue
            except requests.exceptions.ConnectionError:
                last_error = "Connection error (check internet)"
                break
            except Exception as e:
                last_error = str(e)
                break
    
    # CRITICAL: If we got NO data at all, raise an exception to prevent
    # st.cache_data from caching the empty result. The next call will retry.
    if not all_data:
        error_msg = f"İş Yatırım API returned no data for {symbol}"
        if last_error:
            error_msg += f" (last error: {last_error})"
        raise Exception(error_msg)
    
    return all_data


@st.cache_data(ttl=600, show_spinner=False)
def fetch_valuation_data(symbol):
    """
    Fetch current market data for valuation ratios from İş Yatırım's temel göstergeler API.
    Returns dict with market_cap, price, shares_outstanding, etc.
    """
    url = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/OneEndeks498498"
    params = {"companyCode": symbol, "exchange": "TRY", "dataType": "2"}
    try:
        resp = requests.get(url, verify=False, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if "value" in data and data["value"]:
                result = {}
                for item in data["value"]:
                    code = item.get("itemCode", "")
                    val = item.get("value1")
                    desc = item.get("itemDescTr", "")
                    if val is not None:
                        result[code] = {"value": val, "desc": desc}
                return result
    except Exception:
        pass
    
    # Fallback: try hisse temel endpoint
    url2 = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/HisseTekil"
    params2 = {"hession": f"{symbol}.E.BIST"}
    try:
        resp2 = requests.get(url2, verify=False, params=params2, timeout=15)
        if resp2.status_code == 200:
            return resp2.json()
    except Exception:
        pass
    return None


def calculate_valuation_metrics(df_full, current_price, valuation_data=None):
    """
    Calculate P/E, P/B (F/K, PD/DD), and EV/EBITDA from financial data and current price.
    
    Args:
        df_full: Full parsed balance sheet DataFrame
        current_price: Current stock price (TL)
        valuation_data: Optional dict from fetch_valuation_data
    
    Returns: dict with pe_ratio, pb_ratio, ev_ebitda, and component values
    """
    if df_full is None or df_full.empty or current_price is None or current_price <= 0:
        return {}
    
    # Helper to get value by logical key for a period
    def get_val(logical_key, period):
        if "LogicalKey" not in df_full.columns:
            return None
        match = df_full[df_full["LogicalKey"] == logical_key]
        if match.empty or period not in match.columns:
            return None
        v = match[period].iloc[0]
        return float(v) if v is not None and pd.notna(v) else None
    
    periods = [c for c in df_full.columns if "/" in c]
    if not periods:
        return {}
    
    latest = periods[0]  # Most recent period (empty ones already stripped)
    
    # Get key values from latest period
    total_equity = get_val("total_equity", latest)
    paid_in_capital = get_val("paid_in_capital", latest)
    net_profit = get_val("net_profit_parent", latest) or get_val("net_profit", latest)
    operating_profit = get_val("operating_profit", latest)
    depreciation = get_val("depreciation", latest)
    short_debt = get_val("short_borrowings", latest)
    long_debt = get_val("long_borrowings", latest)
    cash = get_val("cash", latest)
    
    result = {"period": latest}
    
    # Estimate shares outstanding from paid-in capital (BIST stocks are typically 1 TL par)
    # Paid-in capital in thousands TL = shares in thousands
    shares = None
    if paid_in_capital and paid_in_capital > 0:
        shares = paid_in_capital * 1000  # Convert from thousands to actual shares
        result["shares"] = shares
    
    market_cap = None
    if shares and current_price:
        market_cap = current_price * shares
        result["market_cap"] = market_cap
        result["market_cap_display"] = market_cap
    
    # P/E Ratio (F/K) — use trailing 12 months net profit
    # The annual (period 12) figure is TTM; for interim periods we need to annualize
    ttm_net_profit = None
    # Try to find the latest annual (Q4/12) figure first
    annual_periods = [p for p in periods if p.endswith("/12")]
    if annual_periods:
        ttm_net_profit = get_val("net_profit_parent", annual_periods[0]) or get_val("net_profit", annual_periods[0])
    
    # If latest period is not annual, try to compute TTM
    if ttm_net_profit is None and net_profit is not None:
        # Get which quarter we're in
        quarter = latest.split("/")[1]
        if quarter == "12":
            ttm_net_profit = net_profit
        elif quarter == "9":
            # 9-month figure, annualize: net_profit * 12/9
            ttm_net_profit = net_profit * 12 / 9
        elif quarter == "6":
            ttm_net_profit = net_profit * 12 / 6
        elif quarter == "3":
            ttm_net_profit = net_profit * 12 / 3
    
    if market_cap and ttm_net_profit and ttm_net_profit != 0:
        # ttm_net_profit is in thousands TL from the API
        pe = market_cap / (ttm_net_profit * 1000)
        result["pe_ratio"] = round(pe, 2)
        result["ttm_net_profit"] = ttm_net_profit
    
    # P/B Ratio (PD/DD) — Market Cap / Total Equity
    if market_cap and total_equity and total_equity != 0:
        pb = market_cap / (total_equity * 1000)
        result["pb_ratio"] = round(pb, 2)
        result["total_equity"] = total_equity
    
    # EBITDA = Operating Profit + Depreciation & Amortization
    ebitda = None
    if operating_profit is not None:
        da = abs(depreciation) if depreciation is not None else 0
        ebitda = operating_profit + da
        result["ebitda_period"] = ebitda
    
    # TTM EBITDA (annualize if needed)
    ttm_ebitda = None
    if ebitda is not None:
        quarter = latest.split("/")[1]
        if quarter == "12":
            ttm_ebitda = ebitda
        elif quarter == "9":
            ttm_ebitda = ebitda * 12 / 9
        elif quarter == "6":
            ttm_ebitda = ebitda * 12 / 6
        elif quarter == "3":
            ttm_ebitda = ebitda * 12 / 3
    
    # EV = Market Cap + Total Debt - Cash
    total_debt = ((short_debt or 0) + (long_debt or 0)) * 1000  # convert to TL
    cash_val = (cash or 0) * 1000
    
    if market_cap:
        ev = market_cap + total_debt - cash_val
        result["enterprise_value"] = ev
        
        if ttm_ebitda and ttm_ebitda != 0:
            ev_ebitda = ev / (ttm_ebitda * 1000)
            result["ev_ebitda"] = round(ev_ebitda, 2)
            result["ttm_ebitda"] = ttm_ebitda
    
    return result


def _match_item_by_desc(item_desc_tr, keyword_patterns):
    """Check if an item's Turkish description matches any of the keyword patterns."""
    desc_lower = item_desc_tr.lower().strip()
    for pattern in keyword_patterns:
        if pattern.lower() in desc_lower:
            return True
    return False


def _build_code_map(raw_data):
    """
    Scan the actual API data and build a mapping:  logical_key -> actual_itemCode
    by matching Turkish descriptions. This handles the varying codes across company types.
    """
    all_items_by_desc = {**KEY_ITEMS_BY_DESC, **KEY_INCOME_BY_DESC}
    code_map = {}  # logical_key -> (itemCode, itemDescTr)
    
    # Use data from the most recent year
    sorted_years = sorted(raw_data.keys(), reverse=True)
    items = raw_data[sorted_years[0]]
    
    for logical_key, (en_label, patterns) in all_items_by_desc.items():
        for item in items:
            desc_tr = item.get("itemDescTr", "")
            actual_code = item.get("itemCode", "")
            if _match_item_by_desc(desc_tr, patterns):
                # Prefer the first (most specific) match; skip if already matched
                if logical_key not in code_map:
                    code_map[logical_key] = (actual_code, desc_tr)
                break
    
    return code_map


def parse_balance_sheet_to_df(raw_data, item_filter=None):
    """
    Parse raw İş Yatırım JSON into a clean DataFrame.
    Columns = periods (e.g. "2025/9", "2025/6", ...), Rows = line items.
    
    If item_filter is provided (dict of logical_key -> (en_label, patterns)),
    only include matched items using description-based fuzzy matching.
    
    Automatically strips out periods where ALL values are null (quarter not yet filed).
    """
    if not raw_data:
        return None
    
    sorted_years = sorted(raw_data.keys(), reverse=True)
    
    # Build code map from actual data if filter provided
    code_map = _build_code_map(raw_data) if item_filter else None
    
    # Determine which actual codes to include
    target_codes = None
    if item_filter and code_map:
        target_codes = {info[0] for info in code_map.values()}  # set of actual itemCodes
    
    rows = []
    first_year_data = raw_data[sorted_years[0]]
    
    for item in first_year_data:
        actual_code = item.get("itemCode", "")
        desc_tr = item.get("itemDescTr", "")
        
        # If filter is active, only include items whose actual code was matched
        if target_codes and actual_code not in target_codes:
            continue
        
        # Find the logical key for this code (for labeling)
        logical_key = ""
        en_label = ""
        if code_map:
            for lk, (ac, _) in code_map.items():
                if ac == actual_code:
                    logical_key = lk
                    all_items = {**KEY_ITEMS_BY_DESC, **KEY_INCOME_BY_DESC}
                    en_label = all_items.get(lk, ("", []))[0]
                    break
        
        row = {
            "Code": actual_code,
            "LogicalKey": logical_key,
            "Item (TR)": desc_tr,
            "Item (EN)": en_label,
        }
        
        # Fill values from each year
        for y in sorted_years:
            year_data = raw_data.get(y, [])
            matching = [i for i in year_data if i.get("itemCode") == actual_code]
            if matching:
                m = matching[0]
                row[f"{y}/12"] = m.get("value1")
                row[f"{y}/9"] = m.get("value2")
                row[f"{y}/6"] = m.get("value3")
                row[f"{y}/3"] = m.get("value4")
            else:
                for q in ["12", "9", "6", "3"]:
                    row[f"{y}/{q}"] = None
        
        rows.append(row)
    
    if not rows:
        return None
    
    df = pd.DataFrame(rows)
    
    # ── Strip empty periods (quarter not yet filed) ──
    period_cols = [c for c in df.columns if "/" in c]
    non_empty_periods = []
    for pc in period_cols:
        col_vals = pd.to_numeric(df[pc], errors='coerce')
        if col_vals.notna().any():
            non_empty_periods.append(pc)
    
    # Keep only non-empty period columns
    meta_cols = [c for c in df.columns if "/" not in c]
    df = df[meta_cols + non_empty_periods]
    
    return df


def calculate_fundamentals(df_bs):
    """
    Calculate key financial ratios from the parsed balance sheet DataFrame.
    Uses the 'LogicalKey' column for reliable item lookup regardless of API codes.
    Returns a dict of ratio name -> list of (period, value) tuples.
    """
    if df_bs is None or df_bs.empty:
        return None
    
    # Helper to get a value by logical key for a given period
    def get_val(logical_key, period):
        if "LogicalKey" not in df_bs.columns:
            return None
        match = df_bs[df_bs["LogicalKey"] == logical_key]
        if match.empty or period not in match.columns:
            return None
        v = match[period].iloc[0]
        return float(v) if v is not None and pd.notna(v) else None
    
    # Get available periods (exclude metadata columns)
    periods = [c for c in df_bs.columns if "/" in c]
    
    ratios = {}
    
    for p in periods:
        total_assets = get_val("total_assets", p)
        current_assets = get_val("current_assets", p)
        current_liab = get_val("current_liabilities", p)
        total_equity = get_val("total_equity", p)
        short_debt = get_val("short_borrowings", p)
        long_debt = get_val("long_borrowings", p)
        net_profit = get_val("net_profit", p) or get_val("net_profit_parent", p)
        revenue = get_val("revenue", p)
        gross_profit = get_val("gross_profit", p)
        operating_profit = get_val("operating_profit", p)
        
        # Current Ratio
        if current_assets and current_liab and current_liab != 0:
            ratios.setdefault("Current Ratio", []).append((p, round(current_assets / current_liab, 2)))
        
        # Debt-to-Equity
        if short_debt is not None and long_debt is not None and total_equity and total_equity != 0:
            total_debt = (short_debt or 0) + (long_debt or 0)
            ratios.setdefault("Debt/Equity", []).append((p, round(total_debt / total_equity, 2)))
        
        # ROE (annualized from cumulative quarterly)
        if net_profit and total_equity and total_equity != 0:
            ratios.setdefault("ROE %", []).append((p, round(net_profit / total_equity * 100, 2)))
        
        # Net Profit Margin
        if net_profit and revenue and revenue != 0:
            ratios.setdefault("Net Margin %", []).append((p, round(net_profit / revenue * 100, 2)))
        
        # Gross Margin
        if gross_profit and revenue and revenue != 0:
            ratios.setdefault("Gross Margin %", []).append((p, round(gross_profit / revenue * 100, 2)))
        
        # Equity Ratio
        if total_equity and total_assets and total_assets != 0:
            ratios.setdefault("Equity Ratio %", []).append((p, round(total_equity / total_assets * 100, 2)))
    
    return ratios


def _make_quarterly_bar_chart(df_source, logical_key, title, color, fallback_key=None):
    """Helper: create a quarterly bar chart for a given item by LogicalKey."""
    row = df_source[df_source["LogicalKey"] == logical_key] if "LogicalKey" in df_source.columns else pd.DataFrame()
    if row.empty and fallback_key:
        row = df_source[df_source["LogicalKey"] == fallback_key] if "LogicalKey" in df_source.columns else pd.DataFrame()
    # Also try by Code as a last resort
    if row.empty:
        row = df_source[df_source["Code"] == logical_key]
    if row.empty and fallback_key:
        row = df_source[df_source["Code"] == fallback_key]
    if row.empty:
        return None
    
    period_cols = [c for c in df_source.columns if "/" in c]
    periods = list(reversed(period_cols))
    vals = []
    for c in periods:
        v = pd.to_numeric(row.iloc[0][c], errors='coerce')
        vals.append(v if pd.notna(v) else 0)
    
    # Color bars: positive = given color, negative = red
    bar_colors = [color if v >= 0 else "#dc3545" for v in vals]
    
    fig = go.Figure(go.Bar(
        x=periods, y=vals,
        marker_color=bar_colors,
        text=[f"{v/1000:,.0f}K" if abs(v) >= 1000 else f"{v:,.0f}" for v in vals],
        textposition='outside',
        textfont_size=8
    ))
    fig.update_layout(
        title=title,
        height=300,
        margin=dict(l=40, r=20, t=40, b=80),
        xaxis_tickangle=-45,
        xaxis_tickfont=dict(size=8),
        yaxis_title="TL (thousands)",
        legend=dict(orientation="h", yanchor="top", y=-0.25,
                    xanchor="center", x=0.5, font=dict(size=10)),
    )
    return fig


def display_balance_sheet(symbol, current_price=None):
    """Display balance sheet section for a stock in the Streamlit dashboard."""
    
    st.markdown("---")
    st.subheader(f"📑 Financials — {symbol}")
    st.caption("Source: İş Yatırım | Quarterly data, last 5 years")
    
    # Fetch with error handling — exceptions prevent caching of empty results
    raw_data = None
    fetch_error = None
    try:
        with st.spinner(f"Fetching financial data for {symbol}..."):
            raw_data = fetch_balance_sheet(symbol)
    except Exception as e:
        fetch_error = str(e)
    
    if not raw_data:
        st.warning(f"⚠️ No financial data available for **{symbol}**")
        if fetch_error:
            st.caption(f"Reason: {fetch_error}")
        
        st.markdown("""
        **Possible causes:**
        - İş Yatırım API may be temporarily down or rate-limiting requests
        - The stock may not have financial data in their system
        - Network/connection issue
        
        **Try:** Click the **🔄 Refresh** button in the sidebar, or wait a few minutes and try again.
        """)
        
        # Offer a manual retry button right here
        if st.button(f"🔄 Retry loading {symbol} financials", key=f"retry_fin_{symbol}"):
            # Clear only the balance sheet cache for this symbol
            fetch_balance_sheet.clear()
            st.rerun()
        return
    
    # Parse key items using description-based matching
    all_key_items = {**KEY_ITEMS_BY_DESC, **KEY_INCOME_BY_DESC}
    df_key = parse_balance_sheet_to_df(raw_data, item_filter=all_key_items)
    
    # Parse full balance sheet (no filter — includes all items, also gets LogicalKey mapped)
    df_full = parse_balance_sheet_to_df(raw_data, item_filter=all_key_items)
    
    # Calculate ratios
    ratios = calculate_fundamentals(df_full if df_full is not None else df_key)
    
    # ═══════════════════════════════════════════════════════════════════
    # VALUATION HEADER — P/E, P/B, EV/EBITDA
    # ═══════════════════════════════════════════════════════════════════
    if current_price and current_price > 0 and df_full is not None:
        valuation = calculate_valuation_metrics(df_full, current_price)
        
        if valuation:
            st.markdown("### 💹 Valuation Multiples")
            period_label = valuation.get("period", "")
            st.caption(f"Based on current price ₺{current_price:.2f} | Financial period: {period_label}")
            
            vc1, vc2, vc3 = st.columns(3)
            
            # P/E
            pe = valuation.get("pe_ratio")
            with vc1:
                if pe is not None:
                    pe_color = "#28a745" if pe < 15 else ("#ffc107" if pe < 25 else "#dc3545")
                    pe_label = "Cheap" if pe < 10 else ("Fair" if pe < 20 else ("Expensive" if pe < 35 else "Very High"))
                    st.markdown(f"""
                    <div class="mobile-score-card" style="border-top: 3px solid {pe_color};">
                        <p class="score-label">P/E Ratio (F/K)</p>
                        <p class="score-value" style="color:{pe_color}">{pe:.1f}x</p>
                        <p class="score-max">{pe_label}</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.metric("P/E (F/K)", "N/A")
            
            # P/B
            pb = valuation.get("pb_ratio")
            with vc2:
                if pb is not None:
                    pb_color = "#28a745" if pb < 1.5 else ("#ffc107" if pb < 3 else "#dc3545")
                    pb_label = "Below Book" if pb < 1 else ("Fair" if pb < 2 else ("Premium" if pb < 4 else "Very High"))
                    st.markdown(f"""
                    <div class="mobile-score-card" style="border-top: 3px solid {pb_color};">
                        <p class="score-label">P/B Ratio (PD/DD)</p>
                        <p class="score-value" style="color:{pb_color}">{pb:.2f}x</p>
                        <p class="score-max">{pb_label}</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.metric("P/B (PD/DD)", "N/A")
            
            # EV/EBITDA
            ev_ebitda = valuation.get("ev_ebitda")
            with vc3:
                if ev_ebitda is not None:
                    ev_color = "#28a745" if ev_ebitda < 8 else ("#ffc107" if ev_ebitda < 15 else "#dc3545")
                    ev_label = "Cheap" if ev_ebitda < 6 else ("Fair" if ev_ebitda < 12 else ("Expensive" if ev_ebitda < 20 else "Very High"))
                    st.markdown(f"""
                    <div class="mobile-score-card" style="border-top: 3px solid {ev_color};">
                        <p class="score-label">EV/EBITDA</p>
                        <p class="score-value" style="color:{ev_color}">{ev_ebitda:.1f}x</p>
                        <p class="score-max">{ev_label}</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.metric("EV/EBITDA", "N/A")
            
            # Market cap info line
            mc = valuation.get("market_cap")
            ev = valuation.get("enterprise_value")
            if mc:
                mc_str = f"₺{mc/1e9:,.2f}B" if mc >= 1e9 else f"₺{mc/1e6:,.0f}M"
                ev_str = f"₺{ev/1e9:,.2f}B" if ev and ev >= 1e9 else (f"₺{ev/1e6:,.0f}M" if ev else "N/A")
                st.caption(f"Market Cap: {mc_str} | Enterprise Value: {ev_str}")
    
    # ═══════════════════════════════════════════════════════════════════
    # QUARTERLY BAR CHARTS — Revenue, Gross Profit, EBITDA, Net Profit
    # ═══════════════════════════════════════════════════════════════════
    if df_full is not None:
        st.markdown("### 📊 Quarterly Financial Trends")
        
        # We need to compute EBITDA row (Operating Profit + D&A) and add it to df_full
        period_cols = [c for c in df_full.columns if "/" in c]
        
        # Build EBITDA row from operating_profit + |depreciation|
        op_row = df_full[df_full["LogicalKey"] == "operating_profit"] if "LogicalKey" in df_full.columns else pd.DataFrame()
        da_row = df_full[df_full["LogicalKey"] == "depreciation"] if "LogicalKey" in df_full.columns else pd.DataFrame()
        
        if not op_row.empty:
            ebitda_row_data = {"Code": "EBITDA_CALC", "LogicalKey": "ebitda", "Item (TR)": "EBITDA", "Item (EN)": "EBITDA"}
            for p in period_cols:
                op_val = pd.to_numeric(op_row.iloc[0].get(p), errors='coerce')
                da_val = pd.to_numeric(da_row.iloc[0].get(p), errors='coerce') if not da_row.empty else 0
                if pd.notna(op_val):
                    ebitda_row_data[p] = op_val + (abs(da_val) if pd.notna(da_val) else 0)
                else:
                    ebitda_row_data[p] = None
            df_full = pd.concat([df_full, pd.DataFrame([ebitda_row_data])], ignore_index=True)
        
        # 2x2 grid of bar charts
        ch_c1, ch_c2 = st.columns(2)
        
        with ch_c1:
            fig_rev = _make_quarterly_bar_chart(df_full, "revenue", "📈 Revenue (Hasılat)", "#17a2b8")
            if fig_rev:
                st.plotly_chart(fig_rev, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Revenue data not available")
        
        with ch_c2:
            fig_gp = _make_quarterly_bar_chart(df_full, "gross_profit", "📈 Gross Profit (Brüt Kar)", "#28a745")
            if fig_gp:
                st.plotly_chart(fig_gp, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Gross Profit data not available")
        
        ch_c3, ch_c4 = st.columns(2)
        
        with ch_c3:
            fig_ebitda = _make_quarterly_bar_chart(df_full, "ebitda", "📈 EBITDA", "#fd7e14")
            if fig_ebitda is None:
                # Fallback: show Operating Profit if EBITDA calc failed
                fig_ebitda = _make_quarterly_bar_chart(df_full, "operating_profit", "📈 Operating Profit (EBIT)", "#fd7e14")
            if fig_ebitda:
                st.plotly_chart(fig_ebitda, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("EBITDA data not available")
        
        with ch_c4:
            fig_np = _make_quarterly_bar_chart(df_full, "net_profit_parent", "📈 Net Profit (Net Kar)", "#6f42c1", fallback_key="net_profit")
            if fig_np:
                st.plotly_chart(fig_np, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Net Profit data not available")
    
    # ═══════════════════════════════════════════════════════════════════
    # DETAILED TABS — Ratios, Balance Sheet, Income Statement, Full Data
    # ═══════════════════════════════════════════════════════════════════
    tab_ratios, tab_bs, tab_is, tab_full = st.tabs([
        "📊 Key Ratios", "🏦 Balance Sheet", "💰 Income Statement", "📋 Full Data"
    ])
    
    # ── TAB 1: Key Ratios ──
    with tab_ratios:
        if ratios:
            # Summary cards for latest period
            first_ratio_periods = list(ratios.values())[0] if ratios else []
            if first_ratio_periods:
                latest_period = first_ratio_periods[0][0]
                st.markdown(f"**Latest Period: {latest_period}**")
                
                # Display ratio cards in a grid
                ratio_names = list(ratios.keys())
                for i in range(0, len(ratio_names), 3):
                    cols = st.columns(min(3, len(ratio_names) - i))
                    for j, col in enumerate(cols):
                        if i + j < len(ratio_names):
                            name = ratio_names[i + j]
                            values = ratios[name]
                            latest_val = values[0][1] if values else "N/A"
                            prev_val = values[1][1] if len(values) > 1 else None
                            
                            delta = None
                            if prev_val is not None and latest_val != "N/A":
                                delta = f"{latest_val - prev_val:+.2f}"
                            
                            with col:
                                st.metric(name, f"{latest_val}", delta=delta)
            
            # Ratio trend charts
            st.markdown("#### 📈 Ratio Trends")
            for ratio_name, values in ratios.items():
                if len(values) >= 2:
                    periods_r = [v[0] for v in reversed(values)]
                    vals_r = [v[1] for v in reversed(values)]
                    
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=periods_r, y=vals_r,
                        mode='lines+markers',
                        name=ratio_name,
                        line=dict(width=2),
                        marker=dict(size=6)
                    ))
                    
                    # Add reference lines for certain ratios
                    if ratio_name == "Current Ratio":
                        fig.add_hline(y=1.0, line_dash="dash", line_color="red",
                                      annotation_text="Min Healthy (1.0)")
                    elif ratio_name == "Debt/Equity":
                        fig.add_hline(y=1.0, line_dash="dash", line_color="orange",
                                      annotation_text="Caution (1.0)")
                    
                    fig.update_layout(
                        title=ratio_name,
                        height=250,
                        margin=dict(l=40, r=20, t=40, b=70),
                        legend=dict(orientation="h", yanchor="top", y=-0.2,
                                    xanchor="center", x=0.5, font=dict(size=10)),
                        xaxis_tickangle=-45,
                        xaxis_tickfont=dict(size=8)
                    )
                    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        else:
            st.info("Ratio data could not be calculated for this stock.")
    
    # ── TAB 2: Balance Sheet Key Items ──
    with tab_bs:
        if df_key is not None and "LogicalKey" in df_key.columns:
            bs_keys = list(KEY_ITEMS_BY_DESC.keys())
            df_bs_display = df_key[df_key["LogicalKey"].isin(bs_keys)].copy()
            if not df_bs_display.empty:
                period_cols = [c for c in df_bs_display.columns if "/" in c]
                display_df = df_bs_display[["Item (EN)", "Item (TR)"] + period_cols].copy()
                display_df = display_df.rename(columns={"Item (EN)": "Item", "Item (TR)": "Kalem"})
                
                for col in period_cols:
                    display_df[col] = pd.to_numeric(display_df[col], errors='coerce')
                    display_df[col] = display_df[col].apply(
                        lambda x: f"₺{x/1000:,.0f}K" if pd.notna(x) and abs(x) >= 1000
                        else (f"₺{x:,.0f}" if pd.notna(x) else "—")
                    )
                
                st.dataframe(display_df, use_container_width=True, hide_index=True)
                
                # Asset composition chart (latest period)
                latest_p = period_cols[0] if period_cols else None
                if latest_p:
                    def _get_bs_val(lk):
                        r = df_key[df_key["LogicalKey"] == lk]
                        if r.empty or latest_p not in r.columns:
                            return 0
                        v = pd.to_numeric(r[latest_p].iloc[0], errors='coerce')
                        return float(v) if pd.notna(v) else 0
                    
                    comp_data = [
                        ("Current Assets", _get_bs_val("current_assets")),
                        ("Non-Current Assets", _get_bs_val("noncurrent_assets")),
                        ("Current Liabilities", _get_bs_val("current_liabilities")),
                        ("Non-Current Liabilities", _get_bs_val("noncurrent_liab")),
                        ("Equity", _get_bs_val("total_equity")),
                    ]
                    labels = [lbl for lbl, v in comp_data if v != 0]
                    vals = [abs(v) for _, v in comp_data if v != 0]
                    
                    if vals:
                        fig_comp = go.Figure(go.Pie(
                            labels=labels, values=vals, hole=0.4,
                            marker_colors=["#28a745", "#17a2b8", "#dc3545", "#fd7e14", "#6f42c1"],
                            textinfo='label+percent', textfont_size=10
                        ))
                        fig_comp.update_layout(
                            title=f"Balance Sheet Composition ({latest_p})",
                            height=300,
                            margin=dict(l=20, r=20, t=40, b=40),
                            legend=dict(orientation="h", yanchor="top", y=-0.1,
                                        xanchor="center", x=0.5, font=dict(size=9))
                        )
                        st.plotly_chart(fig_comp, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("No balance sheet items found.")
        else:
            st.info("Balance sheet data not available.")
    
    # ── TAB 3: Income Statement ──
    with tab_is:
        if df_key is not None and "LogicalKey" in df_key.columns:
            is_keys = list(KEY_INCOME_BY_DESC.keys())
            df_is_display = df_key[df_key["LogicalKey"].isin(is_keys)].copy()
            if not df_is_display.empty:
                period_cols = [c for c in df_is_display.columns if "/" in c]
                display_df = df_is_display[["Item (EN)", "Item (TR)"] + period_cols].copy()
                display_df = display_df.rename(columns={"Item (EN)": "Item", "Item (TR)": "Kalem"})
                
                for col in period_cols:
                    display_df[col] = pd.to_numeric(display_df[col], errors='coerce')
                    display_df[col] = display_df[col].apply(
                        lambda x: f"₺{x/1000:,.0f}K" if pd.notna(x) and abs(x) >= 1000
                        else (f"₺{x:,.0f}" if pd.notna(x) else "—")
                    )
                
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No income statement items found.")
        else:
            st.info("Income statement data not available.")
    
    # ── TAB 4: Full Raw Data ──
    with tab_full:
        # Parse unfiltered data for full view
        df_full_raw = parse_balance_sheet_to_df(raw_data, item_filter=None)
        if df_full_raw is not None:
            st.caption(f"Showing all {len(df_full_raw)} line items")
            period_cols = [c for c in df_full_raw.columns if "/" in c]
            display_cols = ["Code", "Item (TR)"] + period_cols
            available_cols = [c for c in display_cols if c in df_full_raw.columns]
            st.dataframe(df_full_raw[available_cols], use_container_width=True, hide_index=True, height=500)
        else:
            st.info("Full data not available.")


# =============================================================================
# CANDLESTICK PATTERN DETECTION
# =============================================================================

def detect_patterns(df):
    """
    Detect common candlestick and chart patterns from OHLCV data.
    Returns a list of dicts: [{name, type(bullish/bearish/neutral), index, description}]
    """
    patterns = []
    if df is None or len(df) < 5:
        return patterns
    
    o = df['Open'].values
    h = df['High'].values
    l = df['Low'].values
    c = df['Close'].values
    
    body = c - o
    body_abs = np.abs(body)
    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - l
    avg_body = pd.Series(body_abs).rolling(14).mean().values
    
    for i in range(2, len(df)):
        # Skip if avg_body is nan or zero
        if np.isnan(avg_body[i]) or avg_body[i] == 0:
            continue
        
        idx = df.index[i]
        
        # --- DOJI ---
        if body_abs[i] <= avg_body[i] * 0.1:
            patterns.append({
                "name": "Doji", "type": "neutral", "index": idx,
                "description": "The open and close are virtually equal, forming a cross shape. This signals indecision between buyers and sellers. After a trend, it can precede a reversal. Look for the next candle for confirmation."
            })
        
        # --- HAMMER (bullish) ---
        elif (body[i] > 0 and
              lower_shadow[i] > body_abs[i] * 2 and
              upper_shadow[i] < body_abs[i] * 0.5 and
              c[i-1] < o[i-1]):  # After a red candle
            patterns.append({
                "name": "Hammer", "type": "bullish", "index": idx,
                "description": "A small body at the top with a long lower wick (2x+ the body). Sellers pushed price down significantly but buyers recovered. After a downtrend, this signals potential reversal upward. Higher volume increases reliability."
            })
        
        # --- INVERTED HAMMER ---
        elif (body[i] > 0 and
              upper_shadow[i] > body_abs[i] * 2 and
              lower_shadow[i] < body_abs[i] * 0.5 and
              c[i-1] < o[i-1]):
            patterns.append({
                "name": "Inverted Hammer", "type": "bullish", "index": idx,
                "description": "A small body at the bottom with a long upper wick. Buyers attempted a rally but couldn't hold it. Still bullish after a downtrend as it shows buying interest returning. Needs next-day confirmation."
            })
        
        # --- SHOOTING STAR (bearish) ---
        elif (body[i] < 0 and
              upper_shadow[i] > body_abs[i] * 2 and
              lower_shadow[i] < body_abs[i] * 0.5 and
              c[i-1] > o[i-1]):  # After a green candle
            patterns.append({
                "name": "Shooting Star", "type": "bearish", "index": idx,
                "description": "A small body at the bottom with a long upper wick appearing after an uptrend. Buyers pushed higher but sellers drove it back down. A warning that upward momentum may be fading. Confirmation comes if the next candle closes lower."
            })
        
        # --- HANGING MAN (bearish) ---
        elif (body[i] < 0 and
              lower_shadow[i] > body_abs[i] * 2 and
              upper_shadow[i] < body_abs[i] * 0.5 and
              c[i-1] > o[i-1]):
            patterns.append({
                "name": "Hanging Man", "type": "bearish", "index": idx,
                "description": "Looks like a hammer but appears at the top of an uptrend. The long lower shadow shows sellers tested the market. If the next day closes lower, it confirms a potential top and reversal downward."
            })
        
        # --- BULLISH ENGULFING ---
        if (i >= 1 and body[i-1] < 0 and body[i] > 0 and
            o[i] <= c[i-1] and c[i] >= o[i-1] and
            body_abs[i] > body_abs[i-1]):
            patterns.append({
                "name": "Bullish Engulfing", "type": "bullish", "index": idx,
                "description": "A large green candle completely engulfs the previous red candle's body. This is one of the strongest reversal signals. It shows buyers have overwhelmed sellers decisively. Most reliable after a downtrend and on high volume."
            })
        
        # --- BEARISH ENGULFING ---
        if (i >= 1 and body[i-1] > 0 and body[i] < 0 and
            o[i] >= c[i-1] and c[i] <= o[i-1] and
            body_abs[i] > body_abs[i-1]):
            patterns.append({
                "name": "Bearish Engulfing", "type": "bearish", "index": idx,
                "description": "A large red candle completely engulfs the previous green candle's body. Strong reversal signal at the top of an uptrend. Sellers have taken control. The larger the engulfing candle relative to recent candles, the stronger the signal."
            })
        
        # --- MORNING STAR (3-candle bullish reversal) ---
        if (i >= 2 and body[i-2] < 0 and
            body_abs[i-1] < avg_body[i] * 0.4 and
            body[i] > 0 and c[i] > (o[i-2] + c[i-2]) / 2):
            patterns.append({
                "name": "Morning Star", "type": "bullish", "index": idx,
                "description": "A three-candle pattern: (1) large red candle, (2) small-bodied candle (indecision), (3) large green candle closing above the midpoint of candle 1. One of the most reliable bullish reversal patterns. The gap and recovery show bears losing control."
            })
        
        # --- EVENING STAR (3-candle bearish reversal) ---
        if (i >= 2 and body[i-2] > 0 and
            body_abs[i-1] < avg_body[i] * 0.4 and
            body[i] < 0 and c[i] < (o[i-2] + c[i-2]) / 2):
            patterns.append({
                "name": "Evening Star", "type": "bearish", "index": idx,
                "description": "A three-candle pattern: (1) large green candle, (2) small-bodied candle (indecision at the top), (3) large red candle closing below the midpoint of candle 1. A reliable top reversal pattern. Volume on the third candle adds confirmation."
            })
        
        # --- THREE WHITE SOLDIERS (bullish) ---
        if (i >= 2 and
            body[i] > 0 and body[i-1] > 0 and body[i-2] > 0 and
            c[i] > c[i-1] > c[i-2] and
            o[i] > o[i-1] > o[i-2] and
            body_abs[i] > avg_body[i] * 0.7 and
            body_abs[i-1] > avg_body[i] * 0.7):
            patterns.append({
                "name": "Three White Soldiers", "type": "bullish", "index": idx,
                "description": "Three consecutive strong green candles, each closing higher than the last and opening within the prior candle's body. Signals strong buying pressure and a powerful trend reversal or continuation. Most significant after a prolonged decline."
            })
        
        # --- THREE BLACK CROWS (bearish) ---
        if (i >= 2 and
            body[i] < 0 and body[i-1] < 0 and body[i-2] < 0 and
            c[i] < c[i-1] < c[i-2] and
            o[i] < o[i-1] < o[i-2] and
            body_abs[i] > avg_body[i] * 0.7 and
            body_abs[i-1] > avg_body[i] * 0.7):
            patterns.append({
                "name": "Three Black Crows", "type": "bearish", "index": idx,
                "description": "Three consecutive strong red candles, each closing lower. The opposite of Three White Soldiers. Signals aggressive selling and a possible trend reversal downward. Very bearish when it appears after an extended uptrend."
            })
    
    # --- DOUBLE BOTTOM / DOUBLE TOP (chart patterns on recent data) ---
    if len(df) >= 20:
        recent = df.tail(40) if len(df) >= 40 else df
        lows = recent['Low'].values
        highs = recent['High'].values
        
        # Simple double bottom detection: two lows within 3% of each other
        min_idx1 = np.argmin(lows[:len(lows)//2])
        min_idx2 = np.argmin(lows[len(lows)//2:]) + len(lows)//2
        if min_idx1 != min_idx2:
            low1, low2 = lows[min_idx1], lows[min_idx2]
            if abs(low1 - low2) / max(low1, low2) < 0.03 and min_idx2 - min_idx1 >= 5:
                between_high = np.max(highs[min_idx1:min_idx2])
                if between_high > low1 * 1.03:
                    patterns.append({
                        "name": "Double Bottom (W)", "type": "bullish",
                        "index": recent.index[min_idx2],
                        "description": f"Two price lows at approximately the same level (₺{low1:.2f} and ₺{low2:.2f}), with a rally between them forming a 'W' shape. This is a classic reversal pattern. The breakout above the middle peak (₺{between_high:.2f}) confirms the pattern and targets a move equal to the depth of the W."
                    })
        
        # Simple double top detection
        max_idx1 = np.argmax(highs[:len(highs)//2])
        max_idx2 = np.argmax(highs[len(highs)//2:]) + len(highs)//2
        if max_idx1 != max_idx2:
            high1, high2 = highs[max_idx1], highs[max_idx2]
            if abs(high1 - high2) / max(high1, high2) < 0.03 and max_idx2 - max_idx1 >= 5:
                between_low = np.min(lows[max_idx1:max_idx2])
                if between_low < high1 * 0.97:
                    patterns.append({
                        "name": "Double Top (M)", "type": "bearish",
                        "index": recent.index[max_idx2],
                        "description": f"Two price highs at approximately the same level (₺{high1:.2f} and ₺{high2:.2f}), with a dip between them forming an 'M' shape. This is a classic bearish reversal. A break below the middle trough (₺{between_low:.2f}) confirms the pattern."
                    })
    
    # Deduplicate: keep only the most recent occurrence of each pattern name
    seen = set()
    unique = []
    for p in reversed(patterns):
        if p["name"] not in seen:
            seen.add(p["name"])
            unique.append(p)
    unique.reverse()
    
    return unique


def display_pattern_tab(df, stock):
    """Display the pattern detection results in a tab."""
    patterns = detect_patterns(df)
    
    if not patterns:
        st.info("No significant candlestick or chart patterns detected in the current timeframe. This can happen during low-volatility consolidation periods.")
        return
    
    # Filter to recent patterns (last 20% of data)
    cutoff_idx = len(df) - max(int(len(df) * 0.2), 10)
    cutoff_date = df.index[cutoff_idx] if cutoff_idx >= 0 else df.index[0]
    recent_patterns = [p for p in patterns if p["index"] >= cutoff_date]
    older_patterns = [p for p in patterns if p["index"] < cutoff_date]
    
    # Show recent patterns prominently
    if recent_patterns:
        st.markdown("#### 🔥 Recent Patterns Detected")
        for p in recent_patterns:
            color = "#28a745" if p["type"] == "bullish" else "#dc3545" if p["type"] == "bearish" else "#ffc107"
            emoji = "🟢" if p["type"] == "bullish" else "🔴" if p["type"] == "bearish" else "🟡"
            label = p["type"].upper()
            st.markdown(f"""
            <div style="border-left: 4px solid {color}; padding: 0.8rem 1rem; margin: 0.5rem 0; background: rgba(0,0,0,0.05); border-radius: 0 8px 8px 0;">
                <strong>{emoji} {p['name']}</strong> <span style="color:{color}; font-size:0.85rem;">({label})</span>
                <br><span style="font-size:0.8rem; color:#888;">Detected at: {p['index']}</span>
                <p style="margin-top:0.5rem;">{p['description']}</p>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No patterns detected in the most recent period. Showing older patterns below.")
    
    if older_patterns:
        with st.expander(f"📜 Earlier Patterns ({len(older_patterns)} found)"):
            for p in older_patterns:
                emoji = "🟢" if p["type"] == "bullish" else "🔴" if p["type"] == "bearish" else "🟡"
                st.markdown(f"**{emoji} {p['name']}** ({p['type']}) — {p['index']}")
                st.caption(p['description'])
    
    # Mark patterns on the price chart
    st.markdown("#### 📊 Patterns on Chart")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'
    ))
    
    for p in recent_patterns:
        color = "green" if p["type"] == "bullish" else "red" if p["type"] == "bearish" else "gold"
        marker_y = df.loc[p["index"], 'Low'] * 0.995 if p["type"] == "bullish" else df.loc[p["index"], 'High'] * 1.005
        fig.add_annotation(
            x=p["index"], y=marker_y,
            text=p["name"], showarrow=True,
            arrowhead=2, arrowcolor=color, arrowsize=1.5,
            font=dict(size=9, color=color),
            bgcolor="rgba(255,255,255,0.85)", bordercolor=color
        )
    
    fig.update_layout(
        title=f"{stock} — Pattern Annotations",
        height=400, xaxis_rangeslider_visible=False,
        margin=dict(l=40, r=20, t=40, b=70),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=10))
    )
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
    
    # Pattern summary
    bullish_count = sum(1 for p in recent_patterns if p["type"] == "bullish")
    bearish_count = sum(1 for p in recent_patterns if p["type"] == "bearish")
    st.markdown("#### 🎯 Pattern Summary")
    if bullish_count > bearish_count:
        st.success(f"**Net Bullish** — {bullish_count} bullish vs {bearish_count} bearish patterns in the recent period. The candlestick structure favors upward movement.")
    elif bearish_count > bullish_count:
        st.error(f"**Net Bearish** — {bearish_count} bearish vs {bullish_count} bullish patterns in the recent period. The candlestick structure warns of potential downside.")
    else:
        st.info(f"**Neutral** — Equal bullish and bearish patterns ({bullish_count} each). No clear directional bias from candlestick analysis alone.")


# =============================================================================
# MONTE CARLO SIMULATION
# =============================================================================

def run_monte_carlo(df, stock, num_simulations=1000, forecast_days=30):
    """Run Monte Carlo simulation and display results."""
    
    if df is None or len(df) < 20:
        st.warning("Insufficient data for Monte Carlo simulation (need at least 20 data points).")
        return
    
    closes = df['Close'].values
    log_returns = np.diff(np.log(closes))
    
    # Remove any NaN/inf
    log_returns = log_returns[np.isfinite(log_returns)]
    if len(log_returns) < 10:
        st.warning("Insufficient valid return data for simulation.")
        return
    
    mu = np.mean(log_returns)
    sigma = np.std(log_returns)
    last_price = closes[-1]
    
    st.markdown(f"#### ⚙️ Simulation Parameters")
    st.caption(f"Based on {len(log_returns)} historical returns | μ (daily drift) = {mu:.6f} | σ (daily vol) = {sigma:.6f}")
    
    # Let user adjust parameters
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        forecast_days = st.slider("Forecast Days", 5, 120, forecast_days, key="mc_days")
    with col_p2:
        num_simulations = st.slider("Simulations", 100, 5000, num_simulations, step=100, key="mc_sims")
    
    # Run simulations using Geometric Brownian Motion
    np.random.seed(42)
    simulations = np.zeros((num_simulations, forecast_days))
    
    for i in range(num_simulations):
        daily_returns = np.random.normal(mu, sigma, forecast_days)
        price_path = last_price * np.exp(np.cumsum(daily_returns))
        simulations[i] = price_path
    
    final_prices = simulations[:, -1]
    
    # --- Simulation paths chart ---
    st.markdown("#### 📈 Simulated Price Paths")
    fig_paths = go.Figure()
    
    # Plot a subset of paths for clarity
    display_count = min(200, num_simulations)
    for i in range(display_count):
        fig_paths.add_trace(go.Scatter(
            x=list(range(1, forecast_days + 1)),
            y=simulations[i],
            mode='lines',
            line=dict(width=0.5, color='rgba(100,149,237,0.15)'),
            showlegend=False, hoverinfo='skip'
        ))
    
    # Percentile lines
    p5 = np.percentile(simulations, 5, axis=0)
    p25 = np.percentile(simulations, 25, axis=0)
    p50 = np.percentile(simulations, 50, axis=0)
    p75 = np.percentile(simulations, 75, axis=0)
    p95 = np.percentile(simulations, 95, axis=0)
    days_range = list(range(1, forecast_days + 1))
    
    fig_paths.add_trace(go.Scatter(x=days_range, y=p5, mode='lines', line=dict(color='red', dash='dash', width=2), name='5th %ile'))
    fig_paths.add_trace(go.Scatter(x=days_range, y=p25, mode='lines', line=dict(color='orange', dash='dot', width=1.5), name='25th %ile'))
    fig_paths.add_trace(go.Scatter(x=days_range, y=p50, mode='lines', line=dict(color='white', width=3), name='Median'))
    fig_paths.add_trace(go.Scatter(x=days_range, y=p75, mode='lines', line=dict(color='lightgreen', dash='dot', width=1.5), name='75th %ile'))
    fig_paths.add_trace(go.Scatter(x=days_range, y=p95, mode='lines', line=dict(color='green', dash='dash', width=2), name='95th %ile'))
    
    # Starting price reference
    fig_paths.add_hline(y=last_price, line_dash="solid", line_color="yellow", annotation_text=f"Current ₺{last_price:.2f}")
    
    fig_paths.update_layout(
        title=f"{stock} — {num_simulations} Monte Carlo Paths ({forecast_days} days)",
        xaxis_title="Days Forward", yaxis_title="Price (₺)",
        height=400, margin=dict(l=40, r=20, t=40, b=70),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=10))
    )
    st.plotly_chart(fig_paths, use_container_width=True, config=PLOTLY_CONFIG)
    
    # --- Probability Distribution ---
    st.markdown("#### 📊 Final Price Distribution")
    
    fig_dist = go.Figure()
    fig_dist.add_trace(go.Histogram(
        x=final_prices, nbinsx=80,
        marker_color='rgba(100,149,237,0.7)',
        name='Price Distribution'
    ))
    
    fig_dist.add_vline(x=last_price, line_dash="solid", line_color="yellow",
                       annotation_text=f"Current ₺{last_price:.2f}")
    fig_dist.add_vline(x=np.median(final_prices), line_dash="dash", line_color="white",
                       annotation_text=f"Median ₺{np.median(final_prices):.2f}")
    
    fig_dist.update_layout(
        title=f"Distribution of Simulated Prices after {forecast_days} Days",
        xaxis_title="Price (₺)", yaxis_title="Frequency",
        height=350, margin=dict(l=40, r=20, t=40, b=70),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=10))
    )
    st.plotly_chart(fig_dist, use_container_width=True, config=PLOTLY_CONFIG)
    
    # --- Key Statistics ---
    st.markdown("#### 📋 Probability Table")
    
    prob_above = (final_prices > last_price).sum() / len(final_prices) * 100
    prob_up10 = (final_prices > last_price * 1.10).sum() / len(final_prices) * 100
    prob_up20 = (final_prices > last_price * 1.20).sum() / len(final_prices) * 100
    prob_down10 = (final_prices < last_price * 0.90).sum() / len(final_prices) * 100
    prob_down20 = (final_prices < last_price * 0.80).sum() / len(final_prices) * 100
    
    expected_return = (np.mean(final_prices) - last_price) / last_price * 100
    median_return = (np.median(final_prices) - last_price) / last_price * 100
    
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.metric("Median Price", f"₺{np.median(final_prices):.2f}", f"{median_return:+.1f}%")
    with sc2:
        st.metric("Expected Price", f"₺{np.mean(final_prices):.2f}", f"{expected_return:+.1f}%")
    with sc3:
        color = "normal" if prob_above >= 50 else "inverse"
        st.metric("P(Price Up)", f"{prob_above:.1f}%", delta=f"{prob_above-50:+.1f}pp vs 50%", delta_color=color)
    
    prob_data = {
        "Scenario": [
            "Price goes up (any amount)",
            "Price rises > 10%",
            "Price rises > 20%",
            "Price falls > 10%",
            "Price falls > 20%",
        ],
        "Probability": [
            f"{prob_above:.1f}%",
            f"{prob_up10:.1f}%",
            f"{prob_up20:.1f}%",
            f"{prob_down10:.1f}%",
            f"{prob_down20:.1f}%",
        ],
        "Target Price": [
            f"₺{last_price:.2f}+",
            f"₺{last_price*1.10:.2f}+",
            f"₺{last_price*1.20:.2f}+",
            f"below ₺{last_price*0.90:.2f}",
            f"below ₺{last_price*0.80:.2f}",
        ]
    }
    st.dataframe(pd.DataFrame(prob_data), use_container_width=True, hide_index=True)
    
    # Confidence intervals
    st.markdown("#### 📐 Confidence Intervals")
    st.markdown(f"""
    - **90% CI:** ₺{np.percentile(final_prices, 5):.2f} — ₺{np.percentile(final_prices, 95):.2f}
    - **80% CI:** ₺{np.percentile(final_prices, 10):.2f} — ₺{np.percentile(final_prices, 90):.2f}
    - **50% CI:** ₺{np.percentile(final_prices, 25):.2f} — ₺{np.percentile(final_prices, 75):.2f}
    """)
    
    st.caption("⚠️ Monte Carlo simulations assume returns follow a normal distribution with constant drift and volatility derived from historical data. Real markets exhibit fat tails, regime changes, and event risk not captured here. Use as one input among many, not as a prediction.")


# =============================================================================
# FIBONACCI RETRACEMENT ANALYSIS
# =============================================================================

def display_fibonacci_tab(df, stock):
    """Perform Fibonacci retracement analysis and display results."""
    
    if df is None or len(df) < 10:
        st.warning("Insufficient data for Fibonacci analysis.")
        return
    
    closes = df['Close'].values
    highs = df['High'].values
    lows = df['Low'].values
    
    # Detect the most significant swing high and swing low
    swing_high = np.max(highs)
    swing_low = np.min(lows)
    swing_high_idx = np.argmax(highs)
    swing_low_idx = np.argmin(lows)
    
    # Determine trend direction based on which came first
    is_uptrend = swing_low_idx < swing_high_idx  # Low came first = uptrend
    
    # Fibonacci ratios
    fib_ratios = {
        "0% (High)": 0.0,
        "23.6%": 0.236,
        "38.2%": 0.382,
        "50%": 0.500,
        "61.8% (Golden)": 0.618,
        "78.6%": 0.786,
        "100% (Low)": 1.0,
    }
    
    diff = swing_high - swing_low
    current_price = closes[-1]
    
    # Calculate levels
    levels = {}
    for name, ratio in fib_ratios.items():
        if is_uptrend:
            # Retracement from high: price pulled back from the top
            level = swing_high - diff * ratio
        else:
            # Retracement from low: price bounced from the bottom
            level = swing_low + diff * ratio
        levels[name] = level
    
    # Extension levels
    ext_ratios = {
        "127.2% Extension": 1.272,
        "161.8% Extension": 1.618,
        "200% Extension": 2.0,
    }
    ext_levels = {}
    for name, ratio in ext_ratios.items():
        if is_uptrend:
            ext_levels[name] = swing_high - diff * (-ratio + 1)  # Extension above high
        else:
            ext_levels[name] = swing_low + diff * ratio
    
    trend_text = "📈 Uptrend (retracement from high)" if is_uptrend else "📉 Downtrend (bounce from low)"
    
    st.markdown(f"#### {trend_text}")
    st.caption(f"Swing High: ₺{swing_high:.2f} ({df.index[swing_high_idx]}) | Swing Low: ₺{swing_low:.2f} ({df.index[swing_low_idx]}) | Range: ₺{diff:.2f}")
    
    # --- Fibonacci Chart ---
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'
    ))
    
    fib_colors = {
        "0% (High)": "#ff0000",
        "23.6%": "#ff6600",
        "38.2%": "#ffaa00",
        "50%": "#ffff00",
        "61.8% (Golden)": "#00cc00",
        "78.6%": "#0066ff",
        "100% (Low)": "#9900ff",
    }
    
    for name, level in levels.items():
        color = fib_colors.get(name, "gray")
        fig.add_hline(
            y=level, line_dash="dash", line_color=color,
            annotation_text=f"{name}: ₺{level:.2f}",
            annotation_position="right",
            annotation_font_size=9,
            annotation_font_color=color,
        )
    
    # Extension levels (dotted)
    for name, level in ext_levels.items():
        fig.add_hline(
            y=level, line_dash="dot", line_color="rgba(255,255,255,0.4)",
            annotation_text=f"{name}: ₺{level:.2f}",
            annotation_position="right",
            annotation_font_size=8,
        )
    
    fig.update_layout(
        title=f"{stock} — Fibonacci Retracement Levels",
        height=450, xaxis_rangeslider_visible=False,
        margin=dict(l=40, r=120, t=40, b=70),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=10))
    )
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
    
    # --- Levels Table with Commentary ---
    st.markdown("#### 📋 Fibonacci Levels & Commentary")
    
    # Find which level the price is nearest to
    all_levels = {**levels, **ext_levels}
    nearest_name = min(all_levels, key=lambda k: abs(all_levels[k] - current_price))
    
    for name, level in levels.items():
        distance_pct = (current_price - level) / level * 100
        
        # Determine proximity
        if abs(distance_pct) < 1.5:
            proximity = "📍 **CURRENT ZONE**"
        elif distance_pct > 0:
            proximity = f"↑ Price is {distance_pct:.1f}% above"
        else:
            proximity = f"↓ Price is {abs(distance_pct):.1f}% below"
        
        # Commentary per level
        if "0%" in name:
            comment = "The swing high / resistance ceiling. A break above this level on volume signals continuation of the uptrend and opens the way to extension targets."
        elif "23.6" in name:
            comment = "Shallow retracement. In strong trends, pullbacks often hold at this level. If price bounces here, the trend has strong momentum. A break below suggests a deeper correction."
        elif "38.2" in name:
            comment = "Moderate retracement. This is the first 'significant' Fibonacci level. Many institutional traders watch this for entries. Price bouncing here is a healthy sign for trend continuation."
        elif "50%" in name:
            comment = "The halfway point (not a true Fibonacci ratio but widely watched). Represents the psychological midpoint of the move. A key decision zone — holding here keeps the trend structure intact."
        elif "61.8" in name:
            comment = "The GOLDEN RATIO — the most important Fibonacci level. This is where the strongest support/resistance clusters form. A bounce here is considered the 'last stand' for the prevailing trend. A break signals potential full reversal."
        elif "78.6" in name:
            comment = "Deep retracement. At this point, most of the prior move has been erased. The trend is severely weakened but not yet broken. Final support/resistance before a full reversal to 100%."
        elif "100%" in name:
            comment = "Full retracement — the entire prior move has been undone. The trend has reversed completely. Look for new support/resistance forming at this level."
        else:
            comment = ""
        
        color = fib_colors.get(name, "gray")
        is_current = abs(distance_pct) < 1.5
        bg = "rgba(255,255,0,0.1)" if is_current else "transparent"
        
        st.markdown(f"""
        <div style="border-left: 4px solid {color}; padding: 0.6rem 1rem; margin: 0.3rem 0; background: {bg}; border-radius: 0 6px 6px 0;">
            <strong style="color:{color};">{name}</strong>: ₺{level:.2f} — {proximity}
            <p style="margin: 0.3rem 0 0 0; font-size: 0.9rem;">{comment}</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Extension levels
    st.markdown("#### 🚀 Extension Targets")
    for name, level in ext_levels.items():
        distance_pct = (current_price - level) / level * 100
        proximity = f"↑ {distance_pct:.1f}% above" if distance_pct > 0 else f"↓ {abs(distance_pct):.1f}% below"
        
        if "127.2" in name:
            comment = "First extension target. Often acts as the initial profit-taking zone after a breakout above the swing high."
        elif "161.8" in name:
            comment = "The golden extension — the most watched target. Many trend followers set their take-profit at this level."
        elif "200" in name:
            comment = "Double the original move. An ambitious but achievable target in strong trending markets."
        else:
            comment = ""
        
        st.markdown(f"""
        <div style="border-left: 4px solid rgba(255,255,255,0.4); padding: 0.6rem 1rem; margin: 0.3rem 0; border-radius: 0 6px 6px 0;">
            <strong>{name}</strong>: ₺{level:.2f} — {proximity}
            <p style="margin: 0.3rem 0 0 0; font-size: 0.9rem;">{comment}</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Overall Fibonacci Assessment
    st.markdown("---")
    st.markdown("#### 🎯 Fibonacci Assessment")
    
    # Determine where price sits relative to golden ratio
    golden_level = levels["61.8% (Golden)"]
    fifty_level = levels["50%"]
    
    if is_uptrend:
        if current_price > levels["23.6%"]:
            st.success(f"**Strong Position** — Price (₺{current_price:.2f}) is above the 23.6% level, holding within the shallowest retracement zone. The uptrend remains strong with minimal pullback.")
        elif current_price > fifty_level:
            st.info(f"**Moderate Retracement** — Price has pulled back to the 38-50% zone. This is a normal and healthy correction within an uptrend. Watch the 50% level (₺{fifty_level:.2f}) for support.")
        elif current_price > golden_level:
            st.warning(f"**Deep Retracement** — Price is testing the critical 61.8% golden ratio zone (₺{golden_level:.2f}). This is the last strong defense for the uptrend. A bounce here is a high-probability buy zone.")
        else:
            st.error(f"**Very Deep Retracement** — Price has broken below the golden ratio (₺{golden_level:.2f}). The uptrend is in serious jeopardy. A full reversal toward the 100% level (₺{levels['100% (Low)']:.2f}) is possible.")
    else:
        if current_price < levels["23.6%"]:
            st.error(f"**Weak Bounce** — Price is below the 23.6% level. The downtrend remains dominant with very little recovery.")
        elif current_price < fifty_level:
            st.warning(f"**Partial Recovery** — Price has bounced to the 38-50% zone. Some buying interest but not enough to signal a full reversal yet.")
        elif current_price < golden_level:
            st.info(f"**Strong Recovery** — Price is approaching the golden ratio zone. A break above ₺{golden_level:.2f} would be a strong bullish signal.")
        else:
            st.success(f"**Full Recovery** — Price has reclaimed above the 61.8% level. The downtrend may be reversing. Watch for a break above the swing high for confirmation.")


def main():
    try:
        st.markdown('<h1 class="main-header">📊 BIST Ultimate Analysis</h1>', unsafe_allow_html=True)
        st.info(f"📈 Analyzing {len(IMKB)} BIST stocks across 8 timeframes")
        
        auth, msg = setup_tradingview_auth()
        st.session_state.authenticated = auth
        css = "status-realtime" if auth else "status-delayed"
        st.markdown(f'<div class="status-box {css}">{msg}</div>', unsafe_allow_html=True)
        
        with st.sidebar:
            st.header("⚙️ Settings")
            mode = st.radio("Mode", ["📊 Single Stock", "🔍 Stock Screener", "📋 Market Summary"])
            st.markdown("---")
            st.subheader("⏱️ Timeframe")
            available_tf = {k: v for k, v in TIMEFRAMES.items() if not v["auth_required"] or auth}
            tf_options = {k: v["label"] for k, v in available_tf.items()}
            selected_tf = st.selectbox("Select", list(tf_options.keys()), format_func=lambda x: tf_options[x])
            st.session_state.current_timeframe = selected_tf
            
            if mode == "📊 Single Stock":
                st.markdown("---")
                st.subheader("🏛️ Index Filter")
                selected_index = st.selectbox(
                    "Filter by Index",
                    list(INDEX_FILTERS.keys()),
                    index=2,  # Default to "All Stocks"
                    key="index_filter"
                )
                index_stocks = INDEX_FILTERS[selected_index]
                # Only keep stocks that exist in the main IMKB list
                index_stocks = sorted([s for s in index_stocks if s in IMKB])
                
                st.caption(f"{len(index_stocks)} stocks in {selected_index}")
                
                st.markdown("---")
                filter_c = st.checkbox("🔍 Show Only Chosen", value=st.session_state.filter_chosen_only)
                st.session_state.filter_chosen_only = filter_c
                if filter_c:
                    if selected_tf in st.session_state.chosen_stocks and st.session_state.chosen_stocks[selected_tf]:
                        chosen_symbols = [s['symbol'] for s in st.session_state.chosen_stocks[selected_tf]]
                        # Intersect chosen stocks with selected index
                        stocks = sorted([s for s in chosen_symbols if s in index_stocks])
                        if not stocks:
                            st.warning("No chosen stocks in this index. Showing all index stocks.")
                            stocks = index_stocks
                    else:
                        st.warning("Run screener first")
                        stocks = index_stocks
                else:
                    stocks = index_stocks
                stock = st.selectbox("Stock", stocks)
            else:
                if st.button("🚀 Run Screener", use_container_width=True):
                    with st.spinner("Screening..."):
                        results = screen_chosen_stocks(IMKB, interval=selected_tf)
                        st.session_state.chosen_stocks[selected_tf] = results
                    st.success(f"✅ Found {len(results)} stocks!")
            
            if mode == "📋 Market Summary":
                if st.button("🔎 Scan All Stocks", use_container_width=True):
                    with st.spinner("Scanning entire market..."):
                        sentiment_counts, above_sma50, below_sma50, sma50_na = scan_market_summary(IMKB, interval=selected_tf)
                        st.session_state.market_summary[selected_tf] = {
                            'sentiment': sentiment_counts,
                            'above_sma50': above_sma50,
                            'below_sma50': below_sma50,
                            'sma50_na': sma50_na,
                            'scan_time': datetime.now().strftime("%Y-%m-%d %H:%M")
                        }
                    total_scanned = sum(len(v) for v in sentiment_counts.values())
                    st.success(f"✅ Scanned {total_scanned} stocks!")
            if st.button("🔄 Refresh", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        
        if mode == "📊 Single Stock":
            days = TIMEFRAMES[selected_tf]["days"]
            start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            end = datetime.now().strftime("%Y-%m-%d")
            with st.spinner(f"Loading {stock}..."):
                df = fetch_stock_data(stock, start_date=start, end_date=end, interval=selected_tf)
            if df is not None and not df.empty:
                df = calculate_all_indicators(df)
                ind1, vol1 = calculate_simplified_scores(df)
                ind2, vol2 = calculate_original_scores(df)
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                price_change_pct = ((latest['Close'] - prev['Close']) / prev['Close']) * 100 if len(df) > 1 else 0
                sentiment_text, sentiment_emoji, sentiment_class, confidence = calculate_sentiment(
                    ind2, vol2, latest['RSI'], latest['Diff'], price_change_pct
                )
                st.subheader(f"📈 {stock} - {TIMEFRAMES[selected_tf]['label']}")
                st.markdown(f"""
                <div class="{sentiment_class}">
                    {sentiment_emoji} SENTIMENT: {sentiment_text}
                    <br>
                    <span style="font-size: 1rem;">Confidence: {confidence:.0f}%</span>
                </div>
                """, unsafe_allow_html=True)
                # -- Metrics: 2x2 grid (stacks naturally on mobile via CSS) --
                ch = latest['Close'] - prev['Close']
                r1c1, r1c2 = st.columns(2)
                with r1c1:
                    st.metric("Price", f"₺{latest['Close']:.2f}", f"{ch:.2f} ({price_change_pct:.2f}%)")
                with r1c2:
                    st.metric("Volume", f"{latest['Volume']:,.0f}")
                r2c1, r2c2 = st.columns(2)
                with r2c1:
                    st.metric("RSI", f"{latest['RSI']:.2f}")
                with r2c2:
                    st.metric("MACD", f"{latest['MACD']:.4f}")
                
                # -- Scores: compact HTML cards (mobile-friendly, no tiny gauges) --
                ind2_color = "#28a745" if ind2 >= 3 else "#ffc107" if ind2 >= 1 else "#dc3545"
                ind1_color = "#28a745" if ind1 >= 3.5 else "#ffc107" if ind1 >= 2 else "#dc3545"
                vol2_color = "#28a745" if vol2 > 0.7 else "#dc3545"
                vol1_color = "#28a745" if vol1 >= 3 else "#ffc107" if vol1 >= 2 else "#dc3545"
                st.markdown(f"""
                <div class="mobile-score-row">
                    <div class="mobile-score-card">
                        <p class="score-label">Indicator 2 ⭐</p>
                        <p class="score-value" style="color:{ind2_color}">{ind2:.1f}</p>
                        <p class="score-max">/ 10</p>
                    </div>
                    <div class="mobile-score-card">
                        <p class="score-label">Volume 2</p>
                        <p class="score-value" style="color:{vol2_color}">{vol2:.2f}</p>
                        <p class="score-max">{"✅ Above 0.7" if vol2 > 0.7 else "⚠️ Below 0.7"}</p>
                    </div>
                    <div class="mobile-score-card">
                        <p class="score-label">Indicator 1</p>
                        <p class="score-value" style="color:{ind1_color}">{ind1:.1f}</p>
                        <p class="score-max">/ 5</p>
                    </div>
                    <div class="mobile-score-card">
                        <p class="score-label">Volume 1</p>
                        <p class="score-value" style="color:{vol1_color}">{vol1:.1f}</p>
                        <p class="score-max">/ 5</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # ══════════════════════════════════════════════════
                # COMMENTARY — Score Explanation & KPI Evaluation
                # ══════════════════════════════════════════════════
                with st.expander("📝 Score Commentary & KPI Analysis", expanded=True):
                    
                    # --- Indicator Score 2 (Original) Commentary ---
                    st.markdown("#### 📊 Indicator Score 2 (Original) — {:.1f} / 10".format(ind2))
                    st.caption("Counts how many of 10 technical signals just fired a fresh **buy crossover**. Each signal contributes 1 point (MACD can contribute 2). Higher = more indicators are simultaneously turning bullish.")
                    
                    if ind2 >= 6:
                        st.success(f"🟢 **Strong Buy Signal** — {ind2:.0f} out of 10 indicators have triggered fresh buy crossovers. This level of agreement across MACD, RSI, EMA, SMA, Stochastic, CCI, KAMA, and CMF is unusual and suggests strong upward momentum is building.")
                    elif ind2 >= 3:
                        st.info(f"🔵 **Moderate Buy Signal** — {ind2:.0f} indicators are showing fresh crossovers. There is some positive momentum but not full consensus. Look at which specific indicators are confirming before acting.")
                    elif ind2 >= 1:
                        st.warning(f"🟡 **Weak / Neutral** — Only {ind2:.0f} indicator(s) triggered. The stock lacks broad technical confirmation. This could mean the stock is consolidating or between trend phases.")
                    else:
                        st.error(f"🔴 **No Buy Signals** — Zero indicators are showing fresh buy crossovers. The stock may be in a downtrend or still falling. Wait for signals to emerge before considering entry.")
                    
                    # --- Volume Score 2 Commentary ---
                    st.markdown("#### 📊 Volume Score 2 — {:.2f}x".format(vol2))
                    st.caption("Current volume divided by the 15-period volume moving average. A value of 1.0 means average volume. Values above 0.7 indicate sufficient market participation to support a price move.")
                    
                    if vol2 > 2.0:
                        st.success(f"🟢 **Very High Volume** ({vol2:.2f}x average) — Trading activity is more than double the norm. This strongly validates any price movement happening. High volume breakouts are more likely to sustain.")
                    elif vol2 > 1.5:
                        st.success(f"🟢 **High Volume** ({vol2:.2f}x average) — Significantly above normal. Strong market interest is present, which adds conviction to the current trend direction.")
                    elif vol2 > 0.7:
                        st.info(f"🔵 **Adequate Volume** ({vol2:.2f}x average) — Meets the minimum threshold for reliable signals. Volume is sufficient to support price action, though not exceptionally strong.")
                    elif vol2 > 0.5:
                        st.warning(f"🟡 **Below Average Volume** ({vol2:.2f}x average) — Trading activity is thin. Technical signals may be less reliable. Price moves on low volume can reverse easily.")
                    else:
                        st.error(f"🔴 **Very Low Volume** ({vol2:.2f}x average) — Extremely low participation. Any price movement here is unreliable. Be cautious — this often signals lack of interest or a holiday/low-activity period.")
                    
                    st.markdown("---")
                    
                    # --- Individual KPI Breakdown ---
                    st.markdown("#### 🔍 Key Indicators Breakdown")
                    
                    # RSI
                    rsi_val = latest['RSI']
                    if rsi_val > 70:
                        rsi_emoji, rsi_text = "🔴", f"**Overbought** at {rsi_val:.1f} — The stock has risen sharply and may be stretched. Historically, readings above 70 often precede pullbacks or consolidation. Consider caution with new buys."
                    elif rsi_val > 60:
                        rsi_emoji, rsi_text = "🟡", f"**Moderately High** at {rsi_val:.1f} — Upward momentum is present but nearing elevated territory. The trend is intact but watch for signs of exhaustion."
                    elif rsi_val > 40:
                        rsi_emoji, rsi_text = "🔵", f"**Neutral Zone** at {rsi_val:.1f} — No extreme condition. The stock is neither overbought nor oversold. This is the most common range during consolidation or mild trends."
                    elif rsi_val > 30:
                        rsi_emoji, rsi_text = "🟡", f"**Approaching Oversold** at {rsi_val:.1f} — Selling pressure has been significant. If RSI dips below 30 and then bounces back, it can signal a potential reversal entry."
                    else:
                        rsi_emoji, rsi_text = "🟢", f"**Oversold** at {rsi_val:.1f} — The stock has been heavily sold. Contrarian buyers often look for entries here, especially if volume picks up and MACD turns positive."
                    st.markdown(f"{rsi_emoji} **RSI (14):** {rsi_text}")
                    
                    # MACD
                    macd_val = latest['MACD']
                    macd_signal = latest['MACDS']
                    macd_diff = latest['Diff']
                    if macd_diff > 0 and macd_val > 0:
                        macd_emoji, macd_text = "🟢", f"**Bullish** — MACD ({macd_val:.4f}) is above both the signal line and zero. This is the strongest bullish configuration, indicating upward momentum with positive acceleration."
                    elif macd_diff > 0:
                        macd_emoji, macd_text = "🔵", f"**Bullish Crossover** — MACD ({macd_val:.4f}) just crossed above the signal line but is still below zero. Early bullish signal — momentum is improving but hasn't fully reversed yet."
                    elif macd_diff < 0 and macd_val < 0:
                        macd_emoji, macd_text = "🔴", f"**Bearish** — MACD ({macd_val:.4f}) is below both the signal line and zero. This is the most bearish configuration, indicating sustained downward momentum."
                    else:
                        macd_emoji, macd_text = "🟡", f"**Bearish Crossover** — MACD ({macd_val:.4f}) has crossed below the signal line. Momentum is fading. Watch for whether it drops below zero for confirmation."
                    st.markdown(f"{macd_emoji} **MACD:** {macd_text}")
                    
                    # SMA Alignment
                    close = latest['Close']
                    sma5 = latest['SMA5']
                    sma22 = latest['SMA22']
                    sma50 = latest.get('SMA50', None)
                    
                    if close > sma5 > sma22:
                        sma_emoji, sma_text = "🟢", f"**Bullish Alignment** — Price (₺{close:.2f}) > SMA5 (₺{sma5:.2f}) > SMA22 (₺{sma22:.2f}). Short and medium-term trends are both up. This is the ideal structure for trend followers."
                    elif close < sma5 < sma22:
                        sma_emoji, sma_text = "🔴", f"**Bearish Alignment** — Price (₺{close:.2f}) < SMA5 (₺{sma5:.2f}) < SMA22 (₺{sma22:.2f}). Both short and medium-term trends are pointing down. Avoid long entries until this reverses."
                    elif close > sma5:
                        sma_emoji, sma_text = "🟡", f"**Mixed — Short-term Bullish** — Price is above SMA5 (₺{sma5:.2f}) but SMA5 hasn't crossed above SMA22 (₺{sma22:.2f}) yet. The short-term is recovering but the medium-term trend hasn't confirmed."
                    else:
                        sma_emoji, sma_text = "🟡", f"**Mixed — Short-term Weak** — Price (₺{close:.2f}) is below SMA5 (₺{sma5:.2f}). Short-term momentum is weak. Watch for a close above SMA5 as an early reversal signal."
                    st.markdown(f"{sma_emoji} **Moving Averages:** {sma_text}")
                    
                    # SMA50 position
                    if sma50 is not None and pd.notna(sma50):
                        if close > sma50:
                            st.markdown(f"📈 **SMA 50:** Price is **above** the 50-period SMA (₺{sma50:.2f}) — the medium-term trend supports the bulls.")
                        else:
                            st.markdown(f"📉 **SMA 50:** Price is **below** the 50-period SMA (₺{sma50:.2f}) — the medium-term trend favors the bears.")
                    
                    # Bollinger Bands
                    bb_upper = latest['bb_bbh']
                    bb_lower = latest['bb_bbl']
                    bb_mid = latest['bb_bbm']
                    if close > bb_upper:
                        st.markdown(f"⚡ **Bollinger Bands:** Price (₺{close:.2f}) is **above the upper band** (₺{bb_upper:.2f}). The stock is extended — this can mean strong breakout momentum or a potential snapback.")
                    elif close < bb_lower:
                        st.markdown(f"⚡ **Bollinger Bands:** Price (₺{close:.2f}) is **below the lower band** (₺{bb_lower:.2f}). The stock is oversold relative to its recent range — potential bounce zone.")
                    elif close > bb_mid:
                        st.markdown(f"📊 **Bollinger Bands:** Price is in the **upper half** of the bands (mid: ₺{bb_mid:.2f}). Mild bullish positioning within the normal range.")
                    else:
                        st.markdown(f"📊 **Bollinger Bands:** Price is in the **lower half** of the bands (mid: ₺{bb_mid:.2f}). Mild bearish positioning within the normal range.")
                    
                    st.markdown("---")
                    
                    # --- Overall Assessment ---
                    st.markdown("#### 🎯 Overall Assessment")
                    
                    is_chosen = ind2 >= 3 and vol2 > 0.7
                    
                    if is_chosen and ind2 >= 6:
                        st.success(f"✅ **{stock} qualifies as a CHOSEN STOCK** with a strong indicator score of {ind2:.0f}/10 backed by {vol2:.2f}x average volume. Multiple technical indicators are aligned bullish with sufficient volume confirmation. This is one of the strongest technical setups in the current scan.")
                    elif is_chosen:
                        st.success(f"✅ **{stock} qualifies as a CHOSEN STOCK** (Indicator ≥ 3 and Volume > 0.7). The stock shows {ind2:.0f} fresh buy crossovers with adequate volume ({vol2:.2f}x). A moderate setup — not the strongest signal but enough for the screener criteria.")
                    elif ind2 >= 3 and vol2 <= 0.7:
                        st.warning(f"⚠️ **{stock} has good indicator signals ({ind2:.0f}/10) but volume is insufficient** ({vol2:.2f}x). Technical signals without volume backing are less reliable. The buy setup exists but lacks conviction from market participants.")
                    elif ind2 < 3 and vol2 > 0.7:
                        st.warning(f"⚠️ **{stock} has decent volume ({vol2:.2f}x) but few buy signals** ({ind2:.0f}/10). Volume is present but the technical indicators haven't aligned. This could mean distribution (selling with volume) rather than accumulation.")
                    else:
                        st.info(f"ℹ️ **{stock} does not currently meet the screener criteria.** Both indicator score ({ind2:.0f}/10) and volume ({vol2:.2f}x) are below thresholds. The stock lacks a clear technical entry signal at this time.")
                
                # Gauges in an expander (optional detail, not blocking mobile view)
                with st.expander("📊 Detailed Gauge Charts"):
                    gc1, gc2 = st.columns(2)
                    with gc1:
                        st.plotly_chart(create_gauge(ind2, "Indicator 2", 10), use_container_width=True, config=PLOTLY_CONFIG)
                    with gc2:
                        st.plotly_chart(create_gauge(ind1, "Indicator 1"), use_container_width=True, config=PLOTLY_CONFIG)
                    gc3, gc4 = st.columns(2)
                    with gc3:
                        st.plotly_chart(create_gauge(vol1, "Volume 1"), use_container_width=True, config=PLOTLY_CONFIG)
                    with gc4:
                        st.markdown(f"**Volume Score 2:** {vol2:.2f}")
                        if vol2 > 0.7:
                            st.success("✅ Above 0.7")
                        else:
                            st.warning("⚠️ Below 0.7")
                if ind2 >= 3 and vol2 > 0.7:
                    st.markdown('<div class="chosen-stock"><h3>⭐ CHOSEN STOCK! ⭐</h3></div>', unsafe_allow_html=True)
                
                st.subheader("📊 Price Chart")
                st.plotly_chart(create_candlestick(df, stock), use_container_width=True, config=PLOTLY_CONFIG)
                
                # Tabs for additional charts and analysis
                tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
                    "📊 Volume", "📈 MACD", "📉 RSI",
                    "🔮 Patterns", "🎲 Monte Carlo", "📐 Fibonacci"
                ])
                with tab1:
                    st.plotly_chart(create_volume_chart(df), use_container_width=True, config=PLOTLY_CONFIG)
                with tab2:
                    st.plotly_chart(create_macd_chart(df), use_container_width=True, config=PLOTLY_CONFIG)
                with tab3:
                    st.plotly_chart(create_rsi_chart(df), use_container_width=True, config=PLOTLY_CONFIG)
                with tab4:
                    display_pattern_tab(df, stock)
                with tab5:
                    run_monte_carlo(df, stock)
                with tab6:
                    display_fibonacci_tab(df, stock)
                
                # Raw data expander
                with st.expander("📋 View Raw Data"):
                    st.dataframe(df[['Open', 'High', 'Low', 'Close', 'Volume', 'RSI', 'MACD']].tail(100), use_container_width=True)
                
                # Fundamental data section
                display_balance_sheet(stock, current_price=latest['Close'])
            else:
                st.error(f"❌ No data available for {stock}")
        
        elif mode == "🔍 Stock Screener":
            st.subheader("🔍 Chosen Stocks")
            if selected_tf in st.session_state.chosen_stocks and st.session_state.chosen_stocks[selected_tf]:
                results = st.session_state.chosen_stocks[selected_tf]
                df_c = pd.DataFrame(results).sort_values('indicator_score_2', ascending=False)
                st.dataframe(df_c, use_container_width=True)
                cols = st.columns(min(3, max(1, len(df_c))))
                for idx, s in enumerate(df_c.to_dict('records')):
                    with cols[idx % len(cols)]:
                        st.markdown(f"""
                        <div class="chosen-stock">
                            <h4>{s['symbol']}</h4>
                            <p><b>Indicator:</b> {s['indicator_score_2']}</p>
                            <p><b>Volume:</b> {s['volume_score_2']}</p>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.info("Click 'Run Screener'")
        
        elif mode == "📋 Market Summary":
            st.subheader(f"📋 Market Summary - {TIMEFRAMES[selected_tf]['label']}")
            
            if selected_tf in st.session_state.market_summary:
                data = st.session_state.market_summary[selected_tf]
                sentiment = data['sentiment']
                above_sma50 = data['above_sma50']
                below_sma50 = data['below_sma50']
                sma50_na = data['sma50_na']
                scan_time = data['scan_time']
                
                st.caption(f"Last scanned: {scan_time}")
                
                total_valid = sum(len(v) for k, v in sentiment.items() if k != "ERROR")
                total_errors = len(sentiment.get("ERROR", []))
                
                # ── Sentiment Distribution ──
                st.markdown("### 📊 Sentiment Distribution")
                
                sentiment_config = [
                    ("STRONG BULLISH", "🟢", "sentiment-strong-bullish"),
                    ("BULLISH", "🔵", "sentiment-bullish"),
                    ("NEUTRAL", "🟡", "sentiment-neutral"),
                    ("BEARISH", "🟠", "sentiment-bearish"),
                    ("STRONG BEARISH", "🔴", "sentiment-strong-bearish"),
                ]
                
                for label, emoji, css_class in sentiment_config:
                    count = len(sentiment.get(label, []))
                    pct = (count / total_valid * 100) if total_valid > 0 else 0
                    st.markdown(f"""
                    <div class="{css_class}" style="padding: 0.8rem; font-size: 1.1rem; display: flex; justify-content: space-between; align-items: center;">
                        <span>{emoji} {label}</span>
                        <span><b>{count}</b> stocks ({pct:.1f}%)</span>
                    </div>
                    """, unsafe_allow_html=True)
                
                if total_errors > 0:
                    st.caption(f"⚠️ {total_errors} stocks could not be scanned (data unavailable)")
                
                # ── Sentiment bar chart ──
                chart_labels = [c[0] for c in sentiment_config]
                chart_counts = [len(sentiment.get(l, [])) for l in chart_labels]
                chart_colors = ["#00c851", "#33b5e5", "#ffbb33", "#ff8800", "#cc0000"]
                
                fig_sent = go.Figure(go.Bar(
                    x=chart_labels, y=chart_counts,
                    marker_color=chart_colors,
                    text=chart_counts, textposition='auto'
                ))
                fig_sent.update_layout(
                    title="Sentiment Distribution",
                    yaxis_title="Number of Stocks",
                    height=300,
                    margin=dict(l=40, r=20, t=40, b=70),
                    legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, font=dict(size=10)),
                    xaxis_tickangle=-30,
                    xaxis_tickfont=dict(size=9)
                )
                st.plotly_chart(fig_sent, use_container_width=True, config=PLOTLY_CONFIG)
                
                # ── SMA 50 Analysis ──
                st.markdown("### 📈 50-Day SMA Analysis")
                
                total_sma = len(above_sma50) + len(below_sma50)
                above_pct = (len(above_sma50) / total_sma * 100) if total_sma > 0 else 0
                below_pct = (len(below_sma50) / total_sma * 100) if total_sma > 0 else 0
                
                sma_c1, sma_c2 = st.columns(2)
                with sma_c1:
                    st.markdown(f"""
                    <div class="mobile-score-card" style="border: 2px solid #28a745;">
                        <p class="score-label">Above SMA 50</p>
                        <p class="score-value" style="color: #28a745;">{len(above_sma50)}</p>
                        <p class="score-max">{above_pct:.1f}% of stocks</p>
                    </div>
                    """, unsafe_allow_html=True)
                with sma_c2:
                    st.markdown(f"""
                    <div class="mobile-score-card" style="border: 2px solid #dc3545;">
                        <p class="score-label">Below SMA 50</p>
                        <p class="score-value" style="color: #dc3545;">{len(below_sma50)}</p>
                        <p class="score-max">{below_pct:.1f}% of stocks</p>
                    </div>
                    """, unsafe_allow_html=True)
                
                if len(sma50_na) > 0:
                    st.caption(f"ℹ️ {len(sma50_na)} stocks had insufficient data for SMA 50 calculation")
                
                # SMA50 donut chart
                fig_sma = go.Figure(go.Pie(
                    labels=["Above SMA 50", "Below SMA 50"],
                    values=[len(above_sma50), len(below_sma50)],
                    hole=0.5,
                    marker_colors=["#28a745", "#dc3545"],
                    textinfo='label+percent+value',
                    textfont_size=11
                ))
                fig_sma.update_layout(
                    title="Price vs 50-Day SMA",
                    height=300,
                    margin=dict(l=20, r=20, t=40, b=40),
                    legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5, font=dict(size=10))
                )
                st.plotly_chart(fig_sma, use_container_width=True, config=PLOTLY_CONFIG)
                
                # ── Expandable stock lists ──
                st.markdown("### 📋 Stock Lists")
                for label, emoji, _ in sentiment_config:
                    stock_list_for_cat = sentiment.get(label, [])
                    if stock_list_for_cat:
                        with st.expander(f"{emoji} {label} — {len(stock_list_for_cat)} stocks"):
                            st.write(", ".join(sorted(stock_list_for_cat)))
                
                with st.expander(f"📈 Above SMA 50 — {len(above_sma50)} stocks"):
                    st.write(", ".join(sorted(above_sma50)))
                with st.expander(f"📉 Below SMA 50 — {len(below_sma50)} stocks"):
                    st.write(", ".join(sorted(below_sma50)))
            else:
                st.info("👆 Click 'Scan All Stocks' in the sidebar to generate the market summary.")
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        st.info("Please refresh the page and try again.")

if __name__ == "__main__":
    main()
