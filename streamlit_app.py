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
if 'financial_store' not in st.session_state:
    st.session_state.financial_store = {}  # {symbol: raw_data_dict}
if 'financial_import_time' not in st.session_state:
    st.session_state.financial_import_time = None
if 'financial_import_errors' not in st.session_state:
    st.session_state.financial_import_errors = []
if 'value_finder_results' not in st.session_state:
    st.session_state.value_finder_results = None

FINANCIAL_STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "financial_store.json")

def _save_financial_store():
    """Persist financial store to JSON file for cross-session use."""
    try:
        import json
        payload = {
            "import_time": st.session_state.financial_import_time,
            "data": {}
        }
        for symbol, raw_data in st.session_state.financial_store.items():
            # raw_data keys are ints (years), convert to strings for JSON
            payload["data"][symbol] = {str(y): v for y, v in raw_data.items()}
        with open(FINANCIAL_STORE_FILE, 'w') as f:
            json.dump(payload, f)
    except Exception:
        pass  # Non-critical — store still works in session

def _load_financial_store():
    """Load financial store from JSON file if available and session is empty."""
    if st.session_state.financial_store:
        return  # Already loaded
    try:
        import json
        if os.path.exists(FINANCIAL_STORE_FILE):
            with open(FINANCIAL_STORE_FILE, 'r') as f:
                payload = json.load(f)
            st.session_state.financial_import_time = payload.get("import_time")
            for symbol, year_data in payload.get("data", {}).items():
                # Convert string keys back to int years
                st.session_state.financial_store[symbol] = {int(y): v for y, v in year_data.items()}
    except Exception:
        pass

# Auto-load on startup
_load_financial_store()

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
                    latest = df.iloc[-1]
                    prev = df.iloc[-2] if len(df) > 1 else latest
                    price = latest['Close']
                    price_chg = ((price - prev['Close']) / prev['Close']) * 100 if len(df) > 1 else 0
                    rsi = latest.get('RSI', None)
                    
                    row = {
                        'symbol': s,
                        'price': round(price, 2),
                        'chg%': round(price_chg, 2),
                        'RSI': round(rsi, 1) if rsi and pd.notna(rsi) else None,
                        'indicator_score_2': round(ind, 2),
                        'volume_score_2': round(vol, 2),
                    }
                    
                    # Add valuations if financial data available
                    vals = compute_stock_valuations(s, price)
                    row['P/E'] = vals.get('pe')
                    row['PD/DD'] = vals.get('pb')
                    row['EV/EBITDA'] = vals.get('ev_ebitda')
                    row['Fwd P/E'] = vals.get('fwd_pe')
                    row['Fwd PD/DD'] = vals.get('fwd_pb')
                    row['Fwd EV/EBITDA'] = vals.get('fwd_ev_ebitda')
                    row['P/E Δ'] = vals.get('pe_delta')
                    row['EV/EBITDA Δ'] = vals.get('ev_ebitda_delta')
                    
                    chosen.append(row)
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
    "total_assets":        ("Total Assets",              ["toplam varlıklar", "varlıklar toplamı", "varliklar toplami"]),
    "current_assets":      ("Current Assets",            ["dönen varlıklar"]),
    "noncurrent_assets":   ("Non-Current Assets",        ["duran varlıklar"]),
    "cash":                ("Cash & Equivalents",        ["nakit ve nakit benzerleri"]),
    "trade_recv_short":    ("Trade Receivables (Short)",  ["ticari alacaklar"]),
    "inventories":         ("Inventories",               ["stoklar"]),
    "ppe":                 ("Property, Plant & Equip.",   ["maddi duran varlıklar"]),
    "total_liab_equity":   ("Total Liabilities + Equity", ["kaynaklar toplamı", "toplam kaynaklar", "kaynaklar toplami"]),
    "current_liabilities": ("Current Liabilities",       ["kısa vadeli yükümlülükler"]),
    "noncurrent_liab":     ("Non-Current Liabilities",   ["uzun vadeli yükümlülükler"]),
    "short_borrowings":    ("Short-term Borrowings",     ["kısa vadeli borçlanmalar"]),
    "long_borrowings":     ("Long-term Borrowings",      ["uzun vadeli borçlanmalar"]),
    "total_equity":        ("Total Equity",              ["özkaynaklar", "özkaynak", "toplam özkaynaklar"]),
    "paid_in_capital":     ("Paid-in Capital",           ["ödenmiş sermaye", "çıkarılmış sermaye"]),
}

KEY_INCOME_BY_DESC = {
    "revenue":             ("Revenue / Sales",           ["hasılat", "satış gelirleri"]),
    "cost_of_sales":       ("Cost of Sales",             ["satışların maliyeti"]),
    "gross_profit":        ("Gross Profit",              ["brüt kar", "brüt kâr", "ticari faaliyetlerden brüt"]),
    "depreciation":        ("Depreciation & Amort.",     ["amortisman"]),
    "operating_profit":    ("Operating Profit / EBIT",   ["esas faaliyet karı", "esas faaliyet kârı", "faaliyet karı", "faaliyet kârı"]),
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


def _fetch_single_stock_financials(symbol, years=None):
    """
    Fetch financials for a single stock directly (no caching decorator).
    Used by the bulk import process.
    """
    if years is None:
        current_year = datetime.now().year
        years = list(range(current_year, current_year - 5, -1))
    
    all_data = {}
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
                    break
                elif resp.status_code in (503, 429):
                    import time
                    time.sleep(2)
                    continue
                else:
                    break
            except Exception:
                if attempt == 0:
                    import time
                    time.sleep(1)
                    continue
                break
    return all_data


def import_all_financials(stock_list, sleep_between=1.5):
    """
    Bulk import financials for all stocks. Stores in session_state.
    Uses a progress bar. Returns (success_count, error_list).
    """
    import time
    errors = []
    success = 0
    total = len(stock_list)
    
    prog = st.progress(0)
    status = st.empty()
    
    for i, symbol in enumerate(stock_list):
        status.text(f"📥 Importing {symbol}... ({i+1}/{total})")
        prog.progress((i + 1) / total)
        
        try:
            raw_data = _fetch_single_stock_financials(symbol)
            if raw_data:
                st.session_state.financial_store[symbol] = raw_data
                success += 1
            else:
                errors.append(symbol)
        except Exception:
            errors.append(symbol)
        
        # Gentle delay to avoid rate-limiting
        if i < total - 1:
            time.sleep(sleep_between)
    
    prog.empty()
    status.empty()
    
    st.session_state.financial_import_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    st.session_state.financial_import_errors = errors
    
    # Persist to file
    _save_financial_store()
    
    return success, errors


def get_financial_data(symbol):
    """
    Get financial data for a symbol — first checks the local store,
    falls back to live API only if not imported.
    Returns raw_data dict or None.
    """
    # 1. Check session store (bulk imported data)
    if symbol in st.session_state.financial_store:
        return st.session_state.financial_store[symbol]
    
    # 2. Fallback: try live API fetch
    try:
        raw_data = fetch_balance_sheet(symbol)
        return raw_data
    except Exception:
        return None


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
    
    IMPORTANT: İş Yatırım MaliTablo API returns all values in THOUSANDS of TL (Bin TL).
    So a value of 5,000,000 in the API = 5,000,000,000 TL actual = 5 Billion TL.
    
    Args:
        df_full: Full parsed balance sheet DataFrame (values in thousands TL)
        current_price: Current stock price (TL per share)
        valuation_data: Optional dict from fetch_valuation_data
    
    Returns: dict with pe_ratio, pb_ratio, ev_ebitda, and component values
    """
    if df_full is None or df_full.empty or current_price is None or current_price <= 0:
        return {}
    
    UNIT = 1000  # API values are in thousands TL; multiply by UNIT to get actual TL
    
    def get_val(logical_key, period):
        """Get raw API value (in thousands TL) for a logical key and period."""
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
    
    # All values below are in THOUSANDS TL as returned by the API
    total_equity = get_val("total_equity", latest)
    paid_in_capital = get_val("paid_in_capital", latest)
    net_profit = get_val("net_profit_parent", latest) or get_val("net_profit", latest)
    operating_profit = get_val("operating_profit", latest)
    depreciation = get_val("depreciation", latest)
    short_debt = get_val("short_borrowings", latest)
    long_debt = get_val("long_borrowings", latest)
    cash = get_val("cash", latest)
    
    result = {"period": latest}
    
    # ── Shares Outstanding ──
    # BIST stocks have a par value of 1 TL per share.
    # Paid-in capital (Ödenmiş Sermaye) in actual TL = number of shares.
    # API gives paid_in_capital in thousands TL, so:
    #   shares = paid_in_capital * 1000
    shares = None
    if paid_in_capital and paid_in_capital > 0:
        shares = paid_in_capital * UNIT  # actual number of shares
        result["shares"] = shares
    
    # ── Market Cap = Price × Shares (result in TL) ──
    market_cap = None
    if shares and current_price:
        market_cap = current_price * shares  # in TL
        result["market_cap"] = market_cap
    
    # ── P/E Ratio (F/K) = Market Cap / TTM Net Profit ──
    # İş Yatırım income statement figures are CUMULATIVE for the year:
    #   /12 = full year, /9 = first 9 months, /6 = first 6 months, /3 = first 3 months
    # To get TTM: use /12 directly, or annualize interim periods.
    ttm_net_profit_tl = None
    
    # Best: use the latest annual (/12) figure
    annual_periods = [p for p in periods if p.endswith("/12")]
    if annual_periods:
        annual_np = get_val("net_profit_parent", annual_periods[0]) or get_val("net_profit", annual_periods[0])
        if annual_np is not None:
            ttm_net_profit_tl = annual_np * UNIT
    
    # If no annual available, annualize the latest interim figure
    if ttm_net_profit_tl is None and net_profit is not None:
        quarter = latest.split("/")[1]
        annualization_factor = {"12": 1, "9": 12/9, "6": 12/6, "3": 12/3}.get(quarter, 1)
        ttm_net_profit_tl = net_profit * UNIT * annualization_factor
    
    if market_cap and ttm_net_profit_tl and ttm_net_profit_tl != 0:
        result["pe_ratio"] = round(market_cap / ttm_net_profit_tl, 2)
        result["ttm_net_profit"] = ttm_net_profit_tl
    
    # ── P/B Ratio (PD/DD) = Market Cap / Total Equity ──
    if market_cap and total_equity and total_equity != 0:
        total_equity_tl = total_equity * UNIT
        result["pb_ratio"] = round(market_cap / total_equity_tl, 2)
        result["total_equity"] = total_equity
    
    # ── EBITDA = Operating Profit + |Depreciation & Amortization| ──
    # Both are cumulative for the period, in thousands TL.
    # Note: D&A can be reported as negative (expense) or positive; we always add abs value.
    ebitda_thousands = None
    if operating_profit is not None:
        da = abs(depreciation) if (depreciation is not None and depreciation != 0) else 0
        ebitda_thousands = operating_profit + da
        result["ebitda_period"] = ebitda_thousands
    
    # ── TTM EBITDA (annualize if interim period) ──
    ttm_ebitda_tl = None
    if ebitda_thousands is not None and ebitda_thousands != 0:
        quarter = latest.split("/")[1]
        annualization_factor = {"12": 1, "9": 12/9, "6": 12/6, "3": 12/3}.get(quarter, 1)
        ttm_ebitda_tl = ebitda_thousands * UNIT * annualization_factor
    
    # ── Enterprise Value = Market Cap + Total Debt - Cash ──
    total_debt_tl = ((short_debt or 0) + (long_debt or 0)) * UNIT
    cash_tl = (cash or 0) * UNIT
    
    if market_cap:
        ev = market_cap + total_debt_tl - cash_tl
        result["enterprise_value"] = ev
        
        # ── EV/EBITDA ──
        if ttm_ebitda_tl and ttm_ebitda_tl > 0:
            ev_ebitda = ev / ttm_ebitda_tl
            result["ev_ebitda"] = round(ev_ebitda, 2)
            result["ttm_ebitda"] = ttm_ebitda_tl
    
    # ── ROE for forward P/B calculation ──
    if total_equity and total_equity > 0 and net_profit and net_profit != 0:
        quarter = latest.split("/")[1]
        ann_factor = {"12": 1, "9": 12/9, "6": 12/6, "3": 12/3}.get(quarter, 1)
        annualized_np = net_profit * ann_factor
        roe = annualized_np / total_equity
        result["roe"] = round(roe, 4)
    
    return result


def _match_item_by_desc(item_desc_tr, keyword_patterns):
    """Check if an item's Turkish description matches any of the keyword patterns."""
    desc_lower = _normalize_turkish(item_desc_tr)
    for pattern in keyword_patterns:
        if _normalize_turkish(pattern) in desc_lower:
            return True
    return False


def _normalize_turkish(text):
    """Normalize Turkish text for matching: handle kâr/kar, î/i, â/a, û/u etc."""
    t = text.lower().strip()
    t = t.replace("â", "a").replace("î", "i").replace("û", "u").replace("ô", "o")
    t = t.replace("kâr", "kar").replace("kâ", "ka")
    return t


def _match_operating_profit(item_desc_tr):
    """
    Special matching for operating profit / EBIT.
    Must contain 'faaliyet kar' but must NOT be a 'sürdürülen faaliyetler' or
    'vergi öncesi' line (those are different P&L lines below EBIT).
    """
    d = _normalize_turkish(item_desc_tr)
    # Must contain faaliyet karı/kârı
    if "faaliyet kar" not in d:
        return False
    # Exclude these — they are NOT operating profit
    excludes = ["sürdürülen faaliyet", "vergi öncesi", "durdurulan faaliyet",
                "finansman", "yatırım faaliyet", "diğer faaliyet"]
    for ex in excludes:
        if ex in d:
            return False
    return True


def _build_code_map(raw_data):
    """
    Scan the actual API data and build a mapping:  logical_key -> actual_itemCode
    by matching Turkish descriptions. This handles the varying codes across company types.
    
    For items with multiple matches (like "özkaynaklar" appearing in sub-items),
    prefers the item with the SHORTEST description (most likely the parent/total line)
    and that has actual non-null values.
    """
    all_items_by_desc = {**KEY_ITEMS_BY_DESC, **KEY_INCOME_BY_DESC}
    code_map = {}  # logical_key -> (itemCode, itemDescTr)
    
    # Use data from the most recent year
    sorted_years = sorted(raw_data.keys(), reverse=True)
    items = raw_data[sorted_years[0]]
    
    for logical_key, (en_label, patterns) in all_items_by_desc.items():
        # Collect ALL matching items, then pick the best one
        candidates = []
        for item in items:
            desc_tr = item.get("itemDescTr", "")
            actual_code = item.get("itemCode", "")
            
            # Special matching for operating_profit to avoid wrong lines
            if logical_key == "operating_profit":
                matched = _match_operating_profit(desc_tr)
            else:
                matched = _match_item_by_desc(desc_tr, patterns)
            
            if matched:
                # Check if this item has actual values
                has_value = any(item.get(f"value{i}") is not None for i in range(1, 5))
                candidates.append((actual_code, desc_tr, has_value, len(desc_tr)))
        
        if candidates:
            # Sort: prefer items WITH values first, then by shortest description
            # (shortest = most likely the total/parent line, not a sub-item)
            candidates.sort(key=lambda x: (not x[2], x[3]))
            best = candidates[0]
            code_map[logical_key] = (best[0], best[1])
    
    # Special fallback for total_equity: if no match with "toplam özkaynaklar",
    # try matching just "özkaynaklar" but prefer items at the top hierarchy level
    if "total_equity" not in code_map:
        equity_candidates = []
        for item in items:
            desc_tr = item.get("itemDescTr", "").lower().strip()
            actual_code = item.get("itemCode", "")
            if "özkaynak" in desc_tr:
                has_value = any(item.get(f"value{i}") is not None for i in range(1, 5))
                # Shorter codes tend to be parent items (e.g., "2O" vs "2OA")
                equity_candidates.append((actual_code, item.get("itemDescTr", ""), has_value, len(actual_code), len(desc_tr)))
        if equity_candidates:
            # Prefer: has value, shortest code, shortest description
            equity_candidates.sort(key=lambda x: (not x[2], x[3], x[4]))
            best = equity_candidates[0]
            code_map["total_equity"] = (best[0], best[1])
    
    # Same fallback for paid_in_capital
    if "paid_in_capital" not in code_map:
        capital_candidates = []
        for item in items:
            desc_tr = item.get("itemDescTr", "").lower().strip()
            actual_code = item.get("itemCode", "")
            if "sermaye" in desc_tr and "artır" not in desc_tr and "yedek" not in desc_tr:
                has_value = any(item.get(f"value{i}") is not None for i in range(1, 5))
                capital_candidates.append((actual_code, item.get("itemDescTr", ""), has_value, len(actual_code), len(desc_tr)))
        if capital_candidates:
            capital_candidates.sort(key=lambda x: (not x[2], x[3], x[4]))
            best = capital_candidates[0]
            code_map["paid_in_capital"] = (best[0], best[1])
    
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


def _make_quarterly_bar_chart(df_source, logical_key, title, color, fallback_key=None, forecasts=None):
    """
    Helper: create a quarterly bar chart for a given item by LogicalKey.
    If forecasts dict is provided, append forecast bars in a distinct style.
    forecasts: dict {period_label: value} e.g. {"2026/3 F": 1234, ...}
    """
    row = df_source[df_source["LogicalKey"] == logical_key] if "LogicalKey" in df_source.columns else pd.DataFrame()
    if row.empty and fallback_key:
        row = df_source[df_source["LogicalKey"] == fallback_key] if "LogicalKey" in df_source.columns else pd.DataFrame()
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
    
    fig = go.Figure()
    
    # Historical bars
    fig.add_trace(go.Bar(
        x=periods, y=vals,
        marker_color=bar_colors,
        text=[f"{v/1000:,.0f}K" if abs(v) >= 1000 else f"{v:,.0f}" for v in vals],
        textposition='outside',
        textfont_size=8,
        name="Actual"
    ))
    
    # Forecast bars (if provided)
    if forecasts:
        fc_periods = list(forecasts.keys())
        fc_vals = list(forecasts.values())
        fc_colors = ["rgba(255,215,0,0.7)" if v >= 0 else "rgba(255,100,100,0.7)" for v in fc_vals]
        fig.add_trace(go.Bar(
            x=fc_periods, y=fc_vals,
            marker_color=fc_colors,
            marker_line=dict(color="gold", width=2),
            text=[f"{v/1000:,.0f}K" if abs(v) >= 1000 else f"{v:,.0f}" for v in fc_vals],
            textposition='outside',
            textfont_size=8,
            name="Forecast"
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
        showlegend=bool(forecasts),
    )
    return fig


def _extract_standalone_quarters(df_source, logical_key, fallback_key=None):
    """
    Extract STANDALONE quarterly values from cumulative İş Yatırım data.
    
    İş Yatırım reports /3=Q1, /6=H1(cumulative), /9=9M(cumulative), /12=FY(cumulative).
    Standalone: Q1=/3, Q2=/6-/3, Q3=/9-/6, Q4=/12-/9.
    
    Returns: list of (period_label, standalone_value) in chronological order.
    """
    row = df_source[df_source["LogicalKey"] == logical_key] if "LogicalKey" in df_source.columns else pd.DataFrame()
    if row.empty and fallback_key:
        row = df_source[df_source["LogicalKey"] == fallback_key] if "LogicalKey" in df_source.columns else pd.DataFrame()
    if row.empty:
        return []
    
    period_cols = [c for c in df_source.columns if "/" in c]
    # Sort chronologically (oldest first)
    periods = sorted(period_cols, key=lambda x: (int(x.split("/")[0]), int(x.split("/")[1])))
    
    # Group by year
    year_data = {}
    for p in periods:
        y, q = p.split("/")
        y = int(y)
        q = int(q)
        v = pd.to_numeric(row.iloc[0].get(p), errors='coerce')
        if pd.notna(v):
            year_data.setdefault(y, {})[q] = v
    
    standalones = []
    for y in sorted(year_data.keys()):
        qdata = year_data[y]
        for q in [3, 6, 9, 12]:
            if q not in qdata:
                continue
            if q == 3:
                standalone = qdata[3]
            else:
                prev_q = {6: 3, 9: 6, 12: 9}[q]
                if prev_q in qdata:
                    standalone = qdata[q] - qdata[prev_q]
                else:
                    standalone = qdata[q]  # Can't de-cumulate, use as-is
            standalones.append((f"{y}/Q{q//3}", standalone, y, q))
    
    return standalones


def forecast_financials(df_full):
    """
    Intelligent 4-quarter financial forecast using ensemble of methods:
    
    1. Seasonal decomposition: Uses same-quarter-last-year values with growth trend
    2. Rolling momentum: Recent quarter trajectory extrapolation  
    3. Mean reversion: Weighted average toward long-term mean
    
    The final forecast is a weighted blend of all available methods,
    with more weight given to seasonal patterns (which are dominant in
    cyclical industries like Turkish industrials).
    
    Returns: dict of {logical_key: {period_label: forecasted_value_in_thousands}} 
    """
    if df_full is None or df_full.empty:
        return {}
    
    forecast_items = {
        "revenue": "net_profit",  # just iterate keys below
    }
    
    items_to_forecast = [
        ("revenue", "revenue", None),
        ("gross_profit", "gross_profit", None),
        ("ebitda", "ebitda", None),
        ("net_profit", "net_profit_parent", "net_profit"),
    ]
    
    all_forecasts = {}
    
    for label, lk, fallback in items_to_forecast:
        quarters = _extract_standalone_quarters(df_full, lk, fallback)
        if len(quarters) < 4:
            continue
        
        values = [v for _, v, _, _ in quarters]
        years_quarters = [(y, q) for _, _, y, q in quarters]
        
        # Determine next 4 quarters after the last available
        last_y, last_q = years_quarters[-1]
        next_quarters = []
        cy, cq = last_y, last_q
        for _ in range(4):
            cq += 3
            if cq > 12:
                cq = 3
                cy += 1
            next_quarters.append((cy, cq))
        
        forecasts = {}
        
        for fy, fq in next_quarters:
            # ── Method 1: Seasonal (same quarter YoY) ──
            # Find same quarter from previous years
            same_q_vals = [v for _, v, y, q in quarters if q == fq]
            seasonal_forecast = None
            if len(same_q_vals) >= 2:
                # Use YoY growth rate of the most recent same-quarter pair
                recent = same_q_vals[-1]
                prev = same_q_vals[-2]
                if prev != 0 and abs(prev) > 1:
                    yoy_growth = (recent - prev) / abs(prev)
                    # Dampen extreme growth rates (mean-revert toward 0 growth)
                    dampened_growth = yoy_growth * 0.6  # 60% of observed growth
                    seasonal_forecast = recent * (1 + dampened_growth)
                else:
                    seasonal_forecast = recent
            elif len(same_q_vals) == 1:
                seasonal_forecast = same_q_vals[0]
            
            # ── Method 2: Rolling momentum (last 4 quarters trend) ──
            momentum_forecast = None
            if len(values) >= 4:
                recent_4 = values[-4:]
                # Linear regression on last 4 quarters
                x = np.arange(len(recent_4))
                if np.std(recent_4) > 0:
                    slope = np.polyfit(x, recent_4, 1)[0]
                    # Project forward
                    steps_ahead = len([1 for ny, nq in next_quarters if (ny, nq) <= (fy, fq)])
                    momentum_forecast = recent_4[-1] + slope * steps_ahead
            
            # ── Method 3: Mean reversion (weighted avg of all same-quarter values) ──
            reversion_forecast = None
            if len(same_q_vals) >= 2:
                # Exponentially weighted: more recent quarters get more weight
                weights = np.array([0.5 ** (len(same_q_vals) - 1 - i) for i in range(len(same_q_vals))])
                weights /= weights.sum()
                reversion_forecast = np.average(same_q_vals, weights=weights)
            
            # ── Ensemble blend ──
            candidates = []
            weights = []
            
            if seasonal_forecast is not None:
                candidates.append(seasonal_forecast)
                weights.append(0.50)  # Seasonal gets highest weight (cyclicality)
            
            if momentum_forecast is not None:
                candidates.append(momentum_forecast)
                weights.append(0.30)  # Momentum captures recent trajectory
            
            if reversion_forecast is not None:
                candidates.append(reversion_forecast)
                weights.append(0.20)  # Mean reversion acts as stabilizer
            
            if candidates:
                weights = np.array(weights)
                weights /= weights.sum()  # Normalize
                final_forecast = np.average(candidates, weights=weights)
                
                period_label = f"{fy}/Q{fq//3} F"
                forecasts[period_label] = round(final_forecast, 0)
        
        if forecasts:
            all_forecasts[label] = forecasts
    
    return all_forecasts


def _standalone_to_cumulative(standalone_forecasts):
    """
    Convert standalone quarterly forecasts to cumulative values within each year.
    This matches the İş Yatırım display convention: /3=Q1, /6=Q1+Q2, /9=Q1+Q2+Q3, /12=FY
    
    Input:  {"2026/Q1 F": 100, "2026/Q2 F": 120, "2026/Q3 F": 80, "2026/Q4 F": 90}
    Output: {"2026/3 F": 100, "2026/6 F": 220, "2026/9 F": 300, "2026/12 F": 390}
    """
    if not standalone_forecasts:
        return {}
    
    # Parse into year -> {quarter_num: value}
    year_data = {}
    for label, val in standalone_forecasts.items():
        # label is like "2026/Q1 F"
        parts = label.replace(" F", "").split("/")
        y = int(parts[0])
        q_num = int(parts[1].replace("Q", ""))
        period_month = q_num * 3  # Q1->3, Q2->6, Q3->9, Q4->12
        year_data.setdefault(y, []).append((period_month, val))
    
    cumulative = {}
    for y in sorted(year_data.keys()):
        quarters = sorted(year_data[y], key=lambda x: x[0])
        running_sum = 0
        for month, val in quarters:
            running_sum += val
            cumulative[f"{y}/{month} F"] = round(running_sum, 0)
    
    return cumulative


def _cumulate_forecasts(standalone_forecasts):
    """
    Convert standalone quarterly forecasts back to cumulative values
    (matching İş Yatırım convention) for valuation calculations.
    
    Input: {"2026/Q1 F": 100, "2026/Q2 F": 120, "2026/Q3 F": 80, "2026/Q4 F": 90}
    Output: TTM sum = 100 + 120 + 80 + 90 = 390
    """
    vals = list(standalone_forecasts.values())
    return sum(vals) if vals else None


def compute_stock_valuations(symbol, current_price):
    """
    Compute current and forward valuations for a single stock.
    Returns dict with pe, pb, ev_ebitda, forward_pe, forward_ev_ebitda, etc.
    Returns empty dict on failure.
    """
    result = {}
    raw_data = get_financial_data(symbol)
    if not raw_data or not current_price or current_price <= 0:
        return result
    
    try:
        all_key_items = {**KEY_ITEMS_BY_DESC, **KEY_INCOME_BY_DESC}
        df_full = parse_balance_sheet_to_df(raw_data, item_filter=all_key_items)
        if df_full is None or df_full.empty:
            return result
        
        # Add EBITDA row
        period_cols = [c for c in df_full.columns if "/" in c]
        op_row = df_full[df_full["LogicalKey"] == "operating_profit"] if "LogicalKey" in df_full.columns else pd.DataFrame()
        da_row = df_full[df_full["LogicalKey"] == "depreciation"] if "LogicalKey" in df_full.columns else pd.DataFrame()
        if not op_row.empty:
            ebitda_row_data = {"Code": "EBITDA_CALC", "LogicalKey": "ebitda", "Item (TR)": "EBITDA", "Item (EN)": "EBITDA"}
            for p in period_cols:
                op_val = pd.to_numeric(op_row.iloc[0].get(p), errors='coerce')
                da_val = pd.to_numeric(da_row.iloc[0].get(p), errors='coerce') if not da_row.empty else 0
                ebitda_row_data[p] = (op_val + (abs(da_val) if pd.notna(da_val) else 0)) if pd.notna(op_val) else None
            df_full = pd.concat([df_full, pd.DataFrame([ebitda_row_data])], ignore_index=True)
        
        # Current valuations
        valuation = calculate_valuation_metrics(df_full, current_price)
        if valuation:
            result["pe"] = valuation.get("pe_ratio")
            result["pb"] = valuation.get("pb_ratio")
            result["ev_ebitda"] = valuation.get("ev_ebitda")
            result["market_cap"] = valuation.get("market_cap")
        
        # Forward valuations
        forecasts = forecast_financials(df_full)
        if forecasts and valuation:
            fwd = calculate_forward_valuations(current_price, valuation, forecasts)
            result["fwd_pe"] = fwd.get("forward_pe")
            result["fwd_pb"] = fwd.get("forward_pb")
            result["fwd_ev_ebitda"] = fwd.get("forward_ev_ebitda")
            result["roe"] = valuation.get("roe")
        
        # Deltas (positive = current is higher = stock getting cheaper on forward basis)
        if result.get("pe") and result.get("fwd_pe"):
            result["pe_delta"] = round(result["pe"] - result["fwd_pe"], 2)
        if result.get("pb") and result.get("fwd_pb"):
            result["pb_delta"] = round(result["pb"] - result["fwd_pb"], 2)
        if result.get("ev_ebitda") and result.get("fwd_ev_ebitda"):
            result["ev_ebitda_delta"] = round(result["ev_ebitda"] - result["fwd_ev_ebitda"], 2)
    except Exception:
        pass
    
    return result


def calculate_forward_valuations(current_price, valuation, forecasts):
    """
    Calculate forward P/E, P/B, EV/EBITDA using forecasted financials.
    
    Forward P/B uses ROE to estimate how much equity will grow over the next year:
    Forward Equity = Current Equity × (1 + ROE)
    Forward P/B = Market Cap / Forward Equity
    
    Returns dict with forward_pe, forward_pb, forward_ev_ebitda.
    """
    result = {}
    UNIT = 1000
    
    market_cap = valuation.get("market_cap")
    ev = valuation.get("enterprise_value")
    
    if not market_cap:
        return result
    
    # Forward P/E
    np_forecasts = forecasts.get("net_profit")
    if np_forecasts:
        ttm_forecast_np = _cumulate_forecasts(np_forecasts)
        if ttm_forecast_np and ttm_forecast_np != 0:
            forward_pe = market_cap / (ttm_forecast_np * UNIT)
            if 0.5 < forward_pe < 500:
                result["forward_pe"] = round(forward_pe, 2)
                result["forecast_net_profit"] = ttm_forecast_np
    
    # Forward EV/EBITDA
    ebitda_forecasts = forecasts.get("ebitda")
    if ebitda_forecasts and ev:
        ttm_forecast_ebitda = _cumulate_forecasts(ebitda_forecasts)
        if ttm_forecast_ebitda and ttm_forecast_ebitda != 0:
            forward_ev_ebitda = ev / (ttm_forecast_ebitda * UNIT)
            if 0.5 < forward_ev_ebitda < 200:
                result["forward_ev_ebitda"] = round(forward_ev_ebitda, 2)
                result["forecast_ebitda"] = ttm_forecast_ebitda
    
    # Forward P/B = Market Cap / (Current Equity × (1 + ROE))
    # ROE-adjusted: equity grows by retained earnings at the ROE rate
    roe = valuation.get("roe")
    total_equity = valuation.get("total_equity")  # in thousands TL
    
    if total_equity and total_equity > 0 and roe is not None:
        # Project equity forward 1 year with ROE
        forward_equity_thousands = total_equity * (1 + roe)
        forward_equity_tl = forward_equity_thousands * UNIT
        if forward_equity_tl > 0:
            forward_pb = market_cap / forward_equity_tl
            result["forward_pb"] = round(forward_pb, 2)
            result["roe_used"] = round(roe * 100, 1)  # For display
    
    # Fallback: if ROE not available, use current P/B
    if "forward_pb" not in result:
        pb = valuation.get("pb_ratio")
        if pb is not None:
            result["forward_pb"] = pb
    
    return result


def display_balance_sheet(symbol, current_price=None):
    """Display balance sheet section for a stock in the Streamlit dashboard."""
    
    st.markdown("---")
    st.subheader(f"📑 Financials — {symbol}")
    st.caption("Source: İş Yatırım | Quarterly data, last 5 years")
    
    # ── Data source: prefer imported store, fallback to live API ──
    is_from_store = symbol in st.session_state.financial_store
    raw_data = None
    fetch_error = None
    
    if is_from_store:
        raw_data = st.session_state.financial_store[symbol]
        import_time = st.session_state.financial_import_time or "Unknown"
        st.caption(f"📦 Using imported data (last import: {import_time})")
    else:
        # No imported data for this stock — try live API
        try:
            with st.spinner(f"Fetching {symbol} from İş Yatırım API (not in imported data)..."):
                raw_data = fetch_balance_sheet(symbol)
        except Exception as e:
            fetch_error = str(e)
    
    if not raw_data:
        st.warning(f"⚠️ No financial data available for **{symbol}**")
        if fetch_error:
            st.caption(f"API error: {fetch_error}")
        
        if not st.session_state.financial_store:
            st.markdown("""
            **💡 Tip:** Use the **📥 Import Financials** button in the sidebar to bulk-download  
            all financial data once. After importing, financials load instantly from local storage  
            and work even when İş Yatırım is down.
            """)
        else:
            st.caption(f"ℹ️ {len(st.session_state.financial_store)} stocks are imported. This stock was not found — it may lack financial filings.")
        
        if st.button(f"🔄 Try fetching {symbol} from API", key=f"retry_fin_{symbol}"):
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
        
        # ── Generate Forecasts ──
        forecasts = forecast_financials(df_full)
        
        has_forecasts = bool(forecasts)
        if has_forecasts:
            st.caption("🔮 Gold bars = AI forecast (4 quarters ahead, cumulative within year) using seasonal + momentum + mean-reversion ensemble")
        
        # Convert standalone forecasts to cumulative for chart display
        fc_rev_cum = _standalone_to_cumulative(forecasts.get("revenue", {}))
        fc_gp_cum = _standalone_to_cumulative(forecasts.get("gross_profit", {}))
        fc_ebitda_cum = _standalone_to_cumulative(forecasts.get("ebitda", {}))
        fc_np_cum = _standalone_to_cumulative(forecasts.get("net_profit", {}))
        
        # 2x2 grid of bar charts
        ch_c1, ch_c2 = st.columns(2)
        
        with ch_c1:
            fig_rev = _make_quarterly_bar_chart(df_full, "revenue", "📈 Revenue (Hasılat)", "#17a2b8", forecasts=fc_rev_cum)
            if fig_rev:
                st.plotly_chart(fig_rev, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Revenue data not available")
        
        with ch_c2:
            fig_gp = _make_quarterly_bar_chart(df_full, "gross_profit", "📈 Gross Profit (Brüt Kar)", "#28a745", forecasts=fc_gp_cum)
            if fig_gp:
                st.plotly_chart(fig_gp, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Gross Profit data not available")
        
        ch_c3, ch_c4 = st.columns(2)
        
        with ch_c3:
            fig_ebitda = _make_quarterly_bar_chart(df_full, "ebitda", "📈 EBITDA", "#fd7e14", forecasts=fc_ebitda_cum)
            if fig_ebitda is None:
                fig_ebitda = _make_quarterly_bar_chart(df_full, "operating_profit", "📈 Operating Profit (EBIT)", "#fd7e14", forecasts=fc_ebitda_cum)
            if fig_ebitda:
                st.plotly_chart(fig_ebitda, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("EBITDA data not available")
        
        with ch_c4:
            fig_np = _make_quarterly_bar_chart(df_full, "net_profit_parent", "📈 Net Profit (Net Kar)", "#6f42c1", fallback_key="net_profit", forecasts=fc_np_cum)
            if fig_np:
                st.plotly_chart(fig_np, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Net Profit data not available")
        
        # ═══════════════════════════════════════════════════════════════════
        # FORWARD VALUATION BANNERS — Based on Forecasted Financials
        # ═══════════════════════════════════════════════════════════════════
        if has_forecasts and current_price and current_price > 0:
            valuation = calculate_valuation_metrics(df_full, current_price)
            if valuation:
                fwd = calculate_forward_valuations(current_price, valuation, forecasts)
                
                if fwd:
                    st.markdown("### 🔮 Forward Valuation (Forecast-Based)")
                    st.caption("Based on AI-forecasted next 4 quarters financials at current price")
                    
                    fvc1, fvc2, fvc3 = st.columns(3)
                    
                    # Forward P/E
                    with fvc1:
                        fwd_pe = fwd.get("forward_pe")
                        cur_pe = valuation.get("pe_ratio")
                        if fwd_pe is not None:
                            pe_color = "#28a745" if fwd_pe < 15 else ("#ffc107" if fwd_pe < 25 else "#dc3545")
                            pe_label = "Cheap" if fwd_pe < 10 else ("Fair" if fwd_pe < 20 else ("Expensive" if fwd_pe < 35 else "Very High"))
                            delta_str = ""
                            if cur_pe and cur_pe > 0:
                                change = ((fwd_pe - cur_pe) / cur_pe) * 100
                                arrow = "↓" if change < 0 else "↑"
                                delta_str = f"<br><span style='font-size:0.75rem;'>{arrow} {abs(change):.0f}% vs current {cur_pe:.1f}x</span>"
                            st.markdown(f"""
                            <div class="mobile-score-card" style="border-top: 3px solid gold; background: rgba(255,215,0,0.05);">
                                <p class="score-label">🔮 Forward P/E</p>
                                <p class="score-value" style="color:{pe_color}">{fwd_pe:.1f}x</p>
                                <p class="score-max">{pe_label}{delta_str}</p>
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.metric("🔮 Fwd P/E", "N/A")
                    
                    # Forward P/B (ROE-adjusted)
                    with fvc2:
                        fwd_pb = fwd.get("forward_pb")
                        cur_pb = valuation.get("pb_ratio")
                        roe_pct = fwd.get("roe_used")
                        if fwd_pb is not None:
                            pb_color = "#28a745" if fwd_pb < 1.5 else ("#ffc107" if fwd_pb < 3 else "#dc3545")
                            pb_label = "Below Book" if fwd_pb < 1 else ("Fair" if fwd_pb < 2 else ("Premium" if fwd_pb < 4 else "Very High"))
                            delta_str = ""
                            if cur_pb and cur_pb > 0:
                                change = ((fwd_pb - cur_pb) / cur_pb) * 100
                                arrow = "↓" if change < 0 else "↑"
                                delta_str = f"<br><span style='font-size:0.75rem;'>{arrow} {abs(change):.0f}% vs current {cur_pb:.2f}x</span>"
                            roe_note = f"<br><span style='font-size:0.7rem; color:#888;'>ROE: {roe_pct:.1f}%</span>" if roe_pct else ""
                            st.markdown(f"""
                            <div class="mobile-score-card" style="border-top: 3px solid gold; background: rgba(255,215,0,0.05);">
                                <p class="score-label">🔮 Forward PD/DD</p>
                                <p class="score-value" style="color:{pb_color}">{fwd_pb:.2f}x</p>
                                <p class="score-max">{pb_label}{delta_str}{roe_note}</p>
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.metric("🔮 Fwd PD/DD", "N/A")
                    
                    # Forward EV/EBITDA
                    with fvc3:
                        fwd_ev = fwd.get("forward_ev_ebitda")
                        cur_ev = valuation.get("ev_ebitda")
                        if fwd_ev is not None:
                            ev_color = "#28a745" if fwd_ev < 8 else ("#ffc107" if fwd_ev < 15 else "#dc3545")
                            ev_label = "Cheap" if fwd_ev < 6 else ("Fair" if fwd_ev < 12 else ("Expensive" if fwd_ev < 20 else "Very High"))
                            delta_str = ""
                            if cur_ev and cur_ev > 0:
                                change = ((fwd_ev - cur_ev) / cur_ev) * 100
                                arrow = "↓" if change < 0 else "↑"
                                delta_str = f"<br><span style='font-size:0.75rem;'>{arrow} {abs(change):.0f}% vs current {cur_ev:.1f}x</span>"
                            st.markdown(f"""
                            <div class="mobile-score-card" style="border-top: 3px solid gold; background: rgba(255,215,0,0.05);">
                                <p class="score-label">🔮 Forward EV/EBITDA</p>
                                <p class="score-value" style="color:{ev_color}">{fwd_ev:.1f}x</p>
                                <p class="score-max">{ev_label}{delta_str}</p>
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.metric("🔮 Fwd EV/EBITDA", "N/A")
                    
                    # Forecast detail table
                    with st.expander("📋 Forecast Details"):
                        fc_table_rows = []
                        for metric_name, fc_key, display_name in [
                            ("Revenue", "revenue", "Hasılat"),
                            ("Gross Profit", "gross_profit", "Brüt Kar"),
                            ("EBITDA", "ebitda", "FAVÖK"),
                            ("Net Profit", "net_profit", "Net Kar"),
                        ]:
                            fc_data = forecasts.get(fc_key, {})
                            if fc_data:
                                for period, val in fc_data.items():
                                    fc_table_rows.append({
                                        "Metric": f"{metric_name} ({display_name})",
                                        "Period": period.replace(" F", ""),
                                        "Forecast (Bin TL)": f"{val:,.0f}",
                                        "Forecast (M TL)": f"₺{val/1000:,.1f}M",
                                    })
                        if fc_table_rows:
                            st.dataframe(pd.DataFrame(fc_table_rows), use_container_width=True, hide_index=True)
                        
                        st.caption("""
                        **Methodology:**
                        - **Quarterly Forecasts:** Ensemble of Seasonal (50%), Momentum (30%), and Mean Reversion (20%)
                        - **Forward P/E:** Market Cap ÷ Forecasted TTM Net Profit
                        - **Forward PD/DD:** Market Cap ÷ (Current Equity × (1 + ROE)). ROE used to project equity growth from retained earnings.
                        - **Forward EV/EBITDA:** Enterprise Value ÷ Forecasted TTM EBITDA
                        
                        Standalone quarters are de-cumulated from İş Yatırım's cumulative reporting.
                        Forecasts are indicative only and do not constitute investment advice.
                        """)
    
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


# =============================================================================
# MACRO ANALYSIS — Global M2, BTC, Gold, Silver, Country Indicators
# =============================================================================

# Yahoo Finance tickers for assets
MACRO_ASSETS = {
    "BTC": {"ticker": "BTC-USD", "label": "Bitcoin (BTC)", "color": "#f7931a"},
    "Gold": {"ticker": "GC=F", "label": "Gold (XAU)", "color": "#ffd700"},
    "Silver": {"ticker": "SI=F", "label": "Silver (XAG)", "color": "#c0c0c0"},
}

# TradingView ECONOMICS exchange symbols for country indicators
# These are available without authentication via tvDatafeed
COUNTRY_MACRO_CONFIG = {
    "\U0001f1fa\U0001f1f8 US": {
        "m2":                {"symbol": "USM2",     "exchange": "ECONOMICS", "label": "US M2 Money Supply",    "unit": "Trillion $"},
        "employment":        {"symbol": "USUR",     "exchange": "ECONOMICS", "label": "US Unemployment Rate",  "unit": "%"},
        "consumer_spending": {"symbol": "USCCI",    "exchange": "ECONOMICS", "label": "US Consumer Confidence","unit": "Index"},
        "pce_index":         {"symbol": "USIRYY",   "exchange": "ECONOMICS", "label": "US Inflation Rate YoY", "unit": "%"},
        "inflation":         {"symbol": "USCIR",    "exchange": "ECONOMICS", "label": "US Core Inflation",     "unit": "%"},
        "pmi":               {"symbol": "USMPMI",   "exchange": "ECONOMICS", "label": "US Manufacturing PMI",  "unit": "Index"},
    },
    "\U0001f1e9\U0001f1ea Germany": {
        "m2":                {"symbol": "EUM2",     "exchange": "ECONOMICS", "label": "Euro Area M2",          "unit": "Trillion \u20ac"},
        "employment":        {"symbol": "DEUR",     "exchange": "ECONOMICS", "label": "Germany Unemployment",  "unit": "%"},
        "consumer_spending": {"symbol": "DECCI",    "exchange": "ECONOMICS", "label": "Germany Consumer Conf.","unit": "Index"},
        "pce_index":         {"symbol": "DEIRYY",   "exchange": "ECONOMICS", "label": "Germany Inflation YoY", "unit": "%"},
        "inflation":         {"symbol": "DECIR",    "exchange": "ECONOMICS", "label": "Germany Core Inflation","unit": "%"},
        "pmi":               {"symbol": "DEMPMI",   "exchange": "ECONOMICS", "label": "Germany Manuf. PMI",   "unit": "Index"},
    },
    "\U0001f1ef\U0001f1f5 Japan": {
        "m2":                {"symbol": "JPM2",     "exchange": "ECONOMICS", "label": "Japan M2 Money Supply", "unit": "Trillion \u00a5"},
        "employment":        {"symbol": "JPUR",     "exchange": "ECONOMICS", "label": "Japan Unemployment",    "unit": "%"},
        "consumer_spending": {"symbol": "JPCCI",    "exchange": "ECONOMICS", "label": "Japan Consumer Conf.",  "unit": "Index"},
        "pce_index":         {"symbol": "JPIRYY",   "exchange": "ECONOMICS", "label": "Japan Inflation YoY",   "unit": "%"},
        "inflation":         {"symbol": "JPCIR",    "exchange": "ECONOMICS", "label": "Japan Core Inflation",  "unit": "%"},
        "pmi":               {"symbol": "JPMPMI",   "exchange": "ECONOMICS", "label": "Japan Manuf. PMI",     "unit": "Index"},
    },
    "\U0001f1e8\U0001f1f3 China": {
        "m2":                {"symbol": "CNM2",     "exchange": "ECONOMICS", "label": "China M2 Money Supply", "unit": "Trillion \u00a5"},
        "employment":        {"symbol": "CNUR",     "exchange": "ECONOMICS", "label": "China Unemployment",    "unit": "%"},
        "consumer_spending": {"symbol": "CNCCI",    "exchange": "ECONOMICS", "label": "China Consumer Conf.",  "unit": "Index"},
        "pce_index":         {"symbol": "CNIRYY",   "exchange": "ECONOMICS", "label": "China Inflation YoY",   "unit": "%"},
        "inflation":         {"symbol": "CNCIR",    "exchange": "ECONOMICS", "label": "China Core Inflation",  "unit": "%"},
        "pmi":               {"symbol": "CNMPMI",   "exchange": "ECONOMICS", "label": "China Manuf. PMI",     "unit": "Index"},
    },
    "\U0001f1ee\U0001f1f3 India": {
        "m2":                {"symbol": "INM2",     "exchange": "ECONOMICS", "label": "India M2 Money Supply", "unit": "Trillion \u20b9"},
        "employment":        {"symbol": "INUR",     "exchange": "ECONOMICS", "label": "India Unemployment",    "unit": "%"},
        "consumer_spending": {"symbol": "INCCI",    "exchange": "ECONOMICS", "label": "India Consumer Conf.",  "unit": "Index"},
        "pce_index":         {"symbol": "INIRYY",   "exchange": "ECONOMICS", "label": "India Inflation YoY",   "unit": "%"},
        "inflation":         {"symbol": "INCIR",    "exchange": "ECONOMICS", "label": "India Core Inflation",  "unit": "%"},
        "pmi":               {"symbol": "INMPMI",   "exchange": "ECONOMICS", "label": "India Manuf. PMI",     "unit": "Index"},
    },
    "\U0001f1f9\U0001f1f7 Turkey": {
        "m2":                {"symbol": "TRM3",     "exchange": "ECONOMICS", "label": "Turkey M3 Money Supply","unit": "Billion \u20ba"},
        "employment":        {"symbol": "TRUR",     "exchange": "ECONOMICS", "label": "Turkey Unemployment",   "unit": "%"},
        "consumer_spending": {"symbol": "TRCCI",    "exchange": "ECONOMICS", "label": "Turkey Consumer Conf.", "unit": "Index"},
        "pce_index":         {"symbol": "TRIRYY",   "exchange": "ECONOMICS", "label": "Turkey Inflation YoY",  "unit": "%"},
        "inflation":         {"symbol": "TRCIR",    "exchange": "ECONOMICS", "label": "Turkey Core Inflation", "unit": "%"},
        "pmi":               {"symbol": "TRMPMI",   "exchange": "ECONOMICS", "label": "Turkey Manuf. PMI",    "unit": "Index"},
    },
}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_yahoo_chart(ticker, period="10y", interval="1wk"):
    """
    Fetch price data from Yahoo Finance chart API.
    Works for BTC-USD, GC=F, SI=F, indices, etc.
    Returns DataFrame with date index and 'value' column.
    """
    try:
        end_ts = int(datetime.now().timestamp())
        # Calculate start based on period
        years = int(period.replace("y", "")) if "y" in period else 5
        start_ts = int((datetime.now() - timedelta(days=365 * years)).timestamp())
        
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        params = {
            "period1": start_ts,
            "period2": end_ts,
            "interval": interval,
        }
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if result:
                timestamps = result[0].get("timestamp", [])
                closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                if timestamps and closes:
                    dates = [datetime.fromtimestamp(t) for t in timestamps]
                    df = pd.DataFrame({"date": dates, "value": closes}).dropna()
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date")
                    return df
    except Exception:
        pass
    return None


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_tv_macro(symbol, exchange, n_bars=260):
    """
    Fetch macro/economic data from TradingView via tvDatafeed.
    Returns DataFrame with date index and 'value' column.
    Falls back gracefully if tvDatafeed unavailable.
    """
    try:
        from tvDatafeed import TvDatafeed, Interval
        tv = TvDatafeed()
        df = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_monthly, n_bars=n_bars)
        if df is not None and not df.empty:
            df = df[["close"]].rename(columns={"close": "value"})
            df.index = pd.to_datetime(df.index)
            return df
    except Exception:
        pass
    return None


def build_global_m2_index():
    """
    Build a normalized Global M2 index. 
    Try tvDatafeed ECONOMICS first, then Yahoo Finance M2 ETF proxy.
    Returns weekly-resampled DataFrame with 'global_m2' column.
    """
    # Method 1: TradingView ECONOMICS exchange
    m2 = fetch_tv_macro("USM2", "ECONOMICS", n_bars=520)
    
    # Method 2: Fallback to Yahoo - use US Treasury/M2 proxy or Fed balance sheet proxy
    if m2 is None or m2.empty:
        # WM2NS is the FRED ticker on TradingView
        m2 = fetch_tv_macro("WM2NS", "FRED", n_bars=520)
    
    # Method 3: Use a broad liquidity proxy from Yahoo Finance
    if m2 is None or m2.empty:
        m2 = fetch_yahoo_chart("^GSPC", period="10y", interval="1wk")  # S&P 500 as last resort
        if m2 is not None:
            st.caption("⚠️ Using S&P 500 as M2 proxy (TradingView ECONOMICS data unavailable)")
    
    if m2 is None or m2.empty:
        return None
    
    base = m2["value"].iloc[0]
    if not base or base == 0:
        return None
    m2["global_m2"] = (m2["value"] / base) * 100
    return m2[["global_m2"]].resample("W").last().ffill()


def create_m2_vs_asset_chart(m2_df, asset_df, asset_name, asset_color, lag_weeks=0):
    """Create a dual-axis chart: Global M2 vs an asset with optional lag."""
    if m2_df is None or asset_df is None:
        return None
    fig = go.Figure()
    m2_plot = m2_df.copy()
    if lag_weeks > 0:
        m2_plot.index = m2_plot.index - pd.Timedelta(weeks=lag_weeks)
    asset_norm = asset_df.copy()
    base = asset_norm["value"].iloc[0]
    if not base or base == 0:
        return None
    asset_norm["normalized"] = (asset_norm["value"] / base) * 100
    common_start = max(m2_plot.index.min(), asset_norm.index.min())
    common_end = min(m2_plot.index.max(), asset_norm.index.max())
    m2_plot = m2_plot[common_start:common_end]
    asset_norm = asset_norm[common_start:common_end]
    if m2_plot.empty or asset_norm.empty:
        return None
    fig.add_trace(go.Scatter(
        x=m2_plot.index, y=m2_plot["global_m2"],
        mode='lines', name=f"Global M2{f' (shifted {lag_weeks}w)' if lag_weeks else ''}",
        line=dict(color='#00bfff', width=2), yaxis='y'
    ))
    fig.add_trace(go.Scatter(
        x=asset_norm.index, y=asset_norm["normalized"],
        mode='lines', name=asset_name,
        line=dict(color=asset_color, width=2), yaxis='y2'
    ))
    lag_text = f" (M2 leads by {lag_weeks} weeks)" if lag_weeks else ""
    fig.update_layout(
        title=f"Global M2 vs {asset_name}{lag_text}",
        height=350, margin=dict(l=60, r=60, t=40, b=60),
        yaxis=dict(title="Global M2 (Indexed)", side="left", showgrid=False),
        yaxis2=dict(title=asset_name, side="right", overlaying="y", showgrid=False),
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5, font=dict(size=10)),
        hovermode="x unified",
    )
    return fig


def create_country_indicator_chart(df, label, unit, color="#17a2b8"):
    """Create a simple time series chart for a country indicator."""
    if df is None or df.empty:
        return None
    try:
        r = int(color.lstrip("#")[0:2], 16)
        g = int(color.lstrip("#")[2:4], 16)
        b = int(color.lstrip("#")[4:6], 16)
        fill_color = f"rgba({r},{g},{b},0.1)"
    except Exception:
        fill_color = "rgba(23,162,184,0.1)"
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index, y=df["value"], mode='lines', name=label,
        line=dict(color=color, width=2), fill='tozeroy', fillcolor=fill_color
    ))
    fig.update_layout(
        title=label, height=280, margin=dict(l=40, r=20, t=40, b=60),
        yaxis_title=unit, xaxis_title="",
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=10)),
    )
    return fig


def display_macro_analysis():
    """Display the full macro analysis dashboard."""
    st.markdown("### \U0001f30d Macro Analysis Dashboard")
    st.caption("Global liquidity flows, money supply, and key economic indicators")
    
    # =====================================================================
    # TOP: Global M2 vs BTC, Gold, Silver
    # =====================================================================
    with st.spinner("Loading global M2 and asset data..."):
        m2_df = build_global_m2_index()
        btc_df = fetch_yahoo_chart("BTC-USD", period="10y", interval="1wk")
        gold_df = fetch_yahoo_chart("GC=F", period="10y", interval="1wk")
        silver_df = fetch_yahoo_chart("SI=F", period="10y", interval="1wk")
    
    if m2_df is not None:
        st.markdown("#### \U0001f4b0 Global M2 Money Supply vs Assets")
        st.caption("M2 expansion historically leads risk asset prices. Bitcoin shown with 10-week lag.")
        
        fig_btc = create_m2_vs_asset_chart(m2_df, btc_df, "Bitcoin (BTC)", "#f7931a", lag_weeks=10)
        if fig_btc:
            st.plotly_chart(fig_btc, use_container_width=True, config=PLOTLY_CONFIG)
        else:
            st.warning("Could not load BTC data")
        
        gc1, gc2 = st.columns(2)
        with gc1:
            fig_gold = create_m2_vs_asset_chart(m2_df, gold_df, "Gold (XAU)", "#ffd700")
            if fig_gold:
                st.plotly_chart(fig_gold, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.warning("Could not load Gold data")
        with gc2:
            fig_silver = create_m2_vs_asset_chart(m2_df, silver_df, "Silver (XAG)", "#c0c0c0")
            if fig_silver:
                st.plotly_chart(fig_silver, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.warning("Could not load Silver data")
    else:
        st.warning("\u26a0\ufe0f Could not fetch Global M2 data. Install tvDatafeed: `pip install tvDatafeed`")
    
    # =====================================================================
    # BOTTOM: Country-specific Economic Indicators
    # =====================================================================
    st.markdown("---")
    st.markdown("### \U0001f3db\ufe0f Country Economic Indicators")
    
    country = st.selectbox("Select Country", list(COUNTRY_MACRO_CONFIG.keys()), index=0, key="macro_country")
    config = COUNTRY_MACRO_CONFIG[country]
    
    indicator_colors = {
        "m2": "#00bfff", "employment": "#28a745", "consumer_spending": "#fd7e14",
        "pce_index": "#dc3545", "inflation": "#ff6b6b", "pmi": "#6f42c1",
    }
    
    # Check if tvDatafeed is available
    tv_available = False
    try:
        from tvDatafeed import TvDatafeed
        tv_available = True
    except ImportError:
        pass
    
    if not tv_available:
        st.warning("\u26a0\ufe0f `tvDatafeed` library needed for economic indicators. Install with: `pip install tvDatafeed`")
        st.info("Asset charts above use Yahoo Finance (no extra library needed).")
        return
    
    with st.spinner(f"Loading {country} indicators..."):
        indicator_data = {}
        for key, cfg in config.items():
            indicator_data[key] = fetch_tv_macro(cfg["symbol"], cfg["exchange"], n_bars=260)
    
    keys = ["m2", "employment", "consumer_spending", "pce_index", "inflation", "pmi"]
    loaded = sum(1 for k in keys if indicator_data.get(k) is not None and not indicator_data[k].empty)
    if loaded == 0:
        st.warning(f"Could not load indicators for {country}. TradingView ECONOMICS symbols may require authentication.")
        st.info("Try running with TradingView credentials: set TV_USER and TV_PASS environment variables.")
    
    for row_idx in range(0, len(keys), 2):
        col1, col2 = st.columns(2)
        for ci, col in enumerate([col1, col2]):
            k_idx = row_idx + ci
            if k_idx >= len(keys):
                break
            key = keys[k_idx]
            cfg = config[key]
            df = indicator_data.get(key)
            with col:
                if df is not None and not df.empty:
                    fig = create_country_indicator_chart(df, cfg["label"], cfg["unit"], indicator_colors.get(key, "#17a2b8"))
                    if fig:
                        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
                        latest_val = df["value"].iloc[-1]
                        latest_date = df.index[-1].strftime("%Y-%m")
                        st.caption(f"Latest: {latest_val:,.2f} ({latest_date})")
                else:
                    st.info(f"{cfg['label']}: Data not available")
    
    st.caption("Source: TradingView ECONOMICS exchange via tvDatafeed | Asset prices: Yahoo Finance")


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
            mode = st.radio("Mode", ["🌍 Macro Analysis", "📊 Single Stock", "🔍 Stock Screener", "📋 Market Summary", "💎 Value Finder"])
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
            
            if mode == "💎 Value Finder":
                st.markdown("---")
                st.subheader("💎 Value Finder")
                vf_index = st.selectbox(
                    "Scan scope",
                    ["🏦 BIST 30", "📊 BIST 100", "📈 All Stocks"],
                    key="vf_index"
                )
                if "BIST 30" in vf_index:
                    vf_stocks = sorted([s for s in BIST_30 if s in IMKB])
                elif "BIST 100" in vf_index:
                    vf_stocks = sorted([s for s in BIST_100 if s in IMKB])
                else:
                    vf_stocks = IMKB
                st.caption(f"{len(vf_stocks)} stocks to scan")
                
                if not st.session_state.financial_store:
                    st.warning("⚠️ Import financials first for best results!")
                
                if st.button("💎 Scan for Value", use_container_width=True, type="primary"):
                    vf_results = []
                    prog = st.progress(0)
                    stat = st.empty()
                    days = TIMEFRAMES[selected_tf]["days"]
                    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                    
                    for i, s in enumerate(vf_stocks):
                        stat.text(f"Analyzing {s}... ({i+1}/{len(vf_stocks)})")
                        prog.progress((i + 1) / len(vf_stocks))
                        try:
                            df = fetch_stock_data(s, start_date=start_date, interval=selected_tf)
                            if df is None or df.empty:
                                continue
                            price = df['Close'].iloc[-1]
                            vals = compute_stock_valuations(s, price)
                            if vals:
                                vals['symbol'] = s
                                vals['price'] = round(price, 2)
                                vf_results.append(vals)
                        except:
                            continue
                    
                    prog.empty()
                    stat.empty()
                    st.session_state.value_finder_results = vf_results
                    st.success(f"✅ Analyzed {len(vf_results)} stocks!")
                    st.rerun()
            
            if st.button("🔄 Refresh", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
            
            # ── Financial Data Import Section ──
            st.markdown("---")
            st.subheader("📥 Financial Data")
            
            store_count = len(st.session_state.financial_store)
            if store_count > 0:
                import_time = st.session_state.financial_import_time or "Unknown"
                err_count = len(st.session_state.financial_import_errors)
                st.success(f"✅ {store_count} stocks imported")
                st.caption(f"Last import: {import_time}")
                if err_count > 0:
                    with st.expander(f"⚠️ {err_count} failed"):
                        st.write(", ".join(st.session_state.financial_import_errors))
            else:
                st.info("No financials imported yet")
                st.caption("Import once, use offline — data updates quarterly")
            
            # Import scope selection
            import_scope = st.selectbox(
                "Import scope",
                ["🏦 BIST 30 (~1 min)", "📊 BIST 100 (~3 min)", "📈 All Stocks (~15 min)"],
                key="import_scope"
            )
            
            if st.button("📥 Import Financials", use_container_width=True, type="primary"):
                if "BIST 30" in import_scope:
                    target_list = BIST_30
                elif "BIST 100" in import_scope:
                    target_list = BIST_100
                else:
                    target_list = IMKB
                
                success, errors = import_all_financials(target_list, sleep_between=1.0)
                _save_financial_store()
                st.success(f"✅ Imported {success}/{len(target_list)} stocks!")
                if errors:
                    st.warning(f"⚠️ {len(errors)} stocks failed: {', '.join(errors[:10])}{'...' if len(errors) > 10 else ''}")
                st.rerun()
            
            if store_count > 0:
                if st.button("🗑️ Clear Imported Data", use_container_width=True):
                    st.session_state.financial_store = {}
                    st.session_state.financial_import_time = None
                    st.session_state.financial_import_errors = []
                    if os.path.exists(FINANCIAL_STORE_FILE):
                        os.remove(FINANCIAL_STORE_FILE)
                    st.rerun()
        
        if mode == "🌍 Macro Analysis":
            display_macro_analysis()
        
        elif mode == "📊 Single Stock":
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
                
                # Display summary metrics
                sc1, sc2, sc3 = st.columns(3)
                with sc1:
                    st.metric("Chosen Stocks", len(df_c))
                with sc2:
                    avg_ind = df_c['indicator_score_2'].mean()
                    st.metric("Avg Indicator", f"{avg_ind:.1f}")
                with sc3:
                    has_pe = df_c['P/E'].notna().sum()
                    st.metric("With Financials", f"{has_pe}/{len(df_c)}")
                
                # Format display columns
                display_cols = ['symbol', 'price', 'chg%', 'RSI', 'indicator_score_2', 'volume_score_2',
                               'P/E', 'PD/DD', 'EV/EBITDA', 'Fwd P/E', 'Fwd PD/DD', 'Fwd EV/EBITDA', 'P/E Δ', 'EV/EBITDA Δ']
                available_display = [c for c in display_cols if c in df_c.columns]
                
                st.dataframe(
                    df_c[available_display].style.format({
                        'price': '₺{:.2f}',
                        'chg%': '{:+.2f}%',
                        'RSI': '{:.1f}',
                        'indicator_score_2': '{:.1f}',
                        'volume_score_2': '{:.2f}',
                        'P/E': '{:.1f}x',
                        'PD/DD': '{:.2f}x',
                        'EV/EBITDA': '{:.1f}x',
                        'Fwd P/E': '{:.1f}x',
                        'Fwd PD/DD': '{:.2f}x',
                        'Fwd EV/EBITDA': '{:.1f}x',
                        'P/E Δ': '{:+.1f}',
                        'EV/EBITDA Δ': '{:+.1f}',
                    }, na_rep='—', subset=available_display[1:]),
                    use_container_width=True, hide_index=True, height=min(400, 35 * len(df_c) + 38)
                )
                
                # Cards view
                st.markdown("---")
                cols = st.columns(min(3, max(1, len(df_c))))
                for idx, s in enumerate(df_c.to_dict('records')):
                    with cols[idx % len(cols)]:
                        pe_str = f"{s['P/E']:.1f}x" if s.get('P/E') else "—"
                        pb_str = f"{s['PD/DD']:.2f}x" if s.get('PD/DD') else "—"
                        ev_str = f"{s['EV/EBITDA']:.1f}x" if s.get('EV/EBITDA') else "—"
                        fpe_str = f"{s['Fwd P/E']:.1f}x" if s.get('Fwd P/E') else "—"
                        fev_str = f"{s['Fwd EV/EBITDA']:.1f}x" if s.get('Fwd EV/EBITDA') else "—"
                        st.markdown(f"""
                        <div class="chosen-stock">
                            <h4>{s['symbol']} — ₺{s['price']:.2f}</h4>
                            <p><b>Ind:</b> {s['indicator_score_2']} | <b>Vol:</b> {s['volume_score_2']}</p>
                            <p><b>P/E:</b> {pe_str} → {fpe_str} | <b>PD/DD:</b> {pb_str}</p>
                            <p><b>EV/EBITDA:</b> {ev_str} → {fev_str}</p>
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
        
        elif mode == "💎 Value Finder":
            st.subheader("💎 Value Finder — Discover Undervalued Stocks")
            st.caption("Compares current valuation multiples with AI-forecasted forward multiples to find stocks that are expected to become cheaper based on earnings growth.")
            
            vf_data = st.session_state.value_finder_results
            if vf_data:
                df_vf = pd.DataFrame(vf_data)
                
                # Rename for display
                col_map = {
                    'symbol': 'Symbol', 'price': 'Price',
                    'pe': 'P/E', 'pb': 'PD/DD', 'ev_ebitda': 'EV/EBITDA',
                    'fwd_pe': 'Fwd P/E', 'fwd_pb': 'Fwd PD/DD', 'fwd_ev_ebitda': 'Fwd EV/EBITDA',
                    'pe_delta': 'P/E Δ', 'pb_delta': 'PD/DD Δ', 'ev_ebitda_delta': 'EV/EBITDA Δ',
                }
                df_vf = df_vf.rename(columns=col_map)
                
                # Summary
                total = len(df_vf)
                has_pe = df_vf['P/E'].notna().sum()
                has_fwd = df_vf['Fwd P/E'].notna().sum()
                sm1, sm2, sm3 = st.columns(3)
                with sm1:
                    st.metric("Stocks Analyzed", total)
                with sm2:
                    st.metric("With P/E Data", has_pe)
                with sm3:
                    st.metric("With Forward Data", has_fwd)
                
                # Sortable views with 6 criteria
                sort_options = {
                    "📉 Highest P/E Improvement (P/E − Fwd P/E)": ("P/E Δ", False),
                    "📉 Highest PD/DD Improvement (PD/DD − Fwd PD/DD)": ("PD/DD Δ", False),
                    "📉 Highest EV/EBITDA Improvement": ("EV/EBITDA Δ", False),
                    "🏷️ Lowest Forward P/E": ("Fwd P/E", True),
                    "🏷️ Lowest Forward PD/DD": ("Fwd PD/DD", True),
                    "🏷️ Lowest Forward EV/EBITDA": ("Fwd EV/EBITDA", True),
                }
                
                # Tabs for each sort criterion
                tab_names = list(sort_options.keys())
                vf_tabs = st.tabs(tab_names)
                
                display_cols = ['Symbol', 'Price', 'P/E', 'Fwd P/E', 'P/E Δ', 
                               'PD/DD', 'Fwd PD/DD', 'PD/DD Δ',
                               'EV/EBITDA', 'Fwd EV/EBITDA', 'EV/EBITDA Δ']
                available_cols = [c for c in display_cols if c in df_vf.columns]
                
                format_dict = {
                    'Price': '₺{:.2f}',
                    'P/E': '{:.1f}x', 'Fwd P/E': '{:.1f}x', 'P/E Δ': '{:+.1f}',
                    'PD/DD': '{:.2f}x', 'Fwd PD/DD': '{:.2f}x', 'PD/DD Δ': '{:+.2f}',
                    'EV/EBITDA': '{:.1f}x', 'Fwd EV/EBITDA': '{:.1f}x', 'EV/EBITDA Δ': '{:+.1f}',
                }
                
                for tab_idx, (tab_name, (sort_col, ascending)) in enumerate(sort_options.items()):
                    with vf_tabs[tab_idx]:
                        if sort_col not in df_vf.columns:
                            st.info(f"Column {sort_col} not available.")
                            continue
                        
                        # Filter to rows that have the sort column value
                        df_sorted = df_vf[df_vf[sort_col].notna()].copy()
                        
                        if not ascending:
                            # For "improvement" sorts, we want positive deltas (current > forward = getting cheaper)
                            df_sorted = df_sorted[df_sorted[sort_col] > 0]
                        
                        if df_sorted.empty:
                            st.info(f"No stocks with valid {sort_col} data.")
                            continue
                        
                        df_sorted = df_sorted.sort_values(sort_col, ascending=ascending).head(30)
                        
                        # Explanation
                        if "Improvement" in tab_name or "Δ" in sort_col:
                            st.caption(f"Showing stocks where {sort_col.replace(' Δ', '')} is expected to DECREASE (get cheaper). Δ = Current − Forward. Higher Δ = more improvement expected from earnings growth.")
                        else:
                            st.caption(f"Showing stocks with the lowest forecasted {sort_col}. Lower = potentially more undervalued on a forward basis.")
                        
                        # Highlight top 3
                        top3 = df_sorted.head(3)
                        tc1, tc2, tc3 = st.columns(3)
                        for ci, (_, row) in enumerate(top3.iterrows()):
                            with [tc1, tc2, tc3][ci]:
                                medal = ["🥇", "🥈", "🥉"][ci]
                                sym = row['Symbol']
                                sv = row.get(sort_col)
                                sv_str = f"{sv:+.1f}" if "Δ" in sort_col else f"{sv:.1f}x"
                                pe_str = f"{row['P/E']:.1f}x" if pd.notna(row.get('P/E')) else "—"
                                fpe_str = f"{row['Fwd P/E']:.1f}x" if pd.notna(row.get('Fwd P/E')) else "—"
                                st.markdown(f"""
                                <div class="mobile-score-card" style="border-top: 3px solid gold;">
                                    <p class="score-label">{medal} #{ci+1}</p>
                                    <p class="score-value">{sym}</p>
                                    <p class="score-max">₺{row['Price']:.2f} | {sort_col}: {sv_str}</p>
                                    <p style="font-size:0.8rem;">P/E: {pe_str} → {fpe_str}</p>
                                </div>
                                """, unsafe_allow_html=True)
                        
                        # Full table
                        fmt = {k: v for k, v in format_dict.items() if k in available_cols}
                        st.dataframe(
                            df_sorted[available_cols].style.format(fmt, na_rep='—', subset=[c for c in available_cols if c != 'Symbol']),
                            use_container_width=True, hide_index=True,
                            height=min(500, 35 * len(df_sorted) + 38)
                        )
            else:
                st.info("👆 Click **💎 Scan for Value** in the sidebar to analyze stocks.")
                st.markdown("""
                **How it works:**
                1. Select the stock universe (BIST 30, 100, or All)
                2. Make sure financial data is imported (📥 Import Financials)
                3. Click **Scan for Value** — this computes current and forward valuations for all stocks
                4. Results are sorted by 6 criteria across tabs:
                   - **P/E Improvement** — stocks where earnings growth is expected to compress P/E the most
                   - **PD/DD Improvement** — stocks with the biggest book value improvement  
                   - **EV/EBITDA Improvement** — stocks with the biggest EBITDA growth relative to enterprise value
                   - **Lowest Forward P/E/PD/DD/EV/EBITDA** — cheapest stocks on a forward basis
                """)
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        st.info("Please refresh the page and try again.")

if __name__ == "__main__":
    main()
