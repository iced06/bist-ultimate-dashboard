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
from dotenv import load_dotenv

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
