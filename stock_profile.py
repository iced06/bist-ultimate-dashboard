"""🏢 Single Stock alt bölümleri (yfinance tabanlı, BIST + yabancı hisseler):
  * display_company_profile  - ne iş yapar (Yahoo tanımı + isteğe bağlı Gemini ile Türkçe detaylı anlatım),
                               analist görüşleri / hedef fiyatlar, son haberler
  * display_foreign_fundamentals - yabancı hissenin temel verileri (BIST'teki bilanço bölümünün karşılığı)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import global_data as gd

PLOTLY_CFG = {"displaylogo": False, "displayModeBar": False, "responsive": True}
REC_TR = {"strong_buy": "Güçlü Al", "buy": "Al", "hold": "Tut", "underperform": "Düşük getiri",
          "sell": "Sat", "strong_sell": "Güçlü Sat", "none": "—"}
REC_COLS = [("strongBuy", "Güçlü Al", "#1B7F3B"), ("buy", "Al", "#52B36B"), ("hold", "Tut", "#9AA5B8"),
            ("sell", "Sat", "#F2994A"), ("strongSell", "Güçlü Sat", "#D64545")]


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _big(v, ccy=""):
    v = _num(v)
    if v is None:
        return "—"
    for lim, suf in ((1e12, " Tn"), (1e9, " Mr"), (1e6, " Mn")):
        if abs(v) >= lim:
            return f"{ccy}{v / lim:,.2f}{suf}"
    return f"{ccy}{v:,.0f}"


def _pct(v, signed=False):
    v = _num(v)
    return "—" if v is None else (f"{v * 100:+.1f}%" if signed else f"{v * 100:.1f}%")


def _x(v, nd=1):
    v = _num(v)
    return "—" if v is None else f"{v:.{nd}f}x"


# ───────────────────────── Gemini: Türkçe detaylı anlatım ─────────────────────────

BRIEF_PROMPT = """Sen bir hisse senedi araştırma analistisin. Aşağıda bir şirketin Yahoo Finance'tan alınmış
profil verisi ve son haber başlıkları var. Yalnızca bu verilere ve şirket hakkında GENEL KABUL GÖRMÜŞ, doğrulanabilir
bilgilere dayanarak TÜRKÇE, detaylı ve sade bir anlatım yaz. Rakam UYDURMA: verilmeyen finansal sayı verme; emin
olmadığın şeyi söyleme. Yatırım tavsiyesi verme.

ŞİRKET: {name} ({symbol})
SEKTÖR / SANAYİ: {sector} / {industry}
ÜLKE: {country} | ÇALIŞAN: {employees} | WEB: {website}
Yahoo şirket tanımı (İngilizce):
{summary}

Son haber başlıkları (en yeni önce):
{news}

Çıktıyı SADECE şu JSON şemasıyla ver:
{{
  "ne_is_yapar": "3-5 paragraflık, markdown destekli, detaylı anlatım: şirket nasıl para kazanır, ürün/hizmetleri, müşteriler, coğrafya",
  "faaliyet_alanlari": ["kısa madde", "..."],
  "rekabet_ve_konum": "rakipler ve şirketin sektördeki konumu (2-4 cümle)",
  "buyume_itkileri": ["madde", "..."],
  "riskler": ["madde", "..."],
  "haber_ozeti": "yukarıdaki haber başlıklarından çıkan ana temaların 3-5 cümlelik özeti; haber yoksa 'Güncel haber verisi yok.'"
}}"""


@st.cache_data(ttl=43200, show_spinner=False)
def _brief_cached(yahoo_sym: str, payload: str) -> dict:
    """Gemini çağrısı (12 saat önbellek). payload: prompt (önbellek anahtarı da olur)."""
    from sirket_raporlari import _call_gemini_with_retry, _get_gemini_api_key, _parse_llm_json, genai
    if genai is None:
        raise RuntimeError("google-genai paketi kurulu değil.")
    key = _get_gemini_api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY secrets/environment değişkeni eksik.")
    resp = _call_gemini_with_retry(genai.Client(api_key=key), payload, max_output_tokens=16000)
    return _parse_llm_json(resp.text)


def _brief_prompt(symbol, info, news):
    heads = "\n".join(f"- {n['date']} · {n['publisher']}: {n['title']}" for n in news[:10]) or "(haber yok)"
    return BRIEF_PROMPT.format(
        name=info.get("longName") or info.get("shortName") or symbol, symbol=symbol,
        sector=info.get("sector") or "—", industry=info.get("industry") or "—",
        country=info.get("country") or "—", employees=info.get("fullTimeEmployees") or "—",
        website=info.get("website") or "—", summary=(info.get("longBusinessSummary") or "(tanım yok)")[:6000],
        news=heads)


# ───────────────────────── analist bölümü ─────────────────────────

def _targets_figure(t, price, ccy):
    lo, hi, mean, med = t.get("low"), t.get("high"), t.get("mean"), t.get("median")
    cur = price or t.get("current")
    vals = [v for v in (lo, hi, mean, med, cur) if v]
    if len(vals) < 3 or not lo or not hi:
        return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[lo, hi], y=[0, 0], mode="lines", line=dict(color="rgba(120,140,170,0.6)", width=10),
                             hoverinfo="skip", showlegend=False))
    for lab, v, col, sym in (("Düşük", lo, "#D64545", "diamond"), ("Yüksek", hi, "#1B7F3B", "diamond"),
                             ("Ortalama", mean, "#2F6FED", "circle"), ("Medyan", med, "#7B61FF", "circle"),
                             ("Güncel fiyat", cur, "#F2994A", "star")):
        if v:
            fig.add_trace(go.Scatter(x=[v], y=[0], mode="markers", name=f"{lab}: {ccy}{v:,.2f}",
                                     marker=dict(size=16, color=col, symbol=sym, line=dict(width=1, color="white"))))
    fig.update_layout(height=170, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(visible=False, range=[-1, 1]),
                      xaxis=dict(title=f"Hedef fiyat ({ccy.strip() or 'yerel'})"),
                      legend=dict(orientation="h", y=-0.45))
    return fig


def _render_analysts(prof, price, ccy):
    info, targets, rs, ud = prof["info"], prof["targets"], prof["rec_summary"], prof["upgrades"]
    if not (targets or rs is not None or info.get("recommendationKey") or ud is not None):
        st.info("Bu hisse için Yahoo Finance'ta analist verisi bulunamadı (özellikle küçük/yerel hisselerde kapsama "
                "zayıf olabilir).")
        return
    px = price or (targets or {}).get("current") or _num(info.get("currentPrice"))
    mean_t = (targets or {}).get("mean") or _num(info.get("targetMeanPrice"))
    k = st.columns(5)
    rk = str(info.get("recommendationKey") or "none")
    k[0].metric("Konsensüs", REC_TR.get(rk, rk), help="Yahoo'nun analist tavsiyelerinden türettiği genel görüş.")
    rm = _num(info.get("recommendationMean"))
    k[1].metric("Ortalama puan", f"{rm:.2f} / 5" if rm else "—",
                help="1 = Güçlü Al, 3 = Tut, 5 = Güçlü Sat (düşük = daha olumlu).")
    k[2].metric("Analist sayısı", f"{int(_num(info.get('numberOfAnalystOpinions')) or 0)}")
    k[3].metric("Ortalama hedef", f"{ccy}{mean_t:,.2f}" if mean_t else "—")
    k[4].metric("Potansiyel", _pct(mean_t / px - 1, True) if (mean_t and px) else "—",
                help="Ortalama hedef fiyatın güncel fiyata göre farkı.")

    c1, c2 = st.columns(2)
    with c1:
        if rs is not None:
            fig = go.Figure()
            per = rs["period"].map({"0m": "Bu ay", "-1m": "1 ay önce", "-2m": "2 ay önce", "-3m": "3 ay önce"}
                                   ).fillna(rs["period"])
            for col, lab, color in REC_COLS:
                if col in rs.columns:
                    fig.add_trace(go.Bar(name=lab, y=per, x=rs[col], orientation="h", marker_color=color))
            fig.update_layout(barmode="stack", height=260, title="Analist tavsiye dağılımı",
                              margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h", y=-0.2),
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG)
        else:
            st.caption("Tavsiye dağılımı verisi yok.")
    with c2:
        fig = _targets_figure(targets, px, ccy) if targets else None
        if fig is not None:
            st.markdown("**Hedef fiyat aralığı**")
            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG)
            if targets.get("high") and targets.get("low"):
                st.caption(f"Düşük {ccy}{targets['low']:,.2f} · Yüksek {ccy}{targets['high']:,.2f} — "
                           "analistler arası görüş ayrılığı ne kadar genişse belirsizlik o kadar yüksek.")
        else:
            st.caption("Hedef fiyat verisi yok.")

    if ud is not None:
        st.markdown("**Son tavsiye değişiklikleri**")
        show = pd.DataFrame({
            "Tarih": pd.to_datetime(ud.iloc[:, 0], errors="coerce").dt.strftime("%Y-%m-%d"),
            "Kurum": ud.get("Firm"), "Eski": ud.get("FromGrade"), "Yeni": ud.get("ToGrade"),
            "İşlem": ud.get("Action"),
            "Eski hedef": pd.to_numeric(ud.get("priorPriceTarget"), errors="coerce").replace(0, np.nan),
            "Yeni hedef": pd.to_numeric(ud.get("currentPriceTarget"), errors="coerce").replace(0, np.nan),
        })
        st.dataframe(show, hide_index=True, use_container_width=True, height=min(420, 38 * (len(show) + 1)),
                     column_config={"Eski hedef": st.column_config.NumberColumn(format="%.2f"),
                                    "Yeni hedef": st.column_config.NumberColumn(format="%.2f")})
    st.caption("Kaynak: Yahoo Finance (analist kurumların yayımladığı görüşlerin derlemesi). Bu uygulamanın kendi "
               "hesabı değildir; gecikmeli/eksik olabilir. Yatırım tavsiyesi değildir.")


# ───────────────────────── ana bölüm ─────────────────────────

def display_company_profile(symbol: str, price=None):
    """Single Stock'ın en altı: şirket anlatımı, analist görüşleri, haberler. symbol: uygulama sembolü."""
    ysym = gd.yahoo_of(symbol)
    st.markdown("---")
    st.subheader("🏢 Şirket Profili, Haberler ve Analist Görüşleri")
    with st.spinner("Şirket profili, haberler ve analist verileri yükleniyor (Yahoo Finance)..."):
        prof = gd.get_profile(ysym)
    info, news = prof["info"], prof["news"]
    if not info and not news:
        st.info(f"Yahoo Finance'ta {ysym} için profil bulunamadı veya erişilemedi.")
        return
    ccy = gd.ccy_symbol(info.get("currency"))
    name = info.get("longName") or info.get("shortName") or ysym
    st.markdown(f"**{name}** · `{ysym}`")

    t_about, t_analyst, t_news = st.tabs(["🏭 Ne iş yapıyor?", "🎯 Analist görüşleri", f"📰 Haberler ({len(news)})"])

    with t_about:
        f = st.columns(4)
        f[0].metric("Sektör", info.get("sector") or "—", info.get("industry") or None, delta_color="off")
        f[1].metric("Ülke", info.get("country") or "—", info.get("city") or None, delta_color="off")
        emp = _num(info.get("fullTimeEmployees"))
        f[2].metric("Çalışan", f"{int(emp):,}" if emp else "—")
        f[3].metric("Piyasa değeri", _big(info.get("marketCap"), ccy))
        if info.get("website"):
            st.markdown(f"🔗 [{info['website']}]({info['website']})")
        summ = info.get("longBusinessSummary")
        if summ:
            st.markdown("**Yahoo Finance şirket tanımı** _(İngilizce)_")
            st.write(summ)
        else:
            st.caption("Yahoo'da bu şirket için iş tanımı yok.")

        bkey = f"brief_{ysym}"
        st.markdown("**🇹🇷 Türkçe detaylı anlatım**")
        if st.button("✨ Gemini ile Türkçe, detaylı anlat (haber özeti dahil)", key=f"brief_btn_{ysym}",
                     help="Yahoo tanımı ve son haber başlıklarıyla Gemini'den Türkçe detaylı şirket anlatımı ister "
                          "(12 saat önbellek). Rakam uydurmaması istenir ama yine de doğrulayın."):
            try:
                with st.spinner("Gemini yazıyor..."):
                    st.session_state[bkey] = _brief_cached(ysym, _brief_prompt(ysym, info, news))
            except Exception as e:
                st.session_state[bkey] = {"_error": str(e)}
        b = st.session_state.get(bkey)
        if b and b.get("_error"):
            st.error(f"Gemini anlatımı oluşturulamadı: {b['_error']}")
        elif b:
            st.markdown(b.get("ne_is_yapar", ""))
            if b.get("faaliyet_alanlari"):
                st.markdown("**Faaliyet alanları**\n" + "\n".join(f"- {x}" for x in b["faaliyet_alanlari"]))
            if b.get("rekabet_ve_konum"):
                st.markdown(f"**Rekabet ve konum:** {b['rekabet_ve_konum']}")
            g1, g2 = st.columns(2)
            with g1:
                if b.get("buyume_itkileri"):
                    st.markdown("**Büyüme itkileri**\n" + "\n".join(f"- {x}" for x in b["buyume_itkileri"]))
            with g2:
                if b.get("riskler"):
                    st.markdown("**Riskler**\n" + "\n".join(f"- {x}" for x in b["riskler"]))
            if b.get("haber_ozeti"):
                st.markdown(f"**Haberlerin özeti:** {b['haber_ozeti']}")
            st.caption("Bu metin Gemini tarafından, Yahoo verisi ve genel bilgiyle üretildi; yatırım tavsiyesi değildir.")

    with t_analyst:
        _render_analysts(prof, price, ccy)

    with t_news:
        if not news:
            st.info("Bu hisse için güncel haber bulunamadı.")
        for n in news:
            head = f"[{n['title']}]({n['url']})" if n["url"] else n["title"]
            st.markdown(f"**{head}**  \n<small>{n['publisher']} · {n['date']}</small>", unsafe_allow_html=True)
            if n["summary"]:
                st.caption(n["summary"][:420] + ("…" if len(n["summary"]) > 420 else ""))
        if news:
            st.caption("Kaynak: Yahoo Finance haber akışı (genellikle İngilizce; başlıkların Türkçe özeti için "
                       "'Ne iş yapıyor?' sekmesindeki Gemini anlatımını kullanabilirsiniz).")


# ───────────────────────── yabancı hisse temel verileri ─────────────────────────

def display_foreign_fundamentals(symbol: str, price=None):
    """BIST'teki bilanço bölümünün yabancı hisse karşılığı: yfinance çarpanları + çeyreklik gelir tablosu."""
    ysym = gd.yahoo_of(symbol)
    st.markdown("---")
    st.subheader("📊 Temel Veriler (yfinance)")
    info = gd.get_info(ysym)
    if not info:
        st.info("Bu hisse için temel veri alınamadı.")
        return
    ccy = gd.ccy_symbol(info.get("currency"))
    v = gd.valuations_from_info(info)
    r1 = st.columns(4)
    r1[0].metric("Piyasa değeri", _big(info.get("marketCap"), ccy))
    r1[1].metric("F/K (trailing)", _x(v.get("pe")))
    r1[2].metric("İleri F/K", _x(v.get("fwd_pe")), help="Analist konsensüs kâr tahminine göre (Yahoo forwardPE).")
    r1[3].metric("FD/FAVÖK", _x(v.get("ev_ebitda")))
    r2 = st.columns(4)
    r2[0].metric("PD/DD", _x(v.get("pb"), 2))
    r2[1].metric("Özsermaye kârlılığı", _pct(info.get("returnOnEquity")))
    r2[2].metric("Net marj", _pct(info.get("profitMargins")))
    r2[3].metric("Faaliyet marjı", _pct(info.get("operatingMargins")))
    r3 = st.columns(4)
    r3[0].metric("Gelir büyümesi (YoY)", _pct(info.get("revenueGrowth"), True))
    r3[1].metric("Kâr büyümesi (YoY)", _pct(info.get("earningsGrowth"), True))
    de = _num(info.get("debtToEquity"))
    r3[2].metric("Borç / özsermaye", f"%{de:.0f}" if de is not None else "—")
    r3[3].metric("Serbest nakit akışı", _big(info.get("freeCashflow"), ccy))
    r4 = st.columns(4)
    r4[0].metric("Temettü verimi", _pct(info.get("dividendYield") / 100) if _num(info.get("dividendYield")) else "—")
    r4[1].metric("Beta", f"{_num(info.get('beta')):.2f}" if _num(info.get("beta")) is not None else "—")
    r4[2].metric("52 hafta düşük", f"{ccy}{info['fiftyTwoWeekLow']:,.2f}" if _num(info.get("fiftyTwoWeekLow")) else "—")
    r4[3].metric("52 hafta yüksek", f"{ccy}{info['fiftyTwoWeekHigh']:,.2f}" if _num(info.get("fiftyTwoWeekHigh")) else "—")

    q = gd.get_quarterly_income(ysym)
    if q is not None and not q.empty:
        qq = q.T.sort_index()
        fig = go.Figure()
        for col, lab, color in (("Total Revenue", "Gelir", "#2F6FED"), ("EBITDA", "FAVÖK", "#7B61FF"),
                                ("Net Income", "Net kâr", "#1B7F3B")):
            if col in qq.columns:
                fig.add_trace(go.Bar(x=[d.strftime("%Y-%m") for d in qq.index], y=qq[col] / 1e6, name=lab,
                                     marker_color=color))
        fig.update_layout(barmode="group", height=340, title=f"Çeyreklik gelir tablosu (milyon {ccy.strip() or ''})",
                          margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG)
    st.caption("Kaynak: Yahoo Finance. Yabancı hisselerde ileri FD/FAVÖK, PD/DD tahmini ve geçmiş çarpan karşılaştırması "
               "BIST'teki İş Yatırım bilançosuna dayalı olduğu için hesaplanmaz; ileri F/K analist konsensüsünden gelir.")
