"""Genera datos sintéticos de riego (solo para demostración).

Uso:  python tools/generar_ejemplo.py
Crea data/ejemplo_riego.csv con la misma lógica de control del firmware:
la válvula abre con humedad < 20 % y cierra con humedad >= 55 %.
"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
HORAS, PASO = 10, 10  # horas simuladas, segundos entre registros
n = HORAS * 3600 // PASO
t0 = pd.Timestamp("2026-11-16 08:00", tz="America/Bogota")
idx = t0 + pd.to_timedelta(np.arange(n) * PASO, unit="s")

hum, niv, valv = 48.0, 30.0, 0
abierta = 0
rows = []
manual_until = -1
for i, ts in enumerate(idx):
    # secado del suelo y consumo lento
    hum += -0.03 * (1 + 0.5 * np.sin(i / 400)) + rng.normal(0, 0.05)
    # riego manual puntual desde "ThingsBoard"
    if i in (1500, 2900):
        manual_until = i + 30  # 5 min
    manual = i <= manual_until
    if hum < 20:
        valv = 1
    elif hum >= 55 and not manual:
        valv = 0
    if manual:
        valv = 1
    abierta = abierta + 1 if valv else 0
    if valv:
        if abierta > 8:  # el agua tarda ~80 s en llegar al sensor
            hum += 0.45 + rng.normal(0, 0.05)
        niv -= 0.11
    else:
        niv -= 0.0015
    # recarga del tanque
    if i == 2400:
        niv = 90.0
    hum, niv = float(np.clip(hum, 0, 100)), float(np.clip(niv, 0, 100))
    hraw, nraw = int(hum / 100 * 3083), int(niv / 100 * 4095)
    rows.append({
        "Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "humedad_suelo": round(hum, 2), "nivel_agua": round(niv, 2),
        "humedad_raw": hraw, "nivel_raw": nraw,
        "estado_suelo": "SECO" if hum < 20 else "HUMEDO" if hum >= 55 else "INTERMEDIO",
        "estado_nivel": "BAJO" if niv < 20 else "NORMAL",
        "alerta_nivel": int(niv < 20), "alerta_humedad": int(hum < 20), "valvula": valv,
    })

df = pd.DataFrame(rows)
# hueco de datos simulado (corte de WiFi de ~20 min)
df = df.drop(df.index[1000:1120]).reset_index(drop=True)
out = Path(__file__).resolve().parent.parent / "data" / "ejemplo_riego.csv"
out.parent.mkdir(exist_ok=True)
df.to_csv(out, index=False)
print(f"{len(df)} filas -> {out}")
