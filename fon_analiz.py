"""
Fund flow analysis dashboard.

Reads from the "bist" Postgres schema (see db/schema.sql, db/migrate_excel_to_postgres.py).
Three views:
  1. Monthly top buys/sells across all tracked funds
  2. Fund flow ranked by impact relative to each stock's own market cap
  3. Per-stock drill-down: which funds bought/sold it, and how much
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    import psycopg2
except ImportError:
    # Ortamda psycopg2-binary kurulamamis olabilir (bazi Streamlit Cloud
    # build'lerinde gorulen bilinen bir sorun). Bu durumda modul YINE DE
    # import edilebilmeli - Funds sekmesi "veritabani yok" mesaji gosterir,
    # geri kalan uygulama (Single Stock, Screener, vb.) etkilenmez.
    psycopg2 = None

try:
    import borsapy as bp
except ImportError:
    bp = None

# KAP fon raporu import script'i db/ altinda, standalone bir CLI olarak
# yazildi - Funds sekmesindeki "Yeni Ay Icin Ice Aktar" butonu icin ayni
# import_one() fonksiyonunu tekrar yazmadan reuse ediyoruz.
_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db')
try:
    if _DB_DIR not in sys.path:
        sys.path.insert(0, _DB_DIR)
    from import_kap_fund_report import import_one as _kap_import_one
    _KAP_IMPORT_ERROR = None
except Exception as _e:
    _kap_import_one = None
    _KAP_IMPORT_ERROR = _e

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
    if psycopg2 is None:
        return None
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
def _get_fund_list():
    """Fon bazlı drill-down için: sadece gerçekten hisse verisi olan fonlar
    (funds tablosunda fon_holdings'i olmayan bir kayıt varsa listelenmez)."""
    conn = _get_live_connection()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql("""
        SELECT DISTINCT f.fon_kodu, f.fon_adi
        FROM funds f
        JOIN fund_holdings fh ON fh.fon_kodu = f.fon_kodu
        ORDER BY f.fon_kodu
    """, conn)


@st.cache_data(ttl=1800, show_spinner=False)
def _get_positions_for_fund(fon_kodu):
    """Bir fonun TÜM aylara ait pozisyonları + fund_holdings_change'den
    (fiyat/miktar ayrıştırması) o ayki değişimi - _get_holders_for_stock'un
    hisse yerine fon eksenindeki simetriği."""
    conn = _get_live_connection()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql("""
        SELECT s.ticker, s.uyruk, fh.yil, fh.ay,
               fh.toplam_tutar_tl, fh.agirlik_pct,
               fhc.miktar_etkisi_tl, fhc.fiyat_etkisi_tl, fhc.degisim_tl,
               fhc.degisim_agirlik_pct, fhc.degisim_nominal
        FROM fund_holdings fh
        JOIN securities s ON s.id = fh.security_id
        LEFT JOIN fund_holdings_change fhc
               ON fhc.fon_kodu = fh.fon_kodu AND fhc.security_id = fh.security_id
              AND fhc.yil = fh.yil AND fhc.ay = fh.ay
        WHERE fh.fon_kodu = %(fk)s
        ORDER BY fh.yil, fh.ay, fh.agirlik_pct DESC
    """, conn, params={"fk": fon_kodu})


@st.cache_data(ttl=1800, show_spinner=False)
def _get_fund_aum(fon_kodu, yil, ay):
    """Secilen ay icin fonun buyukluk/nakit akisi bilgisi (varsa) - katilma
    payi giris/cikisi baglam vermek icin (fon buyuyor mu kuculuyor mu)."""
    conn = _get_live_connection()
    if conn is None:
        return None
    df = pd.read_sql("""
        SELECT fon_toplam_degeri, pay_fiyati, katilma_payi_giris_tl, katilma_payi_cikis_tl
        FROM fund_aum_monthly WHERE fon_kodu = %(fk)s AND yil = %(yil)s AND ay = %(ay)s
    """, conn, params={"fk": fon_kodu, "yil": yil, "ay": ay})
    return df.iloc[0] if not df.empty else None


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


def _fmt_tl_signed(x):
    """_fmt_tl gibi ama pozitif değerlere de '+' önekler - artış/azalış
    ayrımının tabloda/grafikte tek bakışta görülmesi için (bkz. fon
    drilldown'daki fiyat/miktar etkisi kırılımı)."""
    if x is None or pd.isna(x):
        return "-"
    s = _fmt_tl(x)
    return f"+{s}" if x > 0 else s


def _fmt_adet_signed(x):
    if x is None or pd.isna(x):
        return "-"
    sign = "+" if x > 0 else ""
    return f"{sign}{x:,.0f} adet"


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


def _signed_bar_chart(df, value_col, label_col, title, fmt_func):
    """_bar_chart'ın işaretli (pozitif/negatif) versiyonu - artış yeşil,
    azalış kırmızı. Fon drilldown'daki metrik seçiciyle (Ağırlık/TL/Fiyat
    Etkisi/Miktar Etkisi/Adet Değişimi) kullanılır."""
    d = df.dropna(subset=[value_col]).copy()
    if d.empty:
        return None
    d = d.reindex(d[value_col].abs().sort_values(ascending=False).index)
    colors = ['#22c55e' if v > 0 else '#ef4444' if v < 0 else '#94a3b8' for v in d[value_col]]
    fig = go.Figure(go.Bar(
        x=d[value_col], y=d[label_col], orientation='h', marker_color=colors,
        text=[fmt_func(v) for v in d[value_col]], textposition='auto',
    ))
    fig.update_layout(title=title, height=max(300, 28 * len(d)),
                       margin=dict(l=10, r=10, t=40, b=10),
                       yaxis=dict(autorange="reversed"))
    return fig


def _render_top_buys_sells(yil, ay, uyruk_filter=None):
    df = _get_flow_ranking(yil, ay)
    if uyruk_filter:
        df = df[df['uyruk'] == uyruk_filter]
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


def _render_stock_drilldown(uyruk_filter=None):
    stocks = _get_stock_list()
    if uyruk_filter:
        stocks = stocks[stocks['uyruk'] == uyruk_filter]
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


def _render_fund_drilldown():
    """Hisse bazlı drill-down'un (_render_stock_drilldown) fon eksenindeki
    simetriği: bir FON seçip, secilen ayda o fonun TÜM pozisyonlarını ve
    bir önceki aya göre (fiyat/miktar ayrıştırılmış) değişimini gösterir."""
    funds = _get_fund_list()
    if funds.empty:
        st.info("Fon verisi bulunamadı.")
        return

    funds = funds.copy()
    funds['label'] = funds['fon_kodu'] + ' - ' + funds['fon_adi'].fillna('').str.slice(0, 55)
    sel_label = st.selectbox("Fon seç", options=funds['label'].tolist(), key="fund_drilldown_fon")
    fon_kodu = funds.loc[funds['label'] == sel_label, 'fon_kodu'].iloc[0]

    df = _get_positions_for_fund(fon_kodu)
    if df.empty:
        st.info("Bu fon için pozisyon verisi bulunamadı.")
        return
    for col in ['toplam_tutar_tl', 'agirlik_pct', 'miktar_etkisi_tl', 'fiyat_etkisi_tl',
                'degisim_tl', 'degisim_agirlik_pct', 'degisim_nominal']:
        df[col] = df[col].astype(float)

    periods = sorted(df[['yil', 'ay']].drop_duplicates().itertuples(index=False, name=None))
    yil, ay = _period_selector(periods, key="fund_drilldown_period")
    period_df = df[(df['yil'] == yil) & (df['ay'] == ay)].copy()
    # nominal_deger olmayan (tarihsel Excel) aylarda miktar_etkisi_tl NULL olur;
    # bu durumda ham degisime (fiyat+miktar karisik) fallback yapiyoruz - bkz.
    # _render_stock_drilldown'daki ayni mantik/not.
    period_df['degisim_gosterilecek'] = period_df['miktar_etkisi_tl'].fillna(period_df['degisim_tl'])
    period_df = period_df.sort_values('agirlik_pct', ascending=False, na_position='last')
    period_df['Hisse'] = period_df['ticker'] + period_df['uyruk'].apply(lambda u: '' if u == 'TC' else f" ({u})")

    aum = _get_fund_aum(fon_kodu, yil, ay)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Pozisyon Sayısı", len(period_df))
    with m2:
        st.metric("Toplam Ağırlık (Hisse)", f"{period_df['agirlik_pct'].sum():.1f}%")
    with m3:
        giris = aum['katilma_payi_giris_tl'] if aum is not None else None
        st.metric("Katılma Payı Girişi", _fmt_tl(giris) if pd.notna(giris) else "—")
    with m4:
        cikis = aum['katilma_payi_cikis_tl'] if aum is not None else None
        st.metric("Katılma Payı Çıkışı", _fmt_tl(cikis) if pd.notna(cikis) else "—")

    if period_df['miktar_etkisi_tl'].isna().all():
        st.caption("ℹ️ Bu ay için adet verisi yok — 'Bu Ay Değişim' sütunu ham TL değişimidir "
                   "(fiyat hareketini de içerir).")

    st.markdown(f"#### {sel_label} — {TR_MONTHS_SHORT.get(ay, ay)} {yil} pozisyonları")
    show = period_df.copy()
    show['Ağırlık'] = show['agirlik_pct'].apply(lambda v: f"{v:.2f}%" if pd.notna(v) else "-")
    show['TL Tutar'] = show['toplam_tutar_tl'].apply(_fmt_tl)
    show['Ağırlık Değişimi'] = show['degisim_agirlik_pct'].apply(lambda v: f"{v:+.2f}pp" if pd.notna(v) else "-")
    show['Toplam Değişim (TL)'] = show['degisim_tl'].apply(_fmt_tl_signed)
    show['Fiyat Etkisi (TL)'] = show['fiyat_etkisi_tl'].apply(_fmt_tl_signed)
    show['Miktar Etkisi / Gerçek Al-Sat (TL)'] = show['miktar_etkisi_tl'].apply(_fmt_tl_signed)
    show['Adet Değişimi'] = show['degisim_nominal'].apply(_fmt_adet_signed)
    st.caption("💡 **Fiyat Etkisi**: TL değerindeki değişimin sadece fiyat hareketinden gelen kısmı. "
               "**Miktar Etkisi**: fonun o hissede tuttuğu adedin değişmesinden gelen kısım — yani "
               "**gerçek alım/satım sinyali**. **Adet Değişimi**: elde tutulan nominal adedin kendisi "
               "ne kadar değişti (0 ise fon o hissede hiç işlem yapmamış, sadece fiyat hareket etmiş demektir).")
    st.dataframe(show[['Hisse', 'Ağırlık', 'TL Tutar', 'Ağırlık Değişimi', 'Toplam Değişim (TL)',
                        'Fiyat Etkisi (TL)', 'Miktar Etkisi / Gerçek Al-Sat (TL)', 'Adet Değişimi']],
                 use_container_width=True, hide_index=True,
                 height=min(500, 38 * len(show) + 38))

    st.markdown("##### 📊 Değişim Grafiği")
    metric_options = {
        "Miktar Etkisi — Gerçek Alım/Satım (TL)": ('miktar_etkisi_tl', _fmt_tl_signed),
        "Fiyat Etkisi (TL)": ('fiyat_etkisi_tl', _fmt_tl_signed),
        "Adet Değişimi (Nominal)": ('degisim_nominal', _fmt_adet_signed),
        "Ağırlık Değişimi (pp)": ('degisim_agirlik_pct', lambda v: f"{v:+.2f}pp"),
        "Toplam Değişim (TL)": ('degisim_tl', _fmt_tl_signed),
    }
    metric_label = st.selectbox("Grafikte gösterilecek metrik", options=list(metric_options.keys()),
                                 key="fund_drilldown_metric")
    value_col, fmt_func = metric_options[metric_label]
    fig_metric = _signed_bar_chart(
        period_df, value_col, 'Hisse',
        f"{fon_kodu} — {metric_label} ({TR_MONTHS_SHORT.get(ay, ay)} {yil})", fmt_func)
    if fig_metric is None:
        st.info("Bu dönem için bu metrik hesaplanamadı — muhtemelen bu fonun ilk kayıtlı dönemi "
                 "(karşılaştırılacak önceki ay yok) ya da bu ayda adet verisi mevcut değil.")
    else:
        st.plotly_chart(fig_metric, use_container_width=True, config=PLOTLY_CONFIG)

    # Fonun hisse portföyünün TL büyüklüğü zaman içinde
    trend = df.groupby(['yil', 'ay'], as_index=False)['toplam_tutar_tl'].sum()
    trend = trend.sort_values(['yil', 'ay'])
    trend['label'] = trend.apply(lambda r: f"{TR_MONTHS_SHORT.get(int(r['ay']), r['ay'])} {int(r['yil'])}", axis=1)
    fig = go.Figure(go.Scatter(x=trend['label'], y=trend['toplam_tutar_tl'], mode='lines+markers',
                                line=dict(color='#10b981', width=2)))
    fig.update_layout(title=f"{fon_kodu} — Toplam Hisse Portföyü (Zaman İçinde)", height=300,
                       margin=dict(l=10, r=10, t=40, b=10), yaxis_title="TL")
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


def _render_kap_import_section():
    """Yeni ay icin KAP 'Fon Portfoy Dagilim Raporu' PDF'lerini ice aktarma
    paneli - db/import_kap_fund_report.py'daki import_one()'i reuse eder.
    Yil/Ay secimi bir OVERRIDE degil, sadece BEKLENTI kontrolu: her PDF
    kendi donemini kendi basligindan okur (guvenilir, 4 gercek fonda
    dogrulandi) - burada secilen Yil/Ay sadece "yukledigim gercekten bu
    donem miydi" diye kullaniciya gorunur bir uyari vermek icin kullanilir,
    PDF'in kendi soyledigi donem HER ZAMAN esas alinir."""
    with st.expander("📤 Yeni Ay İçin Fon Raporu İçe Aktar (KAP PDF)"):
        st.caption("KAP'tan indirdiğin (veya şirketin sunduğu) 'Fon Portföy Dağılım Raporu' "
                   "PDF linklerini ya da yerel dosya yollarını yapıştır — her satıra bir tane. "
                   "Sistem her PDF'in kendi başlığından fon kodunu ve dönemi otomatik okur; "
                   "reconciliation (PDF'in kendi yazdığı toplamla karşılaştırma) başarısız "
                   "olursa o rapor GÜVENLİK İÇİN hiç yazılmaz.")

        if _kap_import_one is None:
            st.error(f"İçe aktarma modülü yüklenemedi: {_KAP_IMPORT_ERROR}")
            return

        c1, c2 = st.columns(2)
        with c1:
            exp_yil = st.number_input("Beklenen Yıl", min_value=2015, max_value=2035,
                                       value=datetime.now().year, step=1, key="kap_import_yil")
        with c2:
            exp_ay = st.selectbox("Beklenen Ay", list(range(1, 13)),
                                   format_func=lambda m: TR_MONTHS_SHORT.get(m, m),
                                   index=datetime.now().month - 1, key="kap_import_ay")
        st.caption("↑ Sadece uyarı amaçlı — PDF farklı bir dönem için çıkarsa engellenmez, "
                   "sadece 'beklenenle uyuşmuyor' diye işaretlenir.")

        sources_text = st.text_area(
            "PDF URL'leri veya dosya yolları (satır satır)", height=110,
            key="kap_import_sources",
            placeholder="https://www.kap.org.tr/tr/api/file/download/...\nhttps://www.kap.org.tr/tr/api/file/download/...",
        )

        if st.button("📥 İçe Aktar", use_container_width=True):
            sources = [s.strip() for s in sources_text.splitlines() if s.strip()]
            if not sources:
                st.warning("En az bir URL veya dosya yolu girin.")
                return

            conn = _get_live_connection()
            if conn is None:
                st.error("Veritabanı bağlantısı yok — içe aktarılamadı.")
                return

            results = []
            prog = st.progress(0)
            for i, src in enumerate(sources):
                try:
                    ok, detay, meta = _kap_import_one(conn, src)
                except Exception as e:
                    ok, detay, meta = False, str(e), {}
                results.append((src, ok, detay, meta))
                prog.progress((i + 1) / len(sources))
            prog.empty()

            n_ok = sum(1 for _, ok, _, _ in results if ok)
            (st.success if n_ok == len(results) else st.warning)(
                f"{n_ok}/{len(results)} rapor başarıyla içe aktarıldı."
            )

            for src, ok, detay, meta in results:
                fon_kodu = meta.get('fon_kodu') or '?'
                donem_str = (f"{TR_MONTHS_SHORT.get(meta.get('ay'), meta.get('ay'))} {meta.get('yil')}"
                             if meta.get('yil') and meta.get('ay') else 'dönem okunamadı')
                mismatch = (meta.get('yil') and meta.get('ay')
                            and (int(meta['yil']) != int(exp_yil) or int(meta['ay']) != int(exp_ay)))
                icon = "✅" if ok else "⚠️"
                title = f"{icon} {fon_kodu} — {donem_str}"
                if mismatch:
                    title += f" (BEKLENEN {TR_MONTHS_SHORT.get(exp_ay, exp_ay)} {exp_yil} İLE UYUŞMUYOR!)"
                with st.expander(title):
                    st.caption(src)
                    st.write(detay)

            # Yeni veri hemen gorunsun diye ilgili cache'leri temizle.
            _get_available_periods.clear()
            get_latest_fund_flow_map.clear()
            _get_flow_ranking.clear()
            _get_stock_list.clear()


def display_funds_analysis():
    st.markdown("### 💰 Fund Flow Analysis")
    st.caption("Aylık fon portföy değişimleri — KAP 'Portföy Dağılım Raporu' verisine dayanır. "
               "Yatırım tavsiyesi değildir.")

    conn = _get_live_connection()
    if conn is None:
        st.error("Veritabanı bağlantısı kurulamadı — DATABASE_URL secrets/environment "
                  "değişkeni eksik olabilir.")
        return

    _render_kap_import_section()

    periods = _get_available_periods()
    if not periods:
        st.warning("Henüz fon verisi yüklenmemiş — yukarıdaki 'Yeni Ay İçin Fon Raporu İçe "
                   "Aktar' bölümünden başlayabilirsin.")
        return

    pc1, pc2 = st.columns([2, 1])
    with pc1:
        yil, ay = _period_selector(periods, key="main_period")
    with pc2:
        scope_label = st.radio("Kapsam", ["🌍 Tümü", "🇹🇷 Yerli (TR)", "🌎 Yabancı (FOR)"],
                                horizontal=True, key="uyruk_filter")
    uyruk_filter = {"🌍 Tümü": None, "🇹🇷 Yerli (TR)": "TC", "🌎 Yabancı (FOR)": "FOR"}[scope_label]

    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 En Çok Alınan / Satılan",
        "🎯 Piyasa Değerine Göre Etki",
        "🔍 Hisse Bazlı Fon Takibi",
        "🏦 Fon Bazlı Pozisyonlar",
    ])
    with tab1:
        _render_top_buys_sells(yil, ay, uyruk_filter)
    with tab2:
        if uyruk_filter == 'FOR':
            st.info("Piyasa değeri sadece BIST (yerli) hisseleri için hesaplanabiliyor "
                    "(borsapy kaynaklı) — 'Yabancı (FOR)' kapsamında gösterilecek bir şey yok.")
        else:
            _render_market_impact(yil, ay)
    with tab3:
        _render_stock_drilldown(uyruk_filter)
    with tab4:
        _render_fund_drilldown()
