# 🌱 Sprout · Monitoreo de riego (Streamlit)

Dashboard para analizar los datos de tu sistema de riego con ESP32 (humedad del suelo, nivel del tanque y válvula/servo).
Subes el CSV o XLSX que descargaste y la app muestra todo automáticamente.

## Qué incluye

Una sola página con secciones (en este orden). Cada sección muestra **tablas que explican cada indicador y su significado**; los textos se adaptan al tema claro u oscuro de Streamlit.

| Sección | Contenido |
|---|---|
| 📋 Resumen del monitoreo | Indicadores clave, tiempo por estado del suelo y del tanque, hallazgos automáticos |
| 🛰️ Estado de los sensores | OK / Revisar / Falla, cobertura, huecos, criterios de evaluación |
| 📈 Evolución de las variables | Resumen por variable, resumen por intervalo y gráficas con umbrales y riegos |
| 🪣 Nivel de agua | Indicadores, tendencia, episodios de nivel bajo y consumo por riego |
| 🚿 Datos de riego | Eventos detectados desde `valvula`, efecto en la humedad y origen probable |
| 📊 Análisis estadístico | Resumen, descriptivos detallados, distribución, patrón por hora y resumen diario |
| 🚨 Alertas operativas | Resumen por tipo, reglas vigentes y detalle de cada alerta |
| 🔗 Correlación entre sensores | Pares de variables, relación nivel–humedad, correlación con desfase |
| 🗂️ Registros del sistema | Bitácora de válvula, alertas y cambios de estado; datos procesados |
| ⬇️ Descargar datos procesados | CSV de datos, riegos, alertas, registros, resumen diario y Excel con todo |
| 📖 Glosario | Explicación de cada variable, umbral, alerta e indicador |

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
