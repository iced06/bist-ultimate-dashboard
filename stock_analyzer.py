"""🔬 Stock Analyzer: rapor evreninde Görünüm puanı hesaplanmış TÜM hisseler için
(1) hedef fiyat ve ucuzluk önceliği (+ kalite–ucuzluk haritası, çarpan karşılaştırmaları),
(2) beklenen getiri – risk dağılımı ("yüksek getiri / düşük risk" bölgesi vurgulu, Görünüm işaretli).

Hesaplama Portföy ekranıyla AYNI fonksiyonları kullanır (portfoy_olusturucu / portfolio_valuation /
portfolio_factors); fark: sepet yerine bütün evren, ağırlık yerine sabit nokta boyutu.
"""
import hashlib
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import portfolio_analytics as pa
import portfolio_factors as pf
import portfolio_valuation as pv
from portfoy_olusturucu import (
    LABEL_ICON, LOOKBACKS, PLACEHOLDER, PLOTLY_CFG, UNASSIGNED,
    _build_valuation_results, _default_rf, _fnum, _gorunum_mark, _load_close_prices, _market_window,
    _map_figure, _metric, _num, _peer_valuations, _render_multiple_tables, _render_valuation_notes,
    _return_risk_figure, _to_calendar, _val_history,
)
from sirket_raporlari import DONEM_LABELS, get_available_periods_for_rollup, get_reports_for_period

RET_SOURCES = ["Markowitz (tarihsel, shrunk)", "PCA faktör modeli"]
LABEL_COLOR = {"Çok ucuz": "#2E9E4F", "Ucuz": "#7BC96F", "Makul": "#9AA5B8", "Pahalı": "#F2994A",
               "Çok pahalı": "#E5534B", "—": "#9AA5B8"}


def _quality_cheapness_figure(results, order):
    fig = go.Figure()
    ups = {t: results[t]["upside"] for t in order if np.isfinite(results[t]["upside"]) and results[t]["overall"] is not None}
    label_set = set(sorted(ups, key=ups.get, reverse=True)[:10] + sorted(ups, key=ups.get)[:5])
    for lab in ("Çok ucuz", "Ucuz", "Makul", "Pahalı", "Çok pahalı"):
        ts = [t for t in ups if results[t]["label"] == lab]
        if not ts:
            continue
        fig.add_trace(go.Scatter(
            x=[results[t]["overall"] for t in ts], y=[ups[t] * 100 for t in ts], mode="markers+text", name=lab,
            text=[t if t in label_set else "" for t in ts], textposition="top center", textfont=dict(size=9),
            marker=dict(size=11, color=LABEL_COLOR[lab], opacity=0.85, line=dict(width=0.5, color="white")),
            customdata=[[t, results[t]["gorunum"] if results[t]["gorunum"] is not None else np.nan] for t in ts],
            hovertemplate="<b>%{customdata[0]}</b><br>Overall %{x:.1f}<br>Potansiyel %{y:+.0f}%<br>"
                          "Görünüm %{customdata[1]:.1f}<extra></extra>"))
    fig.add_hline(y=0, line_dash="dot", line_color="gray")
    fig.update_layout(title="Kalite – ucuzluk haritası (sağ üst: yüksek puanlı ve ucuz)", height=420,
                      xaxis_title="Overall puanı", yaxis_title="Potansiyel %",
                      margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h", y=-0.2))
    return fig


def display_stock_analyzer(fetch_fn, valuation_fn=None, valuation_history_fn=None, financial_loader=None):
    st.markdown("### 🔬 Stock Analyzer")
    st.caption("Company Reports'ta Görünüm puanı hesaplanmış tüm hisseler için hedef fiyat / ucuzluk önceliği ve "
               "beklenen getiri – risk dağılımı. Veriler 📄 Company Reports ve finansal veri tabanından gelir. "
               "Yatırım tavsiyesi değildir.")
    if not valuation_fn or not financial_loader:
        st.warning("Değerleme fonksiyonları bu ortamda yüklenemedi.")
        return

    periods = get_available_periods_for_rollup()
    if periods is None or periods.empty:
        st.info("Henüz kayıtlı şirket raporu yok — önce 📄 Company Reports bölümünden rapor ekle.")
        return
    options = [(int(r.yil), r.donem) for r in periods.itertuples()]
    yil, donem = st.selectbox("Rapor dönemi", options, key="sa_period",
                              format_func=lambda p: f"{DONEM_LABELS.get(p[1], p[1])} {p[0]}")
    reports = get_reports_for_period(yil, donem)
    if reports is None or reports.empty:
        st.info("Bu dönem için kayıtlı rapor yok.")
        return
    uni = reports.drop_duplicates("ticker").set_index("ticker", drop=False)
    scored = uni[pd.to_numeric(uni["gorunum_puani"], errors="coerce").notna()]
    st.caption(f"{len(uni)} şirket raporu · {len(scored)} hissede Görünüm puanı hesaplanmış.")
    if scored.empty:
        st.info("Bu dönemde Görünüm puanı hesaplanmış hisse yok (Company Reports › Sektör Analizi › Hesapla).")
        return

    sectors = sorted({s for s in scored["sektor"].dropna().unique()})
    if st.session_state.get("sa_sector") not in ["Tümü"] + sectors:
        st.session_state["sa_sector"] = "Tümü"
    st.session_state.setdefault("sa_lookback", "1 yıl")
    st.session_state.setdefault("sa_ret_src", RET_SOURCES[0])
    st.session_state.setdefault("sa_whist", 50)
    st.session_state.setdefault("sa_kq", 10)
    st.session_state.setdefault("sa_ko", 5)
    c1, c2, c3 = st.columns(3)
    sector_pick = c1.selectbox("Sektör filtresi (gösterim)", ["Tümü"] + sectors, key="sa_sector",
                               help="Yalnızca gösterimi süzer; sektör medyanları ve karşılaştırmalar tüm evrenle "
                                    "hesaplanır.")
    lb_label = c2.selectbox("Geriye bakış (getiri–risk)", list(LOOKBACKS), key="sa_lookback")
    ret_src = c3.selectbox("Beklenen getiri kaynağı", RET_SOURCES, key="sa_ret_src",
                           help="Markowitz: tarihsel ortalamanın kesit ortalamasına %50 çekilmiş hali. PCA: yalnızca "
                                "ortak faktörlerle açıklanan kısım.")
    with st.expander("⚙️ Hedef fiyat varsayımları", expanded=False):
        e1, e2, e3, e4 = st.columns(4)
        w_hist = e1.slider("Geçmiş medyanın ağırlığı %", 0, 100, step=10, key="sa_whist")
        k_q = e2.slider("Kalite primi (Overall, puan başına %)", 0, 25, key="sa_kq")
        k_o = e3.slider("Görünüm primi (puan başına %)", 0, 15, key="sa_ko")
        rf_def = _default_rf()
        rf = e4.number_input("Risksiz faiz % (yıllık)", 0.0, 150.0, round((rf_def or 0.35) * 100, 1), 0.5,
                             key="sa_rf") / 100.0
    params = dict(w_hist=w_hist / 100.0, k_quality=k_q / 100.0, k_outlook=k_o / 100.0)

    if not st.toggle("Analizi çalıştır", key="sa_on",
                     help="Evrenin 6 yıllık fiyatlarını ve finansallarını yükler (ilk açılışta birkaç dakika; sonra "
                          "30 dk önbellekte)."):
        st.info("Analizi başlatmak için üstteki 'Analizi çalıştır' anahtarını aç (ilk seferde birkaç dakika sürer).")
        return

    lookback = LOOKBACKS[lb_label]
    uni_t = tuple(sorted(uni.index))
    with st.spinner("Finansallar, fiyatlar ve çarpanlar hesaplanıyor (ilk seferde birkaç dakika)..."):
        fin = financial_loader(uni_t)
        start, bench_px = _market_window(lookback, fetch_fn)
        uprices, _ = _load_close_prices(uni_t, start, fetch_fn)
        if uprices.empty:
            st.warning("Evren fiyatları alınamadı.")
            return
        last = {t: float(uprices[t].dropna().iloc[-1]) for t in uprices.columns if uprices[t].notna().any()}
        items = tuple((t, round(last[t], 4)) for t in uni_t if t in fin and t in last)
        sig = hashlib.md5("|".join(f"{t}:{p}" for t, p in items).encode()).hexdigest()[:12]
        peers = _peer_valuations(valuation_fn, fin, sig, items)
        hists = {}
        if valuation_history_fn and peers:
            long_start = (date.today() - timedelta(days=6 * 366)).isoformat()
            long_px, _ = _load_close_prices(tuple(sorted(peers)), long_start, fetch_fn)
            for t in peers:
                if t in long_px.columns and long_px[t].notna().any():
                    s_ = long_px[t].dropna()
                    hists[t] = _val_history(valuation_history_fn, t, fin[t], s_, f"{t}:{s_.index[-1]}:{len(s_)}")
    if not peers:
        st.info("Finansal veri bulunamadı (Financial Data içe aktarılmamış olabilir).")
        return

    results, sector_all = _build_valuation_results(uni, list(scored.index), last, peers, hists, params)
    shown = [t for t in scored.index if t in results and (sector_pick == "Tümü" or scored.loc[t, "sektor"] == sector_pick)]

    # ───────────── 1) hedef fiyat ve ucuzluk önceliği ─────────────
    st.markdown("---")
    st.markdown("### 🎯 Hedef fiyat ve ucuzluk önceliği")
    if not shown:
        st.info("Seçilen filtrede değerlemesi hesaplanabilen hisse yok.")
    else:
        pr_all = pv.prioritize({t: results[t] for t in results})              # sıra tüm evrene göre
        pr_df = pr_all[pr_all["ticker"].isin(shown)].reset_index(drop=True)
        ok = pr_df[pr_df["upside"].notna()]
        k1, k2, k3, k4 = st.columns(4)
        _metric(k1, "Hedefi hesaplanan", f"{len(ok)} / {len(pr_df)}", "gösterilen hisseler")
        if len(ok):
            okc = ok[ok["confidence"] != "Düşük"]
            okc = okc if len(okc) else ok
            _metric(k2, "En ucuz", okc.iloc[0]["ticker"], f"%{okc.iloc[0]['upside'] * 100:+.0f} potansiyel")
            _metric(k3, "En pahalı", okc.sort_values("upside").iloc[0]["ticker"],
                    f"%{okc['upside'].min() * 100:+.0f} potansiyel")
            _metric(k4, "Ucuz/pahalı", f"{int((ok['upside'] >= 0.10).sum())} / {int((ok['upside'] <= -0.10).sum())}",
                    "≥%10 / ≤−%10 potansiyel")
        show = pd.DataFrame({
            "Öncelik": pr_df["rank"],
            "Hisse": [t + _gorunum_mark(results[t]["gorunum"]) for t in pr_df["ticker"]],
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
        st.dataframe(show, hide_index=True, use_container_width=True, height=min(640, 38 * (len(show) + 1)),
                     column_config={
                         "Öncelik": st.column_config.NumberColumn(
                             format="%d", help="1 = en ucuz (potansiyele göre, tüm evren içinde)."),
                         "Fiyat ₺": st.column_config.NumberColumn(format="%.2f"),
                         "Hedef fiyat ₺": st.column_config.NumberColumn(format="%.2f"),
                         "Potansiyel %": st.column_config.NumberColumn(format="%+.1f"),
                         "Overall": st.column_config.NumberColumn(format="%.1f"),
                         "Görünüm": st.column_config.NumberColumn(format="%.1f"),
                         "Kalite çarpanı": st.column_config.NumberColumn(format="%.2f")})
        st.caption("Hisse yanındaki işaret Görünüm puanı: **\\*** 4 üzeri, **+** 3–4 arası, **-** 3 altı. Güveni "
                   "'Düşük' olan hedefler (uç değer sınırına çarpan ya da zayıf referanslı) güvenilir olanların "
                   "ARDINA sıralanır; 'En ucuz/En pahalı' kutuları da güvenilir hedeflerden seçilir.")
        n_rej = [t for t in shown if results[t]["rejected"]]
        if n_rej:
            st.caption("ℹ️ Mekanik kâr tahmini uç olan çarpanlar hedefe katılmadı (Not sütunu): " + ", ".join(n_rej))
        missing = [t for t in scored.index if t not in results and (sector_pick == "Tümü"
                                                                  or scored.loc[t, "sektor"] == sector_pick)]
        if missing:
            st.caption("Değerleme hesaplanamayan hisseler (finansal veri yok): " + ", ".join(missing))
        if any(results[t]["clipped"] for t in shown):
            st.caption("⚠️ Bazı hedef fiyatlar uç değer koruması nedeniyle fiyatın 0.5x–2x'i ile sınırlandı.")
        fig_q = _quality_cheapness_figure(results, list(pr_df["ticker"]))
        if len(fig_q.data):
            st.plotly_chart(fig_q, use_container_width=True, config=PLOTLY_CFG, key="sa_quality_cheapness")
        with st.expander("🔬 Çarpan karşılaştırması: güncel · geçmiş · sektör"):
            _render_multiple_tables(results, list(pr_df["ticker"]))
        _render_valuation_notes(w_hist, k_q, k_o)

    # ───────────── 2) beklenen getiri – risk ─────────────
    up = _to_calendar(uprices, (bench_px.index if bench_px is not None else uprices.index)[-(lookback + 1):])
    returns, dropped = pa.build_returns(up, min_obs=max(60, int(0.75 * lookback)))
    if returns.shape[1] < 5:
        st.markdown("---")
        st.markdown("### 📈 Beklenen getiri – risk dağılımı")
        st.info("Ortak tarih penceresinde yeterli hisse kalmadı; geriye bakışı kısaltmayı dene.")
        return
    cov_d, shrink = pa.ledoit_wolf_cov(returns.values)
    cov = cov_d * pa.TRADING_DAYS
    mu_hist = returns.mean().values * pa.TRADING_DAYS
    names_all = list(returns.columns)
    sig_all = np.sqrt(np.diag(cov))
    urets = (up / up.shift(1) - 1.0).iloc[1:].replace([np.inf, -np.inf], np.nan)
    if ret_src == RET_SOURCES[1]:
        pca = pf.pca_factor_mu(urets, k=3)
        mu_all = np.array([float(pca["mu"].get(t, np.nan)) for t in names_all])
        src_note = (f"PCA: 3 faktör evren varyansının %{pca['explained'].sum() * 100:.0f}'ini açıklıyor; beklenen "
                    "getiri yalnızca ortak faktörlerle açıklanan kısım.")
    else:
        mu_all = 0.5 * mu_hist + 0.5 * mu_hist.mean()
        src_note = (f"Markowitz: tarihsel ortalamanın kesit ortalamasına %50 çekilmiş hali; risk Ledoit-Wolf "
                    f"kovaryansı (shrinkage %{shrink * 100:.0f}).")
    _render_return_risk_section(scored, results, names_all, mu_all, sig_all, rf, sector_pick, ret_src, lb_label,
                                src_note, dropped)

    # ───────────── 3) model portföy ─────────────
    bench_ret = ((bench_px / bench_px.shift(1) - 1.0).reindex(urets.index) if bench_px is not None else None)
    _render_model_portfolio(uni, scored, results, names_all, mu_all, cov, rf, urets, bench_ret, ret_src, lookback)


def _render_return_risk_section(scored, results, names_all, mu_all, sig_all, rf, sector_pick, ret_src, lb_label,
                                src_note, dropped):
    st.markdown("---")
    st.markdown("### 📈 Beklenen getiri – risk dağılımı")
    sel = [i for i, t in enumerate(names_all) if t in scored.index and np.isfinite(mu_all[i])
           and (sector_pick == "Tümü" or scored.loc[t, "sektor"] == sector_pick)]
    if len(sel) < 3:
        st.info("Gösterilecek yeterli hisse yok.")
        return
    nm = [names_all[i] for i in sel]
    mu_ = mu_all[sel]
    sg_ = sig_all[sel]
    gv = np.array([_num(scored.loc[t, "gorunum_puani"]) for t in nm])
    ov = np.array([_num(scored.loc[t, "overall_puani"]) for t in nm])
    ups = np.array([(results[t]["upside"] * 100 if t in results and np.isfinite(results[t]["upside"]) else np.nan)
                    for t in nm])
    fz, in_zone = _return_risk_figure(
        nm, mu_, sg_, rf, [t + _gorunum_mark(g) for t, g in zip(nm, gv)], gv, [11] * len(nm),
        extras=[("Overall", ov, ".1f", ""), ("Potansiyel", ups, "+.0f", "%")],
        title=f"Hisse bazında beklenen getiri – risk ({ret_src.split(' (')[0]}, {lb_label})",
        ytitle=f"Beklenen getiri % ({ret_src.split(' (')[0]})", height=600)
    fz.update_traces(textfont=dict(size=9), selector=dict(name="Hisseler"))
    st.plotly_chart(fz, use_container_width=True, config=PLOTLY_CFG, key="sa_ret_risk_scatter")
    sharpe = (mu_ - rf) / sg_
    zone = sorted((t for t, z in zip(nm, in_zone) if z), key=lambda t: -sharpe[nm.index(t)])
    st.caption(f"🟩 Yeşil bölge: risk (σ) gösterilen hisselerin medyanının altında, beklenen getiri medyanının üstünde "
               f"— göreli bir ayrım. Etiket işareti Görünüm puanı: **\\*** 4 üzeri, **+** 3–4, **-** 3 altı. {src_note} "
               + (f"Bölgedeki hisseler (getiri/risk sırasıyla): {', '.join(zone)}." if zone else "Bölgede hisse yok."))
    if dropped:
        st.caption("Geçmişi kısa olduğu için getiri–risk hesabına girmeyenler: " + ", ".join(sorted(dropped)))

    summ = pd.DataFrame({
        "Hisse": nm, "Sektör": [scored.loc[t, "sektor"] for t in nm],
        "Overall": ov, "Görünüm": gv, "Görünüm işareti": [_gorunum_mark(g).strip() for g in gv],
        "Potansiyel %": ups,
        "Ucuzluk": [results[t]["label"] if t in results else "—" for t in nm],
        "Beklenen getiri %": mu_ * 100, "Risk σ %": sg_ * 100, "Getiri/Risk": sharpe,
        "Yüksek getiri · düşük risk": ["✅" if z else "" for z in in_zone],
    }).sort_values("Getiri/Risk", ascending=False)
    st.markdown("**Hisse özeti — kalite, ucuzluk ve getiri/risk birlikte**")
    st.dataframe(summ, hide_index=True, use_container_width=True, height=min(640, 38 * (len(summ) + 1)),
                 column_config={c: st.column_config.NumberColumn(format="%.1f") for c in
                                ("Overall", "Görünüm", "Beklenen getiri %", "Risk σ %")} | {
                     "Potansiyel %": st.column_config.NumberColumn(format="%+.1f"),
                     "Getiri/Risk": st.column_config.NumberColumn(format="%.2f")})


CONF_WEIGHT = {"Yüksek": 1.0, "Orta": 0.6, "Düşük": 0.25}


@st.cache_data(ttl=1800, show_spinner=False)
def _model_select(mu, cov, sectors, k, objective, gamma, rf, cap, min_w, sector_cap):
    sel = pa.select_model_portfolio(np.asarray(mu), np.asarray(cov), list(sectors), k=k, objective=objective,
                                    gamma=gamma, rf=rf, cap=cap, min_w=min_w, sector_cap=sector_cap)
    return {"idx": [int(i) for i in sel["idx"]], "weights": np.asarray(sel["weights"]), "objective": sel["objective"],
            "notes": list(sel["notes"])}


def _send_to_portfolio(tickers):
    """Model portföyü Portföy sekmesindeki sepete aktarır (kayıtlı portföyden ayrılır)."""
    ss = st.session_state
    ss["pf_basket"] = list(tickers)
    ss["pf_ver"] = ss.get("pf_ver", 0) + 1
    ss["pf_active"] = None
    ss["pf_saved_sel"] = PLACEHOLDER
    ss.pop("pf_snapshot", None)
    ss["pf_store_msg"] = ("ok", f"Stock Analyzer model portföyü sepete aktarıldı ({len(tickers)} hisse).")
    ss["sa_mp_sent"] = True


def _render_model_portfolio(uni, scored, results, names_all, mu_base, cov, rf, urets, bench_ret, ret_src, lookback):
    st.markdown("---")
    st.markdown("### 🧺 Model portföy")
    st.caption("Evrenden, beklenen getiriyi risk karşılığında en çok artıracak hisseleri seçip ağırlıklandırır "
               "(kardinalite kısıtlı ortalama-varyans optimizasyonu). Beklenen getiri = seçili kaynak + hedef fiyat "
               "potansiyelinin güvene göre ağırlıklı payı. Yatırım tavsiyesi değildir.")
    st.session_state.setdefault("sa_mp_k", 15)
    st.session_state.setdefault("sa_mp_obj", "Fayda: getiri − risk cezası (önerilen)")
    st.session_state.setdefault("sa_mp_gamma", 4.0)
    st.session_state.setdefault("sa_mp_cap", 15)
    st.session_state.setdefault("sa_mp_min", 2)
    st.session_state.setdefault("sa_mp_sec", 35)
    st.session_state.setdefault("sa_mp_tp", 25)
    st.session_state.setdefault("sa_mp_gmin", 0.0)
    with st.expander("⚙️ Model portföy ayarları", expanded=False):
        a1, a2, a3, a4 = st.columns(4)
        k = a1.slider("Hisse sayısı", 5, 30, key="sa_mp_k")
        obj_label = a2.selectbox("Hedef", ["Fayda: getiri − risk cezası (önerilen)", "Maks. Sharpe"], key="sa_mp_obj",
                                 help="Fayda: w'μ − (γ/2)·w'Σw. TL'de risksiz faiz çok yüksek olduğu için Maks. Sharpe "
                                      "çoğu zaman anlamsızlaşır; fayda yaklaşımı bu durumda daha güvenilirdir.")
        gamma = a3.slider("Risk iştahı γ (yüksek = daha temkinli)", 1.0, 12.0, step=0.5, key="sa_mp_gamma")
        tp_w = a4.slider("Hedef fiyat payı %", 0, 100, step=5, key="sa_mp_tp",
                         help="Beklenen getiriye, hedef fiyat potansiyelinin (−%50..+%100 ile sınırlı) güven ile "
                              "çarpılmış bu yüzdesi eklenir. 0 = yalnızca tarihsel/PCA kaynağı.")
        b1, b2, b3, b4 = st.columns(4)
        cap = b1.slider("Hisse başına üst sınır %", 8, 40, key="sa_mp_cap")
        min_w = b2.slider("Hisse başına alt sınır %", 1, 6, key="sa_mp_min")
        sec_cap = b3.slider("Sektör üst sınırı %", 15, 100, step=5, key="sa_mp_sec")
        g_min = b4.slider("En düşük Görünüm puanı", 0.0, 5.0, step=0.5, key="sa_mp_gmin",
                          help="Aday havuzunu Görünüm puanına göre daraltır (0 = hepsi).")
    objective = "sharpe" if obj_label == "Maks. Sharpe" else "utility"

    mu_arr = np.asarray(mu_base, dtype=float)
    pool = []
    for i, t in enumerate(names_all):
        if t not in scored.index or not np.isfinite(mu_arr[i]):
            continue
        g = _num(scored.loc[t, "gorunum_puani"])
        if np.isfinite(g) and g < g_min:
            continue
        pool.append(i)
    if len(pool) < k:
        st.info(f"Aday havuzu ({len(pool)} hisse) istenen hisse sayısından ({k}) küçük; filtreleri gevşet.")
        return
    tick = [names_all[i] for i in pool]
    view = np.array([(np.clip(results[t]["upside"], -0.5, 1.0) * CONF_WEIGHT.get(results[t]["confidence"], 0.0)
                      if t in results and np.isfinite(results[t]["upside"]) else 0.0) for t in tick])
    mu_pool = mu_arr[pool] + (tp_w / 100.0) * view
    cov_pool = cov[np.ix_(pool, pool)]
    secs = tuple(str(scored.loc[t, "sektor"]) if pd.notna(scored.loc[t, "sektor"]) else UNASSIGNED for t in tick)
    with st.spinner("Model portföy optimize ediliyor..."):
        sel = _model_select(tuple(np.round(mu_pool, 8)), cov_pool, secs, int(k), objective, float(gamma), float(rf),
                            cap / 100.0, min_w / 100.0, sec_cap / 100.0)
    ix = sel["idx"]
    w = np.asarray(sel["weights"])
    m_t = [tick[i] for i in ix]
    mu_m, cov_m = mu_pool[ix], cov_pool[np.ix_(ix, ix)]
    sig_m = np.sqrt(np.diag(cov_m))
    rc = pa.risk_contributions(w, cov_m)
    p_ret, p_sig = float(w @ mu_m), float(np.sqrt(w @ cov_m @ w))
    corr_m = cov_m / np.outer(sig_m, sig_m)
    iu = np.triu_indices(len(w), 1)
    eqw = np.full(len(tick), 1.0 / len(tick))
    e_ret, e_sig = float(eqw @ mu_pool), float(np.sqrt(eqw @ cov_pool @ eqw))
    for nt in sel["notes"]:
        st.caption("ℹ️ " + nt)

    k1, k2, k3, k4, k5 = st.columns(5)
    _metric(k1, "Beklenen getiri", f"%{p_ret * 100:.1f}", f"evren eşit ağırlık %{e_ret * 100:.1f}")
    _metric(k2, "Risk σ", f"%{p_sig * 100:.1f}", f"evren eşit ağırlık %{e_sig * 100:.1f}")
    _metric(k3, "Getiri/Risk", _sharpe_txt(p_ret, rf, p_sig), f"risksiz faiz %{rf * 100:.1f}")
    _metric(k4, "Efektif hisse", f"{1.0 / float(np.sum(w ** 2)):.1f} / {len(w)}")
    _metric(k5, "Ort. ikili korelasyon", f"{float(corr_m[iu].mean()):.2f}")

    rows = []
    for t, wi, mu_i, sg_i, rc_i, ix_i in zip(m_t, w, mu_m, sig_m, rc, ix):
        r = results.get(t)
        rows.append({
            "Hisse": t + _gorunum_mark(_num(scored.loc[t, "gorunum_puani"])),
            "Sektör": secs[ix_i],
            "Ağırlık %": wi * 100,
            "Beklenen getiri %": mu_i * 100,
            "Baz getiri % (kaynak)": mu_arr[pool[ix_i]] * 100,
            "Hedef fiyat katkısı %": (tp_w / 100.0) * view[ix_i] * 100,
            "Risk σ %": sg_i * 100,
            "Getiri/Risk": (mu_i - rf) / sg_i,
            "Risk katkısı %": rc_i * 100,
            "Overall": _num(scored.loc[t, "overall_puani"]),
            "Görünüm": _num(scored.loc[t, "gorunum_puani"]),
            "Potansiyel %": (r["upside"] * 100 if r and np.isfinite(r["upside"]) else np.nan),
            "Güven": (r["confidence"] if r else "—"),
        })
    mt = pd.DataFrame(rows)
    st.dataframe(mt, hide_index=True, use_container_width=True, column_config={
        "Ağırlık %": st.column_config.ProgressColumn("Ağırlık %", min_value=0, max_value=float(max(cap, 1)), format="%.1f"),
        "Risk katkısı %": st.column_config.ProgressColumn("Risk katkısı %", min_value=0, max_value=float(max(cap, 1)),
                                                          format="%.1f"),
        "Beklenen getiri %": st.column_config.NumberColumn(format="%.1f"),
        "Baz getiri % (kaynak)": st.column_config.NumberColumn(format="%.1f"),
        "Hedef fiyat katkısı %": st.column_config.NumberColumn(format="%+.1f"),
        "Risk σ %": st.column_config.NumberColumn(format="%.1f"),
        "Getiri/Risk": st.column_config.NumberColumn(format="%.2f"),
        "Overall": st.column_config.NumberColumn(format="%.1f"),
        "Görünüm": st.column_config.NumberColumn(format="%.1f"),
        "Potansiyel %": st.column_config.NumberColumn(format="%+.1f"),
    })
    st.caption(f"Beklenen getiri = baz kaynak ({ret_src.split(' (')[0]}) + hedef fiyat katkısı (potansiyel × güven × "
               f"%{tp_w}). Geriye bakış {lookback} işlem günü; risk Ledoit-Wolf kovaryansı. Hisse yanındaki işaret "
               "Görünüm puanı (**\\*** >4, **+** 3–4, **-** <3). Seçim ve ağırlıklar bir sezgisel optimizasyonun "
               "sonucudur; küçük girdi değişiklikleri portföyü değiştirebilir.")
    st.button("📐 Model portföyü Portföy sekmesine aktar", key="sa_mp_send", on_click=_send_to_portfolio,
              args=(m_t,))
    if st.session_state.pop("sa_mp_sent", False):
        st.success("Aktarıldı: Portföy sekmesinde sepet olarak göreceksin (kaydetmek için Kayıtlı portföy bölümünü kullan).")

    c1, c2 = st.columns(2)
    with c1:
        fb = go.Figure([go.Bar(name="Ağırlık %", x=m_t, y=w * 100), go.Bar(name="Risk katkısı %", x=m_t, y=rc * 100)])
        fb.update_layout(barmode="group", title="Ağırlık vs risk katkısı", height=340,
                         margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h"))
        st.plotly_chart(fb, use_container_width=True, config=PLOTLY_CFG, key="sa_mp_bar")
    with c2:
        sec_w: dict = {}
        for wi, ix_i in zip(w, ix):
            sec_w[secs[ix_i]] = sec_w.get(secs[ix_i], 0.0) + float(wi)
        fp = go.Figure(go.Pie(labels=list(sec_w), values=[v * 100 for v in sec_w.values()], hole=0.45,
                              textinfo="label+percent"))
        fp.update_layout(title="Sektör dağılımı", height=340, margin=dict(l=10, r=10, t=40, b=10), showlegend=False)
        st.plotly_chart(fp, use_container_width=True, config=PLOTLY_CFG, key="sa_mp_sectors")

    gv_m = np.array([_num(scored.loc[t, "gorunum_puani"]) for t in m_t])
    fz, _ = _return_risk_figure(
        m_t, mu_m, sig_m, rf, [t + _gorunum_mark(g) for t, g in zip(m_t, gv_m)], gv_m, [10 + 60 * float(x) for x in w],
        extras=[("Ağırlık", w * 100, ".1f", "%")],
        port_pts=[("Model portföy", (p_sig, p_ret), "red", "star", 18)],
        title="Model portföy: hisse bazında beklenen getiri – risk (nokta büyüklüğü = ağırlık)",
        ytitle="Beklenen getiri % (model)")
    st.plotly_chart(fz, use_container_width=True, config=PLOTLY_CFG, key="sa_mp_scatter")

    # 3B vektör haritası: evrenin korelasyon uzayı, model portföy hisseleri vektörle
    st.markdown("**🌐 Model portföy — 3B vektör haritası (korelasyon uzayı)**")
    min_obs = max(60, int(0.6 * lookback))
    ur = urets.loc[:, urets.notna().sum() >= min_obs]
    coords, expl = pa.correlation_embedding(ur, k=3, min_periods=min_obs)
    miss = [t for t in m_t if t not in coords.index]
    ustats = pa.universe_stats(ur, bench_ret)
    wmap = dict(zip(m_t, w))
    port_vec = (sum(wmap[t] * coords.loc[t].values for t in m_t) if not miss else None)
    titles = [f"Faktör 1 · ortak/piyasa (%{expl[0] * 100:.0f})", f"Faktör 2 (%{expl[1] * 100:.0f})",
              f"Faktör 3 (%{expl[2] * 100:.0f})"]
    fm = _map_figure(coords, uni, ustats, m_t, wmap, titles, True, port_vec)
    fm.update_layout(height=520)
    st.plotly_chart(fm, use_container_width=True, config=PLOTLY_CFG, key="sa_mp_map")
    st.caption(f"3 faktör evrenin korelasyon yapısının %{expl.sum() * 100:.0f}'ini açıklıyor. Seçili 15 hisse orijinden "
               "çıkan vektör, sarı çubuk model portföyün ağırlıklı vektörüdür; vektörler birbirinden ne kadar "
               "açıkken (düşük kosinüs) o kadar çeşitlenmiş demektir." + (f" Haritada olmayanlar: {', '.join(miss)}." if miss else ""))


def _sharpe_txt(r, rf, s):
    return f"{(r - rf) / s:.2f}" if s > 0 else "—"
