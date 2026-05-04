# Módulo 1 — Extracción GA4 → BigQuery

## ¿Qué hace este módulo?

Conecta con la **GA4 Data API** del Google Merchandise Store (cuenta demo pública de Google), extrae cuatro reportes de comportamiento e-commerce, y los carga como tablas estructuradas en **BigQuery**.

Este módulo es la **base del pipeline completo**: todos los módulos siguientes (QA, análisis de funnel, dashboard) consumen los datos que este módulo deposita en BigQuery.

---

## ¿Por qué este módulo existe en un portafolio de Digital Analytics?

La oferta para la que fue diseñado este proyecto pide explícitamente:

> *"Coordinaremos la implementación técnica con equipos de desarrollo, asegurando que el diseño de medición se traduzca correctamente a la capa de datos."*

Este módulo **es** esa capa de datos: demuestra que el BA no solo analiza dashboards, sino que sabe construir el pipeline que los alimenta.

---

## Archivos

| Archivo | Rol |
|---|---|
| `ga4_extractor.py` | Se conecta a GA4 y devuelve DataFrames |
| `bq_loader.py` | Carga los DataFrames a BigQuery |
| `raw_data/` | CSVs de respaldo generados en cada extracción |
| `extractor.log` | Log de la extracción |
| `loader.log` | Log de la carga a BigQuery |
| `load_metadata.json` | Metadata de la última carga (usado por el Módulo 3) |

---

## Tablas creadas en BigQuery

Todas en el dataset `ecommerce_analytics`:

### `funnel_events`
Eventos del funnel de conversión por canal y dispositivo.

| Campo | Tipo | Descripción |
|---|---|---|
| eventName | STRING | session_start, view_item, add_to_cart, begin_checkout, purchase |
| sessionDefaultChannelGroup | STRING | Canal de adquisición |
| deviceCategory | STRING | desktop / mobile / tablet |
| eventCount | INTEGER | Veces que ocurrió el evento |
| totalUsers | INTEGER | Usuarios únicos |
| extraction_date | DATE | Fecha de extracción |

### `session_overview`
Sesiones, bounce rate y revenue por canal y dispositivo.

### `daily_revenue`
Revenue, transacciones y ticket promedio día a día.

### `device_breakdown`
Conversión y engagement segmentados por dispositivo y OS.

---

## Cómo ejecutar

### 1. Prerrequisitos

```bash
# Clonar el repositorio
git clone https://github.com/tu-usuario/ecommerce-analytics-pipeline.git
cd ecommerce-analytics-pipeline

# Crear entorno virtual (buena práctica: aisla las dependencias del proyecto)
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows

# Instalar dependencias
pip install -r requirements.txt
```

### 2. Configurar credenciales

```bash
# Opción A: Google Cloud SDK (para desarrollo local)
gcloud auth application-default login

# Opción B: Service Account (para producción)
export GOOGLE_APPLICATION_CREDENTIALS="ruta/a/tu/service-account.json"
```

> **¿Qué es una Service Account?**
> Es un usuario de sistema (no humano) en Google Cloud con permisos específicos. En un entorno empresarial, el BA solicita al equipo de infraestructura una SA con acceso de lectura a GA4 y escritura a BigQuery.

### 3. Configurar el proyecto

Editar en `bq_loader.py`:
```python
PROJECT_ID = "tu-proyecto-gcp"   # tu Google Cloud Project ID
```

### 4. Ejecutar

```bash
cd 01_extraction
python bq_loader.py
```

**Output esperado:**
```
2024-01-15 10:23:41 [INFO] MÓDULO 1 — PIPELINE COMPLETO: EXTRACCIÓN + CARGA
2024-01-15 10:23:42 [INFO] GA4Extractor inicializado | Property: 213025502
2024-01-15 10:23:44 [INFO] Reporte completado | 25 filas extraídas
2024-01-15 10:23:46 [INFO] Reporte completado | 18 filas extraídas
...
2024-01-15 10:23:51 [INFO] ✅ Tabla cargada: proyecto.ecommerce_analytics.funnel_events
...
✅ Módulo 1 completado.
🚀 Siguiente paso: python 03_qa/data_quality_checks.py
```

---

## Diagrama de flujo interno

```
GA4 Data API (Google Merchandise Store)
        │
        │  RunReportRequest (dimensions + metrics + dateRange)
        ▼
ga4_extractor.py
        │
        │  4 reportes → 4 DataFrames de pandas
        │  + CSVs de respaldo en raw_data/
        ▼
bq_loader.py
        │
        │  Verifica/crea dataset 'ecommerce_analytics'
        │  Carga cada DataFrame con schema explícito
        │  Escribe load_metadata.json
        ▼
BigQuery: ecommerce_analytics
        ├── funnel_events
        ├── session_overview
        ├── daily_revenue
        └── device_breakdown
        │
        └──► Módulo 3 (QA) ──► Módulo 4 (Funnel) ──► Módulo 5 (Dashboard)
```

---

## Conexión con el resto del pipeline

| Módulo siguiente | Qué tabla consume | Para qué |
|---|---|---|
| `03_qa` | todas | Validar calidad y consistencia |
| `04_funnel_analysis` | `funnel_events` + `device_breakdown` | Construir funnel y detectar fricciones |
| `05_dashboard` | todas via vistas SQL | Alimentar Looker Studio |

---

## Decisiones de diseño

**¿Por qué WRITE_TRUNCATE y no WRITE_APPEND?**
El pipeline extrae siempre los últimos 90 días completos. Si usáramos APPEND, cada ejecución duplicaría los datos. TRUNCATE garantiza que la tabla refleja exactamente el período analizado.

**¿Por qué schemas explícitos y no autodetect?**
La API devuelve todos los valores como strings. Sin schema explícito, BigQuery inferiría `eventCount` como STRING, lo que rompería las queries numéricas en los módulos siguientes.

**¿Por qué guardar CSVs si BigQuery es el destino?**
Respaldo ante fallos de conectividad, y para inspección visual rápida sin necesidad de abrir la consola de BigQuery.
