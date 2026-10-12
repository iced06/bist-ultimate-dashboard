"""Faktör uzayında portföy: her hisse (momentum, risk, ileri FD/FAVÖK) eksenlerinde bir vektör.

- Eksenler (evren üzerinde kesitsel z-skoru, ±3'e kırpılmış): x = momentum, y = risk (yıllık volatilite),
  z = ileri FD/FAVÖK (log; düşük = ucuz). Hissenin YÖNÜ = faktör karakteri u_i = z_i/‖z_i‖.
- Vektör uzunluğu = |beklenen getiri| (en uzun vektör `scale` birim); işareti renkle gösterilir.
  İsteğe bağlı: "konum" kipinde vektör = z-skorunun kendisi.
- Kosinüs benzerliği yönler arasındadır: cos θ_ij = u_i·u_j (benzer karakter = korelasyonun geometrik görünümü).
- PCA: ağırlıklı ikinci moment matrisi M = Σ w_i v_i v_iᵀ (portföy) ve evren kovaryansı Σ = Cov(z) özayrışımı
  Σ u_k = λ_k u_k; öz vektörler 3B'de ok olarak çizilir.
- Portföy vektörü v_p = Σ w_i v_i.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

AXES = ["mom", "vol", "ev"]
AXIS_LABELS = {"mom": "Momentum (z)", "vol": "Risk: volatilite (z)", "ev": "İleri FD/FAVÖK (z; düşük = ucuz)"}
AXIS_SHORT = {"mom": "Momentum", "vol": "Risk", "ev": "FD/FAVÖK"}


def _zscore(s: pd.Series, clip: float = 3.0) -> pd.Series:
    v = s.astype(float)
    sd = v.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return v * 0.0
    return ((v - v.mean()) / sd).clip(-clip, clip)


def factor_matrix(mom: pd.Series, vol: pd.Series, fwd_ev: pd.Series, sector_of: dict, min_peers: int = 3):
    """Evren z-skorları. fwd_ev ham ileri FD/FAVÖK (pozitif değilse/yoksa NaN → sektör, o da yoksa evren medyanı
    ile doldurulur ve imputed=True). Dönüş: DataFrame(index=ticker; mom, vol, ev z; imputed bool)."""
    idx = [t for t in mom.index if t in vol.index and np.isfinite(mom[t]) and np.isfinite(vol[t])]
    ev = pd.Series({t: (np.log(float(fwd_ev[t])) if t in fwd_ev.index and np.isfinite(fwd_ev[t]) and fwd_ev[t] > 0
                        else np.nan) for t in idx})
    glob = float(np.nanmedian(ev.values)) if np.isfinite(ev.values).any() else 0.0
    filled, imputed = {}, {}
    for t in idx:
        if np.isfinite(ev[t]):
            filled[t], imputed[t] = ev[t], False
            continue
        peers = [ev[p] for p in idx if p != t and sector_of.get(p) == sector_of.get(t) and np.isfinite(ev[p])]
        filled[t] = float(np.median(peers)) if sector_of.get(t) is not None and len(peers) >= min_peers else glob
        imputed[t] = True
    df = pd.DataFrame({"mom": _zscore(mom[idx]), "vol": _zscore(vol[idx]), "ev": _zscore(pd.Series(filled))})
    df["imputed"] = pd.Series(imputed)
    return df


def directions(Z: np.ndarray) -> np.ndarray:
    """Satır başına birim yön; sıfır vektör sıfır kalır."""
    n = np.linalg.norm(Z, axis=1, keepdims=True)
    return np.divide(Z, n, out=np.zeros_like(Z, dtype=float), where=n > 1e-12)


def build_vectors(Z: np.ndarray, mu: np.ndarray, mode: str = "return", scale: float = 3.0) -> np.ndarray:
    """mode='return': v_i = (scale·|μ_i|/max|μ|)·u_i ; mode='position': v_i = z_i."""
    Z = np.asarray(Z, float)
    if mode == "position":
        return Z.copy()
    mu = np.abs(np.asarray(mu, float))
    mx = float(mu.max()) if len(mu) and mu.max() > 0 else 1.0
    return directions(Z) * (scale * mu / mx)[:, None]


def cosine_matrix(Z: np.ndarray) -> np.ndarray:
    U = directions(np.asarray(Z, float))
    return U @ U.T


def portfolio_vector(V: np.ndarray, w: np.ndarray) -> np.ndarray:
    return np.asarray(w, float) @ np.asarray(V, float)


def eigen_axes(M: np.ndarray):
    """Simetrik 3x3 matrisin özayrışımı, büyükten küçüğe. Dönüş: (λ[3], U[3x3, sütun = öz vektör], açıklanan[3]).
    Öz vektör işareti: en büyük mutlak bileşeni pozitif olacak şekilde sabitlenir (belirleyici gösterim)."""
    w, U = np.linalg.eigh(np.asarray(M, float))
    order = np.argsort(w)[::-1]
    w, U = np.clip(w[order], 0, None), U[:, order]
    for k in range(U.shape[1]):
        if U[np.argmax(np.abs(U[:, k])), k] < 0:
            U[:, k] = -U[:, k]
    tot = w.sum()
    return w, U, (w / tot if tot > 0 else np.zeros_like(w))


def second_moment(V: np.ndarray, w: np.ndarray) -> np.ndarray:
    V = np.asarray(V, float)
    w = np.asarray(w, float)
    return (V * w[:, None]).T @ V


def exposures(Z: np.ndarray, w: np.ndarray) -> dict:
    """Portföyün ağırlıklı z maruziyeti ve bu maruziyet vektörünün eksenlerle açısı (derece)."""
    e = np.asarray(w, float) @ np.asarray(Z, float)
    n = float(np.linalg.norm(e))
    ang = {k: (float(np.degrees(np.arccos(np.clip(e[i] / n, -1, 1)))) if n > 1e-12 else np.nan)
           for i, k in enumerate(AXES)}
    return dict(exposure=dict(zip(AXES, e.tolist())), norm=n, angle=ang)


def factor_figure(names, V, w, mu, Zb, port_vec, eig_port=None, eig_univ=None, mode="return", height=620,
                  Z_universe=None):
    """3B şekil. V: n x 3 çizilen vektörler; eig_*: (λ, U, açıklanan) ya da None; Z_universe: bağlam bulutu (konum kipi)."""
    V = np.asarray(V, float)
    L = max(float(np.abs(V).max()), float(np.abs(port_vec).max()), 1.0) * 1.15
    fig = go.Figure()
    for k, (i, color) in enumerate(zip(range(3), ("#E5534B", "#6FCF97", "#4C9BE8"))):
        e = np.zeros(3)
        e[i] = L
        fig.add_trace(go.Scatter3d(x=[-e[0], e[0]], y=[-e[1], e[1]], z=[-e[2], e[2]], mode="lines",
                                   line=dict(width=1.5, color="rgba(150,150,150,0.55)"), hoverinfo="skip",
                                   showlegend=False))
        fig.add_trace(go.Scatter3d(x=[e[0]], y=[e[1]], z=[e[2]], mode="text", text=[AXIS_SHORT[AXES[i]]],
                                   textfont=dict(color="rgba(170,170,170,0.9)", size=11), hoverinfo="skip",
                                   showlegend=False))
    if Z_universe is not None and len(Z_universe):
        Zu = np.asarray(Z_universe, float)
        fig.add_trace(go.Scatter3d(x=Zu[:, 0], y=Zu[:, 1], z=Zu[:, 2], mode="markers", name="Evren",
                                   marker=dict(size=2.5, color="rgba(150,150,150,0.35)"), hoverinfo="skip"))
    xs, ys, zs = [], [], []
    for v in V:
        xs += [0, v[0], None]
        ys += [0, v[1], None]
        zs += [0, v[2], None]
    fig.add_trace(go.Scatter3d(x=xs, y=ys, z=zs, mode="lines", name="Hisse vektörleri", hoverinfo="skip",
                               line=dict(width=4, color="rgba(220,220,220,0.7)")))
    sign = np.sign(mu)
    fig.add_trace(go.Scatter3d(
        x=V[:, 0], y=V[:, 1], z=V[:, 2], mode="markers+text", name="Hisseler", text=names, textposition="top center",
        marker=dict(size=[7 + 40 * float(x) for x in w], color=["#2E9E4F" if s >= 0 else "#E5534B" for s in sign],
                    line=dict(width=1.5, color="white")),
        customdata=np.column_stack([np.asarray(mu) * 100, np.asarray(w) * 100, Zb]),
        hovertemplate="<b>%{text}</b><br>Beklenen getiri %{customdata[0]:.1f}%<br>Ağırlık %{customdata[1]:.1f}%<br>"
                      "Momentum z %{customdata[2]:.2f}<br>Risk z %{customdata[3]:.2f}<br>"
                      "FD/FAVÖK z %{customdata[4]:.2f}<extra></extra>"))
    palette = ("#FF6B6B", "#51CF66", "#4DABF7")
    for eig, nm, dash in ((eig_univ, "Evren", "dot"), (eig_port, "Portföy", "solid")):
        if eig is None:
            continue
        lam, U, expl = eig
        for k in range(3):
            ln = 0.9 * L * float(np.sqrt(lam[k] / max(lam[0], 1e-12)))
            d = U[:, k] * ln
            fig.add_trace(go.Scatter3d(
                x=[0, d[0]], y=[0, d[1]], z=[0, d[2]], mode="lines+markers", name=f"{nm} öz vektör {k + 1}",
                line=dict(width=7 if nm == "Portföy" else 4, color=palette[k], dash=dash),
                marker=dict(size=[1, 6], color=palette[k], symbol="diamond"),
                hovertemplate=f"{nm} u{k + 1}: λ={lam[k]:.2f} (%{expl[k] * 100:.0f})<extra></extra>"))
    fig.add_trace(go.Scatter3d(
        x=[0, port_vec[0]], y=[0, port_vec[1]], z=[0, port_vec[2]], mode="lines+markers+text", name="Portföy vektörü",
        text=["", "Portföy"], textposition="top center", line=dict(width=11, color="gold"),
        marker=dict(size=[1, 11], color="gold", symbol="diamond"), hoverinfo="skip"))
    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=0, b=0), uirevision="pf_fs3d", legend=dict(orientation="h", y=-0.02),
        scene=dict(aspectmode="data", camera=dict(eye=dict(x=1.0, y=1.0, z=0.7)),
                   xaxis=dict(title=AXIS_SHORT["mom"], range=[-L, L]),
                   yaxis=dict(title=AXIS_SHORT["vol"], range=[-L, L]),
                   zaxis=dict(title=AXIS_SHORT["ev"], range=[-L, L])))
    return fig


def cosine_heatmap(names, C):
    fig = go.Figure(go.Heatmap(
        z=C, x=list(names), y=list(names), zmin=-1, zmax=1, colorscale="RdBu_r",
        text=np.round(C, 2), texttemplate="%{text}", hovertemplate="%{y} – %{x}: %{z:.2f}<extra></extra>",
        colorbar=dict(thickness=10)))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
    return fig
