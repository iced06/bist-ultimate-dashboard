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
               _load_close_prices, _default_rf):
        fn.clear()
    st.session_state["pf_update_requested"] = True


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
        lb_label = c2.selectbox("Geriye bakış", list(LOOKBACKS), index=1, key="pf_lookback")
        max_w = c3.slider("Hisse başına üst sınır %", 10, 100, 40, 5, key="pf_maxw") / 100.0
        rf_def = _default_rf()
        rf = c4.number_input("Risksiz faiz % (yıllık)", 0.0, 150.0,
                             round((rf_def or 0.35) * 100, 1), 0.5, key="pf_rf",
                             help="Varsayılan: TR 2 yıllık tahvil faizi (alınamazsa %35). "
                                  "Sharpe/Sortino bu değere çok duyarlıdır.") / 100.0
        tilt, mom_tilt = 2.0, 0.0
        if method == "quality_rp":
            t1, t2 = st.columns(2)
            tilt = t1.slider("Kalite eğimi", 0.0, 4.0, 2.0, 0.5, key="pf_tilt",
                             help="Risk bütçesi ∝ Overall puanı^eğim. 0 = kalite etkisiz; "
                                  "yüksek değer iyi puanlı hisselere daha çok risk payı verir.")
            mom_tilt = t2.slider("Momentum eğimi", 0.0, 3.0, 1.0, 0.5, key="pf_mom_tilt",
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
                dropped=dropped, failed=failed, lookback=lookback, start=start, cal=cal, s=s)


def _render_results(a, uni, universe_tickers, fetch_fn):
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
    table = pd.DataFrame({
        "Hisse": names,
        "Sektör": [sector_of[t] for t in names],
        "Ağırlık %": w * 100,
        "Risk katkısı %": rc * 100,
        "Beta": stats["beta"].reindex(names).values,
        "Volatilite %": stats["vol"].reindex(names).values * 100,
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
            "Beta": st.column_config.NumberColumn(format="%.2f"),
            "Volatilite %": st.column_config.NumberColumn(format="%.1f"),
            "Yıllık getiri % (bileşik)": st.column_config.NumberColumn(format="%.1f"),
            "Max DD %": st.column_config.NumberColumn(format="%.1f"),
            "Overall": st.column_config.NumberColumn(format="%.1f"),
        })

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
                    ("Min varyans", pa.optimize_weights("min_var", mu, cov, max_w, rf)[0], "white", "diamond", 11),
                    ("Maks. Sharpe", pa.optimize_weights("max_sharpe", mu, cov, max_w, rf)[0], "orange", "diamond", 11),
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


# ───────────────────────── ana giriş ─────────────────────────

def display_portfolio_builder(fetch_fn):
    """fetch_fn: streamlit_app.fetch_stock_data (symbol, start_date=, interval=)."""
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
        _render_basket_panel(uni)

    # 4) portföy sonuçları
    if analysis and "names" in analysis:
        with box:
            _render_results(analysis, uni, list(uni.index), fetch_fn)
