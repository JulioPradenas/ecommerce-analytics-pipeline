# E-Commerce Analytics Pipeline
### Ciclo completo de medición digital: GA4 → BigQuery → QA → Funnel → Dashboard

---

## ¿Qué es este proyecto?

Pipeline de Digital Analytics que cubre el ciclo completo de medición de un e-commerce:
desde la extracción de datos en GA4 hasta un dashboard accionable en Looker Studio,
pasando por simulación de tagging GTM, QA automatizado y análisis de funnel de conversión.

**Datos:** Google Merchandise Store — cuenta demo pública de Google Analytics 4.

---

## Stack tecnológico

| Herramienta | Rol en el pipeline |
|---|---|
| **Python 3.11** | Lenguaje principal de orquestación y análisis |
| **GA4 Data API** | Fuente de datos de comportamiento de usuarios |
| **BigQuery** | Data Warehouse donde viven los datos |
| **pandas** | Transformación y análisis de datos |
| **great-expectations** | QA automatizado de calidad de datos |
| **Plotly** | Visualizaciones interactivas del funnel |
| **Looker Studio** | Dashboard final conectado a BigQuery |
| **GitHub** | Control de versiones y portafolio |

---

## Módulos

```
01_extraction/       → Extrae GA4 y carga a BigQuery
02_tagging_simulation/ → Simula plan de tagging GTM
03_qa/               → Valida calidad de datos automáticamente
04_funnel_analysis/  → Analiza funnel y detecta fricciones
05_dashboard/        → Vistas SQL + Looker Studio
```

---

## Competencias demostradas

| Módulo | Competencia (según oferta BC Tecnología) |
|---|---|
| 01 | Estrategia de medición · coordinación capa de datos · BigQuery · SQL |
| 02 | Tagging Web & App · GTM · píxeles y eventos · documentación técnica |
| 03 | QA de tagging · consistencia de datos · reporting automatizado |
| 04 | Análisis de funnels · CRO · detección de fricciones · insights accionables |
| 05 | Dashboards Looker Studio · KPIs e-commerce · visualización para decisiones |

---

## Quickstart

```bash
git clone https://github.com/tu-usuario/ecommerce-analytics-pipeline.git
cd ecommerce-analytics-pipeline
pip install -r requirements.txt
gcloud auth application-default login
python 01_extraction/bq_loader.py
```

---

## 🔗 Dashboard en Looker Studio
[Ver dashboard →](https://lookerstudio.google.com/...)

---

## Hallazgo principal del análisis
> El **67% del abandono** en el funnel ocurre entre `add_to_cart` y `begin_checkout` en dispositivos **mobile**, con una tasa de conversión 3.2× menor que en desktop. *(ver Módulo 4 para análisis completo)*
