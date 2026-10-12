"""Beklenen getiri yöntemleri (doğrusal cebir): PCA faktör modeli ve karakteristik regresyonu.

1) PCA faktör modeli (APT):
   Getiri korelasyon matrisinin özayrışımından k ortak faktör çıkarılır (faktör getirisi
   f_t = Σ_i v_i · r_it/σ_i). Her hisse için r_i = α_i + Σ_k β_ik f_k + ε (en küçük kareler);
   beklenen getiri = YALNIZCA ortak faktörlerle açıklanan kısım: μ_i = Σ_k β_ik · λ_k,
   λ_k = ortalama faktör getirisi (yıllık). Hissenin kendine özgü, şans eseri ortalaması (α) atılır.

2) Karakteristik regresyonu (Fama-MacBeth + ridge):
   Her tarihte, hisselerin kesitinde sonraki H günlük (kesit ortalamasından sapma) getiri,
   o günkü özelliklere (sektöre/kendi geçmişine göre ucuzluk, tahmini büyüme, momentum) regresyonla
   bağlanır: γ_t = (X'X + αI)⁻¹ X'y. γ'nın tarihler üzerindeki ortalaması ve t-değeri raporlanır;
   tahmin μ̂_i = taban + (252/H)·z_i·γ̄. Zaman dışı (expanding) bilgi katsayısı (IC) modelin gerçekten
   ayırt edici olup olmadığını gösterir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import portfolio_valuation as pv

TRADING_DAYS = 252
FEATURES = ["cheap_pe_sec", "cheap_ev_sec", "cheap_pe_own", "growth", "mom"]
FEATURE_LABELS = {
    "cheap_pe_sec": "Ucuzluk: ileri F/K, sektöre göre",
    "cheap_ev_sec": "Ucuzluk: ileri FD/FAVÖK, sektöre göre",
    "cheap_pe_own": "Ucuzluk: ileri F/K, kendi geçmişine göre",
    "growth": "Tahmini kâr büyümesi",
    "mom": "Momentum (12-1 ay)",
}
FEATURE_COLS = {
    "cheap_pe_sec": "F/K ucuzluk – sektör (z)",
    "cheap_ev_sec": "FD/FAVÖK ucuzluk – sektör (z)",
    "cheap_pe_own": "F/K ucuzluk – kendi geçmişi (z)",
    "growth": "Kâr büyümesi (z)",
    "mom": "Momentum (z)",
}


# ───────────────────────── 1) PCA faktör modeli ─────────────────────────

def pca_factor_mu(rets: pd.DataFrame, k: int = 3, min_frac: float = 0.6) -> dict:
    """rets: date x ticker günlük getiri (NaN serbest). Dönüş: dict(mu[Series, yıllık, ortak faktörlerin
    açıkladığı beklenen getiri], r2[Series], premia[k, yıllık], explained[k], n_stocks, k).
    Pencerenin en az min_frac'i dolu olmayan hisseler çıkar."""
    X = rets.loc[:, rets.notna().sum() >= int(min_frac * len(rets))]
    if X.shape[1] < k + 2 or len(X) < 30:
        return dict(mu=pd.Series(dtype=float), r2=pd.Series(dtype=float), premia=np.zeros(k),
                    explained=np.zeros(k), n_stocks=int(X.shape[1]), k=k)
    sd = X.std(ddof=1).replace(0, np.nan)
    keep = sd.dropna().index
    X, sd = X[keep], sd[keep]
    C = X.corr(min_periods=int(min_frac * len(X))).fillna(0.0).values.copy()
    np.fill_diagonal(C, 1.0)
    w, V = np.linalg.eigh(C)
    order = np.argsort(w)[::-1][:k]
    V, lam = V[:, order], np.clip(w[order], 0, None)
    explained = lam / w.clip(min=0).sum()
    Xf = X.fillna(0.0).values                                  # ortalama etkisi korunur (demean YOK)
    F = (Xf / sd.values) @ V                                   # T x k faktör getirileri (σ-ölçekli)
    A = np.column_stack([np.ones(len(F)), F])                  # sabit + faktörler
    coef, *_ = np.linalg.lstsq(A, Xf, rcond=None)              # (k+1) x N
    alpha, B = coef[0], coef[1:]
    resid = Xf - A @ coef
    ss_tot = ((Xf - Xf.mean(axis=0)) ** 2).sum(axis=0)
    r2 = 1.0 - (resid ** 2).sum(axis=0) / np.where(ss_tot > 0, ss_tot, np.nan)
    premia = F.mean(axis=0) * TRADING_DAYS
    mu = (B.T @ premia)                                        # Σ_k β_ik λ_k  (yıllık)
    return dict(mu=pd.Series(mu, index=X.columns), r2=pd.Series(r2, index=X.columns), premia=premia,
                explained=explained, n_stocks=int(X.shape[1]), k=k)


# ───────────────────────── 2) karakteristik regresyonu ─────────────────────────

def _period_key(p: str):
    y, m = str(p).split("/")
    return int(y), int(m)


def _winsor_z(s: pd.Series) -> pd.Series:
    """Kesitsel z-skoru (±3'e kırpılmış); NaN'ler sonuçta NaN kalır."""
    v = s.astype(float)
    sd = v.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return v * np.nan
    return ((v - v.mean()) / sd).clip(-3, 3)


def _cheap(x, ref):
    """log(ref/x): ref'ten ucuzsa pozitif. İkisi de pozitif değilse NaN."""
    x_, r_ = pv._pos(x), pv._pos(ref)
    return float(np.log(r_ / x_)) if np.isfinite(x_) and np.isfinite(r_) else np.nan


def _sector_median(values_by_ticker: dict, sector_of: dict, ticker, min_peers=3):
    sec = sector_of.get(ticker)
    peers = [v for t, v in values_by_ticker.items() if sector_of.get(t) == sec and np.isfinite(v) and v > 0]
    if sec is not None and len(peers) >= min_peers:
        return float(np.median(peers))
    allv = [v for v in values_by_ticker.values() if np.isfinite(v) and v > 0]
    return float(np.median(allv)) if allv else np.nan


def _own_median(prev_values, min_obs=4):
    v = [x for x in prev_values if np.isfinite(x) and x > 0]
    return float(np.median(v)) if len(v) >= min_obs else np.nan


def build_panel(hists: dict, prices: dict, sector_of: dict, horizon: int = 63, mom_lookback: int = 252,
                mom_skip: int = 21, params: dict | None = None) -> pd.DataFrame:
    """Geçmiş (hisse, çeyrek) gözlemlerinden eğitim paneli. hists: {ticker: compute_valuation_history çıktısı
    (index=fiyat tarihi, kolonlar period, pe, ev_ebitda, fwd_pe, fwd_ev_ebitda)}, prices: {ticker: split
    düzeltmeli kapanış Series}. Özellikler her çeyrekte kesitsel olarak z-skorlanır (±3). Dönüş: long DataFrame
    [period, ticker, <FEATURES>, target] - target = sonraki `horizon` işlem günü getirisi (kesit ortalaması
    çıkarılmış; ufku dolmayan son gözlemler için NaN)."""
    p = {**pv.DEFAULTS, **(params or {})}
    rows = []
    for t, h in hists.items():
        ps = prices.get(t)
        if h is None or len(h) == 0 or ps is None or len(ps) < mom_lookback + 5:
            continue
        ps = ps.dropna().sort_index()
        prev_pe: list = []
        for date, r in h.sort_index().iterrows():
            fpe = r["fwd_pe"] if pv.forecast_ok(r["pe"], r["fwd_pe"], p)[0] else np.nan
            fev = r["fwd_ev_ebitda"] if pv.forecast_ok(r["ev_ebitda"], r["fwd_ev_ebitda"], p)[0] else np.nan
            if date not in ps.index:
                continue
            pos = ps.index.get_loc(date)
            mom = (ps.iloc[pos - mom_skip] / ps.iloc[pos - mom_lookback] - 1.0) if pos >= mom_lookback else np.nan
            tgt = (ps.iloc[pos + horizon] / ps.iloc[pos] - 1.0) if pos + horizon < len(ps) else np.nan
            growth = float(np.log(pv.forecast_ratio(r["pe"], r["fwd_pe"]))) if np.isfinite(fpe) else np.nan
            rows.append(dict(period=r["period"], ticker=t, fpe=fpe, fev=fev,
                             own_ref=_own_median(prev_pe), growth=growth, mom=mom, target=tgt))
            prev_pe.append(fpe)
    if not rows:
        return pd.DataFrame(columns=["period", "ticker"] + FEATURES + ["target"])
    df = pd.DataFrame(rows)
    out = []
    for per, g in df.groupby("period"):
        pe_map = dict(zip(g["ticker"], g["fpe"]))
        ev_map = dict(zip(g["ticker"], g["fev"]))
        g = g.copy()
        g["cheap_pe_sec"] = [_cheap(r.fpe, _sector_median(pe_map, sector_of, r.ticker)) for r in g.itertuples()]
        g["cheap_ev_sec"] = [_cheap(r.fev, _sector_median(ev_map, sector_of, r.ticker)) for r in g.itertuples()]
        g["cheap_pe_own"] = [_cheap(r.fpe, r.own_ref) for r in g.itertuples()]
        for f in FEATURES:
            g[f] = _winsor_z(g[f])
        g["target"] = g["target"] - g["target"].mean()
        out.append(g[["period", "ticker"] + FEATURES + ["target"]])
    return pd.concat(out, ignore_index=True)


def _spearman(a, b) -> float:
    a, b = pd.Series(a).rank(), pd.Series(b).rank()
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def fama_macbeth_ridge(panel: pd.DataFrame, alpha_frac: float = 1.0, min_cs: int = 12, features=None) -> dict:
    """Her çeyrek için kesit ridge regresyonu (NaN özellik = 0, yani nötr). Dönüş: dict(gammas[DataFrame],
    gamma[Series ortalama], tstat[Series], ic[Series zaman dışı IC], ic_mean, ic_t, n_obs, n_periods)."""
    feats = list(features or FEATURES)
    d = panel.dropna(subset=["target"]).copy()
    d[feats] = d[feats].fillna(0.0)
    gam = {}
    for per, g in d.groupby("period"):
        if len(g) < min_cs:
            continue
        X, y = g[feats].values, g["target"].values
        A = X.T @ X + alpha_frac * len(g) * np.eye(len(feats))
        gam[per] = np.linalg.solve(A, X.T @ y)
    if not gam:
        return dict(gammas=pd.DataFrame(columns=feats), gamma=pd.Series(0.0, index=feats),
                    tstat=pd.Series(np.nan, index=feats), ic=pd.Series(dtype=float), ic_mean=np.nan, ic_t=np.nan,
                    n_obs=0, n_periods=0)
    G = pd.DataFrame(gam, index=feats).T
    G = G.loc[sorted(G.index, key=_period_key)]
    n = len(G)
    gm = G.mean()
    se = G.std(ddof=1) / np.sqrt(n) if n > 1 else pd.Series(np.nan, index=feats)
    tstat = gm / se.replace(0, np.nan)
    ic = {}
    periods = list(G.index)
    for i in range(3, len(periods)):                          # yalnızca öncekilerden öğrenilen katsayı
        per = periods[i]
        g = d[d["period"] == per]
        if len(g) < min_cs:
            continue
        gprev = G.iloc[:i].mean().values
        ic[per] = _spearman(g[feats].values @ gprev, g["target"].values)
    ic = pd.Series(ic, dtype=float)
    ic_t = float(ic.mean() / (ic.std(ddof=1) / np.sqrt(len(ic)))) if len(ic) > 2 and ic.std(ddof=1) > 0 else np.nan
    return dict(gammas=G, gamma=gm, tstat=tstat, ic=ic, ic_mean=float(ic.mean()) if len(ic) else np.nan,
                ic_t=ic_t, n_obs=int(len(d)), n_periods=int(n))


def current_features(peers: dict, hists: dict, prices: dict, sector_of: dict, mom_lookback: int = 252,
                     mom_skip: int = 21, params: dict | None = None) -> pd.DataFrame:
    """Bugünkü kesit için aynı özellikler (z-skorlu). peers: {ticker: compute_stock_valuations çıktısı};
    hists/prices geçmiş ve momentum için. Dönüş: index=ticker, kolonlar FEATURES (z) + ham fwd_pe/fwd_ev."""
    p = {**pv.DEFAULTS, **(params or {})}
    fpe = {t: (v.get("fwd_pe") if pv.forecast_ok(v.get("pe"), v.get("fwd_pe"), p)[0] else np.nan)
           for t, v in peers.items()}
    fev = {t: (v.get("fwd_ev_ebitda") if pv.forecast_ok(v.get("ev_ebitda"), v.get("fwd_ev_ebitda"), p)[0] else np.nan)
           for t, v in peers.items()}
    fpe = {t: pv._pos(x) for t, x in fpe.items()}
    fev = {t: pv._pos(x) for t, x in fev.items()}
    rows = {}
    for t, v in peers.items():
        h = hists.get(t)
        own = _own_median(list(h["fwd_pe"]) if h is not None and len(h) else [])
        ps = prices.get(t)
        mom = np.nan
        if ps is not None:
            ps = ps.dropna()
            if len(ps) > mom_lookback:
                mom = ps.iloc[-1 - mom_skip] / ps.iloc[-1 - mom_lookback] - 1.0
        growth = float(np.log(pv.forecast_ratio(v.get("pe"), v.get("fwd_pe")))) if np.isfinite(fpe[t]) else np.nan
        rows[t] = dict(
            cheap_pe_sec=_cheap(fpe[t], _sector_median(fpe, sector_of, t)),
            cheap_ev_sec=_cheap(fev[t], _sector_median(fev, sector_of, t)),
            cheap_pe_own=_cheap(fpe[t], own), growth=growth, mom=mom, fwd_pe=fpe[t], fwd_ev=fev[t])
    df = pd.DataFrame(rows).T.astype(float)
    for f in FEATURES:
        df[f] = _winsor_z(df[f])
    return df


def predict_mu(zfeat: pd.DataFrame, gamma: pd.Series, horizon: int, base: float,
               score_z: pd.Series | None = None, score_premium: float = 0.0) -> pd.DataFrame:
    """μ̂ = taban + (252/H)·z·γ + puan primi·z_puan. NaN özellik 0 (nötr) sayılır.
    Dönüş: DataFrame [mu, rel_features (yıllık, taban dışı özellik katkısı), rel_score]."""
    z = zfeat[FEATURES].fillna(0.0)
    rel = (z.values @ gamma.reindex(FEATURES).values) * (TRADING_DAYS / horizon)
    sc = (score_z.reindex(z.index).fillna(0.0).values * score_premium) if score_z is not None else np.zeros(len(z))
    return pd.DataFrame({"mu": base + rel + sc, "rel_features": rel, "rel_score": sc}, index=z.index)
