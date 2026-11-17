"""Carga y normalización de datos de riego.

Acepta CSV/XLSX exportados desde:
  * InfluxDB (CSV anotado, formato largo con _time/_field/_value, o ancho)
  * ThingsBoard (Timestamp + una columna por clave de telemetría)
  * Grafana (Time + columnas tipo "humedad_suelo ESP32")
  * Cualquier CSV con una columna de fecha y columnas de sensores
"""
from __future__ import annotations

import io
import re

import numpy as np
import pandas as pd

TZ = "America/Bogota"

# Nombre canónico -> alias aceptados (se comparan en minúsculas, sin espacios)
NUMERIC_COLS = ["humedad_suelo", "nivel_agua", "humedad_raw", "nivel_raw"]
BOOL_COLS = ["valvula", "alerta_nivel", "alerta_humedad", "led_rojo", "led_amarillo", "led_verde"]
TEXT_COLS = ["estado_suelo", "estado_nivel"]
KNOWN = NUMERIC_COLS + BOOL_COLS + TEXT_COLS

ALIASES = {
    "humedad": "humedad_suelo",
    "humedad_pct": "humedad_suelo",
    "soil_moisture": "humedad_suelo",
    "nivel": "nivel_agua",
    "nivel_pct": "nivel_agua",
    "water_level": "nivel_agua",
    "humedadraw": "humedad_raw",
    "nivelraw": "nivel_raw",
    "valve": "valvula",
    "servo": "valvula",
}

TIME_CANDIDATES = [
    "_time", "time", "timestamp", "ts", "fecha", "fecha_hora", "datetime",
    "date", "created_at", "_start", "_stop",
]


class DataFormatError(Exception):
    """El archivo no tiene el formato esperado."""


def _read_raw(name: str, content: bytes) -> pd.DataFrame:
    lname = name.lower()
    if lname.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content))
    text = content.decode("utf-8-sig", errors="replace")
    # Detecta separador (; o ,)
    sample = "\n".join([l for l in text.splitlines() if l and not l.startswith("#")][:5])
    sep = ";" if sample.count(";") > sample.count(",") else ","
    df = pd.read_csv(io.StringIO(text), comment="#", sep=sep, low_memory=False)
    return df


def _clean_influx_headers(df: pd.DataFrame) -> pd.DataFrame:
    """El CSV anotado de Influx repite el encabezado entre tablas y trae
    columnas auxiliares (vacía, result, table). Las elimina."""
    df = df.copy()
    drop = [c for c in df.columns if re.fullmatch(r"Unnamed: 0|result|table|", str(c).strip())]
    df = df.drop(columns=drop)
    # filas que repiten el encabezado (>=2 celdas iguales a su nombre de columna)
    hits = sum((df[c].astype(str) == str(c)).astype(int) for c in df.columns)
    return df.loc[hits < 2].reset_index(drop=True)


def _find_time_col(df: pd.DataFrame) -> str:
    low = {c: str(c).strip().lower() for c in df.columns}
    for cand in TIME_CANDIDATES:
        for c, l in low.items():
            if l == cand:
                return c
    # primera columna que parezca fecha
    for c in df.columns:
        s = df[c].dropna().astype(str).head(20)
        if s.empty:
            continue
        if s.str.match(r"^\d{4}-\d{2}-\d{2}").mean() > 0.8 or s.str.match(r"^\d{4}/\d{2}/\d{2}").mean() > 0.8:
            return c
    raise DataFormatError(
        "No encontré una columna de fecha/hora. Se esperaba algo como "
        "'_time', 'Timestamp', 'Time' o 'fecha'."
    )


def _parse_time(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        # epoch en ms (ThingsBoard) o s
        unit = "ms" if s.dropna().median() > 1e11 else "s"
        t = pd.to_datetime(s, unit=unit, utc=True, errors="coerce")
    else:
        t = pd.to_datetime(s, errors="coerce", utc=False, format="mixed")
        if t.dt.tz is None:
            t = t.dt.tz_localize(TZ, nonexistent="shift_forward", ambiguous="NaT")
        else:
            t = t.dt.tz_convert("UTC")
    return t.dt.tz_convert(TZ)


def _canon(col: str) -> str | None:
    """Mapea un nombre de columna a su nombre canónico (o None)."""
    c = re.sub(r"\s+", " ", str(col).strip().lower())
    c = c.replace('"', "")
    first = c.split(" ")[0]  # "humedad_suelo esp32" -> "humedad_suelo"
    for cand in (c, first):
        cand = cand.replace(" ", "_")
        if cand in KNOWN:
            return cand
        if cand in ALIASES:
            return ALIASES[cand]
    for k in sorted(KNOWN, key=len, reverse=True):
        if c.startswith(k):
            return k
    return None


def _to_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    m = {"true": 1, "false": 0, "1": 1, "0": 0, "on": 1, "off": 0, "si": 1, "sí": 1, "no": 0,
         "abierta": 1, "abierto": 1, "cerrada": 0, "cerrado": 0, "1.0": 1, "0.0": 0}
    out = s.astype(str).str.strip().str.lower().map(m)
    if out.isna().all():
        out = pd.to_numeric(s, errors="coerce")
    return out.astype("float")  # 0/1/NaN, se rellena luego


def load_file(name: str, content: bytes) -> tuple[pd.DataFrame, dict]:
    """Devuelve (df indexado por tiempo, info) con columnas canónicas."""
    raw = _read_raw(name, content)
    if raw.empty:
        raise DataFormatError("El archivo está vacío.")
    raw = _clean_influx_headers(raw)
    info = {"filas_archivo": len(raw), "formato": "ancho"}

    cols_l = {str(c).strip().lower(): c for c in raw.columns}

    # ---- Formato largo (Influx: _time, _field, _value) ----
    if "_field" in cols_l and "_value" in cols_l:
        info["formato"] = "InfluxDB (largo)"
        tcol = cols_l.get("_time") or _find_time_col(raw)
        long = raw[[tcol, cols_l["_field"], cols_l["_value"]]].copy()
        long.columns = ["time", "field", "value"]
        long["time"] = _parse_time(long["time"])
        long["field"] = long["field"].map(_canon)
        long = long.dropna(subset=["time", "field"])
        # separa numérico y texto
        long["num"] = pd.to_numeric(long["value"], errors="coerce")
        wide = long.pivot_table(index="time", columns="field", values="num", aggfunc="last")
        txt = long[long["field"].isin(TEXT_COLS + BOOL_COLS) & long["num"].isna()]
        if not txt.empty:
            tw = txt.pivot_table(index="time", columns="field", values="value", aggfunc="last")
            tw = tw[[c for c in tw.columns if c not in wide.columns]]
            wide = wide.join(tw, how="outer")
        df = wide
    else:
        tcol = _find_time_col(raw)
        info["formato"] = "ancho (columna por sensor)"
        df = raw.copy()
        df["__t"] = _parse_time(df[tcol])
        df = df.dropna(subset=["__t"]).set_index("__t")
        df.index.name = "time"
        rename = {}
        for c in df.columns:
            k = _canon(c)
            if k and k not in rename.values():
                rename[c] = k
        df = df[list(rename)].rename(columns=rename)

    if df.empty or not (set(df.columns) & set(KNOWN)):
        raise DataFormatError(
            "No reconocí columnas de sensores. Se esperaban nombres como "
            + ", ".join(NUMERIC_COLS[:2]) + ", valvula..."
        )

    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    for c in NUMERIC_COLS:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in BOOL_COLS:
        if c in df:
            df[c] = _to_bool(df[c])
    for c in TEXT_COLS:
        if c in df:
            df[c] = df[c].astype("string")

    # Si falta el porcentaje pero hay raw, lo calcula con la calibración del firmware
    if "humedad_suelo" not in df and "humedad_raw" in df:
        df["humedad_suelo"] = (df["humedad_raw"] / 3083 * 100).clip(0, 100)
        info["humedad_calculada"] = True
    if "nivel_agua" not in df and "nivel_raw" in df:
        df["nivel_agua"] = (df["nivel_raw"] / 4095 * 100).clip(0, 100)
        info["nivel_calculado"] = True

    # Recorta valores imposibles de porcentaje
    for c in ("humedad_suelo", "nivel_agua"):
        if c in df:
            df.loc[(df[c] < 0) | (df[c] > 100), c] = np.nan

    info["filas"] = len(df)
    info["inicio"] = df.index.min()
    info["fin"] = df.index.max()
    return df, info


def resample(df: pd.DataFrame, rule: str | None) -> pd.DataFrame:
    """Re-muestrea: media para numéricas, máximo para banderas 0/1, último para texto."""
    if not rule:
        return df
    agg = {}
    for c in df.columns:
        if c in NUMERIC_COLS:
            agg[c] = "mean"
        elif c in BOOL_COLS:
            agg[c] = "max"
        else:
            agg[c] = "last"
    out = df.resample(rule).agg(agg)
    num = [c for c in out.columns if c in NUMERIC_COLS]
    out = out.dropna(how="all", subset=num) if num else out
    return out
