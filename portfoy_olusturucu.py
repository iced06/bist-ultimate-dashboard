"""📐 Portföy Çalışma Alanı (Streamlit arayüzü).

Akış: Company Reports'taki sektör skorlarına göre sıralı sektörlerden hisse seç ->
sepete düşer -> portföy kutusu risk bazlı ağırlıkları, metrikleri ve sağlık skorunu
canlı hesaplar -> altta ayrıntılı değerlendirme. Analitik mantık portfolio_analytics.py'de.
"""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.colors as pcolors
import plotly.graph_objects as go
import streamlit as st

import portfolio_analytics as pa
import portfolio_valuation as pv
import portfoy_store as store
from sirket_raporlari import (
    DONEM_LABELS,
    get_available_periods_for_rollup,
    get_reports_for_period,
    get_sector_rollup,
)

UNASSIGNED = "Sektörü atanmamış"
LOOKBACKS = {"6 ay": 126, "1 yıl": 252, "2 yıl": 504}
LEVEL_ICON = {"ok": "✅", "info": "ℹ️", "warn": "⚠️", "bad": "🔴"}
PLOTLY_CFG = {"displaylogo": False}


# ───────────────────────── veri yükleyiciler ─────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _load_close_prices(tickers: tuple, start_date: str, _fetch_fn):
    """tickers için kapanış fiyatı matrisi (date x ticker) + çekilemeyenler."""
    def one(t):
        try:
            df = _fetch_fn(t, start_date=start_date, interval="1d")
        except Exception:
            return t, None
        if df is None or df.empty or "Close" not in df.columns:
            return t, None
        s = df["Close"].astype(float)
        idx = pd.to_datetime(s.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        s = pd.Series(s.values, index=idx.normalize())
        return t, s[~s.index.duplicated(keep="last")]

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(one, tickers))
    ok = {t: s for t, s in results if s is not None}
    failed = [t for t, s in results if s is None]
    return (pd.DataFrame(ok).sort_index() if ok else pd.DataFrame()), failed


@st.cache_data(ttl=3600, show_spinner=False)
def _default_rf():
    """TR 2 yıllık tahvil faizi (yıllık, ondalık) - alınamazsa None."""
    try:
        import borsapy as bp
        y = float(bp.Bond("2Y").yield_rate)
        if 5 < y < 120:
            return y / 100.0
    except Exception:
        pass
    return None


def _to_calendar(prices: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Fiyatları ortak işlem takvimine oturtur (eksik günler ileri doldurulur)."""
    full = prices.index.union(cal)
    return prices.reindex(full).ffill().reindex(cal)


def _do_update():
    """🔄 Güncelle: Company Reports ve fiyat önbelleklerini temizler."""
    for fn in (get_reports_for_period, get_sector_rollup, get_available_periods_for_rollup,
               _load_close_prices, _default_rf, _saved_portfolios):
        fn.clear()
    st.session_state["pf_update_requested"] = True


# ───────────────────────── kayıtlı (sabit) portföy ─────────────────────────

PLACEHOLDER = "— kayıtlı portföy seç —"
SETTING_KEYS = ("pf_method", "pf_lookback", "pf_maxw", "pf_tilt", "pf_mom_tilt", "pf_wsource")


@st.cache_data(ttl=120, show_spinner=False)
def _saved_portfolios():
    """(ok, [portföyler] | hata). Yazma işlemlerinden ve 🔄 Güncelle'den sonra temizlenir."""
    return store.list_portfolios()


def _valid_setting(key, v):
    if key == "pf_method":
        return v in pa.METHODS
    if key == "pf_lookback":
        return v in LOOKBACKS
    if key == "pf_maxw":
        return isinstance(v, (int, float)) and 10 <= v <= 100
    if key == "pf_tilt":
        return isinstance(v, (int, float)) and 0 <= v <= 4
    if key == "pf_mom_tilt":
        return isinstance(v, (int, float)) and 0 <= v <= 3
    if key == "pf_wsource":
        return v in ("Optimizasyon", "Elle")
    return False


def _current_settings() -> dict:
    """Ağırlık ayarları (widget'ların o anki değerleri); henüz çizilmemiş olanlar atlanır."""
    ss = st.session_state
    return {k: ss[k] for k in SETTING_KEYS if k in ss and _valid_setting(k, ss[k])}


def _snapshot(tickers, settings) -> dict:
    return {"tickers": sorted(set(tickers)), "settings": dict(settings)}


def _msg(kind, text):
    st.session_state["pf_store_msg"] = (kind, text)


def _apply_portfolio(p):
    """Kayıtlı portföyü sepete ve ayarlara yükler (widget'lar çizilmeden önce çağrılmalı:
    callback içinde ya da sayfa başında)."""
    ss = st.session_state
    ss["pf_basket"] = list(p["tickers"])
    _bump()
    for k, v in (p.get("settings") or {}).items():
        if k in SETTING_KEYS and _valid_setting(k, v):
            ss[k] = v
    ss["pf_active"] = p["name"]
    ss["pf_saved_sel"] = p["name"]
    ss["pf_snapshot"] = _snapshot(p["tickers"], p.get("settings") or {})


def _find_saved(name):
    ok, rows = _saved_portfolios()
    return next((r for r in rows if r["name"] == name), None) if ok else None


def _on_pick():
    name = st.session_state.get("pf_saved_sel")
    if name == PLACEHOLDER:
        st.session_state["pf_active"] = None
        st.session_state.pop("pf_snapshot", None)
        return
    p = _find_saved(name)
    if p:
        _apply_portfolio(p)
        _msg("ok", f"'{name}' yüklendi ({len(p['tickers'])} hisse).")


def _save_active():
    ss = st.session_state
    name, tickers, sett = ss.get("pf_active"), list(_basket()), _current_settings()
    ok, res = store.save_portfolio(name, tickers, sett, overwrite=True)
    if ok:
        ss["pf_snapshot"] = _snapshot(tickers, sett)
        _saved_portfolios.clear()
        _msg("ok", f"'{name}' güncellendi ({len(tickers)} hisse).")
    else:
        _msg("err", res)


def _save_as():
    ss = st.session_state
    name, tickers, sett = ss.get("pf_save_name", ""), list(_basket()), _current_settings()
    ok, res = store.save_portfolio(name, tickers, sett, overwrite=False)
    if ok:
        ss["pf_active"], ss["pf_saved_sel"] = res, res
        ss["pf_snapshot"] = _snapshot(tickers, sett)
        ss["pf_save_name"] = ""
        _saved_portfolios.clear()
        _msg("ok", f"'{res}' kaydedildi ({len(tickers)} hisse).")
    else:
        _msg("err", res)


def _ask_delete(flag):
    st.session_state["pf_confirm_del"] = flag


def _delete_active():
    ss = st.session_state
    name = ss.get("pf_active")
    ok, res = store.delete_portfolio(name)
    ss["pf_confirm_del"] = False
    if ok:
        ss["pf_active"], ss["pf_saved_sel"] = None, PLACEHOLDER
        ss.pop("pf_snapshot", None)
        _saved_portfolios.clear()
        _msg("ok", f"'{name}' silindi. Sepet olduğu gibi duruyor.")
    else:
        _msg("err", res)


def _toggle_default():
    ss = st.session_state
    ok, res = store.set_default(ss.get("pf_active") if ss.get("pf_is_default") else None)
    _saved_portfolios.clear()
    if not ok:
        _msg("err", res)


def _autoload_default():
    """Oturumun ilk çalışmasında, sepet boşsa varsayılan kayıtlı portföyü yükler."""
    ss = st.session_state
    if ss.get("pf_autoloaded"):
        return
    ss["pf_autoloaded"] = True
    if ss.get("pf_basket"):
        return
    ok, rows = _saved_portfolios()
    d = next((r for r in rows if r["is_default"]), None) if ok else None
    if d:
        _apply_portfolio(d)
        _msg("ok", f"Varsayılan portföy yüklendi: '{d['name']}' ({len(d['tickers'])} hisse).")


def _render_saved_portfolio():
    """Sağ sütundaki kayıtlı portföy kontrolleri: seç/yükle, güncelle, farklı kaydet, sil."""
    ss = st.session_state
    st.markdown("#### 💾 Kayıtlı portföy")
    if ss.get("pf_store_msg"):
        kind, text = ss.pop("pf_store_msg")
        (st.success if kind == "ok" else st.error)(text)
    ok, rows = _saved_portfolios()
    if not ok:
        st.caption("⚠️ Kayıtlı portföyler kullanılamıyor: " + str(rows))
        return
    names = [r["name"] for r in rows]
    active = ss.get("pf_active")
    if active not in names:
        active = ss["pf_active"] = None
    if ss.get("pf_saved_sel") not in [PLACEHOLDER] + names:
        ss["pf_saved_sel"] = active or PLACEHOLDER
    st.selectbox("Portföy", [PLACEHOLDER] + names, key="pf_saved_sel", on_change=_on_pick,
                 label_visibility="collapsed")
    basket = list(_basket())
    if active:
        saved = _find_saved(active)
        snap = ss.get("pf_snapshot") or _snapshot(saved["tickers"], saved["settings"])
        added = [t for t in basket if t not in snap["tickers"]]
        removed = [t for t in snap["tickers"] if t not in basket]
        cur = _current_settings()
        changed_settings = [k for k in cur if k in snap["settings"] and cur[k] != snap["settings"][k]]
        dirty = bool(added or removed or changed_settings)
        if dirty:
            bits = ([f"➕ {', '.join(added)}"] if added else []) + \
                   ([f"➖ {', '.join(removed)}"] if removed else [])
            if changed_settings:
                bits.append("⚙️ ayarlar")
            st.caption("● Kaydedilmemiş değişiklik: " + " · ".join(bits))
        else:
            st.caption(f"✅ **{active}** güncel ({len(basket)} hisse).")
        st.button("💾 Güncelle", key="pf_save_btn", on_click=_save_active,
                  disabled=not dirty or not basket, type="primary" if dirty else "secondary",
                  use_container_width=True)
        ss["pf_is_default"] = bool(saved and saved["is_default"])
        st.checkbox("⭐ Açılışta bu portföy gelsin", key="pf_is_default", on_change=_toggle_default)
        if ss.get("pf_autosave") and dirty and basket:
            _save_active()
            st.rerun()
    with st.expander("➕ Farklı kaydet / ⚙️ yönet"):
        st.text_input("Yeni portföy adı", key="pf_save_name", max_chars=store.NAME_MAX,
                      placeholder="örn. Çekirdek portföy")
        st.button("➕ Sepeti bu adla kaydet", key="pf_saveas_btn", on_click=_save_as,
                  disabled=not basket or not ss.get("pf_save_name", "").strip(),
                  use_container_width=True)
        if active:
            st.toggle("Değişiklikleri otomatik kaydet", key="pf_autosave",
                      help="Açıkken sepete hisse ekleyip çıkardığında aktif portföy kendiliğinden "
                           "güncellenir.")
            if not ss.get("pf_confirm_del"):
                st.button("🗑️ Bu portföyü sil", key="pf_del_btn", on_click=_ask_delete, args=(True,),
                          use_container_width=True)
            else:
                st.warning(f"'{active}' kalıcı olarak silinecek (sepet etkilenmez).")
                c1, c2 = st.columns(2)
                c1.button("Evet, sil", key="pf_del_yes", on_click=_delete_active, type="primary")
                c2.button("Vazgeç", key="pf_del_no", on_click=_ask_delete, args=(False,))


# ───────────────────────── sepet ─────────────────────────

def _basket() -> list:
    return st.session_state.setdefault("pf_basket", [])


def _bump():
    st.session_state["pf_ver"] = st.session_state.get("pf_ver", 0) + 1


def _add_tickers(ts):
    b = _basket()
    for t in ts:
        if t not in b:
            b.append(t)
    _bump()


def _remove_ticker(t):
    b = _basket()
    if t in b:
        b.remove(t)
    _bump()


def _clear_basket():
    st.session_state["pf_basket"] = []
    _bump()


def _num(v):
    return float(v) if pd.notna(v) else np.nan


# ───────────────────────── sektör seçici ─────────────────────────

def _sector_groups(reports: pd.DataFrame, rollup: pd.DataFrame):
    """[(sektör, sektör_skoru|None, makro_analiz|None, şirketler_df)] - önce sektör
    skoruna göre sıralı rollup sektörleri, sonra analizi henüz hesaplanmamış (yeni)
    sektörler, en sonda sektörü atanmamışlar."""
    reports = reports.copy()
    reports["sektor_g"] = reports["sektor"].fillna(UNASSIGNED)
    score_of, makro_of, groups, seen = {}, {}, [], set()
    if rollup is not None and not rollup.empty:
        for r in rollup.itertuples():
            score_of[r.sektor], makro_of[r.sektor] = r.sektor_skoru, r.makro_analiz
        for s in rollup["sektor"].tolist():
            sub = reports[reports["sektor_g"] == s]
            if len(sub):
                groups.append((s, score_of.get(s), makro_of.get(s), sub))
                seen.add(s)
    rest = [s for s in reports["sektor_g"].unique() if s not in seen]

    def key(s):
        m = reports.loc[reports["sektor_g"] == s, "overall_puani"].mean()
        return (s == UNASSIGNED, -(m if pd.notna(m) else 0.0))

    for s in sorted(rest, key=key):
        groups.append((s, None, None, reports[reports["sektor_g"] == s]))
    return groups


def _render_sector(sektor, skor, makro, df, ver, basket):
    """Bir sektör bölümü; seçili hisselerin listesini döner."""
    skor_str = f"{skor:.1f}/5" if pd.notna(skor) else "analiz bekleniyor"
    with st.expander(f"🏭 {sektor} — Sektör Skoru: {skor_str} ({len(df)} şirket)"):
        if makro:
            st.markdown(makro)
        elif sektor != UNASSIGNED:
            st.caption("Bu sektör için sektör analizi henüz hesaplanmadı — 📄 Company Reports › "
                       "Sektör Analizi › Hesapla / Yenile ile hesaplanır.")
        df = df.sort_values("overall_puani", ascending=False, na_position="last")
        key = hashlib.md5(sektor.encode()).hexdigest()[:8]
        top = [t for t in df.sort_values("overall_puani", ascending=False)["ticker"].head(2)]
        st.button("⭐ En iyi 2'yi ekle", key=f"pf_top_{ver}_{key}",
                  on_click=_add_tickers, args=(top,))
        editor_df = pd.DataFrame({
            "Seç": df["ticker"].isin(basket).values,
            "Hisse": df["ticker"].values,
            "Overall": pd.to_numeric(df["overall_puani"]).values,
            "Marj": pd.to_numeric(df["marj_toplam_puani"]).values,
            "Büyüme": pd.to_numeric(df["buyume_puani"]).values,
            "Görünüm": pd.to_numeric(df["gorunum_puani"]).values,
        })
        num = st.column_config.NumberColumn
        edited = st.data_editor(
            editor_df, key=f"pf_ed_{ver}_{key}", hide_index=True, use_container_width=True,
            disabled=["Hisse", "Overall", "Marj", "Büyüme", "Görünüm"],
            column_config={
                "Seç": st.column_config.CheckboxColumn("Seç", width="small"),
                "Overall": num("Overall", format="%.1f"),
                "Marj": num("Marj", format="%.1f"),
                "Büyüme": num("Büyüme", format="%.1f"),
                "Görünüm": num("Görünüm", format="%.1f"),
            },
        )
        return [t for t, s in zip(edited["Hisse"], edited["Seç"]) if s]


STICKY_CSS = """<style>
div[data-testid="stColumn"]:has(#pf-basket-anchor),
div[data-testid="column"]:has(#pf-basket-anchor) {
    position: sticky; top: 3.75rem; align-self: flex-start;
    max-height: calc(100vh - 4.5rem); overflow-y: auto;
}
div[data-testid="stColumn"]:has(#pf-basket-anchor) [data-testid="stVerticalBlock"],
div[data-testid="column"]:has(#pf-basket-anchor) [data-testid="stVerticalBlock"] { gap: 0.35rem; }
div[data-testid="stColumn"]:has(#pf-basket-anchor) button,
div[data-testid="column"]:has(#pf-basket-anchor) button { min-height: 1.7rem; padding: 0.1rem 0.5rem; }
</style>"""


def _render_basket_panel(uni: pd.DataFrame):
    b = _basket()
    st.markdown('<div id="pf-basket-anchor"></div>', unsafe_allow_html=True)
    st.markdown(f"#### 🧺 Portföy sepeti ({len(b)})")
    if not b:
        st.caption("Soldaki sektörlerden hisse seç; seçtiklerin buraya düşer.")
        return
    st.markdown('<a href="#pf-box" target="_self">⬇️ Portföy kutusuna git</a>', unsafe_allow_html=True)
    for t in b:
        sek = uni.loc[t, "sektor"] if t in uni.index and pd.notna(uni.loc[t, "sektor"]) else "—"
        ov = uni.loc[t, "overall_puani"] if t in uni.index else np.nan
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**{t}** · {sek}" + (f" · {ov:.1f}/5" if pd.notna(ov) else
                                          ("" if t in uni.index else " · _bu dönemde rapor yok_")))
        c2.button("✕", key=f"pf_rm_{t}", on_click=_remove_ticker, args=(t,))
    st.button("🗑️ Sepeti temizle", on_click=_clear_basket, use_container_width=True)


# ───────────────────────── portföy kutusu ─────────────────────────

def _fmt(x, f="{:.2f}"):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f.format(x)


def _metric(col, label, value, sub=None):
    col.metric(label, value)
    if sub:
        col.caption(sub)


def _render_settings() -> dict:
    with st.expander("⚙️ Ayarlar", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        method = c1.selectbox("Ağırlık yöntemi", list(pa.METHODS), format_func=pa.METHODS.get,
                              key="pf_method")
        st.session_state.setdefault("pf_lookback", "1 yıl")
        st.session_state.setdefault("pf_maxw", 40)
        lb_label = c2.selectbox("Geriye bakış", list(LOOKBACKS), key="pf_lookback")
        max_w = c3.slider("Hisse başına üst sınır %", 10, 100, step=5, key="pf_maxw") / 100.0
        rf_def = _default_rf()
        rf = c4.number_input("Risksiz faiz % (yıllık)", 0.0, 150.0,
                             round((rf_def or 0.35) * 100, 1), 0.5, key="pf_rf",
                             help="Varsayılan: TR 2 yıllık tahvil faizi (alınamazsa %35). "
                                  "Sharpe/Sortino bu değere çok duyarlıdır.") / 100.0
        tilt, mom_tilt = 2.0, 0.0
        if method == "quality_rp":
            t1, t2 = st.columns(2)
            st.session_state.setdefault("pf_tilt", 2.0)
            st.session_state.setdefault("pf_mom_tilt", 1.0)
            tilt = t1.slider("Kalite eğimi", 0.0, 4.0, step=0.5, key="pf_tilt",
                             help="Risk bütçesi ∝ Overall puanı^eğim. 0 = kalite etkisiz; "
                                  "yüksek değer iyi puanlı hisselere daha çok risk payı verir.")
            mom_tilt = t2.slider("Momentum eğimi", 0.0, 3.0, step=0.5, key="pf_mom_tilt",
                                 help="Geriye bakış penceresindeki getiriye göre (son 1 ay hariç) "
                                      "sıralanır; risk bütçesi ∝ (0.5 + yüzdelik sıra)^eğim. "
                                      "0 = momentum etkisiz. Geçmiş getiri geleceği garanti etmez.")
        source = st.radio("Ağırlık kaynağı", ["Optimizasyon", "Elle"], horizontal=True,
                          key="pf_wsource")
    return dict(method=method, lookback=LOOKBACKS[lb_label], max_w=max_w, rf=rf, source=source,
                tilt=tilt, mom_tilt=mom_tilt)


def _render_manual(tickers) -> dict:
    sig = hashlib.md5("|".join(tickers).encode()).hexdigest()[:8]
    man = st.data_editor(
        pd.DataFrame({"Hisse": tickers, "Ağırlık %": [round(100.0 / len(tickers), 1)] * len(tickers)}),
        key=f"pf_manual_{sig}", hide_index=True, disabled=["Hisse"],
        column_config={"Ağırlık %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0,
                                                                  format="%.1f")})
    vals = man["Ağırlık %"].fillna(0).clip(lower=0).astype(float)
    st.caption(f"Girilen toplam %{vals.sum():.1f} — hesaplamada %100'e normalize edilir.")
    return dict(zip(man["Hisse"], vals))


def _market_window(lookback, fetch_fn):
    start = (date.today() - timedelta(days=int(lookback * 1.6) + 10)).isoformat()
    bench_df, _ = _load_close_prices(("XU100",), start, fetch_fn)
    bench_px = bench_df["XU100"] if "XU100" in bench_df.columns else None
    return start, bench_px


def _analyze(tickers, uni, fetch_fn, s, manual):
    """Seçilen hisselerin tüm analizini yapar. Dönüş: sonuç dict'i ya da
    {'error': mesaj} / {'single': istatistik_df} (hesaplanamayan durumlar)."""
    lookback = s["lookback"]
    with st.spinner("Fiyat verileri yükleniyor..."):
        start, bench_px = _market_window(lookback, fetch_fn)
        prices, failed = _load_close_prices(tuple(sorted(tickers)), start, fetch_fn)
    if prices.empty:
        return {"error": "Seçilen hisselerin hiçbiri için fiyat verisi çekilemedi: " + ", ".join(failed)}
    cal = (bench_px.index if bench_px is not None else prices.index)[-(lookback + 1):]
    returns, dropped = pa.build_returns(_to_calendar(prices, cal),
                                        min_obs=max(60, int(0.75 * lookback)))
    if returns.empty:
        return {"error": "Ortak tarih penceresinde yeterli veri kalmadı: " + "; ".join(
            f"{t}: {r}" for t, r in dropped.items())}
    names = list(returns.columns)
    bench_ret = None
    if bench_px is not None:
        bench_ret = (bench_px / bench_px.shift(1) - 1.0).reindex(returns.index)

    cov_d, shrink = pa.ledoit_wolf_cov(returns.values)
    cov, mu = cov_d * pa.TRADING_DAYS, returns.mean().values * pa.TRADING_DAYS
    stats = pa.per_stock_stats(returns, bench_ret)
    if len(names) < 2:
        one = stats[["cagr", "vol", "max_dd"]] * 100
        one["beta"] = stats["beta"]
        return {"single": one.round(2).rename(columns={
            "cagr": "Yıllık getiri % (bileşik)", "vol": "Volatilite %", "beta": "Beta",
            "max_dd": "Max DD %"})}

    overall_of = {t: (_num(uni.loc[t, "overall_puani"]) if t in uni.index else np.nan) for t in names}
    overall_of = {t: (None if np.isnan(v) else v) for t, v in overall_of.items()}

    if s["source"] == "Elle":
        vals = np.array([(manual or {}).get(t, 0.0) for t in names], dtype=float)
        w = vals / vals.sum() if vals.sum() > 0 else np.full(len(names), 1.0 / len(names))
        opt_note, method_label = None, "Elle girilen ağırlıklar"
    else:
        w, opt_note = pa.optimize_weights(s["method"], mu, cov, s["max_w"], s["rf"],
                                          quality=[overall_of[t] for t in names],
                                          tilt=s.get("tilt", 2.0),
                                          momentum=pa.momentum_scores(returns).reindex(names).values,
                                          mom_tilt=s.get("mom_tilt", 0.0))
        method_label = pa.METHODS[s["method"]]

    pr = pa.portfolio_return_series(w, returns)
    m = pa.portfolio_metrics(pr, bench_ret, s["rf"])
    corr = returns.corr()
    ds = pa.diversification_stats(w, cov, corr)
    rc = pa.risk_contributions(w, cov)
    sector_of = {t: (uni.loc[t, "sektor"] if t in uni.index and pd.notna(uni.loc[t, "sektor"])
                     else UNASSIGNED) for t in names}
    sect_w: dict = {}
    for t, wi in zip(names, w):
        sect_w[sector_of[t]] = sect_w.get(sector_of[t], 0.0) + wi
    has_q = [t for t in names if overall_of[t] is not None]
    quality = (sum(overall_of[t] * w[names.index(t)] for t in has_q) /
               sum(w[names.index(t)] for t in has_q)) if has_q else None
    health = pa.health_score(n=len(names), avg_corr=ds["avg_corr"], eff_n=ds["eff_n"],
                             max_weight=ds["max_weight"], top_sector_share=max(sect_w.values()),
                             vol=m["vol"], max_dd=m["max_dd"], quality=quality)
    return dict(names=names, returns=returns, bench_ret=bench_ret, cov=cov, mu=mu, shrink=shrink,
                w=w, method_label=method_label, opt_note=opt_note, stats=stats, pr=pr, m=m,
                corr=corr, ds=ds, rc=rc, sector_of=sector_of, overall_of=overall_of, health=health,
                dropped=dropped, failed=failed, lookback=lookback, start=start, cal=cal, s=s,
                manual=manual,
                last_price={t: float(prices[t].dropna().iloc[-1]) for t in names
                            if t in prices.columns and prices[t].notna().any()})


def _render_results(a, uni, universe_tickers, fetch_fn, deps=None):
    names, w, rc, m, ds, health = a["names"], a["w"], a["rc"], a["m"], a["ds"], a["health"]
    mu, cov, rf, max_w = a["mu"], a["cov"], a["s"]["rf"], a["s"]["max_w"]
    stats, sector_of, overall_of = a["stats"], a["sector_of"], a["overall_of"]
    bench_ret, pr, returns = a["bench_ret"], a["pr"], a["returns"]
    lookback, start, cal = a["lookback"], a["start"], a["cal"]

    if a["opt_note"]:
        st.info(a["opt_note"])

    # ── özet metrikler ──
    k = st.columns(6)
    _metric(k[0], "Sağlık skoru", f"{health['total']:.0f}/100", health["label"])
    _metric(k[1], "Yıllık volatilite", f"%{m['vol'] * 100:.1f}",
            f"XU100 %{m['bench_vol'] * 100:.1f}" if m.get("bench_vol") else None)
    _metric(k[2], "Beta (XU100)", _fmt(m["beta"]))
    _metric(k[3], "Sharpe", _fmt(m["sharpe"]))
    _metric(k[4], "Max drawdown", f"%{m['max_dd'] * 100:.1f}",
            f"XU100 %{m['bench_max_dd'] * 100:.1f}" if m.get("bench_max_dd") else None)
    _metric(k[5], "Efektif hisse", f"{ds['eff_n']:.1f} / {len(names)}")

    sc = st.columns(len(health["subs"]))
    for col, (name, v) in zip(sc, health["subs"].items()):
        col.metric(f"{name} skoru", "—" if v is None else f"{v:.0f}/100")
    with st.expander("Sağlık skoru nasıl hesaplanıyor?"):
        st.markdown(
            "- **Çeşitlendirme (%30):** ortalama ikili korelasyon (0.25 → 100, 0.85 → 0) ile efektif "
            "hisse sayısı / hisse sayısı oranının ortalaması.\n"
            "- **Yoğunlaşma (%20):** en büyük hisse ağırlığı (%15 → 100, %45 → 0) ile en büyük sektör "
            "payının (%30 → 100, %80 → 0) ortalaması.\n"
            "- **Risk (%25):** yıllık volatilite (%20 → 100, %55 → 0) ile max drawdown (%15 → 100, "
            "%45 → 0) ortalaması.\n"
            "- **Kalite (%25):** ağırlıklı ortalama Overall Puan (1 → 0, 5 → 100). Rapor puanı yoksa "
            "bu boyut hesaba katılmaz, diğerleri yeniden ölçeklenir.\n"
            "- Toplam = ağırlıklı ortalama; ≥75 Sağlam, ≥60 İyi, ≥45 Orta, altı Zayıf.")

    # ── hisse tablosu ──
    # Markowitz (ortalama-varyans) girdileri: beklenen getiri = tarihsel yıllık ortalama getirinin
    # kesit ortalamasına %50 çekilmiş hali (Maks. Sharpe'taki ile aynı); risk ve kovaryans =
    # Ledoit-Wolf shrinkage'lı kovaryans (cov) - ham örneklem volatilitesinden daha kararlı.
    mu_s = 0.5 * mu + 0.5 * mu.mean()
    sig = np.sqrt(np.diag(cov))
    w_gmv = pa.optimize_weights("min_var", mu, cov, max_w, rf)[0]
    w_tan = pa.optimize_weights("max_sharpe", mu, cov, max_w, rf)[0]
    table = pd.DataFrame({
        "Hisse": names,
        "Sektör": [sector_of[t] for t in names],
        "Ağırlık %": w * 100,
        "Risk katkısı %": rc * 100,
        "Beklenen getiri % (Markowitz)": mu_s * 100,
        "Risk σ % (Markowitz)": sig * 100,
        "Getiri/Risk": (mu_s - rf) / sig,
        "Min-varyans ağırlığı %": w_gmv * 100,
        "Maks-Sharpe ağırlığı %": w_tan * 100,
        "Beta": stats["beta"].reindex(names).values,
        "Yıllık getiri % (bileşik)": stats["cagr"].reindex(names).values * 100,
        "Max DD %": stats["max_dd"].reindex(names).values * 100,
        "Overall": [overall_of[t] for t in names],
    }).sort_values("Ağırlık %", ascending=False)
    st.dataframe(
        table, hide_index=True, use_container_width=True,
        column_config={
            "Ağırlık %": st.column_config.ProgressColumn("Ağırlık %", min_value=0, max_value=100,
                                                          format="%.1f"),
            "Risk katkısı %": st.column_config.ProgressColumn("Risk katkısı %", min_value=0,
                                                               max_value=100, format="%.1f"),
            "Beklenen getiri % (Markowitz)": st.column_config.NumberColumn(
                format="%.1f", help="Tarihsel yıllık ortalama getirinin kesit ortalamasına %50 çekilmiş "
                                    "hali (Markowitz girdisi). Tarihsel ortalamalar gürültülüdür; tahmin "
                                    "değil, geçmişe dayalı bir referanstır."),
            "Risk σ % (Markowitz)": st.column_config.NumberColumn(
                format="%.1f", help="Ledoit-Wolf shrinkage'lı kovaryanstan yıllık standart sapma."),
            "Getiri/Risk": st.column_config.NumberColumn(
                format="%.2f", help="(Beklenen getiri − risksiz faiz) / σ. Risksiz faiz yüksek olduğunda "
                                    "(TL) çoğu hisse için negatif çıkar."),
            "Min-varyans ağırlığı %": st.column_config.NumberColumn(format="%.1f"),
            "Maks-Sharpe ağırlığı %": st.column_config.NumberColumn(format="%.1f"),
            "Beta": st.column_config.NumberColumn(format="%.2f"),
            "Yıllık getiri % (bileşik)": st.column_config.NumberColumn(format="%.1f"),
            "Max DD %": st.column_config.NumberColumn(format="%.1f"),
            "Overall": st.column_config.NumberColumn(format="%.1f"),
        })

    def _mv(wv):
        r_, s_ = float(wv @ mu_s), float(np.sqrt(wv @ cov @ wv))
        return r_ * 100, s_ * 100, (r_ - rf) / s_ if s_ > 0 else np.nan
    mv_rows = []
    for lab, wv in (("Mevcut ağırlıklar", w), ("Min varyans (Markowitz)", w_gmv),
                    ("Maks. Sharpe (Markowitz)", w_tan), ("Eşit ağırlık", np.full(len(names), 1.0 / len(names)))):
        r_, s_, sh_ = _mv(wv)
        mv_rows.append({"Portföy": lab, "Beklenen getiri %": r_, "Risk σ %": s_, "Sharpe": sh_,
                        "Efektif hisse": 1.0 / float(np.sum(wv ** 2))})
    st.markdown("**Markowitz özeti — portföy düzeyi**")
    st.dataframe(pd.DataFrame(mv_rows), hide_index=True, use_container_width=True,
                 column_config={"Beklenen getiri %": st.column_config.NumberColumn(format="%.1f"),
                                "Risk σ %": st.column_config.NumberColumn(format="%.1f"),
                                "Sharpe": st.column_config.NumberColumn(format="%.2f"),
                                "Efektif hisse": st.column_config.NumberColumn(format="%.1f")})
    st.caption(f"Ortalama-varyans: beklenen getiri = tarihsel ortalamanın %50 shrinkage'ı, risk = Ledoit-Wolf "
               f"kovaryans (shrinkage %{a['shrink'] * 100:.0f}), risksiz faiz %{rf * 100:.1f}. Ağırlık üst sınırı "
               f"%{max_w * 100:.0f}. Maks-Sharpe, hiçbir hisse risksiz faizi aşmıyorsa Min varyansa düşer.")

    # ── hisse bazında beklenen getiri – risk dağılımı; "yüksek getiri / düşük risk" bölgesi vurgulu ──
    med_s, med_r = float(np.median(sig)), float(np.median(mu_s))
    in_zone = [bool(s_ <= med_s and r_ >= med_r) for s_, r_ in zip(sig, mu_s)]
    xs_, ys_ = sig * 100, mu_s * 100
    port_pts = [("Mevcut", w, "red", "star", 18), ("Min varyans", w_gmv, "white", "diamond", 12),
                ("Maks. Sharpe", w_tan, "orange", "diamond", 12)]
    px_ = [float(np.sqrt(wv @ cov @ wv) * 100) for _, wv, *_ in port_pts]
    py_ = [float(wv @ mu_s * 100) for _, wv, *_ in port_pts]
    x_lo, x_hi = min(xs_.min(), *px_) * 0.92, max(xs_.max(), *px_) * 1.06
    y_lo, y_hi = min(ys_.min(), *py_, rf * 100) - 4, max(ys_.max(), *py_, rf * 100) + 4
    fz = go.Figure()
    fz.add_shape(type="rect", x0=x_lo, x1=med_s * 100, y0=med_r * 100, y1=y_hi, layer="below",
                 fillcolor="rgba(46,160,67,0.16)", line=dict(width=1, color="rgba(46,160,67,0.6)", dash="dot"))
    fz.add_annotation(x=(x_lo + med_s * 100) / 2, y=y_hi, yanchor="top", showarrow=False,
                      text="<b>Yüksek getiri · düşük risk</b>", font=dict(color="rgb(46,160,67)", size=12))
    fz.add_vline(x=med_s * 100, line_dash="dot", line_color="gray")
    fz.add_hline(y=med_r * 100, line_dash="dot", line_color="gray")
    fz.add_hline(y=rf * 100, line_dash="dash", line_color="orange",
                 annotation_text=f"Risksiz faiz %{rf * 100:.1f}", annotation_position="bottom right")
    fz.add_trace(go.Scatter(
        x=xs_, y=ys_, mode="markers+text", name="Hisseler", text=names, textposition="top center",
        marker=dict(size=[10 + 60 * float(wi) for wi in w],
                    color=["rgb(46,160,67)" if z else "rgb(120,140,170)" for z in in_zone],
                    line=dict(width=[2 if z else 0.5 for z in in_zone], color="white"), opacity=0.9),
        customdata=np.column_stack([w * 100, (mu_s - rf) / sig]),
        hovertemplate="<b>%{text}</b><br>Risk σ %{x:.1f}%<br>Beklenen getiri %{y:.1f}%<br>"
                      "Ağırlık %{customdata[0]:.1f}%<br>Getiri/Risk %{customdata[1]:.2f}<extra></extra>"))
    for (lab, _, color, sym, size), x_, y_ in zip(port_pts, px_, py_):
        fz.add_trace(go.Scatter(x=[x_], y=[y_], mode="markers", name=lab,
                                marker=dict(size=size, color=color, symbol=sym, line=dict(width=1, color="black"))))
    fz.update_layout(title="Hisse bazında beklenen getiri – risk (nokta büyüklüğü = ağırlık)", height=420,
                     xaxis=dict(title="Risk: yıllık standart sapma σ %", range=[x_lo, x_hi]),
                     yaxis=dict(title="Beklenen getiri % (Markowitz)", range=[y_lo, y_hi]),
                     margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fz, use_container_width=True, config=PLOTLY_CFG, key="pf_ret_risk_scatter")
    zone = sorted((t for t, z in zip(names, in_zone) if z),
                  key=lambda t: -((mu_s[names.index(t)] - rf) / sig[names.index(t)]))
    st.caption("🟩 Yeşil bölge: risk (σ) seçili hisselerin medyanının altında, beklenen getiri medyanının üstünde "
               "— göreli bir ayrım, mutlak 'iyi' demek değildir. "
               + ("Bölgedeki hisseler (getiri/risk sırasıyla): " + ", ".join(zone) + "." if zone
                  else "Bölgede hisse yok."))

    _render_valuation(a, uni, universe_tickers, fetch_fn, deps)

    # ── grafikler ──
    g1, g2 = st.columns(2)
    with g1:
        fig = go.Figure([
            go.Bar(name="Ağırlık %", x=names, y=w * 100),
            go.Bar(name="Risk katkısı %", x=names, y=rc * 100),
        ])
        fig.update_layout(barmode="group", title="Ağırlık vs risk katkısı", height=340,
                          margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG)
    with g2:
        vols, rets_, shp = pa.random_portfolios(mu, cov, rf)
        fig = go.Figure(go.Scatter(
            x=vols * 100, y=rets_ * 100, mode="markers", name="Rastgele portföyler",
            marker=dict(size=4, color=shp, colorscale="Viridis", opacity=0.55,
                        colorbar=dict(title="Sharpe", thickness=10))))
        specials = [("Mevcut", w, "red", "star", 16),
                    ("Min varyans", w_gmv, "white", "diamond", 11),
                    ("Maks. Sharpe", w_tan, "orange", "diamond", 11),
                    ("Eşit ağırlık", np.full(len(names), 1.0 / len(names)), "cyan", "square", 9)]
        for label, wv, color, sym, size in specials:
            fig.add_trace(go.Scatter(
                x=[np.sqrt(wv @ cov @ wv) * 100], y=[wv @ mu * 100], mode="markers", name=label,
                marker=dict(size=size, color=color, symbol=sym, line=dict(width=1, color="black"))))
        fig.update_layout(title="Risk–getiri (tarihsel getiri, shrinkage'lı risk)", height=340,
                          xaxis_title="Yıllık volatilite %", yaxis_title="Yıllık getiri %",
                          margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG)

    g3, g4 = st.columns(2)
    with g3:
        cum = (1 + pr).cumprod() * 100
        fig = go.Figure(go.Scatter(x=cum.index, y=cum.values, name="Portföy", line=dict(width=3)))
        if bench_ret is not None:
            bc = (1 + bench_ret.dropna()).cumprod() * 100
            fig.add_trace(go.Scatter(x=bc.index, y=bc.values, name="XU100", line=dict(dash="dot")))
        fig.update_layout(title="Kümülatif performans (100 = başlangıç; sabit ağırlık, günlük yeniden "
                                "dengelenmiş)", height=360,
                          margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG)
    with g4:
        cm = a["corr"].loc[names, names]
        fig = go.Figure(go.Heatmap(
            z=cm.values, x=names, y=names, zmin=-1, zmax=1, colorscale="RdBu_r",
            text=np.round(cm.values, 2), texttemplate="%{text}",
            hovertemplate="%{y} – %{x}: %{z:.2f}<extra></extra>", colorbar=dict(thickness=10)))
        fig.update_layout(title="Korelasyon matrisi (= getiri vektörlerinin kosinüs benzerliği)",
                          height=360, margin=dict(l=10, r=10, t=40, b=10),
                          yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG)

    # ── değerlendirme ──
    st.markdown("---")
    st.markdown("### 🩺 Değerlendirme")
    qd = {}
    for key, col in (("marj", "marj_toplam_puani"), ("buyume", "buyume_puani"),
                     ("gorunum", "gorunum_puani")):
        items = [(w[names.index(t)], _num(uni.loc[t, col])) for t in names
                 if t in uni.index and pd.notna(uni.loc[t, col])]
        qd[key] = (sum(x * y for x, y in items) / sum(x for x, _ in items)) if items else None
    ov_all = pd.to_numeric(uni["overall_puani"]).dropna()
    ctx = dict(
        tickers=names, weights=dict(zip(names, w)), sector_of=sector_of, overall_of=overall_of,
        universe_overall=float(ov_all.mean()) if len(ov_all) else None, metrics=m,
        rc=dict(zip(names, rc)), div=ds, health=health, rf=rf, method_label=a["method_label"],
        opt_note=a["opt_note"], shrinkage=a["shrink"], dropped=a["dropped"], failed=a["failed"],
        jumps=pa.detect_jumps(returns), lookback_days=lookback, quality_detail=qd)
    for sec in pa.build_assessment(ctx):
        st.markdown(f"#### {LEVEL_ICON[sec['level']]} {sec['title']}")
        st.markdown("\n".join(f"- {b}" for b in sec["bullets"]))

    # ── çeşitlendirici öneri ──
    st.markdown("#### 🔎 Çeşitlendirici öneri")
    st.caption("Rapor evrenindeki diğer hisseler arasından, bu portföyle korelasyonu düşük ve "
               "Overall Puanı en az 3.0 olanları arar (ilk çalıştırmada tüm evrenin fiyatı çekildiği "
               "için biraz sürer).")
    sig = hashlib.md5(("|".join(names) + f"|{lookback}|{a['s']['method']}|{max_w}").encode()).hexdigest()[:10]
    if st.button("🔎 Çeşitlendirici öneri bul", key="pf_suggest_btn"):
        with st.spinner("Rapor evreninin fiyatları yükleniyor..."):
            uni_prices, _ = _load_close_prices(tuple(sorted(universe_tickers)), start, fetch_fn)
        if uni_prices.empty:
            st.warning("Evren fiyatları alınamadı.")
        else:
            uni_prices = _to_calendar(uni_prices, cal)
            sg = pa.suggest_diversifiers(
                uni_prices, pr, pd.to_numeric(uni["overall_puani"]), exclude=set(names),
                min_obs=max(60, int(0.75 * lookback)))
            st.session_state["pf_suggestions"] = (sig, sg)
    saved = st.session_state.get("pf_suggestions")
    if saved and saved[0] == sig:
        sg = saved[1]
        if sg.empty:
            st.info("Koşulları sağlayan aday bulunamadı.")
        else:
            show = sg.copy()
            show["Sektör"] = show["ticker"].map(lambda t: uni.loc[t, "sektor"] if t in uni.index else "—")
            show = show.rename(columns={"ticker": "Hisse", "corr": "Portföyle korelasyon",
                                        "overall": "Overall", "vol": "Volatilite"})
            show["Volatilite"] = show["Volatilite"] * 100
            st.dataframe(show[["Hisse", "Sektör", "Portföyle korelasyon", "Overall", "Volatilite"]],
                         hide_index=True, use_container_width=True,
                         column_config={"Portföyle korelasyon": st.column_config.NumberColumn(format="%.2f"),
                                        "Overall": st.column_config.NumberColumn(format="%.1f"),
                                        "Volatilite": st.column_config.NumberColumn("Volatilite %", format="%.1f")})
            st.button("➕ Önerilenleri sepete ekle", key="pf_add_suggested",
                      on_click=_add_tickers, args=(list(sg["ticker"]),))


# ───────────────────────── değerleme: hedef fiyat & ucuzluk ─────────────────────────

LABEL_ICON = {"Çok ucuz": "🟢🟢", "Ucuz": "🟢", "Makul": "⚪", "Pahalı": "🟠", "Çok pahalı": "🔴", "—": ""}


@st.cache_data(ttl=1800, show_spinner=False)
def _peer_valuations(_val_fn, _fin, sig, items):
    """items: ((ticker, fiyat), ...) - her hisse için güncel + ileri çarpanlar (finansal verisi olanlar)."""
    out = {}
    for t, price in items:
        if not _fin.get(t):
            continue
        try:
            v = _val_fn(t, price, financial_store=_fin)
        except Exception:
            v = {}
        if v:
            out[t] = v
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def _val_history(_hist_fn, symbol, _raw, _px, sig):
    return _hist_fn(symbol, _px, _raw)


def _fnum(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return np.nan
    return v if np.isfinite(v) else np.nan


def _render_valuation(a, uni, universe_tickers, fetch_fn, deps):
    st.markdown("---")
    st.markdown("### 🎯 Hedef fiyat ve ucuzluk önceliği")
    if not deps or not deps.get("valuation") or not deps.get("loader"):
        st.caption("Değerleme fonksiyonları bu ortamda yüklenemedi.")
        return
    if not st.toggle("Hedef fiyat analizini aç", key="pf_val_on",
                     help="Rapor evreninin finansallarını ve fiyatlarını yükler (ilk açılışta ~1 dk, sonra "
                          "30 dk önbellekte)."):
        st.caption("Seçili hisselerin ileri F/K ve FD/FAVÖK çarpanlarını kendi geçmişleri ve sektör "
                   "medyanlarıyla karşılaştırır; Overall ve Görünüm puanlarıyla ayarlanmış bir hedef fiyat ve "
                   "ucuzluk sırası çıkarır.")
        return

    st.session_state.setdefault("pf_val_whist", 50)
    st.session_state.setdefault("pf_val_kq", 10)
    st.session_state.setdefault("pf_val_ko", 5)
    with st.expander("⚙️ Varsayımlar", expanded=False):
        c1, c2, c3 = st.columns(3)
        w_hist = c1.slider("Geçmiş medyanın ağırlığı %", 0, 100, step=10, key="pf_val_whist",
                           help="Hedef çarpan = bu ağırlık × kendi geçmiş medyanı + kalan × sektör medyanı.")
        k_q = c2.slider("Kalite primi (Overall, puan başına %)", 0, 25, key="pf_val_kq",
                        help="Overall puanı sektör ortalamasının her +1 puanı için hedef çarpan bu kadar "
                             "yükselir (aşağıda ise düşer).")
        k_o = c3.slider("Görünüm primi (puan başına %)", 0, 15, key="pf_val_ko",
                        help="Görünüm puanının nötr 3'ün üstündeki her puanı için hedef çarpan bu kadar "
                             "yükselir.")
    params = dict(w_hist=w_hist / 100.0, k_quality=k_q / 100.0, k_outlook=k_o / 100.0)

    names = a["names"]
    in_uni = [t for t in names if t in uni.index]
    uni_t = tuple(sorted(universe_tickers))
    with st.spinner("Finansallar, çarpanlar ve geçmiş çarpanlar hesaplanıyor (ilk seferde ~1 dk)..."):
        fin = deps["loader"](uni_t)
        uprices, _ = _load_close_prices(uni_t, a["start"], fetch_fn)
        last = {t: float(uprices[t].dropna().iloc[-1]) for t in uprices.columns if uprices[t].notna().any()}
        last.update({t: p for t, p in a.get("last_price", {}).items() if t not in last})
        items = tuple((t, round(last[t], 4)) for t in uni_t if t in fin and t in last)
        sig = hashlib.md5("|".join(f"{t}:{p}" for t, p in items).encode()).hexdigest()[:12]
        peers = _peer_valuations(deps["valuation"], fin, sig, items)
        hists = {}
        if deps.get("history") and in_uni:
            long_start = (date.today() - timedelta(days=6 * 366)).isoformat()
            hist_px, _ = _load_close_prices(tuple(sorted(in_uni)), long_start, fetch_fn)
            for t in in_uni:
                if t in fin and t in hist_px.columns and hist_px[t].notna().any():
                    s_ = hist_px[t].dropna()
                    hists[t] = _val_history(deps["history"], t, fin[t], s_,
                                            f"{t}:{s_.index[-1]}:{len(s_)}")
    if not peers:
        st.info("Finansal veri bulunamadı (Financial Data içe aktarılmamış olabilir).")
        return

    mult_cols = ("pe", "fwd_pe", "ev_ebitda", "fwd_ev_ebitda")
    rows = pd.DataFrame({t: {k: _fnum(v.get(k)) for k in mult_cols} for t, v in peers.items()}).T
    sector_all = {t: (uni.loc[t, "sektor"] if t in uni.index and pd.notna(uni.loc[t, "sektor"]) else None)
                  for t in rows.index}
    sref_all = pv.sector_reference(rows, sector_all)
    ov_by_sector = pd.to_numeric(uni["overall_puani"], errors="coerce").groupby(uni["sektor"]).mean()

    results = {}
    for t in in_uni:
        v = peers.get(t)
        price = last.get(t)
        if not v or not price:
            continue
        sek = sector_all.get(t)
        sref, fallback = {}, []
        for k in mult_cols:
            sv = sref_all.get(sek, {}).get(k, (np.nan, 0))
            if not np.isfinite(sv[0]):
                sv = sref_all[pv.ALL_KEY].get(k, (np.nan, 0))
                if np.isfinite(sv[0]):
                    fallback.append(k)
            sref[k] = sv
        href = pv.history_reference(hists.get(t), v, pv.DEFAULTS["min_hist"], params)
        ov, go_ = _num(uni.loc[t, "overall_puani"]), _num(uni.loc[t, "gorunum_puani"])
        res = pv.target_for_stock(price, v, href, sref, None if np.isnan(ov) else ov,
                                  _fnum(ov_by_sector.get(sek)), None if np.isnan(go_) else go_, sek, params)
        res.update(overall=None if np.isnan(ov) else ov, gorunum=None if np.isnan(go_) else go_, val=v,
                   href=href, sref=sref, sector=sek or UNASSIGNED, sector_fallback=bool(fallback))
        results[t] = res
    if not results:
        st.info("Seçili hisselerin hiçbiri için değerleme hesaplanamadı (finansal verisi yok).")
        return

    pr_df = pv.prioritize(results)
    w_of = dict(zip(names, a["w"]))
    ok = pr_df[pr_df["upside"].notna()]
    k1, k2, k3, k4 = st.columns(4)
    if len(ok):
        wsum = sum(w_of.get(t, 0.0) for t in ok["ticker"])
        wup = (sum(w_of.get(t, 0.0) * u for t, u in zip(ok["ticker"], ok["upside"])) / wsum) if wsum > 0 else np.nan
        _metric(k1, "Ağırlıklı potansiyel", f"%{wup * 100:+.1f}", f"portföyün %{wsum * 100:.0f}'i kapsanıyor")
        _metric(k2, "En ucuz", ok.iloc[0]["ticker"], f"%{ok.iloc[0]['upside'] * 100:+.0f} potansiyel")
        _metric(k3, "En pahalı", ok.iloc[-1]["ticker"], f"%{ok.iloc[-1]['upside'] * 100:+.0f} potansiyel")
        _metric(k4, "Ucuz/pahalı", f"{int((ok['upside'] >= 0.10).sum())} / {int((ok['upside'] <= -0.10).sum())}",
                "≥%10 / ≤−%10 potansiyel")
    show = pd.DataFrame({
        "Öncelik": pr_df["rank"],
        "Hisse": pr_df["ticker"],
        "Sektör": [results[t]["sector"] for t in pr_df["ticker"]],
        "Fiyat ₺": pr_df["price"],
        "Hedef fiyat ₺": pr_df["target"],
        "Potansiyel %": pr_df["upside"] * 100,
        "Ucuzluk": [(LABEL_ICON.get(l, "") + " " + l).strip() for l in pr_df["label"]],
        "Güven": pr_df["confidence"],
        "Overall": pr_df["overall"],
        "Görünüm": pr_df["gorunum"],
        "Kalite çarpanı": pr_df["adj"],
        "Not": ["; ".join(f"{pv.MULT_LABELS[k]}: {why}" for k, why in results[t]["rejected"].items())
                for t in pr_df["ticker"]],
    })
    st.dataframe(show, hide_index=True, use_container_width=True, column_config={
        "Öncelik": st.column_config.NumberColumn(format="%d", help="1 = en ucuz (potansiyele göre)."),
        "Fiyat ₺": st.column_config.NumberColumn(format="%.2f"),
        "Hedef fiyat ₺": st.column_config.NumberColumn(format="%.2f"),
        "Potansiyel %": st.column_config.NumberColumn(format="%+.1f"),
        "Overall": st.column_config.NumberColumn(format="%.1f"),
        "Görünüm": st.column_config.NumberColumn(format="%.1f"),
        "Kalite çarpanı": st.column_config.NumberColumn(
            format="%.2f", help="Hedef çarpana uygulanan Overall/Görünüm düzeltmesi (1.00 = etkisiz)."),
    })
    n_rej = [t for t in results if results[t]["rejected"]]
    if n_rej:
        st.caption("ℹ️ Uygulamanın mekanik kâr tahmini, kâr dalgalanan/zarar eden şirketlerde uç değerler "
                   "üretebiliyor; tahmini son 12 aya göre makul bandın (0.4x–2.5x) dışında kalan çarpanlar "
                   "hedefe katılmadı (Not sütunu): " + ", ".join(n_rej))
    missing = [t for t in names if t not in results]
    if missing:
        st.caption("Değerleme hesaplanamayan hisseler (finansal veri yok / bu dönemde rapor yok): "
                   + ", ".join(missing))
    if any(r["clipped"] for r in results.values()):
        st.caption("⚠️ Bazı hedef fiyatlar uç değer koruması nedeniyle fiyatın 0.5x–2x'i ile sınırlandı.")

    with st.expander("🔬 Çarpan karşılaştırması: güncel · geçmiş · sektör"):
        for key, title, cur_key in (("fwd_pe", "İleri F/K", "pe"), ("fwd_ev_ebitda", "İleri FD/FAVÖK", "ev_ebitda")):
            rws = []
            for t in pr_df["ticker"]:
                r = results[t]
                if key not in r["methods"] and key not in r["rejected"] and not np.isfinite(_fnum(r["val"].get(key))):
                    continue
                cur = _fnum(r["val"].get(key))
                hr = r["href"].get(key, {})
                hmed, sv = hr.get("median", np.nan), r["sref"][key]
                rws.append({
                    "Hisse": t, "Güncel (trailing)": _fnum(r["val"].get(cur_key)), title: cur,
                    "Geçmiş medyan": hmed, "Geçmiş n": hr.get("n", 0),
                    "Geçmişe göre %": (cur / hmed - 1) * 100 if np.isfinite(hmed) and np.isfinite(cur) else np.nan,
                    "Geçmişte bugünden düşük %": hr.get("pct_below", np.nan) * 100,
                    "Sektör medyan": sv[0], "Sektör n": sv[1],
                    "Sektöre göre %": (cur / sv[0] - 1) * 100 if np.isfinite(sv[0]) and np.isfinite(cur) else np.nan,
                    "Hedef çarpan": r["methods"].get(key, {}).get("target_multiple", np.nan),
                    "Hedef fiyat ₺": r["methods"].get(key, {}).get("target_price", np.nan),
                    "Not": r["rejected"].get(key, ""),
                })
            st.markdown(f"**{title}**" + (" — bankacılık/sigorta/finansta FD/FAVÖK kullanılmaz" if key == "fwd_ev_ebitda" else ""))
            if not rws:
                st.caption("Hesaplanabilen hisse yok.")
                continue
            st.dataframe(pd.DataFrame(rws), hide_index=True, use_container_width=True, column_config={
                c: st.column_config.NumberColumn(format="%.1f" if "%" in c else "%.2f")
                for c in ("Güncel (trailing)", title, "Geçmiş medyan", "Geçmişe göre %", "Geçmişte bugünden düşük %",
                          "Sektör medyan", "Sektöre göre %", "Hedef çarpan", "Hedef fiyat ₺")
                if c != "Not"})
        fb = [t for t in results if results[t]["sector_fallback"]]
        if fb:
            st.caption("Sektörde yeterli hisse (≥3) olmadığı için tüm rapor evreni medyanı kullanılan hisseler: "
                       + ", ".join(fb))

    fig = go.Figure()
    for t in ok["ticker"]:
        r = results[t]
        if r["overall"] is None:
            continue
        fig.add_trace(go.Scatter(
            x=[r["overall"]], y=[r["upside"] * 100], mode="markers+text", text=[t], textposition="top center",
            name=t, showlegend=False,
            marker=dict(size=10 + 60 * w_of.get(t, 0.0), opacity=0.8),
            hovertemplate=f"<b>{t}</b><br>Overall %{{x:.1f}}<br>Potansiyel %{{y:+.0f}}%<extra></extra>"))
    fig.add_hline(y=0, line_dash="dot", line_color="gray")
    fig.update_layout(title="Kalite – ucuzluk haritası (sağ üst: yüksek puanlı ve ucuz)", height=340,
                      xaxis_title="Overall puanı", yaxis_title="Potansiyel %",
                      margin=dict(l=10, r=10, t=40, b=10))
    if len(fig.data):
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG)

    with st.expander("ℹ️ Hedef fiyat nasıl hesaplanıyor? Sınırlar nelerdir?"):
        st.markdown(
            "1. **Çarpanlar:** her hisse için *ileri F/K* (piyasa değeri ÷ tahmini 4 çeyreklik net kâr) ve "
            "*ileri FD/FAVÖK* (firma değeri ÷ tahmini FAVÖK). İleri değerler uygulamanın mekanik tahmininden "
            "(mevsimsellik + momentum + ortalamaya dönüş) gelir; analist konsensüsü değildir.\n"
            "2. **Geçmiş:** hissenin kendi geçmiş çeyrekleri için, o güne kadarki finansallarla ayni tahmin "
            "yöntemi yeniden çalıştırılıp ileri çarpanlar yeniden kurulur (rapor gecikmesi 60 gün, fiyatlar "
            "bölünme düzeltmeli). Medyan için en az 6 gözlem gerekir.\n"
            "3. **Sektör:** aynı sektördeki rapor evreni hisselerinin güncel ileri çarpan medyanı (≥3 hisse; "
            "yoksa tüm evren medyanı).\n"
            f"4. **Hedef çarpan** = %{w_hist} geçmiş + %{100 - w_hist} sektör; sonra *Overall* (sektör ortalamasına "
            f"göre puan başına %{k_q}) ve *Görünüm* (3'e göre puan başına %{k_o}) ile ölçeklenir, "
            "0.75–1.25 aralığına kırpılır.\n"
            "5. **Hedef fiyat:** F/K için fiyat × hedef/güncel çarpan; FD/FAVÖK için (hedef FD/FAVÖK × tahmini "
            "FAVÖK − net borç) ÷ hisse sayısı. Mevcut yöntemlerin ortalaması alınır; fiyatın 0.5x–2x'i ile sınırlıdır.\n"
            "6. **Potansiyel** = hedef/fiyat − 1; **Öncelik** 1 = en yüksek potansiyel. Güven: iki yöntem + hem geçmiş "
            "hem sektör referansı varsa Yüksek.\n\n"
            "**Sınırlar:** hedef fiyat, çarpanların ortalamaya döneceği varsayımıdır (zaman ufku belirsiz); "
            "tahmin gürültülüdür (özellikle kâr dalgalanan/enflasyon muhasebesi etkili şirketlerde); "
            "finansal verisi olmayan hisseler (ör. bazı bankalar) hesaplanamaz. **Yatırım tavsiyesi değildir.**")


# ───────────────────────── 3D harita ─────────────────────────

def _feature_frame(urets, bench_ret, uni, sector_score) -> pd.DataFrame:
    """Parametre uzayı için hisse x parametre tablosu (fiyat bazlı + rapor puanları)."""
    s = pa.universe_stats(urets, bench_ret)
    feat = pd.DataFrame(index=s.index)
    feat["Volatilite %"] = s["vol"] * 100
    feat["Beta"] = s["beta"]
    feat["Yıllık getiri % (bileşik)"] = s["cagr"] * 100
    feat["Max DD %"] = s["max_dd"] * 100
    for label, col in (("Overall", "overall_puani"), ("Marj", "marj_toplam_puani"),
                       ("Büyüme", "buyume_puani"), ("Görünüm", "gorunum_puani")):
        feat[label] = pd.to_numeric(uni[col], errors="coerce").reindex(feat.index)
    feat["Sektör skoru"] = [sector_score.get(uni.loc[t, "sektor"]) if t in uni.index else np.nan
                            for t in feat.index]
    return feat.apply(pd.to_numeric, errors="coerce")


def _map_figure(pos, uni, ustats, basket, weights, axis_titles, vectors, port_vec):
    palette = pcolors.qualitative.D3
    sectors = sorted({(uni.loc[t, "sektor"] if t in uni.index and pd.notna(uni.loc[t, "sektor"])
                       else UNASSIGNED) for t in pos.index})
    color_of = {s: palette[i % len(palette)] for i, s in enumerate(sectors)}

    def info(t):
        sek = uni.loc[t, "sektor"] if t in uni.index and pd.notna(uni.loc[t, "sektor"]) else UNASSIGNED
        ov = _num(uni.loc[t, "overall_puani"]) if t in uni.index else np.nan
        vol = ustats["vol"].get(t, np.nan) if ustats is not None else np.nan
        beta = ustats["beta"].get(t, np.nan) if ustats is not None else np.nan
        txt = f"<b>{t}</b><br>{sek}"
        if not np.isnan(ov):
            txt += f"<br>Overall {ov:.1f}/5"
        if not np.isnan(vol):
            txt += f"<br>Vol %{vol * 100:.0f} · Beta {_fmt(float(beta))}"
        if t in weights:
            txt += f"<br>Portföy ağırlığı %{weights[t] * 100:.1f}"
        return sek, txt

    in_basket = [t for t in pos.index if t in basket]
    others = [t for t in pos.index if t not in basket]
    fig = go.Figure()
    if others:
        infos = [info(t) for t in others]
        fig.add_trace(go.Scatter3d(
            x=pos.loc[others].iloc[:, 0], y=pos.loc[others].iloc[:, 1], z=pos.loc[others].iloc[:, 2],
            mode="markers", name="Evren", hovertext=[i[1] for i in infos], hoverinfo="text",
            marker=dict(size=3.5, opacity=0.45, color=[color_of[i[0]] for i in infos])))
    if in_basket:
        infos = [info(t) for t in in_basket]
        if vectors:
            xs, ys, zs = [], [], []
            for t in in_basket:
                xs += [0, pos.loc[t].iloc[0], None]
                ys += [0, pos.loc[t].iloc[1], None]
                zs += [0, pos.loc[t].iloc[2], None]
            fig.add_trace(go.Scatter3d(x=xs, y=ys, z=zs, mode="lines", name="Vektörler",
                                       hoverinfo="skip", line=dict(width=4, color="rgba(200,200,200,0.7)")))
        fig.add_trace(go.Scatter3d(
            x=pos.loc[in_basket].iloc[:, 0], y=pos.loc[in_basket].iloc[:, 1],
            z=pos.loc[in_basket].iloc[:, 2], mode="markers+text", name="Seçili",
            text=in_basket, textposition="top center", hovertext=[i[1] for i in infos],
            hoverinfo="text",
            marker=dict(size=[min(18, 7 + 40 * weights.get(t, 0.0)) for t in in_basket],
                        color=[color_of[i[0]] for i in infos], opacity=1.0,
                        line=dict(width=2, color="white"))))
    if port_vec is not None:
        fig.add_trace(go.Scatter3d(
            x=[0, port_vec[0]], y=[0, port_vec[1]], z=[0, port_vec[2]], mode="lines+markers",
            name="Portföy", hovertext=["", "Portföy (ağırlıklı vektör toplamı)"], hoverinfo="text",
            line=dict(width=9, color="gold"),
            marker=dict(size=[1, 10], color="gold", symbol="diamond")))
    fig.update_layout(
        height=380, margin=dict(l=0, r=0, t=0, b=0), showlegend=False, uirevision="pf3d",
        scene=dict(xaxis_title=axis_titles[0], yaxis_title=axis_titles[1], zaxis_title=axis_titles[2],
                   aspectmode="cube"))
    return fig


def _render_map(a, uni, sector_score, universe_tickers, fetch_fn):
    st.markdown("##### 🌐 3D harita")
    if not st.toggle("Haritayı aç", key="pf_map_on",
                     help="Tüm rapor evreninin fiyatlarını yükler (ilk açılışta ~1 dk; sonra 1 saat "
                          "önbellekte)."):
        st.caption("Hisselerin birbirine göre konumunu ve seçtiklerini 3 boyutta gösterir.")
        return
    lookback = LOOKBACKS[st.session_state.get("pf_lookback", "1 yıl")]
    with st.spinner("Rapor evreninin fiyatları yükleniyor (ilk seferde ~1 dk)..."):
        start, bench_px = _market_window(lookback, fetch_fn)
        uprices, _ = _load_close_prices(tuple(sorted(universe_tickers)), start, fetch_fn)
    if uprices.empty:
        st.warning("Evren fiyatları alınamadı.")
        return
    cal = (bench_px.index if bench_px is not None else uprices.index)[-(lookback + 1):]
    up = _to_calendar(uprices, cal)
    urets = (up / up.shift(1) - 1.0).iloc[1:].replace([np.inf, -np.inf], np.nan)
    min_obs = max(60, int(0.6 * lookback))
    urets = urets.loc[:, urets.notna().sum() >= min_obs]
    bench_ret = (bench_px / bench_px.shift(1) - 1.0).reindex(urets.index) if bench_px is not None else None
    ustats = pa.universe_stats(urets, bench_ret)

    mode = st.radio("Eksenler", ["Korelasyon uzayı", "Parametre uzayı"], horizontal=True,
                    key="pf_map_mode",
                    help="Korelasyon uzayı: noktalar getiri korelasyon yapısından (PCA) çıkar; iki "
                         "vektör arasındaki açı küçüldükçe hisseler benzer hareket eder. Parametre "
                         "uzayı: eksenleri sen seçersin (volatilite, beta, puanlar...).")
    basket = list(_basket())
    weights = dict(zip(a["names"], a["w"])) if a and "names" in a else {}

    if mode == "Korelasyon uzayı":
        coords, expl = pa.correlation_embedding(urets, k=3, min_periods=min_obs)
        pos, vectors = coords, True
        titles = [f"Faktör 1 · ortak/piyasa (%{expl[0] * 100:.0f})",
                  f"Faktör 2 (%{expl[1] * 100:.0f})", f"Faktör 3 (%{expl[2] * 100:.0f})"]
        port_vec = None
        if weights and all(t in coords.index for t in weights):
            port_vec = sum(weights[t] * coords.loc[t].values for t in weights)
        st.caption(f"3 faktör, evrenin korelasyon yapısının %{expl.sum() * 100:.0f}'ini açıklıyor. "
                   "Seçili hisseler orijinden çıkan vektör; sarı çubuk portföyün ağırlıklı vektörü.")
    else:
        feat = _feature_frame(urets, bench_ret, uni, sector_score)
        cols = list(feat.columns)
        defaults = [cols.index("Volatilite %"), cols.index("Beta"), cols.index("Overall")]
        c = st.columns(3)
        axes = [c[i].selectbox(f"{'XYZ'[i]} ekseni", cols, index=defaults[i], key=f"pf_map_ax{i}")
                for i in range(3)]
        if len(set(axes)) < 3:
            st.warning("Üç eksen için farklı parametreler seç.")
            return
        pos = feat[axes].dropna()
        vectors, port_vec, titles = False, None, axes

    missing = [t for t in basket if t not in pos.index]
    if missing:
        st.caption("Haritada olmayan seçili hisseler (geçmiş/veri yetersiz): " + ", ".join(missing))
    fig = _map_figure(pos, uni, ustats, basket, weights, titles, vectors, port_vec)
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG, key="pf_map_chart")
    if mode == "Korelasyon uzayı":
        _render_cosine(coords, urets, [t for t in basket if t in coords.index], min_obs)


def _cosine(u, v) -> float:
    nu, nv = float(np.linalg.norm(u)), float(np.linalg.norm(v))
    return float(np.dot(u, v) / (nu * nv)) if nu > 0 and nv > 0 else float("nan")


def _render_cosine(coords, urets, in_map, min_obs):
    """İki seçili hissenin 3B vektörleri arasındaki kosinüs benzerliği (ve gerçek korelasyon)."""
    st.markdown("**📐 İki vektörün kosinüs benzerliği**")
    if len(in_map) < 2:
        st.caption("Sepette (haritada olan) en az 2 hisse olunca iki vektör arasındaki kosinüs benzerliği "
                   "burada görünür.")
        return
    ss = st.session_state
    if ss.get("pf_cos_a") not in in_map:
        ss["pf_cos_a"] = in_map[0]
    if ss.get("pf_cos_b") not in in_map or ss.get("pf_cos_b") == ss["pf_cos_a"]:
        ss["pf_cos_b"] = next(t for t in in_map if t != ss["pf_cos_a"])
    c1, c2 = st.columns(2)
    A = c1.selectbox("Vektör A", in_map, key="pf_cos_a")
    B = c2.selectbox("Vektör B", in_map, key="pf_cos_b")
    va, vb = coords.loc[A].values, coords.loc[B].values
    cos = _cosine(va, vb)
    rho = float(urets[[A, B]].corr(min_periods=min_obs).iloc[0, 1]) if A != B else 1.0
    dot = float(np.dot(va, vb))
    m1, m2 = st.columns(2)
    _metric(m1, "Kosinüs (3B)", _fmt(cos), "1 = aynı yön, 0 = bağımsız, −1 = ters")
    _metric(m2, "Açı", "—" if np.isnan(cos) else f"{np.degrees(np.arccos(np.clip(cos, -1, 1))):.0f}°")
    m3, m4 = st.columns(2)
    _metric(m3, "x·y (≈ korelasyon)", _fmt(dot), "vektörlerin nokta çarpımı")
    _metric(m4, "Gerçek korelasyon", _fmt(rho), "tüm geçmişten, 3B'ye indirgemeden")
    st.caption(f"Vektör boyları: {A} {np.linalg.norm(va):.2f} · {B} {np.linalg.norm(vb):.2f}. Kosinüs yalnızca "
               "YÖNÜ ölçer (boylara bölünür), bu yüzden vektörler 1'den kısaysa (3 faktör hisseyi tam "
               "açıklamıyorsa) korelasyondan YÜKSEK çıkar; korelasyonu en iyi nokta çarpım (x·y) yaklaşıklar. "
               "Gerçek korelasyon her zaman kesin değerdir.")
    if len(in_map) > 2:
        with st.expander("Tüm seçili çiftler"):
            rws = []
            for i, x in enumerate(in_map):
                for y in in_map[i + 1:]:
                    c_ = _cosine(coords.loc[x].values, coords.loc[y].values)
                    rws.append({"Hisse A": x, "Hisse B": y, "Kosinüs (3B)": c_,
                                "x·y": float(np.dot(coords.loc[x].values, coords.loc[y].values)),
                                "Açı °": float(np.degrees(np.arccos(np.clip(c_, -1, 1)))) if np.isfinite(c_) else np.nan,
                                "Gerçek korelasyon": float(urets[[x, y]].corr(min_periods=min_obs).iloc[0, 1])})
            st.dataframe(pd.DataFrame(rws).sort_values("Kosinüs (3B)", ascending=False), hide_index=True,
                         use_container_width=True,
                         column_config={"Kosinüs (3B)": st.column_config.NumberColumn(format="%.2f"),
                                        "x·y": st.column_config.NumberColumn(format="%.2f"),
                                        "Açı °": st.column_config.NumberColumn(format="%.0f"),
                                        "Gerçek korelasyon": st.column_config.NumberColumn(format="%.2f")})


# ───────────────────────── zaman yolculuğu & walk-forward ─────────────────────────

TIME_STEPS = {"Aylık (21 gün)": 21, "3 aylık (63 gün)": 63}
TIME_YEARS = {"1 yıl": 1, "2 yıl": 2, "3 yıl": 3}
TRAIL_FRAMES = 5
PRESET_LABELS = ["Eşit ağırlık", "Risk parity", "Minimum varyans", "Ters volatilite",
                 "Maksimum Sharpe", "Kalite eğimli RP", "Momentum eğimli RP", "Kalite + momentum RP"]
PRESET_DEFAULT = ["Eşit ağırlık", "Risk parity", "Kalite + momentum RP"]


def _df_sig(df: pd.DataFrame, *extra) -> str:
    """Önbellek anahtarı: kolonlar + şekil + ilk/son tarih (+ ekstra parametreler)."""
    h = hashlib.md5()
    h.update(",".join(map(str, df.columns)).encode())
    h.update(f"{df.shape}|{df.index[0]}|{df.index[-1]}".encode())
    for e in extra:
        h.update(repr(e).encode())
    return h.hexdigest()


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_embedding(_urets, sig, window, step):
    return pa.rolling_embedding(_urets, window, step)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_walk(_rets, sig, window, step, method, max_w, rf, quality, tilt, mom_tilt, manual, cost):
    ends = pa.time_grid(len(_rets), window, step)
    return pa.walk_forward(_rets, ends, window, method, max_w, rf,
                           quality=list(quality) if quality is not None else None,
                           tilt=tilt, mom_tilt=mom_tilt,
                           manual=dict(manual) if manual else None, cost=cost)


def _time_data(universe_tickers, window, years, fetch_fn):
    """Zaman bölümü için uzun fiyat geçmişi: (evren getirileri, XU100 getirisi) ya da None."""
    total = window + years * 252 + 5
    start, bench_px = _market_window(total, fetch_fn)
    uprices, _ = _load_close_prices(tuple(sorted(universe_tickers)), start, fetch_fn)
    if uprices.empty:
        return None
    cal = (bench_px.index if bench_px is not None else uprices.index)[-(total + 1):]
    up = _to_calendar(uprices, cal)
    urets = (up / up.shift(1) - 1.0).iloc[1:].replace([np.inf, -np.inf], np.nan)
    urets = urets.loc[:, urets.notna().sum() >= int(0.6 * window)]
    bench_ret = ((bench_px / bench_px.shift(1) - 1.0).reindex(urets.index)
                 if bench_px is not None else None)
    return urets, bench_ret


def _method_specs(s, manual) -> dict:
    """Karşılaştırılacak yöntemler: etiket -> parametre dict'i. İlk giriş ayarlardaki yöntemdir."""
    is_q = s["method"] == "quality_rp"
    t = s.get("tilt", 2.0) if is_q else 2.0
    m = s.get("mom_tilt", 1.0) if is_q else 1.0
    if s["source"] == "Elle":
        primary = ("▶ Elle girilen ağırlıklar (her dönem aynı oranlar)",
                   dict(method="equal", manual=dict(manual or {})))
    else:
        primary = ("▶ " + pa.METHODS[s["method"]],
                   dict(method=s["method"], tilt=t if is_q else 2.0, mom_tilt=m if is_q else 0.0))
    presets = {
        "Eşit ağırlık": dict(method="equal"),
        "Risk parity": dict(method="risk_parity"),
        "Minimum varyans": dict(method="min_var"),
        "Ters volatilite": dict(method="inv_vol"),
        "Maksimum Sharpe": dict(method="max_sharpe"),
        "Kalite eğimli RP": dict(method="quality_rp", tilt=t, mom_tilt=0.0),
        "Momentum eğimli RP": dict(method="quality_rp", tilt=0.0, mom_tilt=m),
        "Kalite + momentum RP": dict(method="quality_rp", tilt=t, mom_tilt=m),
    }
    return primary, presets


def _spec_key(sp):
    q = sp["method"] == "quality_rp"
    return (sp["method"], sp.get("tilt", 2.0) if q else None, sp.get("mom_tilt", 0.0) if q else None,
            tuple(sorted(sp["manual"].items())) if sp.get("manual") else None)


def _time_figure(tf, basket, W, health, bench_dd, uni, trail=TRAIL_FRAMES, height=900):
    """Animasyonlu 3D korelasyon haritası + altında nabız şeridi (aynı zaman imleci)."""
    from plotly.subplots import make_subplots
    dates, pos = tf["dates"], tf["pos"]
    n = len(dates)
    all_t = sorted({t for p in pos for t in p.index} | set(basket))
    others = [t for t in all_t if t not in basket]
    nb = len(basket)
    palette = pcolors.qualitative.D3
    sec_of = {t: (uni.loc[t, "sektor"] if t in uni.index and pd.notna(uni.loc[t, "sektor"])
                  else UNASSIGNED) for t in all_t}
    color_of = {s: palette[i % len(palette)] for i, s in enumerate(sorted(set(sec_of.values())))}

    def hover(t):
        ov = _num(uni.loc[t, "overall_puani"]) if t in uni.index else np.nan
        return f"<b>{t}</b><br>{sec_of[t]}" + ("" if np.isnan(ov) else f"<br>Overall {ov:.1f}/5")

    def xyz(i, tickers):
        p = pos[i].reindex(tickers)
        return p["F1"].values, p["F2"].values, p["F3"].values

    def port_vec(i):
        w = W.iloc[i]
        held = [t for t in basket if t in w.index and w[t] > 1e-9 and t in pos[i].index]
        if not held:
            return (np.nan, np.nan, np.nan)
        wv = w[held].values / w[held].sum()
        v = (pos[i].loc[held].values * wv[:, None]).sum(axis=0)
        return tuple(v)

    pvecs = [port_vec(i) for i in range(n)]
    lo, hi = float(np.nanmin(health["avg_corr"].tolist() + tf["avg_corr"])), \
        float(np.nanmax(health["avg_corr"].tolist() + tf["avg_corr"]))
    pad = 0.05 * max(hi - lo, 0.1)
    c_lo, c_hi = lo - pad, hi + pad

    def dyn(i):
        """Karenin dinamik izleri (fig.data'daki ilk 4+nb+1 iz + 2 imleç) için veri."""
        out = []
        ox, oy, oz = xyz(i, others)
        out.append(dict(x=ox, y=oy, z=oz))
        bx, by, bz = xyz(i, basket)
        vx, vy, vz = [], [], []
        for k in range(nb):
            vx += [0, bx[k], None]
            vy += [0, by[k], None]
            vz += [0, bz[k], None]
        out.append(dict(x=vx, y=vy, z=vz))
        w = W.iloc[i]
        out.append(dict(x=bx, y=by, z=bz,
                        marker=dict(size=[min(18, 7 + 40 * float(w.get(t, 0.0))) for t in basket])))
        p = pvecs[i]
        out.append(dict(x=[0, p[0]], y=[0, p[1]], z=[0, p[2]]))
        rng_i = range(max(0, i - trail), i + 1)
        for t in basket:
            tx, ty, tz = [], [], []
            for r in rng_i:
                if t in pos[r].index:
                    tx.append(pos[r].loc[t, "F1"]); ty.append(pos[r].loc[t, "F2"]); tz.append(pos[r].loc[t, "F3"])
            out.append(dict(x=tx, y=ty, z=tz))
        out.append(dict(x=[pvecs[r][0] for r in rng_i], y=[pvecs[r][1] for r in rng_i],
                        z=[pvecs[r][2] for r in rng_i]))
        d = dates[i]
        out.append(dict(x=[d, d], y=[c_lo, c_hi]))
        out.append(dict(x=[d, d], y=[0, 100]))
        return out

    # eksen aralıkları: tüm karelerdeki konumlardan (başlangıç noktası dahil); aspectmode="data"
    # ile birim uzunluk her eksende aynı kalır, böylece vektörler arası açı bozulmaz
    allpos = pd.concat([p for p in pos if len(p)] + [pd.DataFrame([[0.0, 0.0, 0.0]],
                                                                   columns=["F1", "F2", "F3"])])
    rngs = {c: [float(allpos[c].min()) - 0.08, float(allpos[c].max()) + 0.08] for c in ("F1", "F2", "F3")}
    fig = make_subplots(rows=3, cols=1, row_heights=[0.7, 0.15, 0.15], vertical_spacing=0.06,
                        specs=[[{"type": "scene"}], [{"type": "xy", "secondary_y": True}],
                               [{"type": "xy"}]])
    d0 = dyn(n - 1)
    # 3D izler (sıra önemli: dyn() ile aynı)
    fig.add_trace(go.Scatter3d(mode="markers", name="Evren", hoverinfo="text",
                               hovertext=[hover(t) for t in others],
                               marker=dict(size=3.5, opacity=0.4,
                                           color=[color_of[sec_of[t]] for t in others]), **d0[0]),
                  row=1, col=1)
    fig.add_trace(go.Scatter3d(mode="lines", name="Vektörler", hoverinfo="skip",
                               line=dict(width=4, color="rgba(200,200,200,0.6)"), **d0[1]),
                  row=1, col=1)
    fig.add_trace(go.Scatter3d(mode="markers+text", name="Seçili", text=basket,
                               textposition="top center", hoverinfo="text",
                               hovertext=[hover(t) for t in basket],
                               marker=dict(color=[color_of[sec_of[t]] for t in basket], opacity=1.0,
                                           line=dict(width=2, color="white"),
                                           size=d0[2]["marker"]["size"]),
                               x=d0[2]["x"], y=d0[2]["y"], z=d0[2]["z"]), row=1, col=1)
    fig.add_trace(go.Scatter3d(mode="lines+markers", name="Portföy", hoverinfo="skip",
                               line=dict(width=9, color="gold"),
                               marker=dict(size=[1, 10], color="gold", symbol="diamond"), **d0[3]),
                  row=1, col=1)
    for k, t in enumerate(basket):
        fig.add_trace(go.Scatter3d(mode="lines", name=f"İz {t}", hoverinfo="skip",
                                   line=dict(width=4, color=color_of[sec_of[t]]), opacity=0.6,
                                   **d0[4 + k]), row=1, col=1)
    fig.add_trace(go.Scatter3d(mode="lines", name="Portföy izi", hoverinfo="skip", opacity=0.6,
                               line=dict(width=6, color="gold"), **d0[4 + nb]), row=1, col=1)
    n_dyn3d = 5 + nb
    # statik şerit izleri
    fig.add_trace(go.Scatter(x=dates, y=tf["avg_corr"], name="Evren ort. korelasyon",
                             line=dict(color="#4C9BE8", width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=list(health.index), y=health["avg_corr"], name="Portföy ort. korelasyon",
                             line=dict(color="gold", width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=dates, y=bench_dd, name="XU100 tepeden düşüş %", fill="tozeroy",
                             line=dict(color="rgba(230,80,80,0.6)", width=1),
                             fillcolor="rgba(230,80,80,0.18)"), row=2, col=1, secondary_y=True)
    fig.add_trace(go.Scatter(x=list(health.index), y=health["total"], name="Sağlık skoru",
                             line=dict(color="#6FCF97", width=2.5)), row=3, col=1)
    cur2 = len(fig.data)
    fig.add_trace(go.Scatter(x=d0[n_dyn3d]["x"], y=d0[n_dyn3d]["y"], mode="lines", showlegend=False,
                             hoverinfo="skip", line=dict(color="white", width=1.5, dash="dot")),
                  row=2, col=1)
    fig.add_trace(go.Scatter(x=d0[n_dyn3d + 1]["x"], y=d0[n_dyn3d + 1]["y"], mode="lines",
                             showlegend=False, hoverinfo="skip",
                             line=dict(color="white", width=1.5, dash="dot")), row=3, col=1)
    for tr in fig.data[:n_dyn3d]:
        tr.showlegend = False
    dyn_idx = list(range(n_dyn3d)) + [cur2, cur2 + 1]
    fig.frames = [go.Frame(name=str(i), data=[go.Scatter3d(**d) if j < n_dyn3d else go.Scatter(**d)
                                              for j, d in enumerate(dyn(i))], traces=dyn_idx)
                  for i in range(n)]
    anim = dict(frame=dict(duration=550, redraw=True), transition=dict(duration=0), fromcurrent=True)
    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=80, b=70), uirevision="pf3d_time",
        legend=dict(orientation="h", y=-0.07, x=0.0, font=dict(size=10)),
        scene=dict(xaxis=dict(title="Faktör 1 · piyasa", range=rngs["F1"]),
                   yaxis=dict(title="Faktör 2", range=rngs["F2"]),
                   zaxis=dict(title="Faktör 3", range=rngs["F3"]), aspectmode="data",
                   camera=dict(eye=dict(x=1.0, y=1.0, z=0.7))),
        updatemenus=[dict(type="buttons", direction="left", x=0.0, y=1.11, xanchor="left",
                          yanchor="top", showactive=False,
                          buttons=[dict(label="▶ Oynat", method="animate", args=[None, anim]),
                                   dict(label="⏸ Durdur", method="animate",
                                        args=[[None], dict(mode="immediate", frame=dict(duration=0, redraw=False),
                                                           transition=dict(duration=0))])])],
        sliders=[dict(active=n - 1, x=0.2, len=0.8, y=1.12, yanchor="top", pad=dict(t=0, b=0),
                      currentvalue=dict(prefix="Tarih: ", xanchor="left"),
                      steps=[dict(method="animate", label=pd.Timestamp(d).strftime("%Y-%m"),
                                  args=[[str(i)], dict(mode="immediate", frame=dict(duration=0, redraw=True),
                                                       transition=dict(duration=0))])
                             for i, d in enumerate(dates)])])
    fig.update_yaxes(title_text="Ort. korelasyon", range=[c_lo, c_hi], row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="XU100 düşüş %", row=2, col=1, secondary_y=True, showgrid=False,
                     rangemode="tozero", autorange="reversed")
    fig.update_yaxes(title_text="Sağlık", range=[0, 100], row=3, col=1)
    return fig


def _render_time_section(a, uni, universe_tickers, fetch_fn):
    st.markdown("---")
    st.markdown('<div id="pf-time"></div>', unsafe_allow_html=True)
    st.markdown("### ⏳ Zaman yolculuğu ve geriye dönük test")
    if not st.toggle("Zaman bölümünü aç", key="pf_time_on",
                     help="Daha uzun fiyat geçmişi yükler (ilk açılışta 1-2 dk; sonra 1 saat önbellekte)."):
        st.caption("Korelasyon haritasını zamanda oynatır, portföy sağlığının geçmişini gösterir ve "
                   "ağırlık yöntemlerini aylık yeniden dengeleme ile geriye dönük karşılaştırır.")
        return
    s, window = a["s"], a["lookback"]
    c1, c2, c3 = st.columns(3)
    step_label = c1.selectbox("Adım / yeniden dengeleme", list(TIME_STEPS), key="pf_time_step")
    years_label = c2.selectbox("Test süresi", list(TIME_YEARS), index=1, key="pf_time_years")
    cost_bp = c3.number_input("İşlem maliyeti (bp, taraf başı)", 0, 200, 10, 5, key="pf_time_cost",
                              help="Her yeniden dengelemede alınıp satılan tutar × bu oran kesilir "
                                   "(10 bp = %0.1).")
    step, years = TIME_STEPS[step_label], TIME_YEARS[years_label]
    with st.spinner("Uzun fiyat geçmişi yükleniyor (ilk seferde 1-2 dk)..."):
        data = _time_data(universe_tickers, window, years, fetch_fn)
    if data is None:
        st.warning("Evren fiyatları alınamadı.")
        return
    urets, bench_ret = data
    basket = [t for t in _basket() if t in urets.columns]
    ends = pa.time_grid(len(urets), window, step)
    if len(ends) < 3:
        st.warning("Bu geriye bakış ve adım için yeterli geçmiş yok; test süresini artır veya "
                   "geriye bakışı kısalt.")
        return
    if len(basket) < 2:
        st.info("Zaman analizi için sepette, geçmişi yeterli en az 2 hisse olmalı.")
        return
    skipped = [t for t in _basket() if t not in urets.columns]
    if skipped:
        st.caption("Geçmişi yetersiz, testte olmayan hisseler: " + ", ".join(skipped))
    st.caption(f"Pencere = ayarlardaki geriye bakış ({window} gün) · {len(ends)} kare "
               f"({pd.Timestamp(urets.index[ends[0]]).date()} → {pd.Timestamp(urets.index[ends[-1]]).date()}) · "
               "her karedeki ağırlık yalnızca o güne kadarki veriyle hesaplanır.")

    # ── yöntem karşılaştırması ──
    primary, presets = _method_specs(s, a.get("manual"))
    chosen = st.multiselect("Karşılaştırılacak yöntemler (ayardaki yöntem her zaman dahil)",
                            PRESET_LABELS, default=PRESET_DEFAULT, key="pf_time_methods")
    specs: dict = {primary[0]: primary[1]}
    seen = {_spec_key(primary[1])}
    for lab in chosen:
        k = _spec_key(presets[lab])
        if k not in seen:
            seen.add(k)
            specs[lab] = presets[lab]

    sub = urets[basket]
    sig = _df_sig(sub)
    overall = tuple(_num(uni.loc[t, "overall_puani"]) if t in uni.index else np.nan for t in basket)
    results, errs = {}, []
    with st.spinner(f"Geriye dönük test hesaplanıyor ({len(specs)} yöntem)..."):
        for lab, sp in specs.items():
            try:
                results[lab] = _cached_walk(
                    sub, sig, window, step, sp["method"], s["max_w"], s["rf"], overall,
                    sp.get("tilt", 2.0), sp.get("mom_tilt", 0.0),
                    tuple(sorted(sp["manual"].items())) if sp.get("manual") else None, cost_bp / 1e4)
            except Exception as e:                              # tek yöntem hatası diğerlerini bozmasın
                errs.append(f"{lab}: {e}")
    for e in errs:
        st.warning("Hesaplanamadı — " + e)
    if not results:
        return
    first_label = next(iter(results))
    res0 = results[first_label]

    # ── getiri eğrileri + tablo ──
    t0, t1 = res0["port"].index[0], res0["port"].index[-1]
    st.markdown(f"#### 📈 Geriye dönük sonuç ({t0.date()} → {t1.date()})")
    eq = go.Figure()
    palette = pcolors.qualitative.Safe
    for i, (lab, r) in enumerate(results.items()):
        cum = 100.0 * (1.0 + r["port"]).cumprod()
        eq.add_trace(go.Scatter(x=cum.index, y=cum.values, name=lab, mode="lines",
                                line=dict(width=3.5 if i == 0 else 1.8, color=palette[i % len(palette)])))
    bser = None
    if bench_ret is not None:
        bser = bench_ret.reindex(res0["port"].index).fillna(0.0)
        bc = 100.0 * (1.0 + bser).cumprod()
        eq.add_trace(go.Scatter(x=bc.index, y=bc.values, name="XU100", mode="lines",
                                line=dict(width=2, color="gray", dash="dot")))
    eq.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Değer (başlangıç=100)",
                     legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(eq, use_container_width=True, config=PLOTLY_CFG, key="pf_time_equity")

    rows = []
    for lab, r in results.items():
        m = pa.portfolio_metrics(r["port"], bench_ret, s["rf"])
        ann_turn = (r["turnover"].iloc[1:].mean() * 252.0 / step) if len(r["turnover"]) > 1 else np.nan
        sp = specs[lab]
        look = sp["method"] == "quality_rp" and sp.get("tilt", 0.0) > 0
        rows.append({"Yöntem": lab, "Yıllık getiri % (bileşik)": m["cagr"] * 100, "Volatilite %": m["vol"] * 100,
                     "Sharpe": m["sharpe"], "Sortino": m["sortino"], "Max DD %": m["max_dd"] * 100,
                     "Beta": m["beta"], "Yıllık devir %": ann_turn * 100,
                     "Toplam maliyet %": float(r["cost_paid"].iloc[:-1].sum()) * 100,
                     "Bitiş (100 →)": 100.0 * (1 + m["total_return"]),
                     "Not": "⚠️ ileriye bakış" if look else ""})
    if bser is not None:
        mb = pa.portfolio_metrics(bser, None, s["rf"])
        rows.append({"Yöntem": "XU100 (endeks)", "Yıllık getiri % (bileşik)": mb["cagr"] * 100,
                     "Volatilite %": mb["vol"] * 100, "Sharpe": mb["sharpe"], "Sortino": mb["sortino"],
                     "Max DD %": mb["max_dd"] * 100, "Beta": 1.0, "Yıllık devir %": np.nan,
                     "Toplam maliyet %": np.nan, "Bitiş (100 →)": 100.0 * (1 + mb["total_return"]), "Not": ""})
    st.dataframe(pd.DataFrame(rows).set_index("Yöntem").round(2), use_container_width=True)
    warns = ["Sepeti **bugün** seçtin: geçmişte iyi görünmesi seçim yanlılığıdır, geleceği garanti etmez.",
             f"Maliyet: taraf başı {cost_bp} bp uygulandı; vergi/kayma yok. Sharpe/Sortino risksiz faiz "
             f"%{s['rf'] * 100:.1f} ile hesaplandı."]
    if any(sp["method"] == "quality_rp" and sp.get("tilt", 0.0) > 0 for sp in specs.values()):
        warns.append("⚠️ **Kalite eğimi ileriye bakış yanlılığı taşır:** veritabanında tek rapor dönemi "
                     "olduğundan güncel Overall puanları tüm geçmişe uygulanıyor; o dönemde bu puanlar "
                     "bilinmiyordu. Momentum ve risk parity için bu sorun yok.")
    for w_ in warns:
        st.caption("• " + w_)

    # ── ağırlıkların zamanla değişimi (ayardaki yöntem) ──
    st.markdown(f"#### ⚖️ Ağırlıklar zamanla — {first_label.lstrip('▶ ')}")
    W = res0["weights"]
    sec_of = {t: (uni.loc[t, "sektor"] if t in uni.index and pd.notna(uni.loc[t, "sektor"]) else UNASSIGNED)
              for t in basket}
    wf = go.Figure()
    for i, t in enumerate(basket):
        wf.add_trace(go.Scatter(x=W.index, y=W[t] * 100, name=t, mode="lines", stackgroup="w",
                                line=dict(width=0.5, shape="hv"),
                                hovertemplate=f"{t} ({sec_of[t]}): %{{y:.1f}}%<extra></extra>"))
    wf.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Ağırlık %",
                     yaxis_range=[0, 100], legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(wf, use_container_width=True, config=PLOTLY_CFG, key="pf_time_weights")
    st.caption(f"Yıllık ortalama devir: %{res0['turnover'].iloc[1:].mean() * 252.0 / step * 100:.0f} "
               "(tek yön). Ağırlıkların sıçraması yöntemin kararsızlığını, yumuşak akışı kararlılığını gösterir.")
    for note in res0["notes"]:
        st.caption("• " + note)

    # ── animasyon + nabız şeridi ──
    st.markdown("#### 🎞️ Korelasyon haritası zamanda")
    with st.spinner("Kayan pencere haritası hesaplanıyor..."):
        tf = _cached_embedding(urets, _df_sig(urets, window, step), window, step)
        sector_of = {t: (uni.loc[t, "sektor"] if t in uni.index and pd.notna(uni.loc[t, "sektor"])
                         else UNASSIGNED) for t in basket}
        overall_of = {t: (None if np.isnan(v) else v) for t, v in zip(basket, overall)}
        health = pa.health_over_time(sub, ends, window, W, sector_of, overall_of)
        if bench_ret is not None:
            bcum = (1.0 + bench_ret.fillna(0.0)).cumprod()
            bench_dd = ((bcum / bcum.cummax() - 1.0) * 100.0).iloc[ends].values
        else:
            bench_dd = np.full(len(ends), np.nan)
    if health.empty:
        st.info("Portföy sağlığı hesaplanamadı (uygun pencere yok).")
        return
    health = health.reindex(tf["dates"])
    fig = _time_figure(tf, basket, W, health, bench_dd, uni)
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG, key="pf_time_chart")
    st.caption("▶ ile oynat ya da çubuğu sürükle. Altın vektör o tarihteki walk-forward portföyüdür; "
               "kuyruklu izler son birkaç karenin yolunu gösterir. Stres dönemlerinde (kırmızı alan: "
               "XU100 düşüşü) ortalama korelasyon yükselir ve bulut tek faktöre doğru büzülür. "
               "Eksenler kareler arası hizalanmıştır (Procrustes), bu yüzden hareket gerçek "
               "korelasyon değişimidir.")


# ───────────────────────── ana giriş ─────────────────────────

def display_portfolio_builder(fetch_fn, valuation_fn=None, valuation_history_fn=None,
                              financial_loader=None):
    """fetch_fn: streamlit_app.fetch_stock_data (symbol, start_date=, interval=).
    valuation_fn / valuation_history_fn / financial_loader: streamlit_app'teki değerleme
    fonksiyonları (compute_stock_valuations, compute_valuation_history, _load_financial_store_for);
    verilmezse hedef fiyat bölümü devre dışı kalır."""
    deps = dict(valuation=valuation_fn, history=valuation_history_fn, loader=financial_loader)
    st.markdown("### 📐 Portföy Çalışma Alanı")
    st.caption("En iyi sektörlere bak, her sektörden beğendiğin hisseleri seç; portföy kutusu "
               "risk bazlı ağırlıkları, riski ve sağlık skorunu canlı hesaplasın. "
               "Veriler 📄 Company Reports'tan gelir. Yatırım tavsiyesi değildir.")

    periods = get_available_periods_for_rollup()
    if periods is None or periods.empty:
        st.info("Henüz kayıtlı şirket raporu yok — önce 📄 Company Reports bölümünden rapor ekle.")
        return
    options = [(int(r.yil), r.donem) for r in periods.itertuples()]
    top = st.columns([4, 1])
    with top[0]:
        yil, donem = st.selectbox("Rapor dönemi", options, key="pf_period",
                                  format_func=lambda p: f"{DONEM_LABELS.get(p[1], p[1])} {p[0]}")
    with top[1]:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        st.button("🔄 Güncelle", on_click=_do_update, use_container_width=True,
                  help="Company Reports'taki güncel rapor/sektör verilerini ve fiyat verilerini yeniden "
                       "yükler; yeni eklediğin şirketler listeye gelir. Gemini çağrısı yapmaz. Yeni bir "
                       "sektörün skoru için Company Reports › Sektör Analizi › Hesapla/Yenile gerekir.")

    reports = get_reports_for_period(yil, donem)
    if reports is None or reports.empty:
        st.info("Bu dönem için kayıtlı rapor yok.")
        return
    rollup = get_sector_rollup(yil, donem)
    uni = reports.drop_duplicates("ticker").set_index("ticker", drop=False)
    sector_score = ({r.sektor: r.sektor_skoru for r in rollup.itertuples()}
                    if rollup is not None and not rollup.empty else {})

    known = st.session_state.setdefault("pf_known_tickers", {})
    current = set(uni.index)
    if st.session_state.pop("pf_update_requested", False):
        prev = known.get((yil, donem))
        new = sorted(current - prev) if prev is not None else []
        msg = f"✅ Güncellendi: {len(current)} şirket yüklendi."
        if new:
            msg += f" **{len(new)} yeni hisse:** {', '.join(new)}."
        elif prev is not None:
            msg += " Yeni eklenen hisse yok."
        st.success(msg)
    known[(yil, donem)] = current
    _autoload_default()

    ver = st.session_state.get("pf_ver", 0)
    basket = list(_basket())
    st.markdown(STICKY_CSS, unsafe_allow_html=True)
    left, right = st.columns([3, 2])
    box = st.container()      # görsel olarak sütunların altı; içi aşağıda (kod sırasıyla) doldurulur

    # 1) sektör seçici - sepet burada kesinleşir
    with left:
        st.markdown("#### 🏭 Sektörler (sektör skoruna göre)")
        picked: dict = {}
        for sektor, skor, makro, df in _sector_groups(reports, rollup):
            picked[sektor] = (set(df["ticker"]), _render_sector(sektor, skor, makro, df, ver, basket))
        new_basket = list(basket)
        for _, (sector_tickers, checked) in picked.items():
            new_basket = [t for t in new_basket if t not in sector_tickers or t in checked]
            new_basket += [t for t in checked if t not in new_basket]
        st.session_state["pf_basket"] = new_basket

    # 2) ayarlar + analiz (harita ve sonuçlar bunu kullanır)
    tickers = list(_basket())
    analysis = None
    with box:
        if tickers:
            st.markdown("---")
            st.markdown('<div id="pf-box"></div>', unsafe_allow_html=True)
            st.markdown("### 💼 Portföy kutusu")
            s = _render_settings()
            manual = _render_manual(tickers) if s["source"] == "Elle" else None
            analysis = _analyze(tickers, uni, fetch_fn, s, manual)
            if "error" in analysis:
                st.error(analysis["error"])
            elif "single" in analysis:
                st.info("Optimizasyon için en az 2 hisse gerekli (ortak geçmişi yeterli olan). "
                        "Tek hissenin istatistikleri aşağıda.")
                st.dataframe(analysis["single"], use_container_width=True)
        else:
            st.info("💡 Portföy kutusu, sepete hisse eklediğinde burada belirir.")

    # 3) sağ sütun: harita + sepet
    with right:
        _render_map(analysis if analysis and "names" in analysis else None, uni, sector_score,
                    list(uni.index), fetch_fn)
        _render_saved_portfolio()
        _render_basket_panel(uni)

    # 4) portföy sonuçları
    if analysis and "names" in analysis:
        with box:
            _render_results(analysis, uni, list(uni.index), fetch_fn, deps)
            _render_time_section(analysis, uni, list(uni.index), fetch_fn)
