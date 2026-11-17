# 🌱 Sprout · Monitoreo de riego (Streamlit)

Dashboard para analizar los datos de tu sistema de riego con ESP32 (humedad del suelo, nivel del tanque y válvula/servo).
Subes el CSV o XLSX que descargaste y la app muestra todo automáticamente.

## Qué incluye

| Sección | Contenido |
|---|---|
| 📋 Resumen | KPIs, diagnóstico automático, humedad y nivel con franjas de riego, tiempo por estado del suelo |
| 🛰️ Sensores | Estado (OK / Revisar / Falla), cobertura, huecos de datos, registros por día |
| 📈 Evolución | Variables apiladas con suavizado, umbrales y riegos marcados |
| 💧 Nivel de agua | Indicador, tendencia (puntos/hora), estimación al umbral bajo, consumo por riego |
| 🚿 Riego | Eventos detectados desde `valvula`, duración, efecto sobre la humedad, origen probable |
| 📊 Estadística | Descriptivos, distribución, patrón por hora, resumen diario |
| 🚨 Alertas | Suelo seco, tanque bajo, huecos, sensor congelado, riego prolongado / sin efecto / con tanque bajo |
| 🔗 Correlación | Matriz Pearson/Spearman, nivel vs humedad (ajuste lineal) y correlación con desfase |
| 🧾 Registros | Bitácora de válvula, alertas y cambios de estado |
| ⬇️ Descargas | CSV de datos procesados, riegos, alertas, registros, resumen diario y Excel con todo |

## Formatos de archivo aceptados

* **InfluxDB**: *Data Explorer → Download CSV* (formato anotado, largo o pivotado).
* **ThingsBoard**: exportación de telemetría (columna `Timestamp` + una columna por clave).
* **Grafana**: *Inspect → Data → Download CSV* (columnas tipo `humedad_suelo ESP32`).
* Cualquier CSV/XLSX con una columna de fecha (`_time`, `Timestamp`, `Time`, `fecha`…) y estas columnas:
  `humedad_suelo`, `nivel_agua`, `humedad_raw`, `nivel_raw`, `valvula`, `alerta_nivel`, `alerta_humedad`, `estado_suelo`, `estado_nivel`.

Si falta el porcentaje pero está el valor ADC, se calcula con la calibración del firmware.
Las horas se muestran en zona horaria **America/Bogota**. Puedes subir varios archivos a la vez.

## Ejecutar en tu computador

```bash
git clone https://github.com/TU_USUARIO/sprout-riego.git
cd sprout-riego
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Se abre en <http://localhost:8501>. Activa **Usar datos de ejemplo** para ver la app sin tu archivo.

## Publicar en Streamlit Community Cloud (gratis)

1. Sube este proyecto a un repositorio de GitHub.
2. Entra a <https://share.streamlit.io> con tu cuenta de GitHub → **Create app**.
3. Elige tu repositorio, rama `main` y archivo principal `app.py` → **Deploy**.

Cada `git push` actualiza la app automáticamente.

## Umbrales

Los valores por defecto coinciden con el firmware: suelo seco < 20 %, suelo húmedo ≥ 55 %.
El resto (nivel bajo, huecos, sensor congelado, riego prolongado…) se ajusta en la barra lateral → **Umbrales y reglas**.

## Estructura

```
app.py                  # interfaz Streamlit
sprout/loader.py        # lectura y normalización de CSV/XLSX
sprout/analysis.py      # riegos, alertas, estadística y correlación
data/ejemplo_riego.csv  # datos sintéticos de demostración
tools/generar_ejemplo.py
```

> Los datos de `data/ejemplo_riego.csv` son **sintéticos**, solo para demostración.
