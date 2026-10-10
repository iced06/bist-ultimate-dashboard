"""Portföy için çarpan karşılaştırması, hedef fiyat ve ucuzluk önceliklendirmesi (saf fonksiyonlar).

Yöntem (şeffaf ve ayarlanabilir):
  1. Her hisse için İLERİ F/K ve İLERİ FD/FAVÖK (streamlit_app.compute_stock_valuations).
  2. Referans çarpanlar: (a) hissenin KENDİ geçmiş ileri çarpanlarının medyanı
     (compute_valuation_history ile yeniden kurulmuş), (b) aynı sektördeki hisselerin
     güncel ileri çarpan medyanı (sektörde yeterli hisse yoksa tüm rapor evreni).
  3. Hedef çarpan = w_hist * geçmiş + (1 - w_hist) * sektör, sonra KALİTE/GÖRÜNÜM çarpanıyla
     ölçeklenir: 1 + k_quality * (Overall - sektör ort. Overall) + k_outlook * (Görünüm - 3),
     [adj_min, adj_max] aralığına kırpılır.
  4. Hedef fiyat: F/K için fiyat * hedef_çarpan / güncel_çarpan; FD/FAVÖK için hedef firma
     değeri - net borç, hisse sayısına bölünür. Mevcut yöntemlerin ortalaması hedef fiyattır.
  5. Potansiyel = hedef / fiyat - 1; öncelik sırası potansiyele göre.
Bu bir değerleme HEURİSTİĞİDİR (ileri veriler uygulamanın mekanik tahmininden gelir, analist
konsensüsü değildir); yatırım tavsiyesi değildir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MULT_LABELS = {"fwd_pe": "İleri F/K", "fwd_ev_ebitda": "İleri FD/FAVÖK"}
# FD/FAVÖK bu sektörlerde anlamsız (borç = ham madde); yalnızca F/K kullanılır.
NO_EV_SECTORS = {"Bankacılık", "Sigorta ve Emeklilik", "Finans (Banka Dışı)"}
# Holding: değer iştirak/NAV'dan gelir, F/K ve FD/FAVÖK zayıf sinyal - hedef hesaplanır, güven en fazla Düşük.
LOW_CONF_SECTORS = {"Holding"}
# Çarpan çiftleri: (ileri, güncel/trailing) - ileri/güncel kazanç oranı = trailing_çarpan / ileri_çarpan
PAIR = {"fwd_pe": "pe", "fwd_ev_ebitda": "ev_ebitda"}
ALL_KEY = "__ALL__"

DEFAULTS = dict(
    w_hist=0.5,            # geçmiş medyanın hedef çarpandaki ağırlığı (kalan: sektör)
    k_quality=0.10,        # Overall puanı, sektör ortalamasının her +1 puanı için +%10 çarpan
    k_outlook=0.05,        # Görünüm puanı, nötr 3'ün her +1 puanı için +%5 çarpan
    adj_min=0.75, adj_max=1.25,
    min_hist=6,            # geçmiş medyan için en az gözlem
    min_peers=3,           # sektör medyanı için en az hisse
    tp_clip=(0.5, 2.0),    # birleşik hedef fiyat, fiyatın 0.5x-2x'i ile sınırlanır (uç değer koruması)
    min_growth=0.4,        # tahmin/son-12-ay kazanç oranı bu bandın dışındaysa tahmin güvenilmez sayılır
    max_growth=2.5,        # (mekanik tahmin, kâr dalgalanan/zarar eden şirketlerde uçuyor)
)

LABELS = [(0.30, "Çok ucuz"), (0.10, "Ucuz"), (-0.10, "Makul"), (-0.30, "Pahalı")]


def _pos(x):
    """Sonlu ve pozitifse float, değilse NaN."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return np.nan
    return v if np.isfinite(v) and v > 0 else np.nan


def forecast_ratio(trailing, forward):
    """İleri/güncel kazanç oranı = trailing_çarpan / ileri_çarpan (ikisi de pozitifse), değilse NaN."""
    t, f = _pos(trailing), _pos(forward)
    return t / f if np.isfinite(t) and np.isfinite(f) else np.nan


def forecast_ok(trailing, forward, p) -> tuple[bool, str]:
    """Tahmin makul mü? Güncel çarpan yoksa/negatifse (zarar) ya da ileri kazanç, son 12 aya göre
    [min_growth, max_growth] bandının dışındaysa False + neden."""
    if not np.isfinite(_pos(trailing)):
        return False, "son 12 ay zarar/veri yok"
    r = forecast_ratio(trailing, forward)
    if not np.isfinite(r):
        return False, "ileri çarpan yok"
    if r > p["max_growth"]:
        return False, f"tahmin son 12 aya göre ×{r:.1f} (uç)"
    if r < p["min_growth"]:
        return False, f"tahmin son 12 aya göre ×{r:.2f} (uç)"
    return True, ""


def robust_median(values, min_n: int = 1):
    """Pozitif/sonlu değerlerin (medyan, n). n < min_n ise (nan, n)."""
    v = np.array([_pos(x) for x in values], dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < min_n or len(v) == 0:
        return np.nan, int(len(v))
    return float(np.median(v)), int(len(v))


def sector_reference(rows: pd.DataFrame, sector_of: dict, min_peers: int = 3) -> dict:
    """rows: index=ticker, kolonlar fwd_pe/fwd_ev_ebitda/pe/ev_ebitda (güncel çarpanlar).
    Dönüş: {sektör: {kolon: (medyan, n)}, '__ALL__': {...}}. Bir sektörde bir çarpan için
    min_peers altında hisse varsa o sektörün o çarpanı NaN olur (arayüz evren medyanına düşer)."""
    cols = [c for c in ("fwd_pe", "fwd_ev_ebitda", "pe", "ev_ebitda") if c in rows.columns]
    out: dict = {ALL_KEY: {c: robust_median(rows[c], 1) for c in cols}}
    groups: dict = {}
    for t in rows.index:
        groups.setdefault(sector_of.get(t), []).append(t)
    for sek, ts in groups.items():
        if sek is None:
            continue
        out[sek] = {c: robust_median(rows.loc[ts, c], min_peers) for c in cols}
    return out


def history_reference(hist: pd.DataFrame | None, current: dict, min_obs: int = 6, params: dict | None = None) -> dict:
    """Hissenin geçmiş çarpanlarından {kolon: dict(median, q25, q75, n, pct_below)}.
    pct_below: geçmiş gözlemlerin kaçta kaçı GÜNCEL çarpandan düşük (0-1; düşük = bugün geçmişe göre ucuz)."""
    out = {}
    if hist is None or len(hist) == 0:
        return out
    p = {**DEFAULTS, **(params or {})}
    for c in ("fwd_pe", "fwd_ev_ebitda", "pe", "ev_ebitda"):
        if c not in hist.columns:
            continue
        col = hist[c]
        if c in PAIR and PAIR[c] in hist.columns:
            # geçmiş ileri çarpan gözlemlerinden, o günkü tahmini uç olanlar (kâr tabanı küçük/zarar) elenir
            keep = [forecast_ok(t, f, p)[0] for t, f in zip(hist[PAIR[c]], hist[c])]
            col = col[np.array(keep, dtype=bool)]
        v = np.array([_pos(x) for x in col], dtype=float)
        v = v[np.isfinite(v)]
        if len(v) < min_obs:
            continue
        cur = _pos(current.get(c))
        out[c] = dict(median=float(np.median(v)), q25=float(np.percentile(v, 25)),
                      q75=float(np.percentile(v, 75)), n=int(len(v)),
                      pct_below=(float((v < cur).mean()) if np.isfinite(cur) else np.nan))
    return out


def quality_adjustment(overall, sector_overall_mean, gorunum, params: dict) -> tuple[float, str]:
    """Hedef çarpana uygulanan kalite/görünüm çarpanı ve kısa açıklaması."""
    f, parts = 1.0, []
    if overall is not None and np.isfinite(overall) and sector_overall_mean is not None \
            and np.isfinite(sector_overall_mean):
        d = overall - sector_overall_mean
        f += params["k_quality"] * d
        parts.append(f"Overall {overall:.1f} (sektör ort. {sector_overall_mean:.1f}) → {params['k_quality'] * d * 100:+.0f}%")
    if gorunum is not None and np.isfinite(gorunum):
        d = gorunum - 3.0
        f += params["k_outlook"] * d
        parts.append(f"Görünüm {gorunum:.1f} → {params['k_outlook'] * d * 100:+.0f}%")
    f = float(np.clip(f, params["adj_min"], params["adj_max"]))
    return f, "; ".join(parts) if parts else "puan yok, düzeltme yapılmadı"


def label_for(upside: float) -> str:
    if not np.isfinite(upside):
        return "—"
    for thr, lab in LABELS:
        if upside >= thr:
            return lab
    return "Çok pahalı"


def target_for_stock(price: float, val: dict, hist_ref: dict, sec_ref: dict, overall, sector_overall_mean,
                     gorunum, sector, params: dict | None = None) -> dict:
    """Tek hisse için hedef fiyat. val: compute_stock_valuations çıktısı (fwd_pe, fwd_ev_ebitda,
    ev, market_cap, shares, fwd_ebitda). hist_ref: history_reference çıktısı; sec_ref:
    {kolon: (medyan, n)} (sektör, yetersizse evren). Hedef hesaplanamazsa target_price=NaN."""
    p = {**DEFAULTS, **(params or {})}
    adj, adj_note = quality_adjustment(overall, sector_overall_mean, gorunum, p)
    methods: dict = {}
    rejected: dict = {}
    for key in ("fwd_pe", "fwd_ev_ebitda"):
        if key == "fwd_ev_ebitda" and sector in NO_EV_SECTORS:
            continue
        cur = _pos(val.get(key))
        if not np.isfinite(cur):
            continue
        ok, why = forecast_ok(val.get(PAIR[key]), cur, p)
        if not ok:
            rejected[key] = why
            continue
        H = hist_ref.get(key, {}).get("median", np.nan)
        S = sec_ref.get(key, (np.nan, 0))[0] if isinstance(sec_ref.get(key), tuple) else np.nan
        refs = [(w, r) for w, r in ((p["w_hist"], H), (1.0 - p["w_hist"], S)) if np.isfinite(r)]
        if not refs:
            continue
        wsum = sum(w for w, _ in refs)
        base = sum(w * r for w, r in refs) / wsum
        T = base * adj
        if key == "fwd_pe":
            tp = price * T / cur
        else:
            ev, mcap, shares = _pos(val.get("ev")), _pos(val.get("market_cap")), _pos(val.get("shares"))
            fe = _pos(val.get("fwd_ebitda"))
            if not (np.isfinite(mcap) and np.isfinite(shares) and np.isfinite(fe)) or val.get("ev") is None:
                continue
            net_debt = float(val["ev"]) - mcap
            tp = (T * fe * 1000.0 - net_debt) / shares
            if not np.isfinite(tp) or tp <= 0:
                continue
        methods[key] = dict(current=cur, hist=H, sector=S, base=base, adj=adj, target_multiple=T,
                            target_price=float(tp), n_hist=hist_ref.get(key, {}).get("n", 0),
                            pct_below=hist_ref.get(key, {}).get("pct_below", np.nan))
    res = dict(price=price, adj=adj, adj_note=adj_note, methods=methods, rejected=rejected,
               target_price=np.nan, upside=np.nan, label="—", confidence="—", clipped=False)
    if not methods:
        return res
    tps = [m["target_price"] for m in methods.values()]
    tp = float(np.mean(tps))
    lo, hi = p["tp_clip"]
    clipped = tp < price * lo or tp > price * hi
    tp = float(np.clip(tp, price * lo, price * hi))
    both_refs = any(np.isfinite(m["hist"]) and np.isfinite(m["sector"]) for m in methods.values())
    if len(methods) >= 2 and both_refs:
        conf = "Yüksek"
    elif len(methods) >= 2 or both_refs:
        conf = "Orta"
    else:
        conf = "Düşük"
    if sector in LOW_CONF_SECTORS:
        conf = "Düşük"
    elif clipped:
        conf = "Düşük"          # hedef fiyat uç değer sınırına çarptı: çarpanlardan biri güvenilmez
    res.update(target_price=tp, upside=tp / price - 1.0, label=label_for(tp / price - 1.0),
               confidence=conf, clipped=clipped)
    return res


def prioritize(results: dict) -> pd.DataFrame:
    """results: {ticker: target_for_stock çıktısı + 'overall' + 'gorunum'}. Potansiyele göre sıralı tablo
    (Öncelik 1 = en ucuz). Hedefi olmayanlar sona atılır, sırası boş kalır."""
    rows = []
    for t, r in results.items():
        rows.append(dict(ticker=t, price=r["price"], target=r["target_price"], upside=r["upside"],
                         label=r["label"], confidence=r["confidence"], adj=r["adj"],
                         overall=r.get("overall"), gorunum=r.get("gorunum"),
                         n_methods=len(r["methods"]), clipped=r["clipped"]))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("upside", ascending=False, na_position="last").reset_index(drop=True)
    df["rank"] = np.where(df["upside"].notna(), np.arange(1, len(df) + 1), np.nan)
    return df
