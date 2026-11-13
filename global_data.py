"""🌎 Yabancı (ve genel) hisse verisi - yfinance katmanı.

borsapy yalnızca BIST/TradingView-TR sembollerini bilir; yabancı hisseler (fon portföylerindeki
`uyruk='FOR'` kalemleri) için fiyat, temel veri, haber ve analist görüşü yfinance'tan alınır.

Sembol kimliği (uygulama içinde):
  * BIST hissesi      -> "THYAO"            (eskisi gibi, borsapy)
  * Yabancı hisse     -> "FOR:AAPL"         (önek + Yahoo sembolü, yfinance)
Böylece iki piyasadaki aynı kodlu hisseler çakışmaz ve `fetch_stock_data` / `compute_stock_valuations`
gibi tek giriş noktaları öneke bakıp doğru kaynağa yönlendirir.

Bu modül veri döndürür; Streamlit arayüzü (`scope_selector` dışında) içermez.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import streamlit as st

try:
    import yfinance as yf
except Exception:  # yfinance kurulu değilse uygulama çökmesin; yabancı özellikler devre dışı kalır
    yf = None

FOR_PREFIX = "FOR:"
SCOPE_OPTIONS = {"🌍 Tümü": "ALL", "🇹🇷 Yerli (TR)": "TR", "🌎 Yabancı (FOR)": "FOR"}
_MAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "foreign_symbol_map.json")

# Bloomberg borsa son eki (fon raporlarındaki "SMSN LI" biçimi) -> Yahoo son eki
BBG_SUFFIX = {
    "US": "", "UN": "", "UW": "", "UQ": "", "UA": "", "UR": "", "UF": "",
    "LN": ".L", "LI": ".IL", "GY": ".DE", "GR": ".DE", "FP": ".PA", "NA": ".AS", "IM": ".MI", "SM": ".MC",
    "SW": ".SW", "SS": ".ST", "DC": ".CO", "NO": ".OL", "FH": ".HE", "BB": ".BR", "PL": ".LS", "AV": ".VI",
    "ID": ".IR", "HK": ".HK", "JT": ".T", "KS": ".KS", "KQ": ".KQ", "TT": ".TW", "AU": ".AX", "CN": ".TO",
    "CT": ".TO", "IN": ".NS", "SJ": ".JO", "BZ": ".SA", "MM": ".MX", "SP": ".SI",
}
CCY_SYMBOL = {"TRY": "₺", "USD": "$", "EUR": "€", "GBP": "£", "GBp": "GBp ", "JPY": "¥", "CHF": "CHF ", "HKD": "HK$",
              "CAD": "C$", "AUD": "A$", "KRW": "₩", "CNY": "¥", "SEK": "kr ", "DKK": "kr ", "NOK": "kr "}


# ───────────────────────── sembol kimliği ─────────────────────────

def is_foreign(symbol) -> bool:
    return isinstance(symbol, str) and symbol.startswith(FOR_PREFIX)


def yahoo_of(symbol: str) -> str:
    """Uygulama sembolünden Yahoo sembolü: 'FOR:AAPL' -> 'AAPL'; BIST 'THYAO' -> 'THYAO.IS'."""
    return symbol[len(FOR_PREFIX):] if is_foreign(symbol) else f"{symbol}.IS"


def display_symbol(symbol: str) -> str:
    return (symbol[len(FOR_PREFIX):] + " 🌎") if is_foreign(symbol) else symbol


def ccy_symbol(ccy) -> str:
    return CCY_SYMBOL.get(ccy or "TRY", f"{ccy} ")


def _load_map() -> dict:
    try:
        with open(_MAP_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def yahoo_symbol_for(ticker: str, isin: str | None = None, symbol_map: dict | None = None) -> str | None:
    """DB'deki (fon raporu) yabancı hisse kodundan Yahoo sembolü. Önce önceden çözülmüş harita
    (ISIN / ham kod), sonra Bloomberg son eki kuralı, sonra ABD ISIN'li düz kod. Çözülemezse None."""
    m = symbol_map if symbol_map is not None else _load_map()
    t = (ticker or "").strip()
    isin = isin.strip() if isinstance(isin, str) and isin.strip() else None      # NaN/None -> None
    if isin and isin in m:
        return m[isin] or None
    if t in m:
        return m[t] or None
    mt = re.match(r"^(.+?)\s+([A-Z]{2})$", t)
    if mt:
        base, suf = mt.group(1), mt.group(2)
        if suf in BBG_SUFFIX:
            if suf == "HK" and base.isdigit():
                base = base.zfill(4)
            base = re.sub(r"-(OQ|O|N|UN|UW)$", "", base)          # 'ALAB-O US' gibi
            base = m.get(base, base) if BBG_SUFFIX[suf] == "" else base      # takma ad (BRKB -> BRK-B)
            return base.replace("/", "-") + BBG_SUFFIX[suf]
        return None
    if isin and not isin.startswith("US"):
        return None            # ABD dışı ISIN: haritada yoksa tahmin etmiyoruz
    t = re.sub(r"-(OQ|O|N|UN|UW)$", "", t)           # 'ALAB-O' gibi borsa ekleri
    t = m.get(t, t) if isinstance(m.get(t, t), str) else t
    if not re.match(r"^[A-Za-z][A-Za-z0-9./-]{0,9}$", t):
        return None
    return t.replace("/", "-").replace(".", "-")


@st.cache_data(ttl=1800, show_spinner=False)
def foreign_universe() -> pd.DataFrame:
    """Fon portföylerinde bulunan yabancı HİSSELER: kolonlar symbol ('FOR:AAPL'), yahoo, ticker_db, n_fon,
    toplam_tutar (son dönem, TL; yoksa NaN). Aynı Yahoo sembolüne giden kayıtlar birleştirilir; n_fon'a göre
    azalan sıralı. DB yoksa boş DataFrame."""
    cols = ["symbol", "yahoo", "ticker_db", "n_fon"]
    try:
        from fon_analiz import _get_live_connection
        conn = _get_live_connection()
    except Exception:
        conn = None
    if conn is None:
        return pd.DataFrame(columns=cols)
    try:
        raw = pd.read_sql("""
            SELECT s.ticker, s.isin, COUNT(DISTINCT fh.fon_kodu) AS n_fon
            FROM securities s JOIN fund_holdings fh ON fh.security_id = s.id
            WHERE s.uyruk = 'FOR' AND s.varlik_sinifi = 'HISSE_SENEDI'
            GROUP BY s.ticker, s.isin""", conn)
    except Exception:
        return pd.DataFrame(columns=cols)
    m = _load_map()
    dead = set(m.get("_dead", []))                  # satın alınmış / işlemden kalkmış (doğrulanmış)
    rows = {}
    for r in raw.itertuples():
        y = yahoo_symbol_for(r.ticker, r.isin, m)
        if not y or y in dead:
            continue
        cur = rows.setdefault(y, {"symbol": FOR_PREFIX + y, "yahoo": y, "ticker_db": r.ticker, "n_fon": 0})
        cur["n_fon"] = max(cur["n_fon"], int(r.n_fon))        # aynı hissenin farklı gösterimlerinde en yüksek
        if len(r.ticker) < len(cur["ticker_db"]) and " " not in r.ticker:
            cur["ticker_db"] = r.ticker
    df = pd.DataFrame(list(rows.values()), columns=cols)
    return df.sort_values(["n_fon", "yahoo"], ascending=[False, True]).reset_index(drop=True)


def foreign_symbols(top_n: int | None = None) -> list:
    df = foreign_universe()
    syms = df["symbol"].tolist()
    return syms[:top_n] if top_n else syms


def foreign_label(symbol: str) -> str:
    """Seçim kutusu etiketi: 'AAPL · 8 fon'."""
    df = foreign_universe()
    hit = df[df["symbol"] == symbol]
    n = int(hit["n_fon"].iloc[0]) if len(hit) else 0
    return f"{yahoo_of(symbol)} · {n} fon" if n else yahoo_of(symbol)


def foreign_fund_flow_map() -> dict:
    """{'FOR:AAPL': net fon alım/satım TL} - fon_analiz.get_latest_fund_flow_map('FOR') çıktısı Yahoo
    sembollerine çevrilir."""
    try:
        from fon_analiz import get_latest_fund_flow_map
        flows = get_latest_fund_flow_map("FOR")
    except Exception:
        return {}
    df = foreign_universe()
    if df.empty or not flows:
        return {}
    out = {}
    for r in df.itertuples():
        v = flows.get(r.ticker_db)
        if v is not None:
            out[r.symbol] = v
    return out


# ───────────────────────── kapsam seçici (tüm sekmeler) ─────────────────────────

def scope_selector(page: str, default: str = "TR") -> str:
    """Her sekmenin başındaki aynı üç seçenek: Tümü / Yerli (TR) / Yabancı (FOR). Seçim sekmeler arasında
    hatırlanır (kullanıcı bir kez değiştirdikten sonra). Dönüş: 'ALL' | 'TR' | 'FOR'."""
    labels = list(SCOPE_OPTIONS)
    pref = st.session_state.get("_scope_pref") or default
    idx = [SCOPE_OPTIONS[l] for l in labels].index(pref)
    label = st.radio("Kapsam", labels, index=idx, horizontal=True, key=f"scope_{page}")
    scope = SCOPE_OPTIONS[label]
    if scope != st.session_state.get("_scope_pref"):
        st.session_state["_scope_pref"] = scope
    return scope


# ───────────────────────── fiyat verisi ─────────────────────────

_YF_INTERVAL = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "4h": "60m", "1d": "1d",
                "1wk": "1wk"}


def _retry(fn, tries=3, wait=2.0):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:                     # YFRateLimitError dahil
            last = e
            if i < tries - 1:
                time.sleep(wait * (i + 1))
    raise last


def fetch_history(symbol: str, start_date: str, end_date: str | None = None, interval: str = "1d"):
    """Yabancı hisse OHLCV (bölünme düzeltmeli, temettüsüz kapanış). Kolonlar Open High Low Close Volume;
    günlük/haftalık veride tz'siz DatetimeIndex. Veri yoksa None. 'FOR:' öneki ya da çıplak Yahoo sembolü."""
    if yf is None:
        return None
    ysym = symbol[len(FOR_PREFIX):] if is_foreign(symbol) else symbol      # çıplak Yahoo sembolü de olur
    iv = _YF_INTERVAL.get(interval, "1d")
    end = (pd.Timestamp(end_date) if end_date else pd.Timestamp(date.today())) + pd.Timedelta(days=1)
    try:
        df = _retry(lambda: yf.Ticker(ysym).history(start=start_date, end=end.strftime("%Y-%m-%d"), interval=iv,
                                                    auto_adjust=False, actions=False))
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)                # borsa saatiyle duvar saati
    df.index = idx
    if interval in ("1d", "1wk"):
        df.index = df.index.normalize()
    if interval == "4h":
        df = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last",
                                    "Volume": "sum"}).dropna(subset=["Close"])
    return df if len(df) else None


@st.cache_data(ttl=3600, show_spinner=False)
def currency_of(symbol: str) -> str:
    """İşlem para birimi (USD, EUR, GBp, JPY...). Alınamazsa 'USD'."""
    if yf is None:
        return "USD"
    ysym = symbol[len(FOR_PREFIX):] if is_foreign(symbol) else symbol
    try:
        c = _retry(lambda: yf.Ticker(ysym).fast_info["currency"], tries=2)
        return str(c) if c else "USD"
    except Exception:
        return "USD"


@st.cache_data(ttl=3600, show_spinner=False)
def fx_series_to_try(ccy: str, start_date: str) -> pd.Series | None:
    """1 birim ccy = kaç TL (günlük, tz'siz, ileri doldurulmuş). TRY için None (çevirme yok)."""
    if yf is None or ccy in (None, "TRY"):
        return None
    base = {"GBp": "GBP", "GBX": "GBP"}.get(ccy, ccy)
    pair = "TRY=X" if base == "USD" else f"{base}TRY=X"
    try:
        h = _retry(lambda: yf.Ticker(pair).history(start=start_date, interval="1d", auto_adjust=False))
    except Exception:
        return None
    if h is None or h.empty:
        return None
    s = h["Close"].astype(float)
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s = pd.Series(s.values, index=idx.normalize())
    s = s[~s.index.duplicated(keep="last")]
    if ccy in ("GBp", "GBX"):
        s = s / 100.0                                # peni -> sterlin (fiyat 100'e bölünmez, kur 1/100 alınır)
    return s


def to_try(df: pd.DataFrame, ccy: str, start_date: str) -> pd.DataFrame | None:
    """OHLC kolonlarını TL'ye çevirir (işlem günündeki kurla). Kur alınamazsa None (karma para birimi
    portföyü bozmasın diye sessizce yerel fiyat döndürmüyoruz)."""
    if df is None or ccy in (None, "TRY"):
        return df
    fx = fx_series_to_try(ccy, (pd.Timestamp(start_date) - pd.Timedelta(days=10)).strftime("%Y-%m-%d"))
    if fx is None or fx.empty:
        return None
    k = fx.reindex(df.index.normalize().union(fx.index)).ffill().reindex(df.index.normalize()).values
    out = df.copy()
    for c in ("Open", "High", "Low", "Close"):
        out[c] = out[c].values * k
    return out.dropna(subset=["Close"])


# ───────────────────────── temel veri / değerleme ─────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def get_info(yahoo_sym: str) -> dict:
    """yfinance .info (boş sözlük: bulunamadı / hata)."""
    if yf is None:
        return {}
    try:
        info = _retry(lambda: yf.Ticker(yahoo_sym).info, tries=2)
        return dict(info) if isinstance(info, dict) else {}
    except Exception:
        return {}


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def valuations_from_info(info: dict, price=None) -> dict:
    """compute_stock_valuations ile aynı anahtarlar (pe, pb, ev_ebitda, fwd_pe, fwd_pb, fwd_ev_ebitda,
    *_delta, market_cap, ev, shares, roe) + ccy ve analist alanları. Yahoo ileri FD/FAVÖK vermediği için
    fwd_ev_ebitda None kalır; ileri PD/DD yok -> güncel PD/DD (BIST tarafındaki yedekle aynı)."""
    if not info:
        return {}
    r = {}
    pe, fpe = _f(info.get("trailingPE")), _f(info.get("forwardPE"))
    pb, eve = _f(info.get("priceToBook")), _f(info.get("enterpriseToEbitda"))
    if pe is not None and 0 < pe < 1000:
        r["pe"] = round(pe, 2)
    if fpe is not None and 0 < fpe < 1000:
        r["fwd_pe"] = round(fpe, 2)
    if pb is not None and pb > 0:
        r["pb"] = round(pb, 2)
        r["fwd_pb"] = round(pb, 2)
    if eve is not None and 0 < eve < 500:
        r["ev_ebitda"] = round(eve, 2)
    r["market_cap"] = _f(info.get("marketCap"))
    r["ev"] = _f(info.get("enterpriseValue"))
    r["shares"] = _f(info.get("sharesOutstanding"))
    roe = _f(info.get("returnOnEquity"))
    if roe is not None:
        r["roe"] = roe
    if r.get("pe") and r.get("fwd_pe"):
        r["pe_delta"] = round(r["pe"] - r["fwd_pe"], 2)
    if r.get("ev_ebitda") and r.get("fwd_ev_ebitda"):
        r["ev_ebitda_delta"] = round(r["ev_ebitda"] - r["fwd_ev_ebitda"], 2)
    r["ccy"] = info.get("currency") or info.get("financialCurrency")
    for k_src, k_dst in (("targetMeanPrice", "target_mean"), ("targetHighPrice", "target_high"),
                         ("targetLowPrice", "target_low"), ("recommendationMean", "rec_mean"),
                         ("numberOfAnalystOpinions", "n_analyst")):
        v = _f(info.get(k_src))
        if v is not None:
            r[k_dst] = v
    r["rec_key"] = info.get("recommendationKey")
    r["sector"] = info.get("sector")
    r["industry"] = info.get("industry")
    return r


def foreign_valuations(symbol: str, price=None) -> dict:
    return valuations_from_info(get_info(symbol[len(FOR_PREFIX):] if is_foreign(symbol) else symbol), price)


# ───────────────────────── profil / haber / analist (Single Stock alt bölümü) ─────────────────────────

def _news_items(raw) -> list:
    """yfinance .news (yeni 'content' biçimi ya da eski düz biçim) -> [{title, summary, publisher, date, url}]."""
    out = []
    for it in raw or []:
        c = it.get("content") if isinstance(it, dict) and isinstance(it.get("content"), dict) else it
        if not isinstance(c, dict):
            continue
        title = c.get("title")
        if not title:
            continue
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
               or c.get("link") or "")
        prov = c.get("provider")
        publisher = (prov.get("displayName") if isinstance(prov, dict) else None) or c.get("publisher") or ""
        when = c.get("pubDate") or c.get("displayTime")
        if when is None and c.get("providerPublishTime"):
            when = datetime.utcfromtimestamp(c["providerPublishTime"]).isoformat()
        out.append({"title": str(title), "summary": c.get("summary") or c.get("description") or "",
                    "publisher": publisher, "date": str(when or "")[:16].replace("T", " "), "url": url})
    return out


@st.cache_data(ttl=900, show_spinner=False)
def get_profile(yahoo_sym: str) -> dict:
    """Şirket profili + haberler + analist verisi (her parça bağımsız; alınamayan None/boş):
    info, news [..], rec_summary (DataFrame: period/strongBuy/buy/hold/sell/strongSell), targets
    ({current, high, low, mean, median}), upgrades (DataFrame: Firm, ToGrade, FromGrade, Action,
    currentPriceTarget, priorPriceTarget)."""
    out = {"info": {}, "news": [], "rec_summary": None, "targets": None, "upgrades": None}
    if yf is None:
        return out
    t = yf.Ticker(yahoo_sym)

    def safe(fn):
        try:
            return _retry(fn, tries=2, wait=1.0)
        except Exception:
            return None

    info = safe(lambda: t.info)
    out["info"] = dict(info) if isinstance(info, dict) else {}
    out["news"] = _news_items(safe(lambda: t.news))
    rs = safe(lambda: t.recommendations_summary)
    out["rec_summary"] = rs if isinstance(rs, pd.DataFrame) and not rs.empty else None
    pt = safe(lambda: t.analyst_price_targets)
    if isinstance(pt, dict) and any(_f(v) is not None for v in pt.values()):
        out["targets"] = {k: _f(v) for k, v in pt.items()}
    ud = safe(lambda: t.upgrades_downgrades)
    if isinstance(ud, pd.DataFrame) and not ud.empty:
        out["upgrades"] = ud.head(15).reset_index()
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def get_quarterly_income(yahoo_sym: str) -> pd.DataFrame | None:
    """Çeyreklik gelir tablosundan Total Revenue / Net Income / EBITDA / Operating Income (en yeni solda)."""
    if yf is None:
        return None
    try:
        q = _retry(lambda: yf.Ticker(yahoo_sym).quarterly_income_stmt, tries=2, wait=1.0)
    except Exception:
        return None
    if q is None or q.empty:
        return None
    rows = [r for r in ("Total Revenue", "Gross Profit", "Operating Income", "EBITDA", "Net Income") if r in q.index]
    return q.loc[rows] if rows else None
