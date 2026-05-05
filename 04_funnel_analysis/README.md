# Módulo 4 — Análisis de Funnel y Detección de Fricciones

## ¿Qué hace este módulo?

Construye el funnel de conversión e-commerce segmentado por dispositivo, detecta automáticamente los puntos de mayor abandono entre mobile y desktop, cuantifica el impacto en revenue y genera recomendaciones de CRO accionables.

---

## Archivos

| Archivo | Rol |
|---|---|
| `funnel_builder.py` | Calcula métricas del funnel y genera el gráfico comparativo |
| `friction_detector.py` | Detecta fricciones, estima revenue potencial y genera insights |
| `funnel_metrics.csv` | Output: sesiones y tasas por etapa y dispositivo (generado) |
| `funnel_chart.html` | Output: gráfico interactivo de funnel (generado) |
| `friction_insights.json` | Output: hallazgos estructurados con recomendaciones (generado) |
| `device_comparison.html` | Output: gráfico comparativo mobile vs desktop (generado) |

---

## Cómo ejecutar

```bash
# Paso 1: construir el funnel (requiere Módulos 2 y 3 ejecutados)
python 04_funnel_analysis/funnel_builder.py

# Con datos reales de BigQuery (requiere Módulo 1 ejecutado):
python 04_funnel_analysis/funnel_builder.py bigquery

# Paso 2: detectar fricciones
python 04_funnel_analysis/friction_detector.py
```

---

## Flujo de datos

```
[Módulo 3 QA] qa_summary.json
       │ gate: solo continúa si passed=true
       ▼
funnel_builder.py
       │ fuente: gtm_events_raw.json (synthetic) o BigQuery (real)
       │ calcula sesiones únicas por etapa y dispositivo
       ▼
funnel_metrics.csv
       ▼
friction_detector.py
       │ calcula ratios desktop/mobile por transición
       │ estima revenue potencial recuperable
       ▼
friction_insights.json + device_comparison.html
```

---

## Outputs explicados

### `funnel_metrics.csv`

| Campo | Descripción |
|---|---|
| `etapa` | Nombre del evento GA4 |
| `device_category` | desktop / mobile / tablet |
| `sesiones` | Sesiones únicas que llegaron a esta etapa |
| `tasa_vs_anterior` | % que avanzó desde la etapa previa |
| `tasa_vs_inicio` | Conversión acumulada desde session_start |
| `abandono_abs` | Sesiones que abandonaron en esta etapa |

### `friction_insights.json`

```json
{
  "ratio_conversion_desktop_vs_mobile": 3.5,
  "hallazgo_principal": "El 55% del abandono en mobile ocurre en 'Carrito → Checkout'...",
  "fricciones_detectadas": [
    {
      "transicion": "Carrito → Inicio de checkout",
      "tasa_desktop": 58.0,
      "tasa_mobile": 45.0,
      "ratio_desktop_mobile": 1.29,
      "revenue_potencial_usd": 585.0,
      "prioridad": "MEDIA"
    }
  ],
  "recomendaciones": [...]
}
```

### Gráficos interactivos (HTML)

- **`funnel_chart.html`**: funnel de barras + líneas de conversión acumulada por dispositivo
- **`device_comparison.html`**: brechas de conversión + ratio D/M por transición (rojo = fricción alta)

---

## Lógica de detección de fricciones

**Métrica principal:** ratio de conversión desktop/mobile en cada transición.

| Ratio | Prioridad | Interpretación |
|---|---|---|
| ≥ 1.5× | ALTA | Mobile convierte 50%+ menos que desktop en esta etapa |
| 1.2× – 1.5× | MEDIA | Brecha significativa, investigar con heatmaps |
| < 1.2× | BAJA | Comportamiento similar entre dispositivos |

**Revenue potencial:** sesiones mobile que avanzarían si tuvieran la misma tasa de conversión que desktop × ticket promedio (~$45).

---

## Hallazgo principal del análisis

> La mayor fricción se concentra en la transición **add_to_cart → begin_checkout** en mobile, con una tasa de conversión consistentemente más baja que desktop. La hipótesis principal: el formulario de checkout no está optimizado para mobile (campos pequeños, sin métodos de pago nativos como Apple Pay/Google Pay).

**Recomendación prioritaria:** implementar one-page checkout con Apple Pay / Google Pay en mobile. Impacto estimado: recuperar ~13 puntos de conversión en la transición crítica.

---

## Conexión con el pipeline

| Módulo | Qué consume | Para qué |
|---|---|---|
| `03_qa` | `qa_summary.json` | Gate de calidad antes de analizar |
| `02_tagging_simulation` | `gtm_events_raw.json` | Fuente de datos (modo synthetic) |
| `01_extraction` | Tablas BigQuery | Fuente de datos (modo bigquery) |
| `05_dashboard` | `funnel_metrics.csv` + `friction_insights.json` | Vistas SQL y KPIs del dashboard |
