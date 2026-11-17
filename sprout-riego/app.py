"""Sprout · Monitoreo de riego (Streamlit).

Sube el CSV/XLSX descargado de InfluxDB, ThingsBoard o Grafana y la app muestra
resumen, sensores, evolución, nivel de agua, riego, estadística, alertas,
correlaciones, registros del sistema y descargas de datos procesados.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from sprout import analysis as an
from sprout import loader

st.set_page_config(page_title="Sprout · Monitoreo de riego", page_icon="🌱",
                   layout="wide", initial_sidebar_state="expanded")

GREEN, BLUE, ORANGE, RED, YELLOW, BROWN = "#2e9e5b", "#1f77b4", "#f28e2b", "#d62728", "#f2c14e", "#8d6e63"
LABELS = {
    "humedad_suelo": "Humedad del suelo (%)", "nivel_agua": "Nivel de agua (%)",
    "humedad_raw": "Humedad (ADC)", "nivel_raw": "Nivel (ADC)", "valvula": "Válvula (0/1)",
}
COLORS = {"humedad_suelo": BROWN, "nivel_agua": BLUE, "humedad_raw": GREEN, "nivel_raw": "#17becf", "valvula": ORANGE}
SAMPLE = Path(__file__).parent / "data" / "ejemplo_riego.csv"

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.6rem;}
      div[data-testid="stMetric"] {background:#f6faf7; border:1px solid #e1ece4;
                                   border-radius:12px; padding:12px 14px;}
      .stTabs [data-baseweb="tab-list"] {gap: 4px; flex-wrap: wrap;}
      .stTabs [data-baseweb="tab"] {border-radius: 8px 8px 0 0; padding: 8px 14px;}
      .pill {display:inline-block; padding:2px 10px; border-radius:999px; font-size:.8rem; font-weight:600;}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Helpers de UI
# --------------------------------------------------------------------------
def show(fig: go.Figure, key: str | None = None) -> None:
    fig.update_layout(template="plotly_white", margin=dict(l=10, r=10, t=40, b=10),
                      hovermode="x unified" if fig.layout.hovermode is None else fig.layout.hovermode,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    try:
        st.plotly_chart(fig, width="stretch", key=key)
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key=key)


def table(df: pd.DataFrame, **kw) -> None:
    try:
        st.dataframe(df, width="stretch", **kw)
    except TypeError:
        st.dataframe(df, use_container_width=True, **kw)


def download(label: str, df: pd.DataFrame, name: str, key: str) -> None:
    st.download_button(label, to_csv(df), file_name=name, mime="text/csv", key=key, disabled=df.empty)


def naive(df: pd.DataFrame) -> pd.DataFrame:
    """Quita zona horaria para exportar (Excel no admite tz-aware)."""
    out = df.copy()
    if isinstance(out.index, pd.DatetimeIndex):
        out = out.reset_index()
    for c in out.columns:
        if isinstance(out[c].dtype, pd.DatetimeTZDtype):
            out[c] = out[c].dt.tz_localize(None)
    return out


def to_csv(df: pd.DataFrame) -> bytes:
    return naive(df).to_csv(index=False).encode("utf-8-sig")


def to_excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, d in sheets.items():
            naive(d).to_excel(xw, sheet_name=name[:31], index=False)
    return buf.getvalue()


def add_events_bands(fig: go.Figure, events: pd.DataFrame, row=None, col=None, max_n: int = 150) -> None:
    if events.empty or len(events) > max_n:
        return
    for _, e in events.iterrows():
        kw = dict(x0=e.inicio, x1=e.fin, fillcolor=ORANGE, opacity=0.18, line_width=0, layer="below")
        if row:
            fig.add_vrect(row=row, col=col or 1, **kw)
        else:
            fig.add_vrect(**kw)


# --------------------------------------------------------------------------
# Carga de datos
# --------------------------------------------------------------------------
@st.cache_data(show_spinner="Leyendo archivo…")
def cached_load(name: str, content: bytes):
    return loader.load_file(name, content)


def load_sources(files) -> tuple[pd.DataFrame, list[dict]]:
    frames, infos = [], []
    for f in files:
        df, info = cached_load(f.name, f.getvalue())
        info["archivo"] = f.name
        frames.append(df)
        infos.append(info)
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df, infos


st.sidebar.title("🌱 Sprout")
st.sidebar.caption("Monitoreo de riego y tanque")
uploads = st.sidebar.file_uploader(
    "Adjunta la data de riego", type=["csv", "xlsx", "xls"], accept_multiple_files=True,
    help="CSV/XLSX exportado de InfluxDB, ThingsBoard o Grafana. Puedes subir varios.")
use_sample = st.sidebar.toggle("Usar datos de ejemplo", value=False,
                               help="Datos sintéticos para ver cómo luce la app.")

if not uploads and not use_sample:
    st.title("🌱 Monitoreo de riego")
    st.info("Adjunta tu archivo en la barra lateral (**CSV o XLSX**) para ver el análisis, "
            "o activa **Usar datos de ejemplo**.")
    c1, c2, c3 = st.columns(3)
    c1.markdown("**1. Exporta** los datos desde InfluxDB (Data Explorer → Download CSV), "
                "ThingsBoard (Latest/Timeseries → Export) o Grafana (Inspect → Data → CSV).")
    c2.markdown("**2. Adjunta** el archivo en la barra lateral. Reconozco las columnas "
                "`humedad_suelo`, `nivel_agua`, `humedad_raw`, `nivel_raw`, `valvula`, "
                "`alerta_nivel`, `alerta_humedad`, `estado_suelo`, `estado_nivel`.")
    c3.markdown("**3. Explora** el resumen, sensores, evolución, riego, alertas, "
                "correlaciones y **descarga** los datos procesados.")
    st.stop()

try:
    if uploads:
        data, infos = load_sources(uploads)
    else:
        class _F:  # archivo de ejemplo con la misma interfaz que un upload
            name = SAMPLE.name
            def getvalue(self): return SAMPLE.read_bytes()
        data, infos = load_sources([_F()])
except loader.DataFormatError as e:
    st.error(f"No pude leer el archivo: {e}")
    st.stop()
except Exception as e:  # noqa: BLE001
    st.error(f"Error inesperado leyendo el archivo: {e}")
    st.stop()

# ---- Filtros ----
st.sidebar.divider()
st.sidebar.subheader("Filtros")
tmin, tmax = data.index.min(), data.index.max()
rng = st.sidebar.date_input("Rango de fechas", value=(tmin.date(), tmax.date()),
                            min_value=tmin.date(), max_value=tmax.date())
if isinstance(rng, tuple) and len(rng) == 2:
    d0 = pd.Timestamp(rng[0], tz=loader.TZ)
    d1 = pd.Timestamp(rng[1], tz=loader.TZ) + pd.Timedelta(days=1)
    data = data.loc[(data.index >= d0) & (data.index < d1)]
if data.empty:
    st.warning("No hay datos en el rango elegido.")
    st.stop()

RULES = {"Datos originales": None, "10 segundos": "10s", "1 minuto": "1min", "5 minutos": "5min",
         "15 minutos": "15min", "1 hora": "1h", "1 día": "1D"}
default_rule = 0 if len(data) <= 4000 else 2 if len(data) <= 50000 else 3
rule_label = st.sidebar.selectbox("Agrupar datos (gráficos)", list(RULES), index=default_rule,
                                  help="Promedia los datos para que los gráficos sean fluidos. "
                                       "Los eventos y alertas usan siempre los datos originales.")
rule = RULES[rule_label]

with st.sidebar.expander("Umbrales y reglas", expanded=False):
    p = an.Params(
        hum_seca=st.number_input("Humedad seca (< %)", 0.0, 100.0, 20.0, 1.0),
        hum_humeda=st.number_input("Humedad húmeda (≥ %)", 0.0, 100.0, 55.0, 1.0),
        nivel_bajo=st.number_input("Nivel de tanque bajo (< %)", 0.0, 100.0, 20.0, 1.0),
        gap_min=st.number_input("Hueco de datos (min)", 1.0, 1440.0, 10.0, 1.0),
        frozen_min=st.number_input("Sensor congelado (min)", 1.0, 1440.0, 30.0, 5.0),
        riego_max_min=st.number_input("Riego prolongado (> min)", 0.5, 240.0, 10.0, 0.5),
        post_min=st.number_input("Medir efecto del riego a (min)", 0.0, 60.0, 2.0, 0.5),
        delta_min=st.number_input("Mejora mínima de humedad (pts %)", 0.0, 50.0, 2.0, 0.5),
    )

with st.sidebar.expander("Info del archivo"):
    for i in infos:
        st.write(f"**{i['archivo']}** — {i['formato']}, {i['filas']:,} registros")

# --------------------------------------------------------------------------
# Cálculos
# --------------------------------------------------------------------------
dfr = loader.resample(data, rule)
events = an.riego_events(data, p)
alerts = an.compute_alerts(data, events, p)
log = an.system_log(data, events, alerts)
status = an.sensor_status(data, p)
est = an.estados(dfr, p)
processed = pd.concat([dfr, est], axis=1)
daily = an.daily_summary(data, events, p)
dt = an.sampling_interval(data)
has_h, has_n, has_v = "humedad_suelo" in data, "nivel_agua" in data, "valvula" in data

st.title("🌱 Monitoreo de riego y tanque")
st.caption(f"{data.index.min():%Y-%m-%d %H:%M} → {data.index.max():%Y-%m-%d %H:%M} (hora Colombia) · "
           f"{len(data):,} registros · intervalo típico {dt.total_seconds():.0f} s · gráficos: {rule_label.lower()}")

tabs = st.tabs(["📋 Resumen", "🛰️ Sensores", "📈 Evolución", "💧 Nivel de agua", "🚿 Riego",
                "📊 Estadística", "🚨 Alertas", "🔗 Correlación", "🧾 Registros", "⬇️ Descargas"])

# ============================ RESUMEN ============================
with tabs[0]:
    last = data.iloc[-1]
    c = st.columns(6)
    if has_h:
        prev = data["humedad_suelo"].dropna()
        c[0].metric("Humedad actual", f"{prev.iloc[-1]:.1f}%",
                    f"{prev.iloc[-1] - prev.iloc[0]:+.1f} pts vs inicio")
    if has_n:
        prevn = data["nivel_agua"].dropna()
        c[1].metric("Nivel actual", f"{prevn.iloc[-1]:.1f}%", f"{prevn.iloc[-1] - prevn.iloc[0]:+.1f} pts vs inicio")
    c[2].metric("Riegos", f"{len(events)}")
    c[3].metric("Válvula abierta", f"{events['duracion_min'].sum():.1f} min" if has_v else "—")
    n_high = int((alerts["severidad"] == "Alta").sum()) if not alerts.empty else 0
    c[4].metric("Alertas", f"{len(alerts)}", f"{n_high} altas" if n_high else "sin altas",
                delta_color="inverse" if n_high else "off")
    c[5].metric("Registros", f"{len(data):,}")

    st.subheader("Diagnóstico automático")
    msgs = []
    if has_h:
        h = data["humedad_suelo"].dropna()
        seco = (h < p.hum_seca).mean() * 100
        hum = (h >= p.hum_humeda).mean() * 100
        msgs.append(f"El suelo estuvo **seco {seco:.0f}%**, **intermedio {100 - seco - hum:.0f}%** y "
                    f"**húmedo {hum:.0f}%** del tiempo (media {h.mean():.1f}%).")
    if has_n:
        n = data["nivel_agua"].dropna()
        bajo = (n < p.nivel_bajo).mean() * 100
        msgs.append(f"El tanque estuvo bajo el umbral ({p.nivel_bajo:.0f}%) el **{bajo:.0f}%** del tiempo "
                    f"(mín {n.min():.1f}%, máx {n.max():.1f}%).")
    if has_v and len(events):
        ef = events["mejora_humedad"].dropna()
        txt = f" Mejora media de humedad tras regar: **{ef.mean():+.1f} pts**." if len(ef) else ""
        msgs.append(f"Se registraron **{len(events)} riegos** (duración media "
                    f"{events['duracion_min'].mean():.1f} min).{txt}")
    elif has_v:
        msgs.append("La válvula no se abrió en el periodo seleccionado.")
    if not alerts.empty:
        top = alerts["tipo"].value_counts().head(3)
        msgs.append("Alertas más frecuentes: " + ", ".join(f"**{k}** ({v})" for k, v in top.items()) + ".")
    bad = status[status["estado"] != "OK"] if not status.empty else status
    msgs.append("Todos los sensores operan con normalidad." if bad.empty else
                "Sensores a revisar: " + ", ".join(f"**{r.sensor}** ({r.estado})" for r in bad.itertuples()) + ".")
    for m in msgs:
        st.markdown("- " + m)

    left, right = st.columns([2, 1])
    with left:
        fig = make_subplots(specs=[[{"secondary_y": False}]])
        for col in [c_ for c_ in ("humedad_suelo", "nivel_agua") if c_ in dfr]:
            fig.add_trace(go.Scatter(x=dfr.index, y=dfr[col], name=LABELS[col],
                                     line=dict(color=COLORS[col], width=2)))
        if has_h:
            fig.add_hline(y=p.hum_seca, line_dash="dot", line_color=RED, annotation_text="Seco")
        add_events_bands(fig, events)
        fig.update_yaxes(range=[0, 100], title="%")
        fig.update_layout(title="Humedad y nivel (franjas naranjas = riego)", height=380)
        show(fig, "res_main")
    with right:
        if has_h:
            h = data["humedad_suelo"].dropna()
            parts = pd.Series({"Seco": (h < p.hum_seca).sum(),
                               "Intermedio": ((h >= p.hum_seca) & (h < p.hum_humeda)).sum(),
                               "Húmedo": (h >= p.hum_humeda).sum()})
            fig = px.pie(values=parts.values, names=parts.index, hole=0.55,
                         color=parts.index, color_discrete_map={"Seco": RED, "Intermedio": YELLOW, "Húmedo": GREEN},
                         title="Tiempo por estado del suelo")
            fig.update_layout(height=380)
            show(fig, "res_pie")

# ============================ SENSORES ============================
with tabs[1]:
    st.subheader("Estado de los sensores")
    if status.empty:
        st.info("No hay columnas de sensores reconocidas.")
    else:
        icon = {"OK": "🟢 OK", "Revisar": "🟡 Revisar", "Falla": "🔴 Falla"}
        cols = st.columns(len(status))
        for col, r in zip(cols, status.itertuples()):
            col.metric(r.sensor, icon[r.estado], f"Último: {r.ultimo_valor:.1f}" if pd.notna(r.ultimo_valor) else "sin datos",
                       delta_color="off")
            col.caption(r.motivo)
        s = status.copy()
        s["estado"] = s["estado"].map(icon)
        table(s, hide_index=True, column_config={
            "ultima_lectura": st.column_config.DatetimeColumn("última lectura", format="YYYY-MM-DD HH:mm:ss"),
            "cobertura_%": st.column_config.ProgressColumn("cobertura %", min_value=0, max_value=100, format="%.0f%%"),
        })
    per_day = data.resample("D").size().rename("registros").reset_index()
    fig = px.bar(per_day, x="time", y="registros", title="Registros recibidos por día", color_discrete_sequence=[GREEN])
    fig.update_layout(height=300)
    show(fig, "sens_day")
    if len(data) > 1:
        gaps = data.index.to_series().diff().dt.total_seconds().div(60).dropna()
        fig = px.histogram(gaps[gaps > 0], nbins=50, log_y=True, title="Distribución del intervalo entre registros (min)",
                           color_discrete_sequence=[BLUE])
        fig.update_layout(height=300, xaxis_title="minutos entre registros", yaxis_title="frecuencia (log)")
        show(fig, "sens_gap")

# ============================ EVOLUCIÓN ============================
with tabs[2]:
    avail = [c_ for c_ in ("humedad_suelo", "nivel_agua", "humedad_raw", "nivel_raw", "valvula") if c_ in dfr]
    sel = st.multiselect("Variables", avail, default=[c_ for c_ in avail if c_ in ("humedad_suelo", "nivel_agua")],
                         format_func=lambda k: LABELS[k])
    k1, k2 = st.columns(2)
    smooth = k1.slider("Suavizado (promedio móvil, muestras)", 1, 60, 1)
    bands = k2.checkbox("Marcar riegos", value=True)
    if sel:
        fig = make_subplots(rows=len(sel), cols=1, shared_xaxes=True, vertical_spacing=0.05,
                            subplot_titles=[LABELS[k] for k in sel])
        for i, col in enumerate(sel, start=1):
            y = dfr[col].rolling(smooth, min_periods=1).mean() if smooth > 1 and col != "valvula" else dfr[col]
            fig.add_trace(go.Scatter(x=dfr.index, y=y, name=LABELS[col], line=dict(color=COLORS[col], width=2),
                                     line_shape="hv" if col == "valvula" else "linear"), row=i, col=1)
            if col == "humedad_suelo":
                fig.add_hline(y=p.hum_seca, line_dash="dot", line_color=RED, row=i, col=1)
                fig.add_hline(y=p.hum_humeda, line_dash="dot", line_color=GREEN, row=i, col=1)
            if col == "nivel_agua":
                fig.add_hline(y=p.nivel_bajo, line_dash="dot", line_color=RED, row=i, col=1)
            if bands and col != "valvula":
                add_events_bands(fig, events, row=i)
        fig.update_layout(height=260 * len(sel) + 60, showlegend=False)
        fig.update_xaxes(rangeslider_visible=False)
        show(fig, "evo")
    else:
        st.info("Elige al menos una variable.")

# ============================ NIVEL ============================
with tabs[3]:
    if not has_n:
        st.info("El archivo no incluye `nivel_agua` ni `nivel_raw`.")
    else:
        n = data["nivel_agua"].dropna()
        g, m = st.columns([1, 2])
        with g:
            fig = go.Figure(go.Indicator(
                mode="gauge+number", value=float(n.iloc[-1]), number={"suffix": "%"},
                title={"text": "Nivel actual"},
                gauge={"axis": {"range": [0, 100]}, "bar": {"color": BLUE},
                       "steps": [{"range": [0, p.nivel_bajo], "color": "#f8c9c9"},
                                 {"range": [p.nivel_bajo, 100], "color": "#d9efe1"}],
                       "threshold": {"line": {"color": RED, "width": 3}, "value": p.nivel_bajo}}))
            fig.update_layout(height=300)
            show(fig, "niv_g")
        with m:
            k = st.columns(4)
            k[0].metric("Mínimo", f"{n.min():.1f}%")
            k[1].metric("Máximo", f"{n.max():.1f}%")
            k[2].metric("Media", f"{n.mean():.1f}%")
            k[3].metric("Tiempo bajo umbral", f"{(n < p.nivel_bajo).mean() * 100:.0f}%")
            hrs = (n.index - n.index[0]).total_seconds() / 3600
            if len(n) > 3 and hrs.max() > 0:
                slope = np.polyfit(hrs, n.to_numpy(), 1)[0]
                tend = "baja" if slope < 0 else "sube"
                st.markdown(f"**Tendencia global:** el nivel {tend} **{abs(slope):.2f} puntos por hora**.")
                if slope < 0:
                    h_left = (n.iloc[-1] - p.nivel_bajo) / abs(slope)
                    if h_left > 0:
                        st.markdown(f"A este ritmo llegaría al umbral bajo en ~**{h_left:.1f} h** "
                                    "(estimación lineal, sin recargas).")
            if len(events) and events["consumo_nivel"].notna().any():
                st.markdown(f"**Consumo medio por riego:** {events['consumo_nivel'].mean():.2f} puntos de nivel.")
        fig = go.Figure(go.Scatter(x=dfr.index, y=dfr["nivel_agua"], name="Nivel", fill="tozeroy",
                                   line=dict(color=BLUE, width=2)))
        fig.add_hrect(y0=0, y1=p.nivel_bajo, fillcolor=RED, opacity=0.08, line_width=0)
        fig.add_hline(y=p.nivel_bajo, line_dash="dot", line_color=RED, annotation_text="Umbral bajo")
        add_events_bands(fig, events)
        fig.update_yaxes(range=[0, 100], title="%")
        fig.update_layout(title="Nivel de agua del tanque", height=380)
        show(fig, "niv_l")
        a, b = st.columns(2)
        fig = px.histogram(n, nbins=30, title="Distribución del nivel", color_discrete_sequence=[BLUE])
        fig.update_layout(height=300, showlegend=False, xaxis_title="% nivel")
        with a:
            show(fig, "niv_h")
        if len(events) and events["consumo_nivel"].notna().any():
            ev = events.dropna(subset=["consumo_nivel"])
            fig = px.bar(ev, x="inicio", y="consumo_nivel", title="Consumo de nivel por riego (puntos %)",
                         color_discrete_sequence=[ORANGE])
            fig.update_layout(height=300)
            show(fig, "niv_c")

# ============================ RIEGO ============================
with tabs[4]:
    if not has_v:
        st.info("El archivo no incluye la columna `valvula`; no puedo detectar riegos.")
    elif events.empty:
        st.info("La válvula no se abrió en el periodo seleccionado.")
    else:
        k = st.columns(5)
        k[0].metric("Riegos", len(events))
        k[1].metric("Duración media", f"{events['duracion_min'].mean():.1f} min")
        k[2].metric("Tiempo total abierta", f"{events['duracion_min'].sum():.1f} min")
        ef = events["mejora_humedad"].dropna()
        k[3].metric("Mejora media humedad", f"{ef.mean():+.1f} pts" if len(ef) else "—")
        k[4].metric("Riegos efectivos", f"{(ef >= p.delta_min).mean() * 100:.0f}%" if len(ef) else "—")
        a, b = st.columns(2)
        per = events.assign(dia=events["inicio"].dt.floor("D")).groupby("dia").size().reset_index(name="riegos")
        fig = px.bar(per, x="dia", y="riegos", title="Riegos por día", color_discrete_sequence=[GREEN])
        fig.update_layout(height=320)
        with a:
            show(fig, "rie_dia")
        fig = px.histogram(events, x="duracion_min", nbins=20, title="Duración de los riegos (min)",
                           color_discrete_sequence=[ORANGE])
        fig.update_layout(height=320)
        with b:
            show(fig, "rie_dur")
        ev = events.dropna(subset=["humedad_inicio", "humedad_post"])
        if not ev.empty:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=ev["inicio"], y=ev["humedad_inicio"], name="Humedad al abrir", marker_color=BROWN))
            fig.add_trace(go.Bar(x=ev["inicio"], y=ev["humedad_post"], name=f"Humedad +{p.post_min:g} min", marker_color=GREEN))
            fig.update_layout(barmode="group", title="Humedad antes y después de cada riego", height=340)
            show(fig, "rie_ef")
        orig = events["origen_probable"].value_counts().reset_index()
        orig.columns = ["origen", "riegos"]
        st.caption("Origen probable: «Automático» si la humedad al abrir estaba bajo el umbral seco; "
                   "de lo contrario, probablemente fue un accionamiento manual desde ThingsBoard.")
        table(orig, hide_index=True)
        table(events, hide_index=True, column_config={
            "inicio": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
            "fin": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
        })

# ============================ ESTADÍSTICA ============================
with tabs[5]:
    stt = an.stats_table(data)
    if stt.empty:
        st.info("Sin variables numéricas.")
    else:
        st.subheader("Estadística descriptiva")
        table(stt.round(2).T)
        vars_ = list(stt.index)
        a, b = st.columns(2)
        pick = a.selectbox("Distribución de", vars_, format_func=lambda k: LABELS[k])
        fig = px.histogram(data, x=pick, nbins=40, marginal="box", color_discrete_sequence=[COLORS[pick]],
                           title=f"Distribución · {LABELS[pick]}")
        fig.update_layout(height=380)
        show(fig, "est_h")
        hp = an.hourly_pattern(data)
        if not hp.empty:
            fig = go.Figure()
            for col in hp.columns:
                fig.add_trace(go.Scatter(x=hp.index, y=hp[col], name=LABELS[col], mode="lines+markers",
                                         line=dict(color=COLORS[col])))
            fig.update_layout(title="Patrón promedio por hora del día", height=340, xaxis_title="hora",
                              yaxis_title="%", hovermode="x unified")
            show(fig, "est_hr")
        st.subheader("Resumen diario")
        table(daily)
        if len(daily) > 1:
            cols_d = [c_ for c_ in ("humedad_media", "nivel_medio") if c_ in daily]
            fig = px.line(daily.reset_index(), x="time", y=cols_d, markers=True, title="Medias diarias")
            fig.update_layout(height=320)
            show(fig, "est_d")

# ============================ ALERTAS ============================
with tabs[6]:
    st.subheader("Alertas operativas")
    st.caption("Reglas: suelo seco, tanque bajo, huecos de datos, sensor congelado, riego prolongado, "
               "riego sin efecto y riego con tanque bajo (umbrales en la barra lateral).")
    if alerts.empty:
        st.success("No se detectaron alertas en el periodo. ✅")
    else:
        sev_cnt = alerts["severidad"].value_counts()
        k = st.columns(4)
        k[0].metric("Total", len(alerts))
        k[1].metric("Altas", int(sev_cnt.get("Alta", 0)))
        k[2].metric("Medias", int(sev_cnt.get("Media", 0)))
        k[3].metric("Tipos distintos", alerts["tipo"].nunique())
        a, b = st.columns([1, 2])
        bt = alerts["tipo"].value_counts().reset_index()
        bt.columns = ["tipo", "alertas"]
        fig = px.bar(bt, x="alertas", y="tipo", orientation="h", title="Alertas por tipo",
                     color_discrete_sequence=[RED])
        fig.update_layout(height=340, yaxis=dict(autorange="reversed"))
        with a:
            show(fig, "al_t")
        tl = alerts.copy()
        tl["fin_plot"] = tl[["fin", "inicio"]].apply(lambda r: max(r.fin, r.inicio + pd.Timedelta(seconds=30)), axis=1)
        fig = px.timeline(tl, x_start="inicio", x_end="fin_plot", y="tipo", color="severidad",
                          color_discrete_map={"Alta": RED, "Media": YELLOW, "Baja": BLUE},
                          hover_data=["detalle"], title="Línea de tiempo de alertas")
        fig.update_layout(height=340)
        with b:
            show(fig, "al_tl")
        f1, f2 = st.columns(2)
        tsel = f1.multiselect("Tipo", sorted(alerts["tipo"].unique()), default=sorted(alerts["tipo"].unique()))
        ssel = f2.multiselect("Severidad", ["Alta", "Media", "Baja"], default=["Alta", "Media", "Baja"])
        view = alerts[alerts["tipo"].isin(tsel) & alerts["severidad"].isin(ssel)]
        table(view, hide_index=True, column_config={
            "inicio": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
            "fin": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
        })

# ============================ CORRELACIÓN ============================
with tabs[7]:
    st.subheader("Correlación entre sensores")
    method = st.radio("Método", ["pearson", "spearman"], horizontal=True,
                      help="Spearman es más robusto si la relación no es lineal.")
    cm = an.corr_matrix(dfr, method)
    if cm.empty:
        st.info("Se necesitan al menos dos variables con variación.")
    else:
        cm_l = cm.rename(index=LABELS, columns=LABELS)
        fig = px.imshow(cm_l, text_auto=".2f", zmin=-1, zmax=1, color_continuous_scale="RdBu_r",
                        aspect="auto", title=f"Matriz de correlación ({method})")
        fig.update_layout(height=420)
        show(fig, "cor_m")
    if has_h and has_n:
        st.subheader("Relación entre nivel de agua y humedad del suelo")
        res = an.ols(dfr["nivel_agua"], dfr["humedad_suelo"])
        sc = dfr[["nivel_agua", "humedad_suelo"]].dropna()
        if res is None:
            st.info("No hay variación suficiente para ajustar una relación.")
        else:
            a, b = st.columns([2, 1])
            fig = px.scatter(sc.reset_index(), x="nivel_agua", y="humedad_suelo", opacity=0.55,
                             color_discrete_sequence=[GREEN], labels={"nivel_agua": "Nivel (%)", "humedad_suelo": "Humedad (%)"},
                             title="Nivel de agua vs humedad del suelo")
            xs = np.array([sc["nivel_agua"].min(), sc["nivel_agua"].max()])
            fig.add_trace(go.Scatter(x=xs, y=res["pendiente"] * xs + res["intercepto"], mode="lines",
                                     name="Ajuste lineal", line=dict(color=RED, width=3)))
            fig.update_layout(height=420, hovermode="closest")
            with a:
                show(fig, "cor_s")
            with b:
                st.metric("Correlación (r)", f"{res['r']:.2f}")
                st.metric("R²", f"{res['r2']:.2f}")
                st.metric("Pendiente", f"{res['pendiente']:.3f} pts humedad / pt nivel")
                st.caption(f"Relación **{an.interpret_r(res['r'])}** (n = {res['n']:,}). "
                           "Correlación no implica causalidad: el nivel baja cuando riega, y la humedad sube por el riego.")
        # correlación con desfase
        step = rule or f"{max(int(dt.total_seconds()), 1)}s"
        uni = loader.resample(data, step)
        max_lag = st.slider("Desfase máximo (muestras)", 2, 60, 20)
        lc = an.lag_corr(uni["nivel_agua"], uni["humedad_suelo"], max_lag)
        if not lc.empty:
            best = lc.loc[lc["r"].abs().idxmax()]
            fig = px.bar(lc, x="lag", y="r", title="Correlación con desfase: nivel(t) vs humedad(t + k)",
                         color_discrete_sequence=[BLUE])
            fig.update_layout(height=320, xaxis_title=f"desfase k (1 muestra = {step})", yaxis_range=[-1, 1])
            show(fig, "cor_lag")
            st.caption(f"Mayor correlación en k = {int(best['lag'])} muestras (r = {best['r']:.2f}). "
                       "k > 0 significa que la humedad responde después del cambio de nivel.")
    if has_h and has_v and dfr["valvula"].nunique() > 1:
        st.subheader("Humedad según estado de la válvula")
        dd = dfr.assign(valvula_estado=np.where(dfr["valvula"].ffill().fillna(0) >= 0.5, "Abierta", "Cerrada"))
        fig = px.box(dd, x="valvula_estado", y="humedad_suelo", color="valvula_estado",
                     color_discrete_map={"Abierta": ORANGE, "Cerrada": BLUE}, points="outliers")
        fig.update_layout(height=340, showlegend=False)
        show(fig, "cor_box")

# ============================ REGISTROS ============================
with tabs[8]:
    st.subheader("Registros del sistema")
    if log.empty:
        st.info("Sin eventos que registrar.")
    else:
        origins = sorted(log["origen"].unique())
        osel = st.multiselect("Origen", origins, default=origins)
        lv = log[log["origen"].isin(osel)]
        table(lv.sort_values("tiempo", ascending=False), hide_index=True, column_config={
            "tiempo": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss")})
        st.caption(f"{len(lv):,} eventos. Incluye aperturas/cierres de válvula, alertas del firmware, "
                   "cambios de estado y alertas calculadas.")
    with st.expander("Datos crudos (últimos 2,000 registros)"):
        table(data.tail(2000).iloc[::-1])

# ============================ DESCARGAS ============================
with tabs[9]:
    st.subheader("Descargar datos procesados")
    st.caption(f"Datos agrupados: **{rule_label.lower()}** · filtro de fechas aplicado.")
    c1, c2, c3 = st.columns(3)
    with c1:
        download("📥 Datos procesados (CSV)", processed, "datos_procesados.csv", "d1")
        download("📥 Resumen diario (CSV)", daily.reset_index(), "resumen_diario.csv", "d2")
    with c2:
        download("📥 Eventos de riego (CSV)", events, "eventos_riego.csv", "d3")
        download("📥 Alertas (CSV)", alerts, "alertas.csv", "d4")
    with c3:
        download("📥 Registros del sistema (CSV)", log, "registros_sistema.csv", "d5")
        st.download_button(
            "📦 Todo en Excel (.xlsx)",
            to_excel({"datos": processed, "riegos": events, "alertas": alerts, "registros": log,
                      "diario": daily.reset_index(), "sensores": status,
                      "estadistica": an.stats_table(data).reset_index()}),
            file_name="sprout_analisis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="d6")
    st.markdown("**Vista previa de los datos procesados**")
    table(processed.tail(200).iloc[::-1])
