"""
Fund flow analysis dashboard.

Reads from the "bist" Postgres schema (see db/schema.sql, db/migrate_excel_to_postgres.py).
Three views:
  1. Monthly top buys/sells across all tracked funds
  2. Fund flow ranked by impact relative to each stock's own market cap
  3. Per-stock drill-down: which funds bought/sold it, and how much
"""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import plotly.graph_objects as go
import psycopg2
import streamlit as st

try:
    import borsapy as bp
except ImportError:
    bp = None

PLOTLY_CONFIG = {'displayModeBar': False, 'scrollZoom': False, 'responsive': True}

TR_MONTHS_SHORT = {1: 'Oca', 2: 'Şub', 3: 'Mar', 4: 'Nis', 5: 'May', 6: 'Haz',
                    7: 'Tem', 8: 'Ağu', 9: 'Eyl', 10: 'Eki', 11: 'Kas', 12: 'Ara'}


def _get_database_url():
    try:
        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:
        pass
    return os.getenv("DATABASE_URL")


def _make_connection():
    dsn = _get_database_url()
    if not dsn:
        return None
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET search_path TO bist, public;")
    return conn


@st.cache_resource(show_spinner=False)
def _get_connection():
    return _make_connection()


def _get_live_connection():
    """Neon serverless bosta kalinca compute'u askiya alabiliyor (pilotta
    gozlemlendi: birkac dakika bekleyince cache'lenmis baglanti "connection
    already closed" hatasi verdi). Kullanmadan once canliligini kontrol edip
    gerekirse cache'i temizleyip yeniden bağlanıyoruz."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        if conn.closed:
            raise psycopg2.OperationalError("connection closed")
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        _get_connection.clear()
        conn = _get_connection()
    return conn


@st.cache_data(ttl=3600, show_spinner=False)
def _get_available_periods():
    conn = _get_live_connection()
    if conn is None:
        return []
    df = pd.read_sql("SELECT DISTINCT yil, ay FROM fund_holdings ORDER BY yil, ay", conn)
    return list(df.itertuples(index=False, name=None))


@st.cache_data(ttl=1800, show_spinner=False)
def get_latest_fund_flow_map(uyruk='TC'):
    """
    En son donem icin ticker -> net fon alim/satimi (TL) sozlugu.
    streamlit_app.py'daki Screener'in "Fon Net Alımı" kolonu icin -
    tek seferde toplu cekilir, hisse basina ayri sorgu atilmaz.
    Fon verisi olmayan hisseler sozlukte hic yer almaz (None donduruyor gibi
    davranilmali - caller .get(ticker) ile kontrol etmeli).
    """
    conn = _get_live_connection()
    if conn is None:
        return {}
    df = pd.read_sql("""
        SELECT s.ticker, f.net_gercek_alim_satim_tl, f.net_fon_akisi_tl
        FROM stock_fund_flow_monthly f
        JOIN securities s ON s.id = f.security_id
        WHERE s.uyruk = %(uyruk)s
          AND (f.yil, f.ay) = (SELECT yil, ay FROM fund_holdings ORDER BY yil DESC, ay DESC LIMIT 1)
    """, conn, params={"uyruk": uyruk})
    if df.empty:
        return {}
    df['net_gercek_alim_satim_tl'] = df['net_gercek_alim_satim_tl'].astype(float)
    df['net_fon_akisi_tl'] = df['net_fon_akisi_tl'].astype(float)
    result = {}
    for _, r in df.iterrows():
        val = r['net_gercek_alim_satim_tl'] if pd.notna(r['net_gercek_alim_satim_tl']) else r['net_fon_akisi_tl']
        if pd.notna(val):
            result[r['ticker']] = val
    return result


@st.cache_data(ttl=1800, show_spinner=False)
def _get_flow_ranking(yil, ay):
    conn = _get_live_connection()
    if conn is None:
        return pd.DataFrame()
    df = pd.read_sql("""
        SELECT s.ticker, s.ad, s.uyruk,
               f.fon_sayisi, f.toplam_fon_tutari,
               f.net_fon_akisi_tl, f.net_gercek_alim_satim_tl
        FROM stock_fund_flow_monthly f
        JOIN securities s ON s.id = f.security_id
        WHERE f.yil = %(yil)s AND f.ay = %(ay)s
          AND (f.net_gercek_alim_satim_tl IS NOT NULL OR f.net_fon_akisi_tl IS NOT NULL)
    """, conn, params={"yil": yil, "ay": ay})
    if not df.empty:
        # psycopg2 NUMERIC kolonlari Decimal olarak donduruyor -> pandas object
        # dtype'ta kalabiliyor; nlargest/aritmetik icin float'a cevirmek gerekiyor.
        for col in ['toplam_fon_tutari', 'net_fon_akisi_tl', 'net_gercek_alim_satim_tl']:
            df[col] = df[col].astype(float)
        # nominal_deger (adet) tarihsel Excel verisinde yok - bu satirlarda
        # net_gercek_alim_satim_tl NULL kalir. KAP PDF'ten gelen aylarda
        # (nominal_deger dolu oldugunda) hassas metrik kullanilabilir olacak.
        # O zamana kadar ham degisime (fiyat+miktar karisik) fallback yapiyoruz.
        df['metrik_yaklasik_mi'] = df['net_gercek_alim_satim_tl'].isna()
        df['siralama_metrigi'] = df['net_gercek_alim_satim_tl'].fillna(df['net_fon_akisi_tl'])
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def _get_stock_list():
    conn = _get_live_connection()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql("""
        SELECT DISTINCT s.id, s.ticker, s.uyruk, s.ad
        FROM securities s
        JOIN fund_holdings fh ON fh.security_id = s.id
        ORDER BY s.ticker
    """, conn)


@st.cache_data(ttl=1800, show_spinner=False)
def _get_holders_for_stock(security_id):
    conn = _get_live_connection()
    if conn is None:
        return pd.DataFrame()
    df = pd.read_sql("""
        SELECT fh.fon_kodu, fnd.fon_adi, fh.yil, fh.ay,
               fh.toplam_tutar_tl, fh.agirlik_pct,
               fhc.miktar_etkisi_tl, fhc.fiyat_etkisi_tl, fhc.degisim_tl
        FROM fund_holdings fh
        JOIN funds fnd ON fnd.fon_kodu = fh.fon_kodu
        LEFT JOIN fund_holdings_change fhc
               ON fhc.fon_kodu = fh.fon_kodu AND fhc.security_id = fh.security_id
              AND fhc.yil = fh.yil AND fhc.ay = fh.ay
        WHERE fh.security_id = %(sid)s
        ORDER BY fh.yil, fh.ay, fh.fon_kodu
    """, conn, params={"sid": int(security_id)})
    if df.empty:
        return df
    for col in ['toplam_tutar_tl', 'agirlik_pct', 'miktar_etkisi_tl', 'fiyat_etkisi_tl', 'degisim_tl']:
        df[col] = df[col].astype(float)
    return df


def _fetch_one_market_cap(ticker):
    try:
        fi = bp.Ticker(ticker).fast_info
        if fi and getattr(fi, 'market_cap', None):
            return ticker, fi.market_cap
    except Exception:
        pass
    return ticker, None


@st.cache_data(ttl=3600, show_spinner=False)
def _get_market_caps(tickers):
    """Canlı BIST piyasa değeri (borsapy fast_info) — sadece TC hisseleri için çalışır.

    NOT: borsapy'nin altyapısi (TradingView) kimlik doğrulanmamış istekleri
    agresif rate-limit'liyor (429) - pilotta 10 eşzamanlı istekle bazı
    hisseler 17+ saniye retry-backoff'a girdi. Ana uygulama TRADINGVIEW_
    USERNAME/PASSWORD ile authenticate olduğunda (setup_tradingview_auth,
    bkz. streamlit_app.py) limitler muhtemelen daha yüksek; yine de
    savunmacı olarak düşük bir eşzamanlılık kullanıyoruz.
    """
    caps = {}
    if bp is None or not tickers:
        return caps
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(_fetch_one_market_cap, t) for t in tickers]
        for fut in as_completed(futures):
            ticker, cap = fut.result()
            if cap:
                caps[ticker] = cap
    return caps


def _fmt_tl(x):
    if x is None or pd.isna(x):
        return "-"
    a = abs(x)
    sign = "-" if x < 0 else ""
    if a >= 1e9:
        return f"{sign}{a/1e9:,.2f} Mr TL"
    if a >= 1e6:
        return f"{sign}{a/1e6:,.1f} Mn TL"
    return f"{sign}{a:,.0f} TL"


def _period_selector(periods, key):
    labels = [f"{TR_MONTHS_SHORT.get(ay, ay)} {yil}" for yil, ay in periods]
    idx = st.selectbox("Dönem", options=list(range(len(periods))),
                        format_func=lambda i: labels[i], index=len(periods) - 1, key=key)
    return periods[idx]


def _bar_chart(df, x_col, y_col, colors, title):
    fig = go.Figure(go.Bar(
        x=df[x_col], y=df[y_col], orientation='h',
        marker_color=colors,
        text=[_fmt_tl(v) for v in df[x_col]], textposition='auto',
    ))
    fig.update_layout(title=title, height=max(300, 28 * len(df)),
                       margin=dict(l=10, r=10, t=40, b=10),
                       yaxis=dict(autorange="reversed"))
    return fig


def _render_top_buys_sells(yil, ay):
    df = _get_flow_ranking(yil, ay)
    if df.empty:
        st.info("Bu dönem için veri bulunamadı.")
        return

    n_approx = int(df['metrik_yaklasik_mi'].sum())
    if n_approx == len(df):
        st.warning("⚠️ Bu dönem için **adet (nominal) verisi yok** (henüz sadece Excel kaynaklı "
                   "veri yüklü) — sıralama fiyat hareketiyle miktar değişiminin karışık olduğu "
                   "**ham değişime** göre yapılıyor. KAP'tan aylık veri eklendikçe bu otomatik "
                   "olarak gerçek alım/satım bazlı hassas sıralamaya geçecek.")
    elif n_approx > 0:
        st.caption(f"Sıralama gerçek alım/satım (adet değişimi) esasına göre — {n_approx} hisse "
                   "için adet verisi olmadığından ham değişim kullanıldı.")
    else:
        st.caption("Sıralama **gerçek alım/satım** (adet değişimi) esasına göredir — sadece fiyat "
                   "hareketinden gelen değişim buraya dahil değildir.")

    n = st.slider("Kaç hisse gösterilsin?", 5, 30, 15, key="topn_buysell")

    buys = df[df['siralama_metrigi'] > 0].nlargest(n, 'siralama_metrigi')
    sells = df[df['siralama_metrigi'] < 0].nsmallest(n, 'siralama_metrigi')

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 🟢 En Çok Alınan")
        if not buys.empty:
            st.plotly_chart(_bar_chart(buys, 'siralama_metrigi', 'ticker',
                                        '#22c55e', "Net Alım (TL)"),
                             use_container_width=True, config=PLOTLY_CONFIG)
        else:
            st.info("Bu dönemde net alım kaydı yok.")
    with c2:
        st.markdown("#### 🔴 En Çok Satılan")
        if not sells.empty:
            st.plotly_chart(_bar_chart(sells, 'siralama_metrigi', 'ticker',
                                        '#ef4444', "Net Satım (TL)"),
                             use_container_width=True, config=PLOTLY_CONFIG)
        else:
            st.info("Bu dönemde net satım kaydı yok.")

    with st.expander("📋 Tüm hisseler — detay tablo"):
        show = df.sort_values('siralama_metrigi', ascending=False).copy()
        show['Net Alım/Satım'] = show['siralama_metrigi'].apply(_fmt_tl)
        show['Kesinlik'] = show['metrik_yaklasik_mi'].map({True: 'Yaklaşık (fiyat+miktar)', False: 'Gerçek (adet bazlı)'})
        show['Toplam Fon Tutarı'] = show['toplam_fon_tutari'].apply(_fmt_tl)
        st.dataframe(show[['ticker', 'ad', 'fon_sayisi', 'Net Alım/Satım',
                            'Kesinlik', 'Toplam Fon Tutarı']],
                     use_container_width=True, hide_index=True)


def _render_market_impact(yil, ay):
    df = _get_flow_ranking(yil, ay)
    df = df[df['uyruk'] == 'TC'].copy()
    if df.empty:
        st.info("Bu dönem için yerli hisse verisi bulunamadı.")
        return

    st.caption("Piyasa değeri **borsapy üzerinden canlı** çekilir (bugünkü değer) — geçmiş "
               "dönemler için yaklaşık bir referans olarak kullanılmalı, o ayki gerçek piyasa "
               "değeri değildir. Sadece yerli (BIST) hisseler için hesaplanabilir.")
    if df['metrik_yaklasik_mi'].any():
        st.caption("ℹ️ Adet verisi olmayan aylarda pay değişimi yerine ham TL değişimi kullanılıyor "
                   "(bkz. 'En Çok Alınan/Satılan' sekmesindeki not).")

    n = st.slider("Kaç hisse gösterilsin?", 5, 30, 15, key="topn_impact")

    # borsapy her hisse icin ayri bir ag cagrisi yapiyor - bu donemde 200+ TC
    # hissesi olabiliyor, hepsi icin canli piyasa degeri cekmek cok yavas
    # olurdu. Once ham TL degisimine gore genis bir aday listesi (candidate
    # pool) sec, piyasa degerini SADECE bu adaylar icin cek.
    candidate_pool = min(max(n * 2, 20), len(df), 40)
    candidates = df.reindex(df['siralama_metrigi'].abs().sort_values(ascending=False).index).head(candidate_pool)

    with st.spinner(f"{len(candidates)} hisse için piyasa değeri çekiliyor..."):
        caps = _get_market_caps(tuple(candidates['ticker'].unique()))

    candidates = candidates.copy()
    candidates['market_cap'] = candidates['ticker'].map(caps)
    candidates = candidates.dropna(subset=['market_cap'])
    candidates = candidates[candidates['market_cap'] > 0]
    if candidates.empty:
        st.warning("Piyasa değeri verisi çekilemedi.")
        return

    candidates['etki_pct'] = candidates['siralama_metrigi'] / candidates['market_cap'] * 100
    top = candidates.reindex(candidates['etki_pct'].abs().sort_values(ascending=False).index).head(n)

    colors = ['#22c55e' if v > 0 else '#ef4444' for v in top['etki_pct']]
    fig = go.Figure(go.Bar(
        x=top['etki_pct'], y=top['ticker'], orientation='h', marker_color=colors,
        text=[f"{v:+.3f}%" for v in top['etki_pct']], textposition='auto',
    ))
    fig.update_layout(title="Fon Akışının Piyasa Değerine Oranı (%)",
                       height=max(300, 28 * len(top)),
                       margin=dict(l=10, r=10, t=40, b=10),
                       yaxis=dict(autorange="reversed"),
                       xaxis_title="Net gerçek alım/satım ÷ piyasa değeri (%)")
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

    with st.expander("📋 Detay tablo"):
        show = top.copy()
        show['Piyasa Değeri'] = show['market_cap'].apply(_fmt_tl)
        show['Net Alım/Satım'] = show['siralama_metrigi'].apply(_fmt_tl)
        show['Etki (%)'] = show['etki_pct'].apply(lambda v: f"{v:+.3f}%")
        st.dataframe(show[['ticker', 'ad', 'Net Alım/Satım', 'Piyasa Değeri', 'Etki (%)']],
                     use_container_width=True, hide_index=True)


def _render_stock_drilldown():
    stocks = _get_stock_list()
    if stocks.empty:
        st.info("Fon verisi bulunan hisse yok.")
        return

    stocks = stocks.copy()
    stocks['label'] = stocks['ticker'] + stocks['uyruk'].apply(lambda u: '' if u == 'TC' else f" ({u})")
    sel_label = st.selectbox("Hisse seç", options=stocks['label'].tolist(), key="drilldown_stock")
    row = stocks[stocks['label'] == sel_label].iloc[0]

    df = _get_holders_for_stock(row['id'])
    if df.empty:
        st.info("Bu hisse için fon verisi bulunamadı.")
        return

    periods = sorted(df[['yil', 'ay']].drop_duplicates().itertuples(index=False, name=None))
    yil, ay = _period_selector(periods, key="drilldown_period")
    period_df = df[(df['yil'] == yil) & (df['ay'] == ay)].copy()
    # nominal_deger olmayan (tarihsel Excel) aylarda miktar_etkisi_tl NULL olur;
    # bu durumda ham degisime (fiyat+miktar karisik) fallback yapiyoruz.
    period_df['degisim_gosterilecek'] = period_df['miktar_etkisi_tl'].fillna(period_df['degisim_tl'])
    period_df = period_df.sort_values('degisim_gosterilecek', ascending=False, na_position='last')
    if period_df['miktar_etkisi_tl'].isna().all():
        st.caption("ℹ️ Bu ay için adet verisi yok — 'Değişim' sütunu ham TL değişimidir "
                   "(fiyat hareketini de içerir).")

    st.markdown(f"#### {sel_label} — {TR_MONTHS_SHORT.get(ay, ay)} {yil} itibarıyla fon dağılımı")
    show = period_df.copy()
    show['TL Tutar'] = show['toplam_tutar_tl'].apply(_fmt_tl)
    show['Ağırlık'] = show['agirlik_pct'].apply(lambda v: f"{v:.2f}%" if pd.notna(v) else "-")
    show['Bu Ay Değişim'] = show['degisim_gosterilecek'].apply(_fmt_tl)
    st.dataframe(show[['fon_kodu', 'fon_adi', 'TL Tutar', 'Ağırlık', 'Bu Ay Değişim']],
                 use_container_width=True, hide_index=True)

    # Zaman icinde toplam fon sahipliği trendi
    trend = df.groupby(['yil', 'ay'], as_index=False)['toplam_tutar_tl'].sum()
    trend = trend.sort_values(['yil', 'ay'])
    trend['label'] = trend.apply(lambda r: f"{TR_MONTHS_SHORT.get(int(r['ay']), r['ay'])} {int(r['yil'])}", axis=1)
    fig = go.Figure(go.Scatter(x=trend['label'], y=trend['toplam_tutar_tl'], mode='lines+markers',
                                line=dict(color='#3b82f6', width=2)))
    fig.update_layout(title="Toplam Fon Sahipliği (Zaman İçinde)", height=300,
                       margin=dict(l=10, r=10, t=40, b=10), yaxis_title="TL")
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


def display_funds_analysis():
    st.markdown("### 💰 Fund Flow Analysis")
    st.caption("Aylık fon portföy değişimleri — KAP 'Portföy Dağılım Raporu' verisine dayanır. "
               "Yatırım tavsiyesi değildir.")

    conn = _get_live_connection()
    if conn is None:
        st.error("Veritabanı bağlantısı kurulamadı — DATABASE_URL secrets/environment "
                  "değişkeni eksik olabilir.")
        return

    periods = _get_available_periods()
    if not periods:
        st.warning("Henüz fon verisi yüklenmemiş.")
        return

    yil, ay = _period_selector(periods, key="main_period")

    tab1, tab2, tab3 = st.tabs([
        "📈 En Çok Alınan / Satılan",
        "🎯 Piyasa Değerine Göre Etki",
        "🔍 Hisse Bazlı Fon Takibi",
    ])
    with tab1:
        _render_top_buys_sells(yil, ay)
    with tab2:
        _render_market_impact(yil, ay)
    with tab3:
        _render_stock_drilldown()
