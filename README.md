# E-Commerce Analytics Pipeline

Pipeline completo de Digital Analytics construido sobre datos reales del **Google Merchandise Store** (cuenta demo pública de GA4). Cubre el ciclo completo de medición: extracción de datos, simulación de tagging GTM, QA automatizado, análisis de funnel y dashboard ejecutivo en Looker Studio.

**Datos:** [Google Merchandise Store](https://shop.googlemerchandisestore.com) — propiedad GA4 pública (ID: `213025502`)

---

## Hallazgo principal

> Mobile genera el **58% del tráfico** pero convierte **3.2× menos** que desktop. El mayor punto de abandono está en la transición **Carrito → Checkout**: solo el 45% de los usuarios mobile que agregan un producto al carrito inician el proceso de pago, frente al 58% en desktop.
>
> **Recomendación prioritaria:** one-page checkout con Apple Pay / Google Pay en mobile. Impacto estimado: +13 puntos de conversión en la transición crítica.

---

## Arquitectura del pipeline

```
GA4 Data API
(Google Merchandise Store)
        │
        │  4 reportes: funnel_events, session_overview,
        │              daily_revenue, device_breakdown
        ▼
┌─────────────────────────┐
│  01 · Extracción        │  ga4_extractor.py + bq_loader.py
│  GA4 → BigQuery         │  Schemas explícitos · Logs · CSVs de respaldo
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  02 · Tagging GTM       │  tag_schema.json · gtm_events_simulator.py
│  Tracking Plan +        │  tracking_plan.md
│  Dataset Sintético      │  1 000 sesiones simuladas · 5 eventos · 3 devices
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  03 · QA Automatizado   │  data_quality_checks.py
│  great-expectations     │  17 checks · 2 niveles · Exit code CI/CD
│  + pandas               │  qa_report.csv · qa_summary.json
└────────────┬────────────┘
             │ gate: solo continúa si passed = true
             ▼
┌─────────────────────────┐
│  04 · Análisis Funnel   │  funnel_builder.py · friction_detector.py
│  Conversión + CRO       │  Plotly interactivo · friction_insights.json
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  05 · Dashboard         │  bq_views.sql · looker_studio_guide.md
│  BigQuery → Looker      │  5 vistas SQL · 4 páginas documentadas
└─────────────────────────┘
```

---

## Stack tecnológico

| Herramienta | Versión | Rol |
|---|---|---|
| Python | 3.11 | Orquestación y análisis |
| GA4 Data API | `google-analytics-data 0.18` | Extracción de datos de comportamiento |
| BigQuery | `google-cloud-bigquery 3.13` | Data Warehouse — tablas y vistas |
| pandas | 2.1 | Transformación, análisis y QA |
| great-expectations | 0.18 | Validación declarativa de calidad de datos |
| Plotly | 5.18 | Visualizaciones interactivas (HTML) |
| Looker Studio | — | Dashboard ejecutivo conectado a BigQuery |

---

## Módulos

### 01 · Extracción GA4 → BigQuery

Conecta con la GA4 Data API del Google Merchandise Store y carga 4 reportes como tablas estructuradas en BigQuery con schemas explícitos.

**Tablas creadas** en el dataset `ecommerce_analytics`:

| Tabla | Contenido |
|---|---|
| `funnel_events` | Eventos del funnel por canal y dispositivo |
| `session_overview` | Sesiones, bounce rate y revenue por canal |
| `daily_revenue` | Revenue, transacciones y ticket promedio día a día |
| `device_breakdown` | Conversión y engagement por dispositivo y OS |

**Por qué schemas explícitos y no autodetect:** la GA4 Data API devuelve todos los valores como strings. Sin schema explícito, BigQuery inferiría `eventCount` como `STRING`, lo que rompería las queries numéricas de los módulos siguientes.

```bash
cd 01_extraction
python bq_loader.py
# → Extrae 90 días de GA4 y carga 4 tablas en BigQuery
```

---

### 02 · Simulación de Tagging GTM + Tracking Plan

Define el plan de medición completo y genera un dataset sintético de 1 000 sesiones con la estructura exacta del dataLayer de GTM.

**Archivos:**
- `tag_schema.json` — especificación de 5 eventos con parámetros, tipos y reglas de QA
- `gtm_events_simulator.py` — genera el dataset validado contra el schema
- `tracking_plan.md` — documento técnico entregable al equipo de desarrollo

**Tasas de conversión simuladas por dispositivo** (basadas en benchmarks Baymard Institute):

| Transición | Desktop | Mobile | Brecha |
|---|---|---|---|
| Sesión → Vista de producto | 72% | 68% | −4 pp |
| Vista → Carrito | 35% | 22% | −13 pp |
| Carrito → Checkout | 58% | 45% | −13 pp |
| Checkout → Compra | 62% | 38% | −24 pp |

El simulador usa `seed=42` — el dataset es reproducible en cualquier máquina.

```bash
python 02_tagging_simulation/gtm_events_simulator.py
# → gtm_events_raw.json · gtm_funnel_summary.csv
```

---

### 03 · QA Automatizado de Calidad de Datos

Valida el dataset en dos niveles antes de permitir que el análisis continúe.

**Nivel 1 — Column Checks (great-expectations):** 11 validaciones por columna.

```python
# Ejemplos de expectativas declaradas
df_ge.expect_column_values_to_not_be_null("session_id")
df_ge.expect_column_values_to_be_in_set("device_category", ["desktop", "mobile", "tablet"])
df_ge.expect_column_values_to_be_between("price", min_value=0.01)
```

**Nivel 2 — Cross-Event Checks (pandas):** 6 validaciones entre eventos de la misma sesión.

| Check | Qué detecta en producción |
|---|---|
| `transaction_id` único | Doble conteo de revenue por recarga de página |
| Timestamps en orden | Bug en trigger GTM o clock del cliente |
| Purchase con checkout previo | Tag disparado en página incorrecta |
| `revenue = cart_value + shipping + tax` | Cálculo incorrecto en el tag de GTM |

El script termina con `exit(1)` si hay FAILs, compatible con CI/CD y Airflow.

```bash
python 03_qa/data_quality_checks.py
# → qa_report.csv · qa_summary.json (campo passed: true/false)
```

---

### 04 · Análisis de Funnel y Detección de Fricciones

Construye el funnel segmentado por dispositivo, detecta las brechas más significativas entre mobile y desktop, y cuantifica el impacto en revenue.

**`funnel_builder.py`**
- Acepta dos fuentes: dataset sintético (Módulo 2) o tablas reales de BigQuery (Módulo 1)
- Verifica `qa_summary.json` antes de procesar — no analiza datos que fallaron el QA
- Genera `funnel_chart.html`: gráfico interactivo con volumen absoluto + conversión acumulada

**`friction_detector.py`**

| Transición | Ratio D/M | Prioridad | Revenue potencial |
|---|---|---|---|
| Checkout → Compra | 1.6× | ALTA | mayor impacto |
| Vista → Carrito | 1.6× | ALTA | segundo mayor |
| Carrito → Checkout | 1.3× | MEDIA | — |

- Ratio D/M = cuántas veces más convierte desktop que mobile en esa transición
- Revenue potencial = sesiones recuperables × ticket promedio si mobile igualara a desktop

```bash
python 04_funnel_analysis/funnel_builder.py
python 04_funnel_analysis/friction_detector.py
# → funnel_metrics.csv · friction_insights.json · funnel_chart.html · device_comparison.html
```

---

### 05 · Dashboard: Vistas SQL + Looker Studio

5 vistas de BigQuery que transforman los datos crudos en métricas pre-calculadas para el dashboard.

```sql
-- Ejemplo: tasa de conversión acumulada por etapa y dispositivo
SELECT
    etapa_orden,
    etapa,
    dispositivo,
    usuarios,
    ROUND(
        SAFE_DIVIDE(usuarios, sesiones_inicio) * 100, 2
    ) AS tasa_conversion_acumulada_pct
FROM ...
```

**Decisiones de diseño SQL notables:**
- `SAFE_DIVIDE` en lugar de `/` — evita errores por divisor cero en segmentos pequeños
- `AVG() OVER (ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)` — media móvil 7 días nativa en BigQuery para suavizar estacionalidad semanal
- Flag `posible_anomalia` — detecta caídas de revenue > 30% en un día (posible bug de tracking)
- `ratio_vs_desktop` pre-calculado en SQL — evita fórmulas frágiles en Looker Studio

**Páginas del dashboard:**
1. Resumen ejecutivo — KPIs globales + ratio desktop/mobile
2. Funnel de conversión — por etapa y dispositivo con filtro de canal
3. Rendimiento por canal — revenue share + conversión segmentada
4. Mobile vs Desktop — tendencia temporal + brecha de conversión + insight accionable

```bash
# Crear las vistas en BigQuery
bq query --use_legacy_sql=false < 05_dashboard/bq_views.sql
```

---

## Cómo ejecutar el pipeline completo

### Prerrequisitos

```bash
git clone https://github.com/JulioPradenas/ecommerce-analytics-pipeline.git
cd ecommerce-analytics-pipeline
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Credenciales de Google Cloud

```bash
# Para desarrollo local
gcloud auth application-default login

# Para producción (Service Account)
export GOOGLE_APPLICATION_CREDENTIALS="ruta/service-account.json"
```

Editar `PROJECT_ID` en `01_extraction/bq_loader.py` con el Project ID de Google Cloud.

### Ejecución módulo a módulo

```bash
# Módulo 1: extracción GA4 → BigQuery (requiere GCP configurado)
python 01_extraction/bq_loader.py

# Módulo 2: generar dataset sintético
python 02_tagging_simulation/gtm_events_simulator.py

# Módulo 3: QA de calidad de datos
python 03_qa/data_quality_checks.py

# Módulo 4: análisis de funnel
python 04_funnel_analysis/funnel_builder.py
python 04_funnel_analysis/friction_detector.py

# Módulo 5: crear vistas en BigQuery
bq query --use_legacy_sql=false < 05_dashboard/bq_views.sql
```

> Los Módulos 2, 3 y 4 funcionan de forma autónoma sin BigQuery. El Módulo 1 requiere acceso a Google Cloud.

---

## Estructura del repositorio

```
ecommerce-analytics-pipeline/
│
├── 01_extraction/
│   ├── ga4_extractor.py        # Conexión GA4 API · 4 reportes · DataFrames
│   ├── bq_loader.py            # Carga BigQuery · schemas explícitos · metadata
│   └── README.md
│
├── 02_tagging_simulation/
│   ├── tag_schema.json         # Especificación de 5 eventos con qa_checks
│   ├── gtm_events_simulator.py # 1 000 sesiones · validación contra schema
│   ├── tracking_plan.md        # Entregable técnico para equipo de desarrollo
│   └── README.md
│
├── 03_qa/
│   ├── data_quality_checks.py  # 17 checks · great-expectations + pandas
│   └── README.md
│
├── 04_funnel_analysis/
│   ├── funnel_builder.py       # Métricas por etapa y device · Plotly
│   ├── friction_detector.py    # Ratios D/M · revenue potencial · recomendaciones CRO
│   └── README.md
│
├── 05_dashboard/
│   ├── bq_views.sql            # 5 vistas BigQuery para Looker Studio
│   ├── looker_studio_guide.md  # Configuración del dashboard paso a paso
│   └── README.md
│
├── requirements.txt
└── README.md
```

---

## Dashboard en Looker Studio

[Ver dashboard →](https://lookerstudio.google.com/...)

---

## Contacto

**Julio Pradenas** · [pradnas@gmail.com](mailto:pradnas@gmail.com) · [github.com/JulioPradenas](https://github.com/JulioPradenas)
