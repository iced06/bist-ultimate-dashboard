"""
Real-Time Technical Analysis Dashboard for Turkish Stock Market (BIST)
COMPLETE VERSION with Multi-Timeframe Analysis
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
    initial_sidebar_state="expanded"
)

load_dotenv()

st.markdown("""
<style>
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
    .timeframe-badge {
        background-color: #e7f3ff;
        border-left: 4px solid #0066cc;
        padding: 0.5rem;
        margin: 0.5rem 0;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'chosen_stocks' not in st.session_state:
    st.session_state.chosen_stocks = {}  # Changed to dict to store per timeframe
if 'filter_chosen_only' not in st.session_state:
    st.session_state.filter_chosen_only = False
if 'current_timeframe' not in st.session_state:
    st.session_state.current_timeframe = "1d"

IMKB = [
    "THYAO", "GARAN", "ASELS", "EREGL", "AKBNK", "SAHOL", "TUPRS", "YKBNK",
    "KCHOL", "PETKM", "VAKBN", "SISE", "TCELL", "ENKAI", "ISCTR", "KOZAL",
    "TTKOM", "DOHOL", "FROTO", "HALKB", "ARCLK", "BIMAS", "EKGYO", "TAVHL",
    "ALARK", "PGSUS", "ODAS", "MGROS", "SOKM", "KRDMD", "ALBRK", "SKBNK",
    "TSKB", "ICBCT", "KLNMA", "AKGRT", "ANHYT", "ANSGR", "AGESA", "TURSG",
    "RAYSG", "CRDFA", "GARFA", "ISFIN", "LIDFA", "SEKFK", "ULUFA", "VAKFN",
    "A1CAP", "GEDIK", "GLBMD", "INFO", "ISMEN", "OSMEN", "OYYAT", "TERA"
]
IMKB = sorted(list(set(IMKB)))

# Timeframe configurations
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

@st.cache_resource
def setup_tradingview_auth():
    try:
        username = os.getenv("TRADINGVIEW_USERNAME")
        password = os.getenv("TRADINGVIEW_PASSWORD")
        if username and password:
            bp.set_tradingview_credentials(username=username, password=password)
            return True, "✅ Real-time data enabled"
        return False, "⚠️ Using free tier (15-min delay)"
    except:
        return False, "❌ Authentication failed"

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
    except Exception as e:
        st.error(f"Error: {e}")
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
    except Exception as e:
        st.error(f"Error: {e}")
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
    if latest['Close'] < latest['bb_bbl']: score += 1
    elif latest['Close'] > latest['bb_bbh']: score -= 1
    if len(df) >= 5:
        pc = (latest['Close'] - df.iloc[-5]['Close']) / df.iloc[-5]['Close']
        if pc > 0.05: score += 1
        elif pc < -0.05: score -= 1
    score = max(0, min(5, score + 2.5))
    vr = latest["Volume"] / latest["VSMA15"]
    vs = 5 if vr > 2 else 4 if vr > 1.5 else 3 if vr > 1.2 else 2 if vr > 0.8 else 1
    return round(score, 1), round(vs, 1)

def screen_chosen_stocks(stock_list, interval="1d"):
    """Screen stocks for a specific timeframe"""
    chosen = []
    prog = st.progress(0)
    stat = st.empty()
    
    # Calculate appropriate date range for the timeframe
    days = TIMEFRAMES[interval]["days"]
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    for i, s in enumerate(stock_list):
        stat.text(f"Screening {s} ({interval})... ({i+1}/{len(stock_list)})")
        prog.progress((i + 1) / len(stock_list))
        try:
            df = fetch_stock_data(s, start_date=start_date, interval=interval)
            if df is not None and not df.empty:
                df = calculate_all_indicators(df)
                ind, vol = calculate_original_scores(df)
                if ind >= 3 and vol > 0.7:
                    chosen.append({
                        'symbol': s, 
                        'indicator_score_2': round(ind, 2), 
                        'volume_score_2': round(vol, 2),
                        'timeframe': interval
                    })
        except:
            continue
    prog.empty()
    stat.empty()
    return chosen

def create_gauge(v, t, m=5):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=v, title={'text': t, 'font': {'size': 18}},
        gauge={'axis': {'range': [None, m]}, 'bar': {'color': "#1f77b4"},
               'steps': [{'range': [0, 2], 'color': "#ffcccc"}, 
                        {'range': [2, 3.5], 'color': "#ffffcc"}, 
                        {'range': [3.5, m], 'color': "#ccffcc"}]}
    ))
    fig.update_layout(height=200, margin=dict(l=20, r=20, t=40, b=20))
    return fig

def create_candlestick(df, s):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'))
    fig.add_trace(go.Scatter(x=df.index, y=df['bb_bbh'], mode='lines', line=dict(color='rgba(255,0,0,0.5)', width=1), name='BB Upper'))
    fig.add_trace(go.Scatter(x=df.index, y=df['bb_bbl'], mode='lines', line=dict(color='rgba(0,0,255,0.5)', width=1), name='BB Lower', fill='tonexty', fillcolor='rgba(200,200,200,0.2)'))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA5'], mode='lines', line=dict(color='orange', width=2), name='SMA 5'))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA22'], mode='lines', line=dict(color='green', width=2), name='SMA 22'))
    fig.update_layout(title=f"{s} - Price Chart", xaxis_title="Date/Time", yaxis_title="Price (TRY)", height=500, xaxis_rangeslider_visible=False)
    return fig

def create_volume_chart(df):
    fig = go.Figure()
    colors = ['red' if df['Close'].iloc[i] < df['Open'].iloc[i] else 'green' for i in range(len(df))]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='Volume', marker_color=colors))
    fig.add_trace(go.Scatter(x=df.index, y=df['VSMA15'], mode='lines', line=dict(color='blue', width=2), name='VSMA 15'))
    fig.update_layout(title="Volume Analysis", xaxis_title="Date/Time", yaxis_title="Volume", height=300)
    return fig

def create_macd_chart(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], mode='lines', line=dict(color='blue', width=2), name='MACD'))
    fig.add_trace(go.Scatter(x=df.index, y=df['MACDS'], mode='lines', line=dict(color='red', width=2), name='Signal'))
    colors = ['green' if val > 0 else 'red' for val in df['Diff']]
    fig.add_trace(go.Bar(x=df.index, y=df['Diff'], name='Histogram', marker_color=colors))
    fig.update_layout(title="MACD Indicator", xaxis_title="Date/Time", yaxis_title="Value", height=300)
    return fig

def create_rsi_chart(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], mode='lines', line=dict(color='purple', width=2), name='RSI'))
    fig.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought (70)")
    fig.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold (30)")
    fig.update_layout(title="RSI Indicator", xaxis_title="Date/Time", yaxis_title="RSI", yaxis_range=[0, 100], height=300)
    return fig

def main():
    st.markdown('<h1 class="main-header">📊 BIST Multi-Timeframe Analysis</h1>', unsafe_allow_html=True)
    
    auth, msg = setup_tradingview_auth()
    st.session_state.authenticated = auth
    css = "status-realtime" if auth else "status-delayed"
    st.markdown(f'<div class="status-box {css}">{"🎉" if auth else "⚠️"} {msg}</div>', unsafe_allow_html=True)
    
    with st.sidebar:
        st.header("⚙️ Settings")
        mode = st.radio("Mode", ["📊 Single Stock", "🔍 Stock Screener"])
        
        st.markdown("---")
        st.subheader("⏱️ Timeframe")
        
        # Get available timeframes based on authentication
        available_timeframes = {k: v for k, v in TIMEFRAMES.items() 
                               if not v["auth_required"] or auth}
        
        timeframe_options = {k: v["label"] for k, v in available_timeframes.items()}
        selected_timeframe = st.selectbox(
            "Select Timeframe",
            options=list(timeframe_options.keys()),
            format_func=lambda x: timeframe_options[x],
            index=list(timeframe_options.keys()).index(st.session_state.current_timeframe) 
                  if st.session_state.current_timeframe in timeframe_options 
                  else 0
        )
        st.session_state.current_timeframe = selected_timeframe
        
        if not auth and selected_timeframe != "1d" and selected_timeframe != "1wk":
            st.warning("⚠️ Intraday timeframes require TradingView authentication")
        
        # Display timeframe info
        st.markdown(f'<div class="timeframe-badge">📈 Current: {TIMEFRAMES[selected_timeframe]["label"]}</div>', 
                   unsafe_allow_html=True)
        
        if mode == "📊 Single Stock":
            st.markdown("---")
            filter_chosen = st.checkbox(
                "🔍 Show Only Chosen Stocks",
                value=st.session_state.filter_chosen_only,
                help=f"Filter to show only chosen stocks for {TIMEFRAMES[selected_timeframe]['label']} timeframe"
            )
            st.session_state.filter_chosen_only = filter_chosen
            
            if filter_chosen:
                if selected_timeframe in st.session_state.chosen_stocks and st.session_state.chosen_stocks[selected_timeframe]:
                    stocks = [s['symbol'] for s in st.session_state.chosen_stocks[selected_timeframe]]
                    st.markdown(f'<div class="filter-info">📌 Showing {len(stocks)} chosen stocks ({TIMEFRAMES[selected_timeframe]["label"]})</div>', 
                               unsafe_allow_html=True)
                else:
                    st.warning(f"⚠️ Run Stock Screener for {TIMEFRAMES[selected_timeframe]['label']} first")
                    stocks = IMKB
            else:
                stocks = IMKB
            
            stock = st.selectbox("Stock Symbol", stocks)
            
            st.subheader("📅 Custom Date Range")
            use_custom = st.checkbox("Use custom dates", value=False)
            if use_custom:
                col1, col2 = st.columns(2)
                with col1:
                    start = st.date_input("Start", value=datetime.now() - timedelta(days=TIMEFRAMES[selected_timeframe]["days"]))
                with col2:
                    end = st.date_input("End", value=datetime.now())
            else:
                start = datetime.now() - timedelta(days=TIMEFRAMES[selected_timeframe]["days"])
                end = datetime.now()
                st.info(f"📅 Auto: Last {TIMEFRAMES[selected_timeframe]['days']} days")
        else:
            st.info(f"🔍 Will screen all stocks for {TIMEFRAMES[selected_timeframe]['label']} timeframe")
            st.info("Criteria: Score 2 >= 3 AND Vol > 0.7")
            if st.button("🚀 Run Screener", use_container_width=True):
                with st.spinner(f"Screening all stocks ({TIMEFRAMES[selected_timeframe]['label']})..."):
                    results = screen_chosen_stocks(IMKB, interval=selected_timeframe)
                    st.session_state.chosen_stocks[selected_timeframe] = results
                st.success(f"✅ Found {len(results)} chosen stocks for {TIMEFRAMES[selected_timeframe]['label']}!")
        
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.markdown("---")
        st.markdown("### 📖 Info")
        st.markdown(f"""
        **Current Timeframe:**  
        {TIMEFRAMES[selected_timeframe]['label']}
        
        **Chosen Stocks:**
        """)
        for tf, stocks in st.session_state.chosen_stocks.items():
            if stocks:
                st.markdown(f"- {TIMEFRAMES[tf]['label']}: {len(stocks)} stocks")
    
    if mode == "📊 Single Stock":
        start_str = start.strftime("%Y-%m-%d") if isinstance(start, date) else start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d") if isinstance(end, date) else end.strftime("%Y-%m-%d")
        
        with st.spinner(f"Loading {stock} ({TIMEFRAMES[selected_timeframe]['label']})..."):
            df = fetch_stock_data(stock, start_date=start_str, end_date=end_str, interval=selected_timeframe)
        
        if df is not None and not df.empty:
            df = calculate_all_indicators(df)
            ind1, vol1 = calculate_simplified_scores(df)
            ind2, vol2 = calculate_original_scores(df)
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            
            st.subheader(f"📈 {stock} - {TIMEFRAMES[selected_timeframe]['label']} Analysis")
            if st.session_state.filter_chosen_only:
                st.markdown('<div class="filter-info">🔍 <b>Filtered View</b></div>', unsafe_allow_html=True)
            
            col1, col2, col3, col4, col5 = st.columns(5)
            ch = latest['Close'] - prev['Close']
            pct = (ch / prev['Close']) * 100
            with col1:
                st.metric("Price", f"₺{latest['Close']:.2f}", f"{ch:.2f} ({pct:.2f}%)")
            with col2:
                st.metric("Volume", f"{latest['Volume']:,.0f}")
            with col3:
                st.metric("RSI", f"{latest['RSI']:.2f}")
            with col4:
                st.metric("MACD", f"{latest['MACD']:.4f}")
            with col5:
                st.metric("Data Points", f"{len(df):,}")
            
            st.subheader("🎯 Scores")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### Score 1 (Simplified)")
                c1, c2 = st.columns(2)
                with c1:
                    st.plotly_chart(create_gauge(ind1, "Indicator 1"), use_container_width=True)
                with c2:
                    st.plotly_chart(create_gauge(vol1, "Volume 1"), use_container_width=True)
            with col2:
                st.markdown("#### Score 2 (Original) ⭐")
                c1, c2 = st.columns(2)
                with c1:
                    st.plotly_chart(create_gauge(ind2, "Indicator 2", 10), use_container_width=True)
                with c2:
                    st.metric("Volume 2", f"{vol2:.2f}")
                    st.success("✅ Above 0.7") if vol2 > 0.7 else st.warning("⚠️ Below 0.7")
            
            if ind2 >= 3 and vol2 > 0.7:
                st.markdown(f'<div class="chosen-stock"><h3>⭐ CHOSEN STOCK ({TIMEFRAMES[selected_timeframe]["label"]})! ⭐</h3></div>', 
                           unsafe_allow_html=True)
            
            st.subheader("📊 Charts")
            st.plotly_chart(create_candlestick(df, stock), use_container_width=True)
            
            tab1, tab2, tab3 = st.tabs(["📊 Volume", "📈 MACD", "📉 RSI"])
            with tab1:
                st.plotly_chart(create_volume_chart(df), use_container_width=True)
            with tab2:
                st.plotly_chart(create_macd_chart(df), use_container_width=True)
            with tab3:
                st.plotly_chart(create_rsi_chart(df), use_container_width=True)
            
            with st.expander("📋 Raw Data"):
                st.dataframe(df[['Open', 'High', 'Low', 'Close', 'Volume', 'RSI', 'MACD']].tail(100), 
                           use_container_width=True)
        else:
            st.error(f"❌ No data available for {stock}")
    else:
        st.subheader(f"🔍 Chosen Stocks - {TIMEFRAMES[selected_timeframe]['label']} Timeframe")
        if selected_timeframe in st.session_state.chosen_stocks and st.session_state.chosen_stocks[selected_timeframe]:
            results = st.session_state.chosen_stocks[selected_timeframe]
            st.success(f"✅ Found {len(results)} chosen stocks")
            st.info("💡 Switch to Single Stock + enable filter to analyze!")
            
            df_c = pd.DataFrame(results).sort_values('indicator_score_2', ascending=False)
            st.dataframe(
                df_c.style.background_gradient(subset=['indicator_score_2', 'volume_score_2'], cmap='RdYlGn'),
                use_container_width=True
            )
            
            cols = st.columns(3)
            for idx, s in enumerate(df_c.to_dict('records')):
                with cols[idx % 3]:
                    st.markdown(f"""
                    <div class="chosen-stock">
                        <h4>{s['symbol']}</h4>
                        <p><b>Indicator:</b> {s['indicator_score_2']}</p>
                        <p><b>Volume:</b> {s['volume_score_2']}</p>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info(f"👆 Click 'Run Stock Screener' for {TIMEFRAMES[selected_timeframe]['label']} timeframe")
    
    st.markdown("---")
    st.markdown(
        f"""
        <div style='text-align: center; color: #7f8c8d;'>
            Timeframe: {TIMEFRAMES[selected_timeframe]['label']} | 
            Data: borsapy (TradingView) | {'✅ Real-time' if auth else '⏱️ 15-min delayed'} | 
            Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
