/*
╔══════════════════════════════════════════════════════════════════════════════╗
║                       MÓDULO 5 — BIGQUERY VIEWS                            ║
║                bq_views.sql  |  E-Commerce Analytics Pipeline              ║
╚══════════════════════════════════════════════════════════════════════════════╝

¿QUÉ HACE ESTE ARCHIVO?
───────────────────────
Define las vistas de BigQuery que alimentan el dashboard en Looker Studio.
Cada vista transforma los datos crudos de las tablas del Módulo 1 en un
formato optimizado para visualización: métricas pre-calculadas, campos
renombrados para ser legibles en el dashboard, y joins entre tablas.

¿POR QUÉ VISTAS Y NO CONSULTAS DIRECTAS EN LOOKER STUDIO?
────────────────────────────────────────────────────────────
Looker Studio puede conectarse directamente a una tabla de BigQuery, pero
eso tiene desventajas importantes:

  1. LÓGICA DUPLICADA: si el cálculo de conversion_rate vive en Looker Studio,
     cada chart que lo necesite lo re-calcula. Si cambia la definición, hay
     que actualizar en múltiples lugares. Con una vista, la lógica vive en un
     solo sitio.

  2. RENDIMIENTO: las vistas permiten pre-agregar datos. Looker Studio no
     tiene que escanear millones de filas — lee directamente los totales.

  3. GOBERNANZA: el BA define qué métricas existen y cómo se calculan.
     El dashboard consume las métricas, no las define. Esto es el principio
     de "single source of truth" en data governance.

  4. SEGURIDAD: una vista puede exponer solo columnas específicas, ocultando
     campos sensibles de las tablas base.

¿POR QUÉ 5 VISTAS Y NO UNA?
────────────────────────────
Cada vista alimenta una página o sección del dashboard con una granularidad
distinta. No existe una vista única que sea eficiente para todos los casos:

  v_funnel_conversion   → página de funnel (por etapa y dispositivo)
  v_channel_performance → página de canales (por canal y device)
  v_daily_revenue       → gráfico de tendencia temporal
  v_device_kpis         → tarjetas de KPI comparativas mobile/desktop
  v_executive_summary   → scorecard ejecutivo (una fila, métricas totales)

INSTRUCCIONES DE EJECUCIÓN:
────────────────────────────
Reemplazar 'tu-proyecto-gcp' con el Project ID de Google Cloud.
Ejecutar en la consola de BigQuery o con:

  bq query --use_legacy_sql=false < 05_dashboard/bq_views.sql

Las vistas se crean en el dataset 'ecommerce_analytics', que el Módulo 1
ya creó y populó con datos.
*/


-- ─────────────────────────────────────────────────────────────────────────────
-- VISTA 1: v_funnel_conversion
-- Alimenta: gráfico de funnel de conversión por etapa y dispositivo
-- ─────────────────────────────────────────────────────────────────────────────
/*
  ¿Qué hace esta vista?
  Transforma la tabla funnel_events (una fila por eventName × deviceCategory × canal)
  en un funnel ordenado con tasas de conversión acumuladas y por etapa.

  ¿Por qué el CASE para etapa_orden?
  Looker Studio ordena los valores de un campo de forma alfabética por defecto.
  Sin el campo numérico etapa_orden, el funnel aparecería en orden:
  add_to_cart → begin_checkout → purchase → session_start → view_item.
  El número garantiza el orden correcto del funnel en el gráfico.

  ¿Por qué SAFE_DIVIDE y no la división directa (/)?
  Si totalUsers es 0 para algún segmento (ej: tablets en un canal específico),
  la división daría error en BigQuery. SAFE_DIVIDE retorna NULL en vez de error.
  NULL en Looker Studio se muestra como vacío, no rompe el gráfico.
*/

CREATE OR REPLACE VIEW `tu-proyecto-gcp.ecommerce_analytics.v_funnel_conversion` AS

WITH etapas AS (
    SELECT
        CASE eventName
            WHEN 'session_start'  THEN 1
            WHEN 'view_item'      THEN 2
            WHEN 'add_to_cart'    THEN 3
            WHEN 'begin_checkout' THEN 4
            WHEN 'purchase'       THEN 5
        END                              AS etapa_orden,
        eventName                        AS etapa,
        sessionDefaultChannelGroup       AS canal,
        deviceCategory                   AS dispositivo,
        SUM(totalUsers)                  AS usuarios,
        SUM(eventCount)                  AS eventos_totales
    FROM `tu-proyecto-gcp.ecommerce_analytics.funnel_events`
    GROUP BY
        etapa_orden, etapa, canal, dispositivo
),

sesiones_por_device AS (
    -- Base del funnel: usuarios que iniciaron sesión por dispositivo
    -- Se usa como denominador para calcular conversión acumulada
    SELECT
        deviceCategory  AS dispositivo,
        SUM(totalUsers) AS sesiones_inicio
    FROM `tu-proyecto-gcp.ecommerce_analytics.funnel_events`
    WHERE eventName = 'session_start'
    GROUP BY dispositivo
)

SELECT
    etapas.etapa_orden,
    etapas.etapa,
    etapas.canal,
    etapas.dispositivo,
    etapas.usuarios,
    etapas.eventos_totales,
    sesiones_por_device.sesiones_inicio,
    ROUND(
        SAFE_DIVIDE(etapas.usuarios, sesiones_por_device.sesiones_inicio) * 100,
        2
    )                                    AS tasa_conversion_acumulada_pct,
    extraction_date
FROM etapas
LEFT JOIN sesiones_por_device
    ON etapas.dispositivo = sesiones_por_device.dispositivo
LEFT JOIN (
    -- Fecha de extracción más reciente para saber cuándo se actualizaron los datos
    SELECT MAX(extraction_date) AS extraction_date
    FROM `tu-proyecto-gcp.ecommerce_analytics.funnel_events`
) AS fechas ON TRUE
ORDER BY
    etapas.dispositivo,
    etapas.etapa_orden;


-- ─────────────────────────────────────────────────────────────────────────────
-- VISTA 2: v_channel_performance
-- Alimenta: tabla de rendimiento por canal de adquisición
-- ─────────────────────────────────────────────────────────────────────────────
/*
  ¿Qué hace esta vista?
  Agrega métricas de sesión y revenue por canal de adquisición y dispositivo.
  Calcula el revenue por sesión (RPS) como proxy de eficiencia del canal:
  un canal con pocas sesiones pero alto RPS puede tener mejor ROI que uno
  con mucho tráfico y bajo RPS.

  ¿Por qué incluir deviceCategory aquí?
  Porque la misma fuente de tráfico (ej: Paid Search) puede comportarse
  muy diferente en desktop vs mobile. Un anuncio de búsqueda optimizado
  para desktop puede tener 10% de conversión en desktop y 2% en mobile.
  Sin la segmentación, el 6% promedio ocultaría el problema.
*/

CREATE OR REPLACE VIEW `tu-proyecto-gcp.ecommerce_analytics.v_channel_performance` AS

SELECT
    sessionDefaultChannelGroup              AS canal,
    deviceCategory                          AS dispositivo,
    SUM(sessions)                           AS sesiones,
    SUM(totalUsers)                         AS usuarios,
    ROUND(AVG(bounceRate) * 100, 2)         AS bounce_rate_pct,
    ROUND(AVG(averageSessionDuration), 0)   AS duracion_sesion_seg,
    SUM(conversions)                        AS conversiones,
    ROUND(SUM(totalRevenue), 2)             AS revenue_usd,
    ROUND(
        SAFE_DIVIDE(SUM(conversions), SUM(sessions)) * 100,
        2
    )                                       AS tasa_conversion_pct,
    ROUND(
        SAFE_DIVIDE(SUM(totalRevenue), SUM(sessions)),
        2
    )                                       AS revenue_por_sesion,
    -- Share de revenue: cuánto aporta este canal al total
    ROUND(
        SAFE_DIVIDE(
            SUM(totalRevenue),
            SUM(SUM(totalRevenue)) OVER ()
        ) * 100,
        2
    )                                       AS revenue_share_pct,
    MAX(extraction_date)                    AS extraction_date
FROM `tu-proyecto-gcp.ecommerce_analytics.session_overview`
GROUP BY
    canal, dispositivo
ORDER BY
    revenue_usd DESC;


-- ─────────────────────────────────────────────────────────────────────────────
-- VISTA 3: v_daily_revenue
-- Alimenta: gráfico de tendencia temporal de revenue
-- ─────────────────────────────────────────────────────────────────────────────
/*
  ¿Qué hace esta vista?
  Expone la serie temporal de revenue con métricas derivadas:
  - revenue_7d_avg: promedio móvil de 7 días para suavizar la estacionalidad
    semanal (los fines de semana suelen tener más tráfico en retail)
  - revenue_vs_prev_day: variación porcentual día a día para detectar
    caídas bruscas (posible bug de tracking) o picos (campañas exitosas)

  ¿Por qué el promedio móvil de 7 días?
  El revenue de e-commerce tiene un patrón semanal fuerte: más compras
  el viernes/sábado, menos el lunes. Sin el promedio móvil, el gráfico
  diario parece muy volátil y dificulta ver la tendencia real.
  Con el promedio de 7 días, la tendencia subyacente es clara.
*/

CREATE OR REPLACE VIEW `tu-proyecto-gcp.ecommerce_analytics.v_daily_revenue` AS

WITH base AS (
    SELECT
        CAST(date AS DATE)              AS fecha,
        ROUND(totalRevenue, 2)          AS revenue,
        CAST(transactions AS INT64)     AS transacciones,
        ROUND(averagePurchaseRevenue, 2) AS ticket_promedio
    FROM `tu-proyecto-gcp.ecommerce_analytics.daily_revenue`
)

SELECT
    fecha,
    revenue,
    transacciones,
    ticket_promedio,
    -- Promedio móvil 7 días: suaviza la estacionalidad semanal
    ROUND(
        AVG(revenue) OVER (
            ORDER BY fecha
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ),
        2
    )                                   AS revenue_media_7d,
    -- Variación vs día anterior: para detectar anomalías
    ROUND(
        SAFE_DIVIDE(
            revenue - LAG(revenue) OVER (ORDER BY fecha),
            LAG(revenue) OVER (ORDER BY fecha)
        ) * 100,
        1
    )                                   AS variacion_dia_anterior_pct,
    -- Flag de anomalía: caída > 30% respecto al día anterior
    CASE
        WHEN SAFE_DIVIDE(
            revenue - LAG(revenue) OVER (ORDER BY fecha),
            LAG(revenue) OVER (ORDER BY fecha)
        ) < -0.30
        THEN TRUE
        ELSE FALSE
    END                                 AS posible_anomalia
FROM base
ORDER BY fecha;


-- ─────────────────────────────────────────────────────────────────────────────
-- VISTA 4: v_device_kpis
-- Alimenta: tarjetas de KPI comparativas mobile vs desktop
-- ─────────────────────────────────────────────────────────────────────────────
/*
  ¿Qué hace esta vista?
  Consolida las métricas clave del device_breakdown para comparar
  el comportamiento de mobile vs desktop vs tablet en una sola fila
  por dispositivo. Es la vista que soporta el insight principal del proyecto:
  la brecha de conversión entre dispositivos.

  ¿Por qué calcular el ratio aquí y no en Looker Studio?
  Looker Studio puede hacer cálculos entre campos, pero son frágiles:
  si el nombre de un campo cambia, el cálculo del dashboard se rompe.
  Con el ratio en la vista, el dashboard solo consume un campo calculado.
*/

CREATE OR REPLACE VIEW `tu-proyecto-gcp.ecommerce_analytics.v_device_kpis` AS

WITH metricas AS (
    SELECT
        deviceCategory                          AS dispositivo,
        SUM(sessions)                           AS sesiones,
        SUM(engagedSessions)                    AS sesiones_engaged,
        SUM(conversions)                        AS conversiones,
        ROUND(SUM(totalRevenue), 2)             AS revenue,
        ROUND(AVG(bounceRate) * 100, 2)         AS bounce_rate_pct,
        ROUND(AVG(conversion_rate), 2)          AS tasa_conversion_pct,
        ROUND(
            SAFE_DIVIDE(SUM(engagedSessions), SUM(sessions)) * 100,
            2
        )                                       AS tasa_engagement_pct,
        ROUND(
            SAFE_DIVIDE(SUM(totalRevenue), SUM(conversions)),
            2
        )                                       AS ticket_promedio
    FROM `tu-proyecto-gcp.ecommerce_analytics.device_breakdown`
    GROUP BY dispositivo
),

desktop_ref AS (
    -- Conversión de desktop como referencia para calcular brechas
    SELECT tasa_conversion_pct AS conv_desktop
    FROM metricas
    WHERE dispositivo = 'desktop'
)

SELECT
    metricas.*,
    ROUND(
        SAFE_DIVIDE(metricas.revenue, SUM(metricas.revenue) OVER ()) * 100,
        2
    )                                           AS revenue_share_pct,
    ROUND(
        SAFE_DIVIDE(desktop_ref.conv_desktop, NULLIF(metricas.tasa_conversion_pct, 0)),
        2
    )                                           AS ratio_vs_desktop
    -- ratio_vs_desktop = 1.0 para desktop, >1 indica que desktop convierte N veces más
FROM metricas
CROSS JOIN desktop_ref
ORDER BY revenue DESC;


-- ─────────────────────────────────────────────────────────────────────────────
-- VISTA 5: v_executive_summary
-- Alimenta: scorecard ejecutivo — una fila con los KPIs globales del período
-- ─────────────────────────────────────────────────────────────────────────────
/*
  ¿Qué hace esta vista?
  Produce una sola fila con todas las métricas del scorecard ejecutivo:
  revenue total, sesiones, tasa de conversión global, y los KPIs de
  la brecha mobile/desktop que es el hallazgo principal del proyecto.

  ¿Por qué una sola fila?
  Para las tarjetas de "Big Number" en Looker Studio (los KPIs grandes
  que aparecen en la parte superior del dashboard). Estas tarjetas
  esperan un valor escalar, no una tabla. Una vista que devuelve
  una sola fila es la fuente más simple y eficiente para ese tipo de chart.

  ¿Por qué incluir la fecha de extracción?
  Para mostrar en el dashboard cuándo fueron actualizados los datos.
  Un dashboard sin fecha de última actualización crea desconfianza:
  el usuario no sabe si está viendo datos de hoy o de hace tres meses.
*/

CREATE OR REPLACE VIEW `tu-proyecto-gcp.ecommerce_analytics.v_executive_summary` AS

WITH revenue_total AS (
    SELECT
        SUM(totalRevenue)    AS revenue,
        SUM(transactions)    AS transacciones,
        MIN(date)            AS fecha_inicio,
        MAX(date)            AS fecha_fin,
        MAX(extraction_date) AS ultima_extraccion
    FROM `tu-proyecto-gcp.ecommerce_analytics.daily_revenue`
),

sesiones_total AS (
    SELECT
        SUM(sessions)    AS sesiones,
        SUM(totalUsers)  AS usuarios
    FROM `tu-proyecto-gcp.ecommerce_analytics.session_overview`
),

conversion_por_device AS (
    SELECT
        MAX(CASE WHEN dispositivo = 'desktop' THEN tasa_conversion_pct END) AS conv_desktop_pct,
        MAX(CASE WHEN dispositivo = 'mobile'  THEN tasa_conversion_pct END) AS conv_mobile_pct
    FROM `tu-proyecto-gcp.ecommerce_analytics.v_device_kpis`
)

SELECT
    ROUND(revenue_total.revenue, 2)              AS revenue_total_usd,
    revenue_total.transacciones                  AS transacciones_totales,
    sesiones_total.sesiones                      AS sesiones_totales,
    sesiones_total.usuarios                      AS usuarios_totales,
    ROUND(
        SAFE_DIVIDE(
            revenue_total.transacciones,
            sesiones_total.sesiones
        ) * 100,
        2
    )                                            AS conversion_global_pct,
    ROUND(
        SAFE_DIVIDE(revenue_total.revenue, revenue_total.transacciones),
        2
    )                                            AS ticket_promedio_usd,
    conversion_por_device.conv_desktop_pct       AS conversion_desktop_pct,
    conversion_por_device.conv_mobile_pct        AS conversion_mobile_pct,
    ROUND(
        SAFE_DIVIDE(
            conversion_por_device.conv_desktop_pct,
            NULLIF(conversion_por_device.conv_mobile_pct, 0)
        ),
        1
    )                                            AS ratio_desktop_vs_mobile,
    revenue_total.fecha_inicio                   AS periodo_inicio,
    revenue_total.fecha_fin                      AS periodo_fin,
    revenue_total.ultima_extraccion              AS ultima_actualizacion
FROM revenue_total
CROSS JOIN sesiones_total
CROSS JOIN conversion_por_device;
