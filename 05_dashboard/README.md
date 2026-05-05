# Módulo 5 — Dashboard: Vistas SQL + Looker Studio

## ¿Qué hace este módulo?

Define las vistas de BigQuery que transforman los datos crudos del pipeline en métricas pre-calculadas para el dashboard, y documenta la configuración del informe en Looker Studio.

Es el último paso del pipeline: los datos extraídos (Módulo 1), simulados (Módulo 2), validados (Módulo 3) y analizados (Módulo 4) se convierten aquí en visualizaciones accionables para la toma de decisiones.

---

## Archivos

| Archivo | Rol |
|---|---|
| `bq_views.sql` | 5 vistas de BigQuery listas para ejecutar |
| `looker_studio_guide.md` | Guía paso a paso de configuración del dashboard |

---

## Las 5 vistas

| Vista | Fuente | Alimenta |
|---|---|---|
| `v_funnel_conversion` | `funnel_events` | Gráfico de funnel por etapa y dispositivo |
| `v_channel_performance` | `session_overview` | Tabla de rendimiento por canal de adquisición |
| `v_daily_revenue` | `daily_revenue` | Gráfico de tendencia temporal con media móvil 7d |
| `v_device_kpis` | `device_breakdown` | Tarjetas comparativas mobile vs desktop |
| `v_executive_summary` | Todas las anteriores | Scorecard ejecutivo — KPIs globales del período |

---

## Cómo ejecutar las vistas

```bash
# Opción 1: consola de BigQuery (recomendado para verificar antes de crear)
# Copiar el contenido de bq_views.sql en el editor de BigQuery y ejecutar

# Opción 2: CLI de gcloud
bq query --use_legacy_sql=false --project_id=tu-proyecto-gcp \
  "$(cat 05_dashboard/bq_views.sql)"
```

> Reemplazar `tu-proyecto-gcp` con el Project ID real antes de ejecutar.

---

## Estructura del dashboard (4 páginas)

```
┌─────────────────────────────────────┐
│  Página 1: Resumen Ejecutivo        │
│  Revenue · Sesiones · Conversión    │
│  Ratio Desktop/Mobile               │
├─────────────────────────────────────┤
│  Página 2: Funnel de Conversión     │
│  Por etapa y dispositivo            │
│  Tasa acumulada vs por paso         │
├─────────────────────────────────────┤
│  Página 3: Rendimiento por Canal    │
│  Revenue share · Conversión         │
│  Revenue por sesión por canal       │
├─────────────────────────────────────┤
│  Página 4: Mobile vs Desktop        │
│  Tendencia de revenue               │
│  Brecha de conversión + insight     │
└─────────────────────────────────────┘
```

---

## Decisiones de diseño SQL

**`SAFE_DIVIDE` en vez de `/`**
BigQuery lanza error si el divisor es 0. `SAFE_DIVIDE` retorna NULL, que Looker Studio muestra como vacío en vez de romper el gráfico.

**Media móvil 7 días en `v_daily_revenue`**
El revenue de e-commerce tiene ciclo semanal. Sin el promedio móvil, el gráfico diario es muy volátil y dificulta ver la tendencia real. `AVG() OVER (ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)` es la función de ventana estándar para este cálculo en BigQuery.

**Flag `posible_anomalia` en `v_daily_revenue`**
Detecta automáticamente días con caída > 30% respecto al anterior. Puede indicar un bug de tracking (el evento `purchase` dejó de dispararse) o un problema real de negocio. El dashboard lo visualiza como punto rojo en el gráfico de tendencia.

**`ratio_vs_desktop` en `v_device_kpis`**
Pre-calcula el ratio en SQL con `CROSS JOIN desktop_ref` para que Looker Studio solo consuma un campo ya calculado. Esto evita fórmulas frágiles en el dashboard que se rompen si cambia el nombre de un campo.

**`v_executive_summary` como vista única fila**
Las tarjetas Big Number de Looker Studio esperan un escalar. Una vista de una fila con `CROSS JOIN` entre CTEs es la forma más limpia de proveer múltiples escalares como fuente de datos.

---

## Conexión con el pipeline

```
01_extraction/   → tablas funnel_events, session_overview, daily_revenue, device_breakdown
04_funnel_analysis/funnel_metrics.csv → valida que los números del dashboard son consistentes
05_dashboard/bq_views.sql → transforma tablas en métricas para Looker Studio
looker_studio_guide.md    → configura el informe visual
```
