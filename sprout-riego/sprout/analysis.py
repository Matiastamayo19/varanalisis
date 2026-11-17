"""Lógica de análisis: riego, alertas, estado de sensores, estadística y correlación."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Params:
    hum_seca: float = 20.0      # % por debajo = suelo seco (igual que el firmware)
    hum_humeda: float = 55.0    # % por encima = suelo húmedo
    nivel_bajo: float = 20.0    # % por debajo = tanque bajo
    gap_min: float = 10.0       # minutos sin datos para considerar un hueco
    frozen_min: float = 30.0    # minutos con valor idéntico = sensor congelado
    riego_max_min: float = 10.0  # riego más largo que esto = prolongado
    post_min: float = 2.0       # minutos tras cerrar para medir efecto del riego
    delta_min: float = 2.0      # puntos % mínimos de mejora esperados tras regar


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def episodes(mask: pd.Series) -> pd.DataFrame:
    """Tramos consecutivos donde mask es True.
    Devuelve inicio, fin (instante en que termina el tramo), muestras."""
    m = mask.fillna(False).astype(bool)
    if m.empty:
        return pd.DataFrame(columns=["inicio", "fin", "muestras"])
    v = m.to_numpy()
    prev = np.r_[False, v[:-1]]
    nxt = np.r_[v[1:], False]
    starts = np.flatnonzero(v & ~prev)
    ends = np.flatnonzero(v & ~nxt)
    idx = m.index
    rows = []
    for s, e in zip(starts, ends):
        fin = idx[e + 1] if e + 1 < len(idx) else idx[e]
        rows.append((idx[s], fin, int(e - s + 1)))
    return pd.DataFrame(rows, columns=["inicio", "fin", "muestras"])


def _mins(a, b) -> float:
    return float((b - a).total_seconds() / 60)


def sampling_interval(df: pd.DataFrame) -> pd.Timedelta:
    d = df.index.to_series().diff().dropna()
    return d.median() if len(d) else pd.Timedelta(seconds=10)


# --------------------------------------------------------------------------
# Riego
# --------------------------------------------------------------------------
def riego_events(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    cols = ["inicio", "fin", "duracion_min", "origen_probable", "humedad_inicio",
            "humedad_post", "mejora_humedad", "nivel_inicio", "nivel_fin", "consumo_nivel"]
    if "valvula" not in df:
        return pd.DataFrame(columns=cols)
    v = df["valvula"].ffill().fillna(0) >= 0.5
    ep = episodes(v)
    if ep.empty:
        return pd.DataFrame(columns=cols)

    hum = df["humedad_suelo"].dropna() if "humedad_suelo" in df else pd.Series(dtype=float)
    niv = df["nivel_agua"].dropna() if "nivel_agua" in df else pd.Series(dtype=float)
    last = df.index.max()
    rows = []
    for _, r in ep.iterrows():
        h0 = hum.asof(r.inicio) if len(hum) else np.nan
        tpost = r.fin + pd.Timedelta(minutes=p.post_min)
        h1 = hum.asof(tpost) if len(hum) and tpost <= last else np.nan
        n0 = niv.asof(r.inicio) if len(niv) else np.nan
        n1 = niv.asof(r.fin) if len(niv) else np.nan
        origen = "Automático (suelo seco)" if (pd.notna(h0) and h0 < p.hum_seca) else "Manual / otro"
        rows.append({
            "inicio": r.inicio, "fin": r.fin,
            "duracion_min": round(_mins(r.inicio, r.fin), 2),
            "origen_probable": origen,
            "humedad_inicio": h0, "humedad_post": h1,
            "mejora_humedad": (h1 - h0) if pd.notna(h0) and pd.notna(h1) else np.nan,
            "nivel_inicio": n0, "nivel_fin": n1,
            "consumo_nivel": (n0 - n1) if pd.notna(n0) and pd.notna(n1) else np.nan,
        })
    return pd.DataFrame(rows, columns=cols)


# --------------------------------------------------------------------------
# Estado de sensores
# --------------------------------------------------------------------------
def sensor_status(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    rows = []
    dt = sampling_interval(df)
    span = (df.index.max() - df.index.min()) if len(df) > 1 else pd.Timedelta(0)
    expected = max(int(span / dt) + 1, 1) if dt > pd.Timedelta(0) else len(df)
    sensors = [("humedad_suelo", "Humedad del suelo (%)"), ("nivel_agua", "Nivel de agua (%)"),
               ("humedad_raw", "Humedad ADC"), ("nivel_raw", "Nivel ADC")]
    for col, label in sensors:
        if col not in df:
            continue
        s = df[col]
        valid = s.dropna()
        if valid.empty:
            rows.append({"sensor": label, "estado": "Falla", "motivo": "Sin lecturas válidas",
                         "ultima_lectura": None, "ultimo_valor": np.nan, "cobertura_%": 0.0,
                         "max_hueco_min": np.nan, "min": np.nan, "max": np.nan})
            continue
        gaps = valid.index.to_series().diff().dropna()
        max_gap = _mins(pd.Timestamp(0, tz=valid.index.tz), pd.Timestamp(0, tz=valid.index.tz) + gaps.max()) if len(gaps) else 0.0
        cover = min(100.0, len(valid) / expected * 100)
        # saturación en extremos
        is_pct = col.endswith(("suelo", "agua"))
        lo, hi = (0, 100) if is_pct else (0, 4095)
        sat = ((valid <= lo) | (valid >= hi)).mean() * 100
        # congelado: valor idéntico sostenido, excluyendo extremos
        frozen = episodes((valid.diff() == 0) & (valid > lo) & (valid < hi))
        frozen_long = frozen[frozen.apply(lambda r: _mins(r.inicio, r.fin) >= p.frozen_min, axis=1)] if len(frozen) else frozen

        estado, motivo = "OK", "Lecturas normales"
        if sat > 80:
            estado, motivo = "Falla", f"Saturado en el extremo el {sat:.0f}% del tiempo (¿sensor desconectado?)"
        elif len(frozen_long):
            estado, motivo = "Revisar", f"{len(frozen_long)} tramo(s) con valor constante ≥ {p.frozen_min:.0f} min"
        elif max_gap > p.gap_min:
            estado, motivo = "Revisar", f"Hueco máximo de {max_gap:.1f} min sin datos"
        elif cover < 80:
            estado, motivo = "Revisar", f"Cobertura baja ({cover:.0f}%)"
        rows.append({
            "sensor": label, "estado": estado, "motivo": motivo,
            "ultima_lectura": valid.index[-1], "ultimo_valor": float(valid.iloc[-1]),
            "cobertura_%": round(cover, 1), "max_hueco_min": round(max_gap, 1),
            "min": float(valid.min()), "max": float(valid.max()),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Alertas operativas
# --------------------------------------------------------------------------
def compute_alerts(df: pd.DataFrame, events: pd.DataFrame, p: Params) -> pd.DataFrame:
    out = []

    def add(inicio, fin, tipo, sev, sensor, detalle, valor=np.nan):
        out.append({"inicio": inicio, "fin": fin, "duracion_min": round(_mins(inicio, fin), 2),
                    "tipo": tipo, "severidad": sev, "sensor": sensor,
                    "detalle": detalle, "valor": valor})

    if "humedad_suelo" in df:
        h = df["humedad_suelo"]
        for _, r in episodes(h < p.hum_seca).iterrows():
            seg = h[r.inicio:r.fin]
            add(r.inicio, r.fin, "Suelo seco", "Media", "Humedad",
                f"Humedad < {p.hum_seca:.0f}% (mínimo {seg.min():.1f}%)", float(seg.min()))

    if "nivel_agua" in df:
        n = df["nivel_agua"]
        for _, r in episodes(n < p.nivel_bajo).iterrows():
            seg = n[r.inicio:r.fin]
            add(r.inicio, r.fin, "Nivel de tanque bajo", "Alta", "Nivel",
                f"Nivel < {p.nivel_bajo:.0f}% (mínimo {seg.min():.1f}%)", float(seg.min()))

    # Huecos de datos
    t = df.index.to_series()
    gap = t.diff()
    for ts, g in gap[gap > pd.Timedelta(minutes=p.gap_min)].items():
        prev = t.loc[:ts].iloc[-2]
        add(prev, ts, "Sin datos", "Media", "Sistema", f"{g.total_seconds() / 60:.1f} min sin registros")

    # Sensor congelado
    for col, lbl, lo, hi in [("humedad_suelo", "Humedad", 0, 100), ("nivel_agua", "Nivel", 0, 100)]:
        if col in df:
            s = df[col].dropna()
            ep = episodes((s.diff() == 0) & (s > lo) & (s < hi))
            for _, r in ep.iterrows():
                if _mins(r.inicio, r.fin) >= p.frozen_min:
                    add(r.inicio, r.fin, "Sensor con valor constante", "Media", lbl,
                        f"Mismo valor ({s.loc[r.inicio]:.1f}%) por {_mins(r.inicio, r.fin):.0f} min")

    # Reglas sobre riegos
    for _, e in events.iterrows():
        if e.duracion_min > p.riego_max_min:
            add(e.inicio, e.fin, "Riego prolongado", "Media", "Válvula",
                f"Válvula abierta {e.duracion_min:.1f} min (límite {p.riego_max_min:.0f})", e.duracion_min)
        if pd.notna(e.mejora_humedad) and e.mejora_humedad < p.delta_min:
            add(e.inicio, e.fin, "Riego sin efecto", "Media", "Humedad",
                f"Humedad cambió {e.mejora_humedad:+.1f} pts tras regar (esperado ≥ {p.delta_min:.0f})",
                float(e.mejora_humedad))
        if pd.notna(e.nivel_inicio) and e.nivel_inicio < p.nivel_bajo:
            add(e.inicio, e.fin, "Riego con tanque bajo", "Alta", "Nivel",
                f"Se regó con nivel {e.nivel_inicio:.1f}% (< {p.nivel_bajo:.0f}%)", float(e.nivel_inicio))

    cols = ["inicio", "fin", "duracion_min", "tipo", "severidad", "sensor", "detalle", "valor"]
    res = pd.DataFrame(out, columns=cols)
    if not res.empty:
        res = res.sort_values("inicio").reset_index(drop=True)
    return res


# --------------------------------------------------------------------------
# Registros del sistema
# --------------------------------------------------------------------------
def system_log(df: pd.DataFrame, events: pd.DataFrame, alerts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, e in events.iterrows():
        rows.append((e.inicio, "Válvula", "ABIERTA", f"{e.origen_probable}"))
        rows.append((e.fin, "Válvula", "CERRADA", f"Duración {e.duracion_min:.1f} min"))
    for col, name in [("alerta_nivel", "Alerta nivel (firmware)"), ("alerta_humedad", "Alerta humedad (firmware)")]:
        if col in df:
            for _, r in episodes(df[col].fillna(0) >= 0.5).iterrows():
                rows.append((r.inicio, name, "ACTIVA", ""))
                rows.append((r.fin, name, "RESUELTA", f"Duración {_mins(r.inicio, r.fin):.1f} min"))
    for col, name in [("estado_suelo", "Estado suelo"), ("estado_nivel", "Estado nivel")]:
        if col in df:
            s = df[col].dropna()
            chg = s[s != s.shift()]
            for ts, val in chg.items():
                rows.append((ts, name, str(val), "Cambio de estado"))
    for _, a in alerts.iterrows():
        rows.append((a.inicio, f"Alerta: {a.tipo}", "INICIO", a.detalle))
    log = pd.DataFrame(rows, columns=["tiempo", "origen", "evento", "detalle"])
    return log.sort_values("tiempo").reset_index(drop=True) if not log.empty else log


# --------------------------------------------------------------------------
# Estadística
# --------------------------------------------------------------------------
def stats_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ["humedad_suelo", "nivel_agua", "humedad_raw", "nivel_raw"] if c in df]
    rows = []
    for c in cols:
        s = df[c].dropna()
        if s.empty:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        out = int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum())
        rows.append({
            "variable": c, "n": len(s), "media": s.mean(), "desv_est": s.std(),
            "min": s.min(), "p5": s.quantile(0.05), "p25": q1, "mediana": s.median(),
            "p75": q3, "p95": s.quantile(0.95), "max": s.max(),
            "coef_var_%": (s.std() / s.mean() * 100) if s.mean() else np.nan,
            "asimetria": s.skew(), "curtosis": s.kurt(), "atipicos_IQR": out,
        })
    return pd.DataFrame(rows).set_index("variable") if rows else pd.DataFrame()


def estados(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Columnas calculadas: estado de suelo, estado de nivel y riego activo."""
    out = pd.DataFrame(index=df.index)
    if "humedad_suelo" in df:
        h = df["humedad_suelo"]
        out["estado_suelo_calc"] = np.select([h < p.hum_seca, h >= p.hum_humeda],
                                             ["SECO", "HUMEDO"], default="INTERMEDIO")
        out.loc[h.isna(), "estado_suelo_calc"] = np.nan
    if "nivel_agua" in df:
        n = df["nivel_agua"]
        out["estado_nivel_calc"] = np.where(n < p.nivel_bajo, "BAJO", "NORMAL")
        out.loc[n.isna(), "estado_nivel_calc"] = np.nan
    if "valvula" in df:
        out["riego_activo"] = (df["valvula"].ffill().fillna(0) >= 0.5).astype(int)
    return out


def daily_summary(df: pd.DataFrame, events: pd.DataFrame, p: Params) -> pd.DataFrame:
    d = pd.DataFrame(index=df.resample("D").mean(numeric_only=True).index)
    if "humedad_suelo" in df:
        g = df["humedad_suelo"].resample("D")
        d["humedad_media"], d["humedad_min"], d["humedad_max"] = g.mean(), g.min(), g.max()
        d["%_tiempo_seco"] = (df["humedad_suelo"] < p.hum_seca).resample("D").mean() * 100
    if "nivel_agua" in df:
        g = df["nivel_agua"].resample("D")
        d["nivel_medio"], d["nivel_min"], d["nivel_max"] = g.mean(), g.min(), g.max()
        d["%_tiempo_nivel_bajo"] = (df["nivel_agua"] < p.nivel_bajo).resample("D").mean() * 100
    if not events.empty:
        ev = events.copy()
        ev["dia"] = ev["inicio"].dt.floor("D")
        d["riegos"] = ev.groupby("dia").size().reindex(d.index).fillna(0).astype(int)
        d["min_valvula_abierta"] = ev.groupby("dia")["duracion_min"].sum().reindex(d.index).fillna(0)
    elif "valvula" in df:
        d["riegos"], d["min_valvula_abierta"] = 0, 0.0
    return d.round(2)


def hourly_pattern(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ["humedad_suelo", "nivel_agua"] if c in df]
    return df[cols].groupby(df.index.hour).mean() if cols else pd.DataFrame()


# --------------------------------------------------------------------------
# Correlación
# --------------------------------------------------------------------------
def corr_matrix(df: pd.DataFrame, method: str = "pearson") -> pd.DataFrame:
    cols = [c for c in ["humedad_suelo", "nivel_agua", "humedad_raw", "nivel_raw", "valvula"] if c in df]
    x = df[cols].copy()
    if "valvula" in x:
        x["valvula"] = x["valvula"].ffill().fillna(0)
    x = x.loc[:, x.nunique(dropna=True) > 1]
    return x.corr(method=method) if x.shape[1] > 1 else pd.DataFrame()


def ols(x: pd.Series, y: pd.Series) -> dict | None:
    d = pd.concat([x, y], axis=1).dropna()
    if len(d) < 3 or d.iloc[:, 0].nunique() < 2:
        return None
    xv, yv = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()
    slope, intercept = np.polyfit(xv, yv, 1)
    r = float(np.corrcoef(xv, yv)[0, 1])
    return {"pendiente": float(slope), "intercepto": float(intercept), "r": r, "r2": r * r, "n": len(d)}


def interpret_r(r: float) -> str:
    a = abs(r)
    fuerza = "muy débil" if a < 0.2 else "débil" if a < 0.4 else "moderada" if a < 0.6 else "fuerte" if a < 0.8 else "muy fuerte"
    sentido = "positiva" if r > 0 else "negativa"
    return f"{fuerza} {sentido}"


def lag_corr(a: pd.Series, b: pd.Series, max_lag: int) -> pd.DataFrame:
    """Correlación entre a(t) y b(t+k). k>0: b reacciona después de a."""
    d = pd.concat([a, b], axis=1).dropna()
    if len(d) < max_lag * 2 + 3:
        return pd.DataFrame(columns=["lag", "r"])
    x, y = d.iloc[:, 0], d.iloc[:, 1]
    res = []
    for k in range(-max_lag, max_lag + 1):
        r = x.corr(y.shift(-k))
        res.append((k, r))
    return pd.DataFrame(res, columns=["lag", "r"]).dropna()
