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

# Key balance sheet items to display (itemCode -> English label)
KEY_ITEMS = {
    # Assets
    "1A": ("Total Assets", "Toplam Varlıklar"),
    "1AK": ("Current Assets", "Dönen Varlıklar"),
    "1AD": ("Non-Current Assets", "Duran Varlıklar"),
    "1AKA": ("Cash & Equivalents", "Nakit ve Nakit Benzerleri"),
    "1AKC": ("Trade Receivables (Short)", "Ticari Alacaklar (Kısa)"),
    "1AKD": ("Inventories", "Stoklar"),
    "1ADC": ("Property, Plant & Equipment", "Maddi Duran Varlıklar"),
    # Liabilities & Equity
    "2": ("Total Liabilities + Equity", "Toplam Kaynaklar"),
    "2K": ("Current Liabilities", "Kısa Vadeli Yükümlülükler"),
    "2D": ("Non-Current Liabilities", "Uzun Vadeli Yükümlülükler"),
    "2KA": ("Short-term Borrowings", "Kısa Vadeli Borçlanmalar"),
    "2DA": ("Long-term Borrowings", "Uzun Vadeli Borçlanmalar"),
    "2O": ("Total Equity", "Özkaynaklar"),
    "2OA": ("Paid-in Capital", "Ödenmiş Sermaye"),
}

# Income statement items (financial group XI_29 includes these)
KEY_INCOME_ITEMS = {
    "PIIA": ("Revenue / Sales", "Hasılat"),
    "PIIB": ("Cost of Sales", "Satışların Maliyeti"),
    "PII1": ("Gross Profit", "Brüt Kar"),
    "PIIIA": ("Depreciation & Amortization", "Amortisman Giderleri"),
    "PIV": ("Operating Profit / EBIT", "Esas Faaliyet Karı"),
    "PVA": ("Financial Income", "Finansal Gelirler"),
    "PVB": ("Financial Expenses", "Finansal Giderler"),
    "PVI": ("Profit Before Tax", "Vergi Öncesi Kar"),
    "PVII": ("Net Profit", "Net Dönem Karı"),
    "PVIII": ("Net Profit (Parent)", "Ana Ortaklık Net Karı"),
}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_balance_sheet(symbol, years=None):
    """
    Fetch quarterly balance sheet data from İş Yatırım API.
    Returns a dict of {year: raw_json_response} for each year.
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
        try:
            resp = requests.get(ISYATIRIM_API_URL, verify=False, params=params, timeout=15)
            if resp.status_code == 200:
                json_data = resp.json()
                if "value" in json_data and json_data["value"]:
                    all_data[y] = json_data["value"]
        except Exception:
            continue
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
    
    # Helper to get value by code for a period
    def get_val(code, period):
        match = df_full[df_full["Code"] == code]
        if match.empty or period not in match.columns:
            return None
        v = match[period].iloc[0]
        return float(v) if v is not None and pd.notna(v) else None
    
    periods = [c for c in df_full.columns if "/" in c]
    if not periods:
        return {}
    
    latest = periods[0]  # Most recent period
    
    # Get key values from latest period
    total_equity = get_val("2O", latest)
    paid_in_capital = get_val("2OA", latest)
    net_profit = get_val("PVIII", latest) or get_val("PVII", latest)
    operating_profit = get_val("PIV", latest)
    depreciation = get_val("PIIIA", latest)
    short_debt = get_val("2KA", latest)
    long_debt = get_val("2DA", latest)
    cash = get_val("1AKA", latest)
    
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
        ttm_net_profit = get_val("PVIII", annual_periods[0]) or get_val("PVII", annual_periods[0])
    
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


def parse_balance_sheet_to_df(raw_data, item_filter=None):
    """
    Parse raw İş Yatırım JSON into a clean DataFrame.
    Columns = periods (e.g. "2024/12", "2024/9", ...), Rows = line items.
    """
    if not raw_data:
        return None
    
    rows = []
    periods = []
    
    # Build period columns in chronological order
    sorted_years = sorted(raw_data.keys(), reverse=True)
    for y in sorted_years:
        for q in ["12", "9", "6", "3"]:
            periods.append(f"{y}/{q}")
    
    # Map period to value key
    period_value_map = {}
    for y in sorted_years:
        period_value_map[f"{y}/12"] = "value1"
        period_value_map[f"{y}/9"] = "value2"
        period_value_map[f"{y}/6"] = "value3"
        period_value_map[f"{y}/3"] = "value4"
    
    # Get all items from first available year
    first_year_data = raw_data[sorted_years[0]]
    
    for item in first_year_data:
        code = item.get("itemCode", "")
        
        # If filter provided, only include matching items
        if item_filter and code not in item_filter:
            continue
        
        row = {
            "Code": code,
            "Item (TR)": item.get("itemDescTr", ""),
            "Item (EN)": item_filter.get(code, ("", ""))[0] if item_filter and code in item_filter else "",
        }
        
        # Fill values from each year
        for y in sorted_years:
            year_data = raw_data.get(y, [])
            # Find this item in the year's data
            matching = [i for i in year_data if i.get("itemCode") == code]
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
    return df


def calculate_fundamentals(df_bs):
    """
    Calculate key financial ratios from the parsed balance sheet DataFrame.
    Returns a dict of ratio name -> list of (period, value) tuples.
    """
    if df_bs is None or df_bs.empty:
        return None
    
    # Helper to get a value by code for a given period
    def get_val(code, period):
        match = df_bs[df_bs["Code"] == code]
        if match.empty or period not in match.columns:
            return None
        v = match[period].iloc[0]
        return float(v) if v is not None and pd.notna(v) else None
    
    # Get available periods (exclude metadata columns)
    periods = [c for c in df_bs.columns if "/" in c]
    
    ratios = {}
    
    for p in periods:
        total_assets = get_val("1A", p)
        current_assets = get_val("1AK", p)
        current_liab = get_val("2K", p)
        total_equity = get_val("2O", p)
        total_liab_equity = get_val("2", p)
        short_debt = get_val("2KA", p)
        long_debt = get_val("2DA", p)
        net_profit = get_val("PVII", p) or get_val("PVIII", p)
        revenue = get_val("PIIA", p)
        gross_profit = get_val("PII1", p)
        operating_profit = get_val("PIV", p)
        
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


def _make_quarterly_bar_chart(df_source, item_code, title, color, fallback_code=None):
    """Helper: create a quarterly bar chart for a given income statement item."""
    row = df_source[df_source["Code"] == item_code]
    if row.empty and fallback_code:
        row = df_source[df_source["Code"] == fallback_code]
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
    
    with st.spinner(f"Fetching financial data for {symbol}..."):
        raw_data = fetch_balance_sheet(symbol)
    
    if not raw_data:
        st.warning(f"No financial data available for {symbol}. This may be a recently listed stock or the data may not be covered.")
        return
    
    # Parse key items
    all_key_items = {**KEY_ITEMS, **KEY_INCOME_ITEMS}
    df_key = parse_balance_sheet_to_df(raw_data, item_filter=all_key_items)
    
    # Parse full balance sheet (no filter)
    df_full = parse_balance_sheet_to_df(raw_data)
    
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
        
        # Build EBITDA row from PIV + |PIIIA|
        op_row = df_full[df_full["Code"] == "PIV"]
        da_row = df_full[df_full["Code"] == "PIIIA"]
        
        if not op_row.empty:
            ebitda_row_data = {"Code": "EBITDA_CALC", "Item (TR)": "EBITDA", "Item (EN)": "EBITDA"}
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
            fig_rev = _make_quarterly_bar_chart(df_full, "PIIA", "📈 Revenue (Hasılat)", "#17a2b8")
            if fig_rev:
                st.plotly_chart(fig_rev, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Revenue data not available")
        
        with ch_c2:
            fig_gp = _make_quarterly_bar_chart(df_full, "PII1", "📈 Gross Profit (Brüt Kar)", "#28a745")
            if fig_gp:
                st.plotly_chart(fig_gp, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("Gross Profit data not available")
        
        ch_c3, ch_c4 = st.columns(2)
        
        with ch_c3:
            fig_ebitda = _make_quarterly_bar_chart(df_full, "EBITDA_CALC", "📈 EBITDA", "#fd7e14")
            if fig_ebitda is None:
                # Fallback: show Operating Profit if EBITDA calc failed
                fig_ebitda = _make_quarterly_bar_chart(df_full, "PIV", "📈 Operating Profit (EBIT)", "#fd7e14")
            if fig_ebitda:
                st.plotly_chart(fig_ebitda, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("EBITDA data not available")
        
        with ch_c4:
            fig_np = _make_quarterly_bar_chart(df_full, "PVIII", "📈 Net Profit (Net Kar)", "#6f42c1", fallback_code="PVII")
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
        if df_key is not None:
            bs_codes = list(KEY_ITEMS.keys())
            df_bs_display = df_key[df_key["Code"].isin(bs_codes)].copy()
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
                    current_a = df_key[df_key["Code"] == "1AK"][latest_p].values
                    noncurrent_a = df_key[df_key["Code"] == "1AD"][latest_p].values
                    current_l = df_key[df_key["Code"] == "2K"][latest_p].values
                    noncurrent_l = df_key[df_key["Code"] == "2D"][latest_p].values
                    equity = df_key[df_key["Code"] == "2O"][latest_p].values
                    
                    vals = []
                    labels = []
                    for lbl, arr in [("Current Assets", current_a), ("Non-Current Assets", noncurrent_a),
                                     ("Current Liabilities", current_l), ("Non-Current Liabilities", noncurrent_l),
                                     ("Equity", equity)]:
                        v = float(arr[0]) if len(arr) > 0 and arr[0] is not None and pd.notna(arr[0]) else 0
                        if v != 0:
                            vals.append(abs(v))
                            labels.append(lbl)
                    
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
        if df_key is not None:
            is_codes = list(KEY_INCOME_ITEMS.keys())
            df_is_display = df_key[df_key["Code"].isin(is_codes)].copy()
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
        if df_full is not None:
            st.caption(f"Showing all {len(df_full)} line items")
            period_cols = [c for c in df_full.columns if "/" in c]
            display_cols = ["Code", "Item (TR)"] + period_cols
            st.dataframe(df_full[display_cols], use_container_width=True, hide_index=True, height=500)
        else:
            st.info("Full data not available.")


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
                filter_c = st.checkbox("🔍 Show Only Chosen", value=st.session_state.filter_chosen_only)
                st.session_state.filter_chosen_only = filter_c
                if filter_c:
                    if selected_tf in st.session_state.chosen_stocks and st.session_state.chosen_stocks[selected_tf]:
                        stocks = [s['symbol'] for s in st.session_state.chosen_stocks[selected_tf]]
                    else:
                        st.warning("Run screener first")
                        stocks = IMKB
                else:
                    stocks = IMKB
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
                
                # Tabs for additional charts
                tab1, tab2, tab3 = st.tabs(["📊 Volume", "📈 MACD", "📉 RSI"])
                with tab1:
                    st.plotly_chart(create_volume_chart(df), use_container_width=True, config=PLOTLY_CONFIG)
                with tab2:
                    st.plotly_chart(create_macd_chart(df), use_container_width=True, config=PLOTLY_CONFIG)
                with tab3:
                    st.plotly_chart(create_rsi_chart(df), use_container_width=True, config=PLOTLY_CONFIG)
                
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
