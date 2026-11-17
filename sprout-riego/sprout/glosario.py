"""Textos explicativos (glosario) que se muestran como tablas en la app."""
from __future__ import annotations

import pandas as pd

from .analysis import Params


def _df(rows: list[tuple], cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=cols)


def variables() -> pd.DataFrame:
    return _df([
        ("humedad_suelo", "%", "Humedad del suelo ya convertida a porcentaje.",
         "Pin 32 (ADC). Promedio de 8 lecturas; 0 = seco (raw 0) y 100 = mojado (raw 3083).", "0 a 100"),
        ("humedad_raw", "ADC", "Lectura cruda del sensor de humedad.", "Promedio de 8 lecturas del conversor analógico-digital de 12 bits.", "0 a 4095"),
        ("nivel_agua", "%", "Nivel de agua del tanque en porcentaje.",
         "Pin 33 (ADC). 0 = vacío (raw 0) y 100 = lleno (raw 4095).", "0 a 100"),
        ("nivel_raw", "ADC", "Lectura cruda del sensor de nivel.", "Promedio de 8 lecturas del ADC de 12 bits.", "0 a 4095"),
        ("valvula", "0 / 1", "Estado de la válvula (servo).", "1 = abierta (servo a 180°), 0 = cerrada (servo a 90°).", "0 o 1"),
        ("alerta_nivel", "0 / 1", "Alerta de tanque bajo del firmware.",
         "Se activa con nivel_raw ≤ 16.84 y se apaga con nivel_raw ≥ 29.18 (histéresis para evitar parpadeo).", "0 o 1"),
        ("alerta_humedad", "0 / 1", "Alerta de suelo seco del firmware.", "Activa cuando humedad_suelo < 20 %.", "0 o 1"),
        ("estado_suelo", "texto", "Clasificación del suelo.", "SECO (< 20 %), INTERMEDIO (20–55 %), HUMEDO (≥ 55 %).", "3 estados"),
        ("estado_nivel", "texto", "Clasificación del tanque.", "NORMAL o BAJO según la alerta de nivel del firmware.", "2 estados"),
        ("led_rojo / led_amarillo / led_verde", "0 / 1", "Estado de los LED del montaje.",
         "Rojo: suelo seco. Verde: suelo húmedo. Amarillo parpadeando: tanque bajo.", "0 o 1"),
    ], ["Variable (columna)", "Unidad", "Qué significa", "Cómo se obtiene en el ESP32", "Rango"])


def umbrales(p: Params) -> pd.DataFrame:
    return _df([
        ("Suelo SECO", f"humedad < {p.hum_seca:g} %", "Se abre la válvula automáticamente y se enciende el LED rojo."),
        ("Suelo INTERMEDIO", f"{p.hum_seca:g} % ≤ humedad < {p.hum_humeda:g} %",
         "Zona de histéresis: la válvula mantiene su estado anterior (no abre ni cierra por sí sola)."),
        ("Suelo HÚMEDO", f"humedad ≥ {p.hum_humeda:g} %", "Se cierra la válvula automáticamente y se enciende el LED verde."),
        ("Tanque BAJO", f"nivel < {p.nivel_bajo:g} %", "La app marca alerta. (El firmware usa su propio umbral sobre el valor ADC.)"),
        ("Tanque NORMAL", f"nivel ≥ {p.nivel_bajo:g} %", "Sin alerta."),
    ], ["Estado", "Condición (umbral actual)", "Qué ocurre"])


def alertas(p: Params) -> pd.DataFrame:
    return _df([
        ("Suelo seco", "Media", f"Humedad < {p.hum_seca:g} %.",
         "Las plantas pueden estresarse si el riego no responde.", "Verificar que la válvula abra y que haya agua."),
        ("Nivel de tanque bajo", "Alta", f"Nivel < {p.nivel_bajo:g} %.",
         "Sin agua el riego automático deja de funcionar.", "Recargar el tanque."),
        ("Sin datos", "Media", f"Más de {p.gap_min:g} min entre dos registros.",
         "Se pierde monitoreo; puede haber cortes de WiFi o apagado del ESP32.", "Revisar alimentación y conexión."),
        ("Sensor con valor constante", "Media", f"Mismo valor (entre 0 y 100 %) durante ≥ {p.frozen_min:g} min.",
         "Un sensor real siempre fluctúa; un valor fijo sugiere sensor desconectado o bloqueado.", "Revisar cableado del sensor."),
        ("Riego prolongado", "Media", f"Válvula abierta más de {p.riego_max_min:g} min.",
         "Posible válvula atascada, sensor de humedad que no responde o desperdicio de agua.", "Cerrar manualmente y revisar el sensor."),
        ("Riego sin efecto", "Media", f"La humedad mejora menos de {p.delta_min:g} puntos {p.post_min:g} min después de cerrar.",
         "El agua no está llegando al suelo o el sensor no mide bien.", "Revisar tuberías, goteros y sensor."),
        ("Riego con tanque bajo", "Alta", f"La válvula se abre con nivel < {p.nivel_bajo:g} %.",
         "Se riega con poca agua: el riego puede ser insuficiente o la bomba trabajar en vacío.", "Recargar el tanque antes de regar."),
    ], ["Alerta", "Severidad", "Regla (umbrales actuales)", "Por qué importa", "Qué hacer"])


def estados_sensor() -> pd.DataFrame:
    return _df([
        ("🟢 OK", "Lecturas normales: cobertura alta, sin huecos grandes, sin valores constantes ni saturación."),
        ("🟡 Revisar", "Cobertura < 80 %, hueco de datos mayor al umbral, o valor constante sostenido."),
        ("🔴 Falla", "Sin lecturas válidas, o saturado en 0 / 100 % (o 0 / 4095 ADC) más del 80 % del tiempo."),
    ], ["Estado", "Criterio"])


def estadisticos() -> pd.DataFrame:
    return _df([
        ("n", "Cantidad de lecturas válidas usadas."),
        ("media", "Promedio aritmético. Valor típico del periodo."),
        ("desv_est", "Desviación estándar: cuánto se alejan los datos de la media. Alta = muy variable."),
        ("min / max", "Valores extremos observados."),
        ("p5, p25, mediana, p75, p95", "Percentiles: el X % de las lecturas está por debajo de ese valor. La mediana (p50) no se distorsiona con extremos."),
        ("coef_var_%", "Desviación estándar / media × 100. Permite comparar variabilidad entre variables de distinta escala."),
        ("asimetria", "0 = simétrica; > 0 = cola larga hacia valores altos; < 0 = cola hacia valores bajos."),
        ("curtosis", "0 ≈ distribución normal; > 0 = muchos valores extremos; < 0 = distribución más plana."),
        ("atipicos_IQR", "Lecturas fuera de [Q1 − 1.5·IQR, Q3 + 1.5·IQR]. Posibles lecturas anómalas."),
    ], ["Estadístico", "Qué significa"])


def columnas_riego() -> pd.DataFrame:
    return _df([
        ("inicio / fin", "Instante en que la válvula pasa de cerrada a abierta y de abierta a cerrada."),
        ("duracion_min", "Minutos entre inicio y fin."),
        ("origen_probable", "«Automático» si la humedad al abrir estaba bajo el umbral seco; si no, «Manual / otro» (por ejemplo, el switch de ThingsBoard)."),
        ("humedad_inicio", "Humedad (%) justo al abrir la válvula."),
        ("humedad_post", "Humedad (%) algunos minutos después de cerrar (se configura en la barra lateral)."),
        ("mejora_humedad", "humedad_post − humedad_inicio, en puntos porcentuales. Mide la efectividad del riego."),
        ("nivel_inicio / nivel_fin", "Nivel del tanque (%) al abrir y al cerrar."),
        ("consumo_nivel", "nivel_inicio − nivel_fin: puntos de nivel que gastó el riego."),
    ], ["Columna", "Qué significa"])


def correlacion() -> pd.DataFrame:
    return _df([
        ("r", "Coeficiente de correlación entre −1 y 1. Cerca de 1: suben juntas; cerca de −1: una sube y la otra baja; cerca de 0: sin relación lineal."),
        ("R²", "r al cuadrado: proporción de la variación de la humedad que explica el nivel (0 a 1)."),
        ("Pearson", "Mide relaciones lineales."),
        ("Spearman", "Mide relaciones monótonas (por rangos); es más robusto con valores atípicos."),
        ("Desfase (k)", "Correlación entre el nivel en el tiempo t y la humedad en t + k. Con k > 0 la humedad reacciona después del cambio de nivel."),
        ("Advertencia", "Correlación no implica causalidad: el nivel baja porque se riega, y la humedad sube por el riego."),
    ], ["Concepto", "Qué significa"])


def formatos() -> pd.DataFrame:
    return _df([
        ("InfluxDB", "Data Explorer → Download CSV. Acepta formato anotado, largo (_time/_field/_value) o pivotado."),
        ("ThingsBoard", "Exportar telemetría: columna Timestamp (ms o fecha) y una columna por clave."),
        ("Grafana", "Inspect → Data → Download CSV. Columnas como «humedad_suelo ESP32»."),
        ("Excel / CSV propio", "Una columna de fecha (_time, Timestamp, Time, fecha…) y columnas con los nombres de la tabla de variables."),
        ("Zona horaria", "Todas las horas se muestran en America/Bogota (UTC−5)."),
    ], ["Origen", "Cómo exportarlo / qué se espera"])
