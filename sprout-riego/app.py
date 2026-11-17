"""Sprout · Monitoreo de riego (Streamlit).

Sube el CSV/XLSX descargado de InfluxDB, ThingsBoard o Grafana. La app muestra tablas
explicativas de cada indicador (resumen, sensores, evolución, nivel, riego, estadística,
alertas, correlación, registros), descargas de datos procesados y un glosario final.
"""
from __future__ import annotations

import html as _html
import io
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from sprout import analysis as an
from sprout import glosario as gl
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
      .block-container {padding-top: 1.4rem; max-width: 1400px;}
      /* Tablas explicativas: colores translúcidos que funcionan en tema claro y oscuro */
      .tbl-wrap {overflow-x: auto; line-height: 0; margin: 4px 0 22px 0; border: 1px solid rgba(128,128,128,0.35); border-radius: 10px;}
      table.tbl {border-collapse: collapse; width: 100%; font-size: 0.93rem; color: inherit; background: transparent;}
      table.tbl th {background: rgba(46,158,91,0.22); color: inherit; text-align: left; font-weight: 700;
                    padding: 10px 14px; border-bottom: 2px solid rgba(128,128,128,0.45);
                    vertical-align: bottom; line-height: 1.3;}
      table.tbl td {padding: 9px 14px; border-bottom: 1px solid rgba(128,128,128,0.25); color: inherit;
                    vertical-align: top; line-height: 1.45; white-space: normal; overflow-wrap: break-word; word-break: normal;}
      table.tbl tr:nth-child(even) td {background: rgba(128,128,128,0.07);}
      table.tbl tr:last-child td {border-bottom: none;}
      table.tbl td.k {font-weight: 600;}
      table.tbl td.n {text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums;}
      .sec-note {opacity: 0.8; font-size: 0.92rem; margin: -6px 0 10px 0;}
      h2, h3 {margin-top: 0.6rem !important;}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Helpers de UI
# --------------------------------------------------------------------------
def _fmt(v) -> str:
    if v is None:
        return "—"
    try:
        if pd.isna(v):
            return "—"
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, (bool, np.bool_)):
        return "Sí" if v else "No"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        return f"{v:,.2f}"
    return str(v)


_HEAD = {"minimo": "Mínimo", "maximo": "Máximo", "min": "Mín.", "max": "Máx.", "n": "n",
         "desv_est": "Desv. estándar", "coef_var_%": "Coef. variación %", "asimetria": "Asimetría",
         "atipicos_IQR": "Atípicos (IQR)", "ultima": "Última", "p5": "P5", "p25": "P25", "p75": "P75", "p95": "P95"}


def _pretty(c: str) -> str:
    c = str(c)
    if c in _HEAD:
        return _HEAD[c]
    c = c.replace("_", " ")
    return c[:1].upper() + c[1:]


def tbl(df: pd.DataFrame, widths: list[int] | None = None, key_col: bool = True) -> None:
    """Tabla HTML con texto que se ajusta. widths = porcentajes por columna."""
    if df is None or df.empty:
        st.info("Sin datos para esta tabla.")
        return
    cols = list(df.columns)
    colgroup = ""
    if widths:
        colgroup = "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in widths) + "</colgroup>"
    head = "".join(f"<th>{_html.escape(_pretty(c))}</th>" for c in cols)
    rows = []
    for r in df.to_dict("records"):  # conserva el tipo de cada columna (enteros siguen siendo enteros)
        tds = []
        for i, c in enumerate(cols):
            v = r[c]
            numeric = isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, (bool, np.bool_))
            cls = "k" if (i == 0 and key_col) else ("n" if numeric else "")
            tds.append(f'<td class="{cls}">{_html.escape(_fmt(v))}</td>')
        rows.append("<tr>" + "".join(tds) + "</tr>")
    min_w = max(480, 100 * len(cols))  # en pantallas angostas la tabla se desplaza, no se aplasta
    st.markdown(f'<div class="tbl-wrap"><table class="tbl" style="min-width:{min_w}px">{colgroup}<thead><tr>{head}</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>', unsafe_allow_html=True)


def kpi(rows: list[tuple[str, str, str]]) -> None:
    """Tabla Indicador | Valor | Qué significa."""
    tbl(pd.DataFrame(rows, columns=["Indicador", "Valor", "Qué significa"]), widths=[24, 18, 58])


def section(title: str, note: str = "") -> None:
    st.markdown(f"### {title}")
    if note:
        st.markdown(f'<div class="sec-note">{note}</div>', unsafe_allow_html=True)


def dtbl(df: pd.DataFrame, **kw) -> None:
    """Tabla interactiva (ordenable) para listados largos."""
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kw)
    except TypeError:
        st.dataframe(df, use_container_width=True, hide_index=True, **kw)


def chart(fig: go.Figure, title: str, height: int = 380, hover: str = "x unified", key: str | None = None) -> None:
    fig.update_layout(
        height=height, hovermode=hover, font=dict(size=13),
        title=dict(text=title, x=0, xanchor="left", y=0.97, yanchor="top", font=dict(size=16)),
        margin=dict(l=70, r=25, t=75, b=95),
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0, font=dict(size=12)),
    )
    fig.update_xaxes(automargin=True, title_standoff=12)
    fig.update_yaxes(automargin=True, title_standoff=12)
    try:
        st.plotly_chart(fig, width="stretch", key=key)
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key=key)


def naive(df: pd.DataFrame) -> pd.DataFrame:
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


def bands(fig: go.Figure, events: pd.DataFrame, max_n: int = 120) -> None:
    if events.empty or len(events) > max_n:
        return
    for _, e in events.iterrows():
        fig.add_vrect(x0=e.inicio, x1=e.fin, fillcolor=ORANGE, opacity=0.2, line_width=0, layer="below")


SEV = {"Alta": "🔴 Alta", "Media": "🟠 Media", "Baja": "🔵 Baja"}


def f1(x, suf="") -> str:
    return "—" if x is None or pd.isna(x) else f"{x:,.1f}{suf}"


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
    section("Cómo empezar")
    tbl(pd.DataFrame([
        ("1. Exporta", "Descarga los datos desde InfluxDB (Data Explorer → Download CSV), ThingsBoard (exportar telemetría) o Grafana (Inspect → Data → CSV)."),
        ("2. Adjunta", "Arrastra el archivo a la barra lateral. Se reconocen las columnas humedad_suelo, nivel_agua, humedad_raw, nivel_raw, valvula, alerta_nivel, alerta_humedad, estado_suelo y estado_nivel."),
        ("3. Explora", "Cada pestaña muestra tablas con el valor de cada indicador y su explicación. La pestaña Glosario explica todos los términos."),
        ("4. Descarga", "En la pestaña Descargas obtienes los datos procesados en CSV o Excel."),
    ], columns=["Paso", "Qué hacer"]), widths=[16, 84])
    tbl(gl.formatos(), widths=[22, 78])
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
soil_t, tank_t = an.time_in_states(data, p)

st.title("🌱 Monitoreo de riego y tanque")
st.caption(f"{data.index.min():%Y-%m-%d %H:%M} → {data.index.max():%Y-%m-%d %H:%M} (hora Colombia) · "
           f"{len(data):,} registros · intervalo típico {dt.total_seconds():.0f} s")

import contextlib


def sec(title: str):
    """Sección de la página: separador + encabezado."""
    st.divider()
    st.header(title)
    return contextlib.nullcontext()

# ============================ RESUMEN ============================
with sec("📋 Resumen del monitoreo"):
    section("Indicadores clave", "Cada fila indica el valor calculado y qué significa.")
    rows = [
        ("Periodo analizado", f"{data.index.min():%d/%m/%Y %H:%M} → {data.index.max():%d/%m/%Y %H:%M}",
         "Rango de fechas con datos, tras aplicar el filtro de la barra lateral (hora Colombia)."),
        ("Registros", f"{len(data):,}", "Cantidad de filas de datos analizadas."),
        ("Intervalo típico", f"{dt.total_seconds():.0f} s", "Mediana del tiempo entre dos registros consecutivos."),
    ]
    if has_h:
        h = data["humedad_suelo"].dropna()
        rows += [
            ("Humedad actual", f1(h.iloc[-1], " %"), "Última lectura válida de humedad del suelo."),
            ("Variación de humedad", f"{h.iloc[-1] - h.iloc[0]:+.1f} pts", "Última lectura menos la primera del periodo."),
            ("Humedad media / mín / máx", f"{h.mean():.1f} / {h.min():.1f} / {h.max():.1f} %",
             "Promedio y extremos de humedad en el periodo."),
        ]
    if has_n:
        n = data["nivel_agua"].dropna()
        rows += [
            ("Nivel actual", f1(n.iloc[-1], " %"), "Última lectura válida del nivel del tanque."),
            ("Variación de nivel", f"{n.iloc[-1] - n.iloc[0]:+.1f} pts", "Última lectura menos la primera del periodo."),
            ("Nivel medio / mín / máx", f"{n.mean():.1f} / {n.min():.1f} / {n.max():.1f} %", "Promedio y extremos del nivel."),
        ]
    if has_v:
        rows += [
            ("Riegos detectados", f"{len(events)}", "Veces que la válvula pasó de cerrada a abierta."),
            ("Tiempo con válvula abierta", f"{events['duracion_min'].sum():.1f} min" if len(events) else "0 min",
             "Suma de la duración de todos los riegos."),
        ]
    n_high = int((alerts["severidad"] == "Alta").sum()) if not alerts.empty else 0
    n_med = int((alerts["severidad"] == "Media").sum()) if not alerts.empty else 0
    rows.append(("Alertas operativas", f"{len(alerts)} ({n_high} altas, {n_med} medias)",
                 "Eventos que requieren atención; el detalle está en la pestaña Alertas."))
    bad = status[status["estado"] != "OK"] if not status.empty else status
    rows.append(("Sensores a revisar", f"{len(bad)} de {len(status)}",
                 "Sensores en estado «Revisar» o «Falla»; ver pestaña Sensores."))
    kpi(rows)

    section("Tiempo por estado del suelo", "Cuánto tiempo estuvo el suelo en cada rango de humedad.")
    if not soil_t.empty:
        cond = {"SECO": f"humedad < {p.hum_seca:g} %", "INTERMEDIO": f"{p.hum_seca:g} % a {p.hum_humeda:g} %",
                "HÚMEDO": f"humedad ≥ {p.hum_humeda:g} %"}
        mean_ = {"SECO": "Necesita riego; el sistema abre la válvula.",
                 "INTERMEDIO": "Zona de histéresis; la válvula conserva su estado.",
                 "HÚMEDO": "Suelo suficientemente húmedo; la válvula se cierra."}
        s = soil_t.copy()
        s.insert(1, "condición", s["estado"].map(cond))
        s["qué significa"] = s["estado"].map(mean_)
        s = s.rename(columns={"porcentaje": "% del tiempo"})
        tbl(s, widths=[13, 17, 11, 11, 12, 36])
    section("Tiempo por estado del tanque")
    if not tank_t.empty:
        cond = {"BAJO": f"nivel < {p.nivel_bajo:g} %", "NORMAL": f"nivel ≥ {p.nivel_bajo:g} %"}
        mean_ = {"BAJO": "Riesgo de quedarse sin agua para regar.", "NORMAL": "Agua suficiente."}
        s = tank_t.copy()
        s.insert(1, "condición", s["estado"].map(cond))
        s["qué significa"] = s["estado"].map(mean_)
        s = s.rename(columns={"porcentaje": "% del tiempo"})
        tbl(s, widths=[13, 17, 11, 11, 12, 36])

    section("Hallazgos automáticos", "Conclusiones generadas a partir de los datos.")
    finds = []
    if has_h:
        sec_ = soil_t.set_index("estado")["porcentaje"]
        finds.append(("Suelo", f"Seco {sec_.get('SECO', 0):.0f} %, intermedio {sec_.get('INTERMEDIO', 0):.0f} %, "
                               f"húmedo {sec_.get('HÚMEDO', 0):.0f} % del tiempo."))
    if has_n:
        finds.append(("Tanque", f"Bajo el umbral ({p.nivel_bajo:g} %) el {tank_t.set_index('estado')['porcentaje'].get('BAJO', 0):.0f} % del tiempo."))
    if has_v and len(events):
        ef = events["mejora_humedad"].dropna()
        finds.append(("Riego", f"{len(events)} riegos con duración media de {events['duracion_min'].mean():.1f} min"
                               + (f" y mejora media de humedad de {ef.mean():+.1f} pts." if len(ef) else ".")))
    elif has_v:
        finds.append(("Riego", "La válvula no se abrió en el periodo."))
    if not alerts.empty:
        top = alerts["tipo"].value_counts().head(3)
        finds.append(("Alertas", "Más frecuentes: " + ", ".join(f"{k} ({v})" for k, v in top.items()) + "."))
    finds.append(("Sensores", "Todos operan con normalidad." if bad.empty else
                  "A revisar: " + ", ".join(f"{r.sensor} ({r.estado})" for r in bad.itertuples()) + "."))
    tbl(pd.DataFrame(finds, columns=["Tema", "Hallazgo"]), widths=[14, 86])

    fig = go.Figure()
    for col in [c_ for c_ in ("humedad_suelo", "nivel_agua") if c_ in dfr]:
        fig.add_trace(go.Scatter(x=dfr.index, y=dfr[col], name=LABELS[col], line=dict(color=COLORS[col], width=2)))
    bands(fig, events)
    fig.update_yaxes(range=[0, 100], title_text="%")
    chart(fig, "Humedad y nivel en el tiempo (franjas naranjas = riego)", key="res_main")

# ============================ SENSORES ============================
with sec("🛰️ Estado de los sensores"):
    section("Estado de cada sensor", "Evaluación automática de la calidad de las lecturas.")
    if status.empty:
        st.info("No hay columnas de sensores reconocidas.")
    else:
        icon = {"OK": "🟢 OK", "Revisar": "🟡 Revisar", "Falla": "🔴 Falla"}
        s = status.copy()
        s["estado"] = s["estado"].map(icon)
        s = s.rename(columns={"ultima_lectura": "última lectura", "ultimo_valor": "último valor",
                              "cobertura_%": "cobertura %", "max_hueco_min": "mayor hueco (min)"})
        tbl(s, widths=[13, 9, 25, 14, 8, 8, 8, 7, 8])
    section("Cómo se evalúa el estado")
    tbl(gl.estados_sensor(), widths=[16, 84])

    section("Cobertura de datos por día", "Registros recibidos frente a los esperados según el intervalo típico.")
    exp_day = 86400 / max(dt.total_seconds(), 1)
    gaps = data.index.to_series().diff().dt.total_seconds().div(60)
    byday = pd.DataFrame({
        "día": data.resample("D").size().index.strftime("%Y-%m-%d"),
        "registros": data.resample("D").size().values,
        "esperados": int(exp_day),
        "mayor hueco (min)": gaps.groupby(data.index.floor("D")).max().reindex(data.resample("D").size().index).values,
    })
    byday["cobertura %"] = (byday["registros"] / byday["esperados"] * 100).clip(upper=100).round(1)
    tbl(byday, widths=[18, 17, 17, 24, 24])

# ============================ EVOLUCIÓN ============================
with sec("📈 Evolución de las variables"):
    section("Resumen de la evolución por variable", "Cómo empezó, cómo terminó y cuándo ocurrieron los extremos.")
    tr = an.trend_table(data)
    if not tr.empty:
        tr["variable"] = tr["variable"].map(LABELS)
        tr = tr.rename(columns={"valor_inicial": "valor inicial", "valor_final": "valor final",
                                "hora_minimo": "hora del mínimo", "hora_maximo": "hora del máximo"})
        tbl(tr, widths=[16, 8, 8, 8, 8, 8, 17, 8, 17])

    section("Resumen por intervalo", "Medias, extremos y riegos en cada bloque de tiempo.")
    span_h = (data.index.max() - data.index.min()).total_seconds() / 3600
    opts = {"15 minutos": "15min", "1 hora": "1h", "1 día": "1D"}
    default_b = 2 if span_h > 72 else 1 if span_h > 3 else 0
    bl = st.radio("Tamaño del bloque", list(opts), index=default_b, horizontal=True)
    bt = an.bucket_table(data, events, p, opts[bl])
    bt = bt.reset_index().rename(columns={"time": "inicio del bloque"})
    bt["inicio del bloque"] = bt["inicio del bloque"].dt.strftime("%Y-%m-%d %H:%M")
    if len(bt) <= 250:
        tbl(bt)
    else:
        dtbl(bt)
        st.caption(f"{len(bt):,} bloques: tabla interactiva (ordena haciendo clic en los encabezados).")

    section("Gráficas", "Una gráfica por variable; las franjas naranjas indican riego.")
    avail = [c_ for c_ in ("humedad_suelo", "nivel_agua", "humedad_raw", "nivel_raw", "valvula") if c_ in dfr]
    sel = st.multiselect("Variables", avail, default=[c_ for c_ in avail if c_ in ("humedad_suelo", "nivel_agua")],
                         format_func=lambda k: LABELS[k])
    smooth = st.slider("Suavizado (promedio móvil, en muestras)", 1, 60, 1)
    for col in sel:
        y = dfr[col].rolling(smooth, min_periods=1).mean() if smooth > 1 and col != "valvula" else dfr[col]
        fig = go.Figure(go.Scatter(x=dfr.index, y=y, name=LABELS[col], line=dict(color=COLORS[col], width=2),
                                   line_shape="hv" if col == "valvula" else "linear"))
        if col == "humedad_suelo":
            fig.add_hline(y=p.hum_seca, line_dash="dot", line_color=RED, annotation_text="Seco", annotation_position="top left")
            fig.add_hline(y=p.hum_humeda, line_dash="dot", line_color=GREEN, annotation_text="Húmedo", annotation_position="top left")
        if col == "nivel_agua":
            fig.add_hline(y=p.nivel_bajo, line_dash="dot", line_color=RED, annotation_text="Umbral bajo", annotation_position="top left")
        if col != "valvula":
            bands(fig, events)
        chart(fig, LABELS[col], height=320, key=f"evo_{col}")

# ============================ NIVEL ============================
with sec("🪣 Nivel de agua"):
    if not has_n:
        st.info("El archivo no incluye `nivel_agua` ni `nivel_raw`.")
    else:
        n = data["nivel_agua"].dropna()
        low = alerts[alerts["tipo"] == "Nivel de tanque bajo"] if not alerts.empty else alerts
        section("Indicadores del nivel de agua")
        rows = [
            ("Nivel actual", f1(n.iloc[-1], " %"), "Última lectura válida."),
            ("Nivel mínimo", f"{n.min():.1f} % ({n.idxmin():%d/%m %H:%M})", "Punto más bajo y cuándo ocurrió."),
            ("Nivel máximo", f"{n.max():.1f} % ({n.idxmax():%d/%m %H:%M})", "Punto más alto y cuándo ocurrió."),
            ("Nivel medio", f"{n.mean():.1f} %", "Promedio del periodo."),
            ("Tiempo bajo el umbral", f"{(n < p.nivel_bajo).mean() * 100:.0f} %", f"Porcentaje del tiempo con nivel < {p.nivel_bajo:g} %."),
            ("Episodios de nivel bajo", f"{len(low)}", "Tramos continuos con el nivel bajo el umbral."),
        ]
        hrs = (n.index - n.index[0]).total_seconds() / 3600
        if len(n) > 3 and hrs.max() > 0:
            slope = np.polyfit(hrs, n.to_numpy(), 1)[0]
            rows.append(("Tendencia global", f"{slope:+.2f} pts/h",
                         "Pendiente de una recta ajustada: negativo = el nivel baja en promedio; positivo = sube."))
            if slope < 0 and n.iloc[-1] > p.nivel_bajo:
                rows.append(("Tiempo estimado al umbral bajo", f"{(n.iloc[-1] - p.nivel_bajo) / abs(slope):.1f} h",
                             "Estimación lineal si el ritmo de descenso continúa y no hay recargas."))
        if len(events) and events["consumo_nivel"].notna().any():
            rows += [("Consumo medio por riego", f"{events['consumo_nivel'].mean():.2f} pts",
                      "Puntos de nivel que gasta un riego, en promedio."),
                     ("Consumo total en riegos", f"{events['consumo_nivel'].sum():.2f} pts", "Suma del consumo de todos los riegos.")]
        kpi(rows)

        section("Episodios de nivel bajo", "Cada fila es un tramo continuo con el tanque bajo el umbral.")
        if low.empty:
            st.success("El tanque no bajó del umbral en este periodo.")
        else:
            tbl(low[["inicio", "fin", "duracion_min", "valor"]].rename(
                columns={"duracion_min": "duración (min)", "valor": "nivel mínimo (%)"}), widths=[25, 25, 25, 25], key_col=False)

        if len(events) and events["consumo_nivel"].notna().any():
            section("Consumo de nivel por riego")
            tbl(events[["inicio", "duracion_min", "nivel_inicio", "nivel_fin", "consumo_nivel"]].rename(
                columns={"duracion_min": "duración (min)", "nivel_inicio": "nivel al abrir (%)",
                         "nivel_fin": "nivel al cerrar (%)", "consumo_nivel": "consumo (pts)"}), key_col=False)

        fig = go.Figure(go.Scatter(x=dfr.index, y=dfr["nivel_agua"], name="Nivel", fill="tozeroy",
                                   line=dict(color=BLUE, width=2)))
        fig.add_hrect(y0=0, y1=p.nivel_bajo, fillcolor=RED, opacity=0.08, line_width=0)
        fig.add_hline(y=p.nivel_bajo, line_dash="dot", line_color=RED, annotation_text="Umbral bajo", annotation_position="top left")
        bands(fig, events)
        fig.update_yaxes(range=[0, 100], title_text="%")
        chart(fig, "Nivel de agua del tanque", key="niv_l")

# ============================ RIEGO ============================
with sec("🚿 Datos de riego"):
    if not has_v:
        st.info("El archivo no incluye la columna `valvula`; no puedo detectar riegos.")
    elif events.empty:
        st.info("La válvula no se abrió en el periodo seleccionado.")
    else:
        ef = events["mejora_humedad"].dropna()
        section("Indicadores de riego")
        kpi([
            ("Riegos", f"{len(events)}", "Veces que se abrió la válvula."),
            ("Duración media", f"{events['duracion_min'].mean():.1f} min", "Promedio de minutos abierta por riego."),
            ("Duración máxima", f"{events['duracion_min'].max():.1f} min", "Riego más largo del periodo."),
            ("Tiempo total abierta", f"{events['duracion_min'].sum():.1f} min", "Suma de todos los riegos."),
            ("Mejora media de humedad", f"{ef.mean():+.1f} pts" if len(ef) else "—",
             f"Cambio de humedad {p.post_min:g} min después de cerrar, frente a la humedad al abrir."),
            ("Riegos efectivos", f"{(ef >= p.delta_min).mean() * 100:.0f} %" if len(ef) else "—",
             f"Porcentaje de riegos con mejora de al menos {p.delta_min:g} puntos."),
        ])

        section("Riegos por origen probable", "Separa los riegos automáticos de los accionados a mano.")
        og = events.groupby("origen_probable").agg(
            riegos=("inicio", "size"), duracion_media=("duracion_min", "mean"),
            mejora_media=("mejora_humedad", "mean"), consumo_medio=("consumo_nivel", "mean")).reset_index()
        og = og.rename(columns={"origen_probable": "origen", "duracion_media": "duración media (min)",
                                "mejora_media": "mejora media (pts)", "consumo_medio": "consumo medio (pts)"})
        tbl(og)

        section("Riegos por día")
        pd_ = events.assign(día=events["inicio"].dt.strftime("%Y-%m-%d")).groupby("día").agg(
            riegos=("inicio", "size"), minutos_abierta=("duracion_min", "sum"),
            mejora_media=("mejora_humedad", "mean")).reset_index()
        tbl(pd_.rename(columns={"minutos_abierta": "minutos abierta", "mejora_media": "mejora media (pts)"}))

        section("Detalle de cada riego", "Tabla interactiva: haz clic en un encabezado para ordenar.")
        ev_view = events.rename(columns={
            "duracion_min": "duración (min)", "origen_probable": "origen probable",
            "humedad_inicio": "humedad al abrir (%)", "humedad_post": "humedad después (%)",
            "mejora_humedad": "mejora (pts)", "nivel_inicio": "nivel al abrir (%)",
            "nivel_fin": "nivel al cerrar (%)", "consumo_nivel": "consumo (pts)"})
        dtbl(ev_view, column_config={
            "inicio": st.column_config.DatetimeColumn("inicio", format="YYYY-MM-DD HH:mm:ss", width="medium"),
            "fin": st.column_config.DatetimeColumn("fin", format="YYYY-MM-DD HH:mm:ss", width="medium"),
            "origen probable": st.column_config.TextColumn("origen probable", width="medium"),
        })
        section("Qué significa cada columna")
        tbl(gl.columnas_riego(), widths=[24, 76])

        ev = events.dropna(subset=["humedad_inicio", "humedad_post"])
        if not ev.empty:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=ev["inicio"], y=ev["humedad_inicio"], name="Humedad al abrir", marker_color=BROWN))
            fig.add_trace(go.Bar(x=ev["inicio"], y=ev["humedad_post"], name=f"Humedad {p.post_min:g} min después", marker_color=GREEN))
            fig.update_layout(barmode="group")
            fig.update_yaxes(title_text="%")
            chart(fig, "Humedad antes y después de cada riego", key="rie_ef")

# ============================ ESTADÍSTICA ============================
with sec("📊 Análisis estadístico"):
    stt = an.stats_table(data)
    if stt.empty:
        st.info("Sin variables numéricas.")
    else:
        section("Resumen estadístico", "Promedio, extremos y variabilidad de cada variable.")
        unit = {"humedad_suelo": "%", "nivel_agua": "%", "humedad_raw": "ADC", "nivel_raw": "ADC"}
        simple = pd.DataFrame({
            "Variable": [LABELS[v] for v in stt.index], "Unidad": [unit[v] for v in stt.index],
            "Promedio": stt["media"].values, "Mínimo": stt["min"].values, "Máximo": stt["max"].values,
            "Desviación estándar": stt["desv_est"].values, "Registros": stt["n"].astype(int).values})
        tbl(simple, widths=[26, 9, 13, 13, 13, 16, 10])
        section("Estadística descriptiva detallada", "Una columna por variable; cada estadístico se explica más abajo.")
        t = stt.T.astype(object)
        for r_ in ("n", "atipicos_IQR"):
            t.loc[r_] = t.loc[r_].astype(int)
        t.columns = [LABELS[c] for c in t.columns]
        names_ = {"n": "n (registros)", "media": "Media", "desv_est": "Desviación estándar", "min": "Mínimo",
                  "p5": "Percentil 5", "p25": "Percentil 25", "mediana": "Mediana", "p75": "Percentil 75",
                  "p95": "Percentil 95", "max": "Máximo", "coef_var_%": "Coef. de variación (%)",
                  "asimetria": "Asimetría", "curtosis": "Curtosis", "atipicos_IQR": "Atípicos (IQR)"}
        t.index = [names_.get(i, i) for i in t.index]
        t = t.reset_index().rename(columns={"index": "Estadístico"})
        tbl(t)
        section("Qué significa cada estadístico")
        tbl(gl.estadisticos(), widths=[26, 74])

        section("Distribución por rangos", "Porcentaje de lecturas que cae en cada tramo de 20 puntos.")
        bins = [0, 20, 40, 60, 80, 100.0001]
        names = ["0–20 %", "20–40 %", "40–60 %", "60–80 %", "80–100 %"]
        dist = pd.DataFrame({"rango": names})
        for c in ("humedad_suelo", "nivel_agua"):
            if c in data:
                v = pd.cut(data[c].dropna(), bins=bins, labels=names, right=False)
                dist[LABELS[c] + " · registros"] = v.value_counts().reindex(names).values
                dist[LABELS[c] + " · % del tiempo"] = (v.value_counts(normalize=True).reindex(names).values * 100).round(1)
        tbl(dist)

        section("Patrón promedio por hora del día")
        hp = an.hourly_pattern(data)
        if not hp.empty:
            hp = hp.rename(columns=LABELS).reset_index().rename(columns={"index": "hora", "time": "hora"})
            hp.columns = ["hora"] + list(hp.columns[1:])
            hp["registros"] = data.groupby(data.index.hour).size().values
            hp["hora"] = hp["hora"].map(lambda h: f"{int(h):02d}:00")
            tbl(hp)

        section("Resumen diario")
        dd = daily.reset_index().rename(columns={"time": "día"})
        dd["día"] = dd["día"].dt.strftime("%Y-%m-%d")
        tbl(dd)

        pick = st.selectbox("Histograma de", list(stt.index), format_func=lambda k: LABELS[k])
        fig = px.histogram(data, x=pick, nbins=40, marginal="box", color_discrete_sequence=[COLORS[pick]])
        fig.update_layout(showlegend=False)
        fig.update_xaxes(title_text=LABELS[pick])
        fig.update_yaxes(title_text="registros", row=1, col=1)
        chart(fig, f"Distribución · {LABELS[pick]}", height=420, hover="closest", key="est_h")

# ============================ ALERTAS ============================
with sec("🚨 Alertas operativas"):
    section("Resumen de alertas por tipo", "Cuántas veces ocurrió cada alerta y qué implica.")
    if alerts.empty:
        st.success("No se detectaron alertas en el periodo. ✅")
    else:
        why = gl.alertas(p).set_index("Alerta")["Por qué importa"]
        sm = an.alert_summary(alerts)
        sm["por qué importa"] = sm["tipo"].map(why)
        sm["severidad"] = sm["severidad"].map(SEV)
        sm = sm.rename(columns={"duracion_total_min": "duración total (min)", "peor_valor": "peor valor"})
        tbl(sm, widths=[14, 8, 8, 10, 14, 14, 8, 24])

    section("Reglas de alerta vigentes", "Se calculan con los umbrales de la barra lateral.")
    ra = gl.alertas(p)
    ra["Severidad"] = ra["Severidad"].map(SEV)
    tbl(ra, widths=[14, 8, 24, 28, 26])

    if not alerts.empty:
        section("Detalle de cada alerta", "Filtra por tipo y severidad.")
        f1_, f2_ = st.columns(2)
        tsel = f1_.multiselect("Tipo", sorted(alerts["tipo"].unique()), default=sorted(alerts["tipo"].unique()))
        ssel = f2_.multiselect("Severidad", ["Alta", "Media", "Baja"], default=["Alta", "Media", "Baja"])
        view = alerts[alerts["tipo"].isin(tsel) & alerts["severidad"].isin(ssel)].rename(
            columns={"duracion_min": "duración (min)"})
        view["severidad"] = view["severidad"].map(SEV)
        dtbl(view, column_config={
            "inicio": st.column_config.DatetimeColumn("inicio", format="YYYY-MM-DD HH:mm:ss", width="medium"),
            "fin": st.column_config.DatetimeColumn("fin", format="YYYY-MM-DD HH:mm:ss", width="medium"),
            "detalle": st.column_config.TextColumn("detalle", width="large"),
        })
        tl = alerts.copy()
        tl["fin_plot"] = tl[["fin", "inicio"]].apply(lambda r: max(r.fin, r.inicio + pd.Timedelta(seconds=30)), axis=1)
        fig = px.timeline(tl, x_start="inicio", x_end="fin_plot", y="tipo", color="severidad",
                          color_discrete_map={"Alta": RED, "Media": YELLOW, "Baja": BLUE}, hover_data=["detalle"])
        fig.update_yaxes(title_text=None)
        chart(fig, "Línea de tiempo de alertas", height=120 + 55 * tl["tipo"].nunique(), hover="closest", key="al_tl")

# ============================ CORRELACIÓN ============================
with sec("🔗 Correlación entre sensores"):
    method = st.radio("Método de correlación", ["pearson", "spearman"], horizontal=True,
                      help="Spearman es más robusto si la relación no es lineal.")
    cm = an.corr_matrix(dfr, method)
    section("Pares de variables", "Cada fila es una pareja de variables; r va de −1 a 1.")
    if cm.empty:
        st.info("Se necesitan al menos dos variables con variación.")
    else:
        cp = an.corr_pairs(cm)
        cp["variable_a"] = cp["variable_a"].map(LABELS)
        cp["variable_b"] = cp["variable_b"].map(LABELS)
        cp = cp.rename(columns={"variable_a": "variable A", "variable_b": "variable B", "interpretacion": "interpretación"})
        tbl(cp, widths=[28, 28, 12, 32])

    if has_h and has_n:
        section("Relación entre nivel de agua y humedad del suelo")
        res = an.ols(dfr["nivel_agua"], dfr["humedad_suelo"])
        if res is None:
            st.info("No hay variación suficiente para ajustar una relación.")
        else:
            kpi([
                ("Correlación (r)", f"{res['r']:.2f}", f"Relación {an.interpret_r(res['r'])} entre nivel y humedad."),
                ("R²", f"{res['r2']:.2f}", "Proporción de la variación de la humedad explicada linealmente por el nivel."),
                ("Pendiente", f"{res['pendiente']:.3f}", "Puntos de humedad que cambian por cada punto de nivel."),
                ("Intercepto", f"{res['intercepto']:.2f}", "Humedad estimada cuando el nivel es 0 %."),
                ("Pares de datos (n)", f"{res['n']:,}", "Cantidad de puntos usados en el ajuste."),
            ])
            sc = dfr[["nivel_agua", "humedad_suelo"]].dropna()
            fig = px.scatter(sc.reset_index(), x="nivel_agua", y="humedad_suelo", opacity=0.55,
                             color_discrete_sequence=[GREEN])
            xs = np.array([sc["nivel_agua"].min(), sc["nivel_agua"].max()])
            fig.add_trace(go.Scatter(x=xs, y=res["pendiente"] * xs + res["intercepto"], mode="lines",
                                     name="Ajuste lineal", line=dict(color=RED, width=3)))
            fig.update_xaxes(title_text="Nivel de agua (%)")
            fig.update_yaxes(title_text="Humedad del suelo (%)")
            chart(fig, "Nivel de agua vs humedad del suelo", height=420, hover="closest", key="cor_s")

        section("Correlación con desfase", "¿La humedad reacciona después de un cambio en el nivel?")
        step = rule or f"{max(int(dt.total_seconds()), 1)}s"
        uni = loader.resample(data, step)
        max_lag = st.slider("Desfase máximo (muestras)", 2, 60, 20)
        lc = an.lag_corr(uni["nivel_agua"], uni["humedad_suelo"], max_lag)
        if not lc.empty:
            top = lc.reindex(lc["r"].abs().sort_values(ascending=False).index).head(5).copy()
            top["interpretación"] = top["r"].map(an.interpret_r)
            top["r"] = top["r"].round(3)
            top["lag"] = top["lag"].astype(int)
            top = top.rename(columns={"lag": "desfase k (muestras)"})
            top["tiempo equivalente"] = top["desfase k (muestras)"].map(lambda k: f"{k} × {step}")
            tbl(top, widths=[22, 14, 30, 34], key_col=False)
            fig = px.bar(lc, x="lag", y="r", color_discrete_sequence=[BLUE])
            fig.update_yaxes(range=[-1, 1], title_text="r")
            fig.update_xaxes(title_text=f"desfase k (1 muestra = {step})")
            chart(fig, "Correlación: nivel(t) vs humedad(t + k)", height=320, hover="closest", key="cor_lag")

    if has_h and has_v and dfr["valvula"].nunique() > 1:
        section("Humedad según el estado de la válvula")
        dd = dfr.assign(estado=np.where(dfr["valvula"].ffill().fillna(0) >= 0.5, "Abierta", "Cerrada"))
        g = dd.groupby("estado")["humedad_suelo"].agg(["count", "mean", "median", "min", "max"]).reset_index()
        g.columns = ["válvula", "registros", "media (%)", "mediana (%)", "mínimo (%)", "máximo (%)"]
        tbl(g)
    section("Cómo leer la correlación")
    tbl(gl.correlacion(), widths=[20, 80])

# ============================ REGISTROS ============================
with sec("🗂️ Registros del sistema"):
    section("Resumen de eventos del sistema", "Cuántos eventos de cada tipo hay en la bitácora.")
    if log.empty:
        st.info("Sin eventos que registrar.")
    else:
        rs = log.groupby(["origen", "evento"]).size().reset_index(name="cantidad")
        tbl(rs, widths=[40, 40, 20])
        section("Bitácora completa", "Más recientes primero. Haz clic en un encabezado para ordenar.")
        origins = sorted(log["origen"].unique())
        osel = st.multiselect("Origen", origins, default=origins)
        lv = log[log["origen"].isin(osel)].sort_values("tiempo", ascending=False)
        dtbl(lv, column_config={
            "tiempo": st.column_config.DatetimeColumn("tiempo", format="YYYY-MM-DD HH:mm:ss", width="medium"),
            "origen": st.column_config.TextColumn("origen", width="medium"),
            "detalle": st.column_config.TextColumn("detalle", width="large"),
        })
        st.caption("Incluye aperturas y cierres de válvula, alertas del firmware, cambios de estado y alertas calculadas.")
    section("Datos procesados", "Registros con los estados calculados. Más recientes primero (últimos 500).")
    st.dataframe(naive(processed.tail(500).iloc[::-1]), width="stretch", hide_index=True)
    st.download_button("⬇️ Descargar datos procesados", to_csv(processed), file_name="datos_procesados.csv",
                       mime="text/csv", key="dl_reg")

# ============================ DESCARGAS ============================
with sec("⬇️ Descargar datos procesados"):
    section("Descargar datos procesados", f"Datos agrupados: {rule_label.lower()}. Se aplica el filtro de fechas.")
    stats_df = an.stats_table(data).reset_index()
    files = [
        ("datos_procesados.csv", "Serie de tiempo con sensores y estados calculados (estado_suelo_calc, estado_nivel_calc, riego_activo).", processed),
        ("resumen_diario.csv", "Medias, mínimos, máximos, tiempo en estado seco/bajo y riegos por día.", daily.reset_index()),
        ("eventos_riego.csv", "Un renglón por riego: duración, humedad antes/después, nivel y consumo.", events),
        ("alertas.csv", "Alertas operativas con inicio, fin, severidad y detalle.", alerts),
        ("registros_sistema.csv", "Bitácora de válvula, alertas del firmware y cambios de estado.", log),
    ]
    summary = pd.DataFrame([(n_, d_, len(df_), len(df_.columns) + (1 if isinstance(df_.index, pd.DatetimeIndex) else 0))
                            for n_, d_, df_ in files],
                           columns=["Archivo", "Contenido", "Filas", "Columnas"])
    tbl(summary, widths=[20, 56, 12, 12])
    cols = st.columns(3)
    for i, (n_, d_, df_) in enumerate(files):
        cols[i % 3].download_button(f"📥 {n_}", to_csv(df_), file_name=n_, mime="text/csv",
                                    key=f"dl{i}", disabled=df_.empty, width="stretch")
    cols[2].download_button(
        "📦 sprout_analisis.xlsx (todo)",
        to_excel({"datos": processed, "riegos": events, "alertas": alerts, "registros": log,
                  "diario": daily.reset_index(), "sensores": status, "estadistica": stats_df}),
        file_name="sprout_analisis.xlsx", key="dlx", width="stretch",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    section("Vista previa de los datos procesados", "Últimos 200 registros.")
    prev = processed.tail(200).iloc[::-1]
    st.dataframe(naive(prev), width="stretch", hide_index=True)

# ============================ GLOSARIO ============================
with sec("📖 Glosario: qué significa cada cosa"):
    st.markdown("Explicación de cada variable, umbral, alerta e indicador usado en esta app.")
    section("Variables del sistema")
    tbl(gl.variables(), widths=[17, 8, 22, 41, 12])
    section("Estados y umbrales")
    tbl(gl.umbrales(p), widths=[18, 30, 52])
    section("Tipos de alerta")
    ga = gl.alertas(p)
    ga["Severidad"] = ga["Severidad"].map(SEV)
    tbl(ga, widths=[14, 8, 24, 28, 26])
    section("Estado de los sensores")
    tbl(gl.estados_sensor(), widths=[16, 84])
    section("Columnas de los eventos de riego")
    tbl(gl.columnas_riego(), widths=[24, 76])
    section("Estadísticos")
    tbl(gl.estadisticos(), widths=[26, 74])
    section("Correlación")
    tbl(gl.correlacion(), widths=[20, 80])
    section("Formatos de archivo aceptados")
    tbl(gl.formatos(), widths=[22, 78])
