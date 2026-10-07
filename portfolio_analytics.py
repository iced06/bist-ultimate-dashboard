"""Portföy analitiği - saf numpy/pandas/scipy, Streamlit'ten bağımsız (test edilebilir).

Akış: fiyat matrisi -> ortak-pencere günlük getiri (build_returns) -> shrinkage'lı
kovaryans (ledoit_wolf_cov) -> ağırlık optimizasyonu (optimize_weights) -> metrikler
(portfolio_metrics, risk_contributions, diversification_stats) -> sağlık skoru
(health_score) -> kural tabanlı değerlendirme metni (build_assessment).

Tüm getiriler günlük basit getiridir; yıllıklaştırma 252 işlem günüyle yapılır.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

TRADING_DAYS = 252

METHODS = {
    "risk_parity": "Risk parity (eşit risk katkısı)",
    "min_var": "Minimum varyans",
    "max_sharpe": "Maksimum Sharpe",
    "inv_vol": "Ters volatilite",
    "equal": "Eşit ağırlık",
}


# ───────────────────────── veri hazırlama ─────────────────────────

def build_returns(prices: pd.DataFrame, min_obs: int = 120):
    """date x ticker kapanış fiyatlarından ortak pencereli günlük getiri matrisi.

    Gün atlayan (işleme kapalı) hisselerin fiyatı ileri doldurulur. Geçmişi
    min_obs'tan kısa olan ya da ortak pencereyi min_obs'un altına daraltan
    hisseler çıkarılır. Dönüş: (returns, dropped{ticker: neden})."""
    prices = prices.sort_index().ffill()
    rets = (prices / prices.shift(1) - 1.0).iloc[1:]
    rets = rets.replace([np.inf, -np.inf], np.nan)
    dropped: dict[str, str] = {}

    for t in list(rets.columns):
        n = int(rets[t].notna().sum())
        if n < min_obs:
            dropped[t] = f"yalnızca {n} günlük geçmiş var (en az {min_obs} gerekli)"
            rets = rets.drop(columns=t)

    while rets.shape[1] > 0 and len(rets.dropna(how="any")) < min_obs:
        starts = {t: rets[t].first_valid_index() for t in rets.columns}
        worst = max(starts, key=lambda t: starts[t])
        dropped[worst] = "geçmişi kısa olduğu için ortak tarih penceresini daraltıyor"
        rets = rets.drop(columns=worst)

    common = rets.dropna(how="any") if rets.shape[1] else rets
    return common, dropped


def detect_jumps(rets: pd.DataFrame, threshold: float = 0.25) -> dict:
    """Tek günde |getiri| > threshold olan hisseler (muhtemel bölünme/bedelsiz
    düzeltmesi). BIST günlük fiyat limiti normalde %10 civarıdır."""
    out = {}
    for t in rets.columns:
        s = rets[t]
        i = s.abs().idxmax()
        if abs(s.loc[i]) > threshold:
            out[t] = (i, float(s.loc[i]))
    return out


def ledoit_wolf_cov(X) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf shrinkage kovaryansı (hedef: ortalama varyanslı birim matris,
    sklearn.covariance.LedoitWolf ile aynı formül). X: (gözlem, varlık) günlük
    getiri. Dönüş: (günlük kovaryans, shrinkage yoğunluğu 0-1)."""
    X = np.asarray(X, dtype=float)
    n, p = X.shape
    Xc = X - X.mean(axis=0)
    S = Xc.T @ Xc / n
    tr = np.trace(S)
    mu = tr / p
    X2 = Xc ** 2
    delta_ = float((S ** 2).sum())
    beta_ = float((X2.T @ X2).sum())
    beta = (beta_ / n - delta_) / (p * n)
    delta = (delta_ - 2.0 * mu * tr + p * mu ** 2) / p
    beta = min(beta, delta)
    shrink = 0.0 if beta <= 0 or delta <= 0 else beta / delta
    cov = (1.0 - shrink) * S + shrink * mu * np.eye(p)
    return cov, float(shrink)


# ───────────────────────── optimizasyon ─────────────────────────

def _cap_redistribute(w: np.ndarray, cap: float, iters: int = 100) -> np.ndarray:
    """Üst sınırı aşan ağırlıkları kırpıp fazlayı diğerlerine orantılı dağıtır."""
    w = np.asarray(w, dtype=float).copy()
    for _ in range(iters):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        under = (~over) & (w < cap - 1e-12)
        if not under.any() or w[under].sum() <= 0:
            break
        w[under] += excess * w[under] / w[under].sum()
    s = w.sum()
    return w / s if s > 0 else np.full_like(w, 1.0 / len(w))


def _clean(w: np.ndarray) -> np.ndarray:
    w = np.clip(np.asarray(w, dtype=float), 0.0, None)
    return w / w.sum()


def _slsqp(fun, jac, x0, cap):
    n = len(x0)
    return minimize(
        fun, x0, jac=jac, method="SLSQP",
        bounds=[(0.0, cap)] * n,
        constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0, "jac": lambda w: np.ones(n)}],
        options={"maxiter": 500, "ftol": 1e-14},
    )


def _min_variance(cov, cap):
    n = cov.shape[0]
    scale = 100.0
    res = _slsqp(lambda w: scale * w @ cov @ w, lambda w: 2 * scale * cov @ w,
                 np.full(n, 1.0 / n), cap)
    return _clean(res.x)


def _risk_parity(cov, cap):
    """min 0.5 y'Σy - (1/n) Σ ln y  (dışbükey; çözüm tam eşit risk katkısı verir),
    sonra normalize. Üst sınır bağlayıcıysa kırpılır (risk katkıları artık tam eşit olmaz)."""
    n = cov.shape[0]
    d = np.sqrt(np.diag(cov))
    y0 = 1.0 / (d * d.sum())

    def f(y):
        return 0.5 * y @ cov @ y - np.log(y).sum() / n

    def g(y):
        return cov @ y - 1.0 / (n * y)

    res = minimize(f, y0, jac=g, method="L-BFGS-B", bounds=[(1e-10, None)] * n,
                   options={"maxiter": 1000, "ftol": 1e-15, "gtol": 1e-12})
    w = _clean(res.x)
    return _cap_redistribute(w, cap)


def _max_sharpe(mu, cov, rf, cap, seed=0):
    n = len(mu)
    ex = mu - rf

    def neg_sharpe(w):
        s = np.sqrt(max(w @ cov @ w, 1e-18))
        return -(w @ ex) / s

    def grad(w):
        s = np.sqrt(max(w @ cov @ w, 1e-18))
        a = w @ ex
        return -ex / s + a * (cov @ w) / s ** 3

    rng = np.random.default_rng(seed)
    starts = [np.full(n, 1.0 / n), _min_variance(cov, cap)]
    starts += [_cap_redistribute(rng.dirichlet(np.ones(n)), cap) for _ in range(4)]
    best_w, best_v = None, np.inf
    for x0 in starts:
        res = _slsqp(neg_sharpe, grad, x0, cap)
        w = _clean(res.x)
        w = _cap_redistribute(w, cap)
        v = neg_sharpe(w)
        if v < best_v:
            best_w, best_v = w, v
    return best_w, -best_v


def optimize_weights(method: str, mu: np.ndarray, cov: np.ndarray,
                     max_weight: float = 1.0, rf: float = 0.0):
    """Long-only ağırlıklar. mu/cov YILLIK. Dönüş: (weights, not).

    Maksimum Sharpe için tarihsel ortalama getiri çok gürültülü olduğundan mu,
    kesit ortalamasına %50 çekilir (shrinkage). Hiçbir portföyün fazla getirisi
    pozitif değilse (Sharpe anlamsız) minimum varyansa düşülür ve not döner."""
    mu = np.asarray(mu, dtype=float)
    cov = np.asarray(cov, dtype=float)
    n = len(mu)
    if n == 1:
        return np.array([1.0]), None
    cap = max(float(max_weight), 1.0 / n + 1e-9)
    note = None
    if cap > max_weight + 1e-12:
        note = (f"Üst sınır %{max_weight * 100:.0f}, {n} hisse için en az "
                f"%{100.0 / n:.1f} olmak zorunda; sınır buna yükseltildi.")

    if method == "equal":
        return np.full(n, 1.0 / n), note
    if method == "inv_vol":
        w = 1.0 / np.sqrt(np.diag(cov))
        return _cap_redistribute(w / w.sum(), cap), note
    if method == "min_var":
        return _min_variance(cov, cap), note
    if method == "risk_parity":
        w = _risk_parity(cov, cap)
        if (w > 0).any() and abs(w.max() - cap) < 1e-9:
            note = ((note + " ") if note else "") + (
                "Üst sınır bağlayıcı oldu; risk katkıları tam eşit değil.")
        return w, note
    if method == "max_sharpe":
        mu_s = 0.5 * mu + 0.5 * mu.mean()
        w, sharpe = _max_sharpe(mu_s, cov, rf, cap)
        pre = (note + " ") if note else ""
        if sharpe <= 0:
            return _min_variance(cov, cap), pre + (
                "Hiçbir hissenin tarihsel getirisi risksiz faizi aşmıyor; "
                "Maksimum Sharpe anlamsız, Minimum varyans kullanıldı.")
        return w, pre + ("Beklenen getiri tarihsel ortalamaya dayanır ve %50 kesit "
                         "ortalamasına çekilmiştir.")
    raise ValueError(f"bilinmeyen yöntem: {method}")


# ───────────────────────── metrikler ─────────────────────────

def risk_contributions(w, cov) -> np.ndarray:
    """Her varlığın portföy varyansına yüzde katkısı (toplam 1)."""
    w = np.asarray(w, dtype=float)
    var = float(w @ cov @ w)
    return w * (cov @ w) / var if var > 0 else np.full(len(w), 1.0 / len(w))


def portfolio_return_series(w, rets: pd.DataFrame) -> pd.Series:
    """Sabit ağırlıklı (günlük yeniden dengelenen) portföy günlük getirisi."""
    return pd.Series(rets.values @ np.asarray(w, dtype=float), index=rets.index)


def _drawdown(cum: np.ndarray) -> np.ndarray:
    """Kümülatif değer serisinden (başlangıç=1.0 dahil) tepeden düşüş serisi."""
    full = np.concatenate([[1.0], cum])
    return (full / np.maximum.accumulate(full) - 1.0)[1:]


def portfolio_metrics(pr: pd.Series, bench: pd.Series | None = None, rf: float = 0.0) -> dict:
    """pr: portföy günlük getirisi; bench: aynı indeksli endeks getirisi (opsiyonel)."""
    r = pr.values
    n = len(r)
    mean_d = r.mean()
    std_d = r.std(ddof=1) if n > 1 else 0.0
    ann_ret = mean_d * TRADING_DAYS
    vol = std_d * np.sqrt(TRADING_DAYS)
    cum = np.cumprod(1.0 + r)
    cagr = cum[-1] ** (TRADING_DAYS / n) - 1.0
    rf_d = (1.0 + rf) ** (1.0 / TRADING_DAYS) - 1.0
    downside = np.sqrt(np.mean(np.minimum(r - rf_d, 0.0) ** 2)) * np.sqrt(TRADING_DAYS)
    dd = _drawdown(cum)
    q05 = np.percentile(r, 5)
    out = {
        "n_obs": n,
        "ann_return": float(ann_ret),
        "cagr": float(cagr),
        "vol": float(vol),
        "sharpe": float((ann_ret - rf) / vol) if vol > 0 else float("nan"),
        "sortino": float((ann_ret - rf) / downside) if downside > 0 else float("nan"),
        "max_dd": float(-dd.min()),
        "var95": float(-q05),
        "cvar95": float(-r[r <= q05].mean()),
        "best_day": float(r.max()),
        "worst_day": float(r.min()),
        "total_return": float(cum[-1] - 1.0),
        "beta": float("nan"), "alpha": float("nan"), "corr_bench": float("nan"),
    }
    if bench is not None:
        b = bench.reindex(pr.index).dropna()
        p = pr.reindex(b.index)
        if len(b) > 30 and b.var(ddof=1) > 0:
            beta = np.cov(p.values, b.values, ddof=1)[0, 1] / b.var(ddof=1)
            out["beta"] = float(beta)
            out["alpha"] = float((p.mean() - rf_d - beta * (b.mean() - rf_d)) * TRADING_DAYS)
            out["corr_bench"] = float(np.corrcoef(p.values, b.values)[0, 1])
            bc = np.cumprod(1.0 + b.values)
            out["bench_total_return"] = float(bc[-1] - 1.0)
            out["bench_vol"] = float(b.std(ddof=1) * np.sqrt(TRADING_DAYS))
            out["bench_cagr"] = float(bc[-1] ** (TRADING_DAYS / len(b)) - 1.0)
            out["bench_max_dd"] = float(-_drawdown(bc).min())
    return out


def per_stock_stats(rets: pd.DataFrame, bench: pd.Series | None = None) -> pd.DataFrame:
    """Hisse bazında yıllık getiri/volatilite/beta/max drawdown (örneklem verisi)."""
    rows = []
    for t in rets.columns:
        s = rets[t]
        cum = np.cumprod(1.0 + s.values)
        dd = _drawdown(cum)
        beta = np.nan
        if bench is not None:
            b = bench.reindex(s.index).dropna()
            if len(b) > 30 and b.var(ddof=1) > 0:
                beta = np.cov(s.reindex(b.index).values, b.values, ddof=1)[0, 1] / b.var(ddof=1)
        rows.append({"ticker": t, "ann_return": s.mean() * TRADING_DAYS,
                     "cagr": cum[-1] ** (TRADING_DAYS / len(s)) - 1.0,
                     "vol": s.std(ddof=1) * np.sqrt(TRADING_DAYS),
                     "beta": beta, "max_dd": -dd.min()})
    return pd.DataFrame(rows).set_index("ticker")


def universe_stats(rets: pd.DataFrame, bench: pd.Series | None = None, min_obs: int = 30) -> pd.DataFrame:
    """Evrendeki her hisse için (kendi geçmişiyle, NaN'lar atlanarak) yıllık getiri/
    bileşik getiri/volatilite/beta/max drawdown. Dönüş: index=ticker."""
    rows = {}
    for t in rets.columns:
        s = rets[t].dropna()
        if len(s) < min_obs:
            continue
        rows[t] = per_stock_stats(s.to_frame(t), bench).loc[t]
    return pd.DataFrame(rows).T if rows else pd.DataFrame(
        columns=["ann_return", "cagr", "vol", "beta", "max_dd"])


def correlation_embedding(rets: pd.DataFrame, k: int = 3, min_periods: int = 60):
    """Hisseleri getiri korelasyon yapısından k boyutlu vektörlere gömer (korelasyon
    matrisinin özayrışımı / PCA): x_i = sqrt(λ_j) · v_ij. Standartlaştırılmış getiri
    vektörlerinin kosinüsü korelasyona eşit olduğundan x_i · x_j ≈ ρ_ij; iki vektörün
    arasındaki açı ne kadar küçükse hisseler o kadar benzer hareket eder. Vektör boyu
    (≤1) k faktörün o hisseyi ne kadar açıkladığını gösterir.

    rets: date x ticker (NaN serbest; çiftler arası korelasyon min_periods ile). Dönüş:
    (coords DataFrame [F1..Fk], açıklanan varyans oranları[k]). F1 işareti ortak
    (piyasa) faktörü pozitif olacak şekilde sabitlenir, F2/F3'ün en büyük yükü pozitif."""
    corr = rets.corr(min_periods=min_periods)
    ok = corr.notna().sum(axis=1) > 1
    corr = corr.loc[ok, ok]
    C = corr.fillna(0.0).values.copy()
    np.fill_diagonal(C, 1.0)
    w, V = np.linalg.eigh(C)
    order = np.argsort(w)[::-1]
    w, V = np.clip(w[order], 0.0, None), V[:, order]
    kk = min(k, len(w))
    coords = np.zeros((len(w), k))
    coords[:, :kk] = V[:, :kk] * np.sqrt(w[:kk])
    for j in range(kk):
        col = coords[:, j]
        pivot = col.sum() if j == 0 else col[np.argmax(np.abs(col))]
        if pivot < 0:
            coords[:, j] = -col
    total = w.sum()
    explained = np.zeros(k)
    explained[:kk] = w[:kk] / total if total > 0 else 0.0
    return pd.DataFrame(coords, index=corr.index, columns=[f"F{j + 1}" for j in range(k)]), explained


def diversification_stats(w, cov, corr: pd.DataFrame) -> dict:
    w = np.asarray(w, dtype=float)
    n = len(w)
    vols = np.sqrt(np.diag(cov))
    port_vol = float(np.sqrt(w @ cov @ w))
    eff_n = float(1.0 / np.sum(w ** 2))
    if n > 1:
        c = corr.values
        iu = np.triu_indices(n, k=1)
        avg_corr = float(c[iu].mean())
        pairs = sorted(((corr.index[i], corr.columns[j], float(c[i, j])) for i, j in zip(*iu)),
                       key=lambda x: x[2])
    else:
        avg_corr, pairs = float("nan"), []
    return {
        "eff_n": eff_n,
        "avg_corr": avg_corr,
        "div_ratio": float((w * vols).sum() / port_vol) if port_vol > 0 else float("nan"),
        "max_weight": float(w.max()),
        "least_corr_pair": pairs[0] if pairs else None,
        "most_corr_pair": pairs[-1] if pairs else None,
    }


def random_portfolios(mu, cov, rf=0.0, n=3000, seed=0):
    """Long-only rastgele portföyler (etkin sınır görseli için)."""
    rng = np.random.default_rng(seed)
    k = len(mu)
    W = np.vstack([rng.dirichlet(np.ones(k), size=n // 2),
                   rng.dirichlet(np.full(k, 0.3), size=n - n // 2)])
    rets = W @ mu
    vols = np.sqrt(np.einsum("ij,jk,ik->i", W, cov, W))
    return vols, rets, (rets - rf) / vols


# ───────────────────────── sağlık skoru ─────────────────────────

def _lin(x, best, worst):
    """x=best -> 100, x=worst -> 0 (doğrusal, kırpılmış)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return float(np.clip((x - worst) / (best - worst), 0.0, 1.0) * 100.0)


HEALTH_WEIGHTS = {"Çeşitlendirme": 0.30, "Yoğunlaşma": 0.20, "Risk": 0.25, "Kalite": 0.25}


def health_score(*, n: int, avg_corr: float, eff_n: float, max_weight: float,
                 top_sector_share: float, vol: float, max_dd: float,
                 quality: float | None) -> dict:
    """0-100 portföy sağlık skoru; alt skorlar şeffaf ve tek tek gösterilir.

    Çeşitlendirme: ort. ikili korelasyon (0.25 ->100, 0.85 ->0) ve efektif hisse
      sayısı / hisse sayısı oranının ortalaması.
    Yoğunlaşma: en büyük ağırlık (%15 ->100, %45 ->0) ve en büyük sektör payı
      (%30 ->100, %80 ->0) ortalaması.
    Risk: yıllık volatilite (%20 ->100, %55 ->0) ve max drawdown (%15 ->100,
      %45 ->0) ortalaması.
    Kalite: ağırlıklı ortalama Overall Puan (1 ->0, 5 ->100); rapor yoksa yok sayılır."""
    subs: dict[str, float | None] = {}
    if n < 2:
        subs["Çeşitlendirme"] = 0.0
        subs["Yoğunlaşma"] = 0.0
    else:
        corr_s = _lin(avg_corr, 0.25, 0.85)
        effn_s = float(np.clip((eff_n - 1.0) / (n - 1.0), 0.0, 1.0) * 100.0)
        subs["Çeşitlendirme"] = float(np.mean([corr_s, effn_s]))
        subs["Yoğunlaşma"] = float(np.mean([_lin(max_weight, 0.15, 0.45),
                                            _lin(top_sector_share, 0.30, 0.80)]))
    subs["Risk"] = float(np.mean([_lin(vol, 0.20, 0.55), _lin(max_dd, 0.15, 0.45)]))
    subs["Kalite"] = None if quality is None else _lin(quality, 5.0, 1.0)

    used = {k: v for k, v in subs.items() if v is not None}
    wsum = sum(HEALTH_WEIGHTS[k] for k in used)
    total = sum(subs[k] * HEALTH_WEIGHTS[k] for k in used) / wsum
    if total >= 75:
        label = "Sağlam"
    elif total >= 60:
        label = "İyi"
    elif total >= 45:
        label = "Orta"
    else:
        label = "Zayıf"
    return {"total": float(total), "label": label, "subs": subs}


# ───────────────────────── öneri: çeşitlendirici adaylar ─────────────────────────

def suggest_diversifiers(universe_prices: pd.DataFrame, port_ret: pd.Series,
                         quality: pd.Series, exclude, min_quality: float = 3.0,
                         min_obs: int = 100, top_k: int = 5) -> pd.DataFrame:
    """Rapor evreninden, portföyle korelasyonu düşük ve Overall Puanı yeterli adaylar.
    Skor = 0.5 * kalite(0-1) + 0.5 * (1 - korelasyon)/2."""
    prices = universe_prices.sort_index().ffill()
    rets = (prices / prices.shift(1) - 1.0).iloc[1:].replace([np.inf, -np.inf], np.nan)
    rows = []
    for t in rets.columns:
        if t in exclude:
            continue
        q = quality.get(t, np.nan)
        if pd.isna(q) or q < min_quality:
            continue
        s = rets[t].dropna()
        common = s.index.intersection(port_ret.index)
        if len(common) < min_obs:
            continue
        c = float(np.corrcoef(s.loc[common].values, port_ret.loc[common].values)[0, 1])
        rows.append({"ticker": t, "corr": c, "overall": float(q),
                     "vol": float(s.loc[common].std(ddof=1) * np.sqrt(TRADING_DAYS)),
                     "score": 0.5 * (q - 1) / 4.0 + 0.5 * (1 - c) / 2.0})
    if not rows:
        return pd.DataFrame(columns=["ticker", "corr", "overall", "vol", "score"])
    return pd.DataFrame(rows).sort_values("score", ascending=False).head(top_k).reset_index(drop=True)


# ───────────────────────── değerlendirme metni ─────────────────────────

def _p(x, d=1):
    return f"{'-' if x < 0 else ''}%{abs(x) * 100:.{d}f}"


def build_assessment(ctx: dict) -> list[dict]:
    """Kural tabanlı, deterministik değerlendirme (LLM yok). Dönüş: bölümler listesi
    [{title, level: ok|info|warn|bad, bullets: [str]}].

    ctx anahtarları: tickers, weights{t:w}, sector_of{t:sektör}, overall_of{t:puan|None},
    universe_overall (evren ort.), metrics, per_stock(DataFrame), rc{t:pay}, div(dict),
    health(dict), rf, method_label, opt_note, shrinkage, dropped{t:neden}, failed[list],
    jumps{t:(tarih,getiri)}, lookback_days, quality_detail{marj,buyume,gorunum: ağırlıklı ort.}."""
    m, d, h = ctx["metrics"], ctx["div"], ctx["health"]
    w, tickers = ctx["weights"], ctx["tickers"]
    n = len(tickers)
    sections: list[dict] = []

    # 1) Genel
    subs = {k: v for k, v in h["subs"].items() if v is not None}
    weakest = min(subs, key=subs.get)
    strongest = max(subs, key=subs.get)
    lvl = {"Sağlam": "ok", "İyi": "ok", "Orta": "warn", "Zayıf": "bad"}[h["label"]]
    sections.append({"title": "Genel değerlendirme", "level": lvl, "bullets": [
        f"Portföy sağlık skoru **{h['total']:.0f}/100 ({h['label']})**. "
        f"En güçlü boyut **{strongest}** ({subs[strongest]:.0f}), en zayıf boyut "
        f"**{weakest}** ({subs[weakest]:.0f}).",
        f"{n} hisse, {len(set(ctx['sector_of'].get(t) for t in tickers))} sektör; "
        f"ağırlıklar **{ctx['method_label']}** yöntemiyle belirlendi, analiz son "
        f"{m['n_obs']} işlem gününe ({ctx['lookback_days']} günlük pencere) dayanıyor.",
    ]})

    # 2) Risk
    risk_b, lvl = [], "info"
    bvol = m.get("bench_vol")
    if bvol:
        ratio = m["vol"] / bvol
        risk_b.append(f"Yıllık volatilite {_p(m['vol'])}; XU100'ünki {_p(bvol)} "
                      f"(portföy endeksin **{ratio:.2f} katı** oynaklıkta).")
        if ratio > 1.3:
            lvl = "warn"
    else:
        risk_b.append(f"Yıllık volatilite {_p(m['vol'])}.")
    if not np.isnan(m["beta"]):
        b = m["beta"]
        yorum = ("piyasa hareketlerine duyarlılığı düşük" if b < 0.8
                 else "piyasa hareketlerini yaklaşık olarak izliyor" if b <= 1.2
                 else "piyasa hareketlerini büyütüyor")
        risk_b.append(f"XU100'e göre beta **{b:.2f}** - {yorum}; endeksle korelasyon "
                      f"{m['corr_bench']:.2f}.")
        if m["corr_bench"] < 0.5:
            risk_b.append("Endeksle korelasyon düşük: düşük beta **düşük risk demek değildir** - "
                          "oynaklığın büyük kısmı endeksten bağımsız, hisselere özgü risktir.")
        if b > 1.3:
            lvl = "warn"
    mdd_txt = f"Dönem içi en büyük düşüş (max drawdown) {_p(m['max_dd'])}"
    if m.get("bench_max_dd"):
        mdd_txt += f"; XU100'de aynı dönemde {_p(m['bench_max_dd'])}"
    risk_b.append(mdd_txt + ".")
    risk_b.append(f"Günlük %95 VaR {_p(m['var95'], 2)}: günlerin %5'inde portföy bundan fazla "
                  f"kaybetti; bu kötü günlerin ortalaması (CVaR) {_p(m['cvar95'], 2)}. "
                  f"En kötü gün {_p(m['worst_day'], 2)}.")
    rc = ctx["rc"]
    for t in sorted(tickers, key=lambda x: -rc[x]):
        if rc[t] > 0.25 and rc[t] > 1.5 * w[t]:
            risk_b.append(f"⚠️ **{t}** portföyün %{w[t] * 100:.0f}'ini oluşturuyor ama riskin "
                          f"**%{rc[t] * 100:.0f}**'ini taşıyor - ağırlığının çok üstünde risk üretiyor.")
            lvl = "warn"
    sections.append({"title": "Risk analizi", "level": lvl, "bullets": risk_b})

    # 3) Çeşitlendirme
    div_b, lvl = [], "ok"
    if n >= 2:
        div_b.append(f"Ortalama ikili korelasyon **{d['avg_corr']:.2f}**; efektif hisse sayısı "
                     f"**{d['eff_n']:.1f}** ({n} hisseden); diversifikasyon oranı "
                     f"{d['div_ratio']:.2f} (1'in üstü = çeşitlendirmenin riski düşürdüğünü gösterir).")
        mc, lc = d["most_corr_pair"], d["least_corr_pair"]
        if mc[2] >= 0.75:
            div_b.append(f"⚠️ **{mc[0]} – {mc[1]}** korelasyonu {mc[2]:.2f}: neredeyse aynı yönde "
                         f"hareket ediyorlar, ikisini birlikte tutmak çeşitlendirme sağlamıyor.")
            lvl = "warn"
        elif n == 2:
            div_b.append(f"{mc[0]} – {mc[1]} korelasyonu {mc[2]:.2f}.")
        else:
            div_b.append(f"En yüksek korelasyon {mc[0]} – {mc[1]} ({mc[2]:.2f}).")
        if n > 2:
            if lc[2] < 0.6:
                div_b.append(f"En düşük korelasyon {lc[0]} – {lc[1]} ({lc[2]:.2f}) - portföyün en "
                             f"iyi dengeleyici çifti.")
            else:
                div_b.append(f"En düşük korelasyon bile yüksek: {lc[0]} – {lc[1]} ({lc[2]:.2f}); "
                             f"portföyde gerçek bir dengeleyici çift yok.")
        if d["avg_corr"] > 0.6:
            div_b.append("Ortalama korelasyon yüksek: hisseler büyük ölçüde birlikte "
                         "hareket ediyor, farklı sektör seçmek bile riski beklendiği kadar azaltmıyor.")
            lvl = "warn"
    sect_w: dict[str, float] = {}
    for t in tickers:
        s = ctx["sector_of"].get(t) or "Sektörü atanmamış"
        sect_w[s] = sect_w.get(s, 0.0) + w[t]
    top_s = max(sect_w, key=sect_w.get)
    div_b.append("Sektör dağılımı: " + ", ".join(
        f"{s} %{v * 100:.0f}" for s, v in sorted(sect_w.items(), key=lambda x: -x[1])) + ".")
    if sect_w[top_s] > 0.5 and len(sect_w) > 1:
        div_b.append(f"⚠️ Portföyün yarısından fazlası tek sektörde (**{top_s}**).")
        lvl = "warn"
    if n < 5:
        div_b.append(f"Yalnızca {n} hisse var; tek tek hisse riskini yeterince dağıtmak için "
                     f"genelde en az 5-8 hisse önerilir.")
        lvl = "warn"
    sections.append({"title": "Çeşitlendirme ve yoğunlaşma", "level": lvl, "bullets": div_b})

    # 4) Kalite
    q_b, lvl = [], "info"
    overall = {t: v for t, v in ctx["overall_of"].items() if v is not None and t in w}
    if overall:
        wq = sum(w[t] * v for t, v in overall.items()) / sum(w[t] for t in overall)
        uo = ctx.get("universe_overall")
        line = f"Ağırlıklı ortalama Overall Puan **{wq:.2f}/5**"
        if uo:
            line += f" (rapor evreni ortalaması {uo:.2f}; "
            line += "evrenin üstünde)" if wq > uo + 0.05 else (
                "evrenin altında)" if wq < uo - 0.05 else "evrene yakın)")
        q_b.append(line + ".")
        qd = ctx.get("quality_detail") or {}
        parts = [f"{lab} {qd[k]:.1f}" for lab, k in
                 (("marj", "marj"), ("büyüme", "buyume"), ("görünüm", "gorunum")) if qd.get(k) is not None]
        if parts:
            q_b.append("Ağırlıklı alt puanlar: " + ", ".join(parts) + " (5 üzerinden).")
        low = [t for t, v in overall.items() if v < 3.0]
        for t in low:
            q_b.append(f"⚠️ **{t}** Overall Puanı {overall[t]:.1f}/5 - temel göstergeler zayıf "
                       f"(portföyde %{w[t] * 100:.0f}).")
            lvl = "warn"
        best_t = max(overall, key=overall.get)
        worst_t = min(overall, key=overall.get)
        q_b.append(f"En yüksek puan: {best_t} ({overall[best_t]:.1f}); en düşük: {worst_t} "
                   f"({overall[worst_t]:.1f}).")
        for t in tickers:
            if overall.get(t) is not None and overall[t] < 3.5 and ctx["rc"][t] > 0.25:
                q_b.append(f"⚠️ Riskin büyük kısmını taşıyan **{t}** aynı zamanda düşük puanlı "
                           f"({overall[t]:.1f}) - yeniden düşünmeye değer.")
                lvl = "warn"
    missing = [t for t in tickers if ctx["overall_of"].get(t) is None]
    if missing:
        q_b.append("Bu dönemde şirket raporu puanı olmayan hisseler: " + ", ".join(missing) + ".")
    if not q_b:
        q_b.append("Seçilen hisseler için şirket raporu puanı bulunamadı.")
    sections.append({"title": "Temel kalite (şirket raporları)", "level": lvl, "bullets": q_b})

    # 5) Tarihsel performans
    perf = [f"Yıllıklandırılmış getiri (CAGR) {_p(m['cagr'])}, toplam getiri "
            f"{_p(m['total_return'])}; Sharpe **{m['sharpe']:.2f}**, Sortino {m['sortino']:.2f} "
            f"(risksiz faiz {_p(ctx['rf'])})."]
    if "bench_total_return" in m:
        diff = m["total_return"] - m["bench_total_return"]
        perf.append(f"Aynı dönemde XU100 toplam getirisi {_p(m['bench_total_return'])}: portföy "
                    f"endeksi **{'geçti' if diff > 0 else 'geçemedi'}** ({diff * 100:+.1f} puan). "
                    f"Jensen alfa {_p(m['alpha'])} (yıllık).")
    perf.append("Bu rakamlar **geçmiş** veriye dayanır; ağırlıklar da aynı geçmişe göre "
                "optimize edildiği için sonuçlar olduğundan iyi görünür (geriye dönük uyum). "
                "Gelecekteki getiriyi garanti etmez.")
    sections.append({"title": "Tarihsel performans (bilgi amaçlı)", "level": "info", "bullets": perf})

    # 6) Öneriler
    rec = []
    if n >= 2 and d["avg_corr"] > 0.6:
        rec.append("Korelasyonu düşük, farklı sektörden bir hisse eklemeyi düşün "
                   "(aşağıdaki **Çeşitlendirici öneri bul** butonu rapor evreninde arar).")
    if sect_w[top_s] > 0.5 and len(sect_w) > 1:
        rec.append(f"**{top_s}** ağırlığını azaltıp başka bir sektörden hisse ekle.")
    heavy = [t for t in tickers if ctx["rc"][t] > 0.3]
    for t in heavy:
        rec.append(f"**{t}**'nin risk payı %{ctx['rc'][t] * 100:.0f}: ağırlığını düşürmek ya da "
                   f"ters korelasyonlu bir hisseyle dengelemek riski dağıtır.")
    if m["vol"] > 0.40:
        rec.append("Volatilite yüksek; Minimum varyans ya da Risk parity yöntemi ve düşük "
                   "betalı sektörler riski azaltır.")
    if not rec:
        rec.append("Belirgin bir yapısal sorun görünmüyor; ağırlıkları periyodik olarak "
                   "yeniden dengelemek yeterli.")
    sections.append({"title": "Öneriler", "level": "info", "bullets": rec})

    # 7) Yöntem ve veri uyarıları
    warn_b = []
    if ctx.get("opt_note"):
        warn_b.append(ctx["opt_note"])
    warn_b.append(f"Kovaryans Ledoit-Wolf shrinkage ile tahmin edildi (shrinkage "
                  f"%{ctx['shrinkage'] * 100:.0f}); {m['n_obs']} günlük örneklem küçük olduğunda "
                  f"ham kovaryans ağırlıkları aşırı oynak yapardı.")
    warn_b.append(f"Risksiz faiz %{ctx['rf'] * 100:.1f} (elle değiştirilebilir); TL'de yüksek "
                  f"faiz ortamında Sharpe oranı bu değere çok duyarlıdır.")
    if ctx.get("dropped"):
        warn_b.append("Geçmişi yetersiz olduğu için analize alınmayanlar: " + "; ".join(
            f"{t} ({r})" for t, r in ctx["dropped"].items()) + ".")
    if ctx.get("failed"):
        warn_b.append("Fiyat verisi çekilemeyenler: " + ", ".join(ctx["failed"]) + ".")
    if ctx.get("jumps"):
        warn_b.append("⚠️ Tek günde %25'ten büyük hareket görülen hisseler (muhtemel bölünme/"
                      "bedelsiz düzeltmesi, sonuçları bozabilir): " + ", ".join(
                          f"{t} ({v[0]:%d.%m.%Y}, {v[1] * 100:+.0f}%)" for t, v in ctx["jumps"].items()))
    warn_b.append("Bu ekran bilgilendirme amaçlıdır, yatırım tavsiyesi değildir.")
    sections.append({"title": "Yöntem notları ve veri uyarıları", "level": "info", "bullets": warn_b})
    return sections
