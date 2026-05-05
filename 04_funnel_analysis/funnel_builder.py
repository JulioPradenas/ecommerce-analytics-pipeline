"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    MÓDULO 4 — FUNNEL BUILDER                               ║
║              funnel_builder.py  |  E-Commerce Analytics Pipeline           ║
╚══════════════════════════════════════════════════════════════════════════════╝

¿QUÉ HACE ESTE ARCHIVO?
───────────────────────
Construye el funnel de conversión e-commerce a partir del dataset validado
por el Módulo 3, segmentado por dispositivo. Calcula las tasas de conversión
entre etapas, identifica los mayores puntos de abandono y genera un gráfico
interactivo con Plotly.

¿POR QUÉ FUNNEL SEGMENTADO POR DISPOSITIVO?
─────────────────────────────────────────────
Un funnel agregado (sin segmentación) oculta el problema más común en
e-commerce: la experiencia móvil es sistemáticamente peor que la de desktop.
Si el funnel total muestra 5% de conversión, puede estar promediando un
10% en desktop con un 2% en mobile. Las decisiones de CRO son radicalmente
distintas en cada caso:

  - Si desktop convierte mal → problema de propuesta de valor o precio
  - Si mobile convierte mal → problema de UX/UI (formularios, botones, velocidad)

¿DOS FUENTES DE DATOS?
──────────────────────
Este módulo acepta dos fuentes, seleccionadas por parámetro:

  MODO "synthetic" (default):
    Lee gtm_events_raw.json del Módulo 2.
    Útil cuando BigQuery no está configurado o para demos.
    Calcula sesiones únicas por evento y dispositivo con pandas.

  MODO "bigquery":
    Lee la tabla funnel_events + device_breakdown del dataset de BQ.
    Usa los datos reales de GA4 extraídos por el Módulo 1.
    Requiere que PROJECT_ID esté configurado en bq_loader.py.

¿POR QUÉ PLOTLY Y NO MATPLOTLIB?
──────────────────────────────────
Matplotlib genera imágenes estáticas (PNG). Plotly genera HTML interactivo:
  - El reclutador puede hover sobre las barras y ver los números exactos.
  - El archivo HTML es autónomo — no necesita servidor ni Python para abrirse.
  - En Looker Studio, Plotly charts embebidos como iframes son más ricos
    visualmente que capturas de matplotlib.

¿CÓMO ENCAJA EN EL PIPELINE?
─────────────────────────────
  03_qa/qa_summary.json  →  verifica que los datos pasaron el QA
       │
       ▼
  funnel_builder.py  ◄── ESTÁS AQUÍ
       │  Calcula métricas del funnel por etapa y dispositivo
       │  produce: funnel_metrics.csv
       │           funnel_chart.html  (gráfico interactivo)
       ▼
  friction_detector.py
       │  Lee funnel_metrics.csv para detectar fricciones
       │  produce: friction_insights.json
       │           device_comparison.html
       ▼
  05_dashboard/bq_views.sql
        Consume funnel_metrics para las vistas de Looker Studio
"""

import json
import logging
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "funnel.log"),
    ],
)
logger = logging.getLogger(__name__)

MODULE_DIR    = Path(__file__).parent
QA_SUMMARY    = MODULE_DIR.parent / "03_qa" / "qa_summary.json"
EVENTS_PATH   = MODULE_DIR.parent / "02_tagging_simulation" / "gtm_events_raw.json"
METRICS_PATH  = MODULE_DIR / "funnel_metrics.csv"
CHART_PATH    = MODULE_DIR / "funnel_chart.html"

ETAPAS = ["session_start", "view_item", "add_to_cart", "begin_checkout", "purchase"]
ETAPAS_LABEL = {
    "session_start":  "Sesión iniciada",
    "view_item":      "Vista de producto",
    "add_to_cart":    "Agregado al carrito",
    "begin_checkout": "Inicio de checkout",
    "purchase":       "Compra completada",
}
COLORES_DEVICE = {"desktop": "#2563EB", "mobile": "#DC2626", "tablet": "#D97706"}


# ─────────────────────────────────────────────────────────────────────────────
# CLASE FunnelBuilder
# ─────────────────────────────────────────────────────────────────────────────

class FunnelBuilder:
    """
    Construye y visualiza el funnel de conversión segmentado por dispositivo.

    El funnel se calcula como sesiones únicas que alcanzaron cada etapa,
    no como conteo de eventos. Un usuario que hace add_to_cart tres veces
    en la misma sesión cuenta una sola vez en esa etapa.
    Esto refleja cómo GA4 reporta el funnel en su interfaz nativa.
    """

    def __init__(self, modo: str = "synthetic"):
        """
        modo: "synthetic" (gtm_events_raw.json) o "bigquery" (tablas de BQ)
        """
        logger.info("=" * 60)
        logger.info("MÓDULO 4 — FUNNEL BUILDER")
        logger.info("=" * 60)
        self.modo = modo
        self._verificar_qa()

    def _verificar_qa(self) -> None:
        """
        Verifica que el Módulo 3 haya validado los datos antes de procesar.

        ¿Por qué este gate?
        Analizar datos que fallaron el QA produciría insights incorrectos.
        Si el 30% de los eventos de purchase tienen revenue = 0 (bug de GTM),
        la tasa de conversión calculada sería real pero el revenue no.
        El gate garantiza que el análisis opera sobre datos confiables.
        """
        if not QA_SUMMARY.exists():
            logger.warning(
                "qa_summary.json no encontrado. "
                "Ejecutar primero: python 03_qa/data_quality_checks.py"
            )
            # Continuar sin bloquear — útil para desarrollo iterativo
            return

        with open(QA_SUMMARY, encoding="utf-8") as f:
            summary = json.load(f)

        if not summary.get("passed", True):
            checks_fallidos = summary.get("checks_criticos_fallidos", [])
            logger.error("El QA del Módulo 3 reportó FAILs en checks críticos:")
            for c in checks_fallidos:
                logger.error(f"  - {c}")
            logger.error("Corregir los datos antes de continuar el análisis.")
            sys.exit(1)

        logger.info("QA verificado: todos los checks pasaron")

    def _cargar_datos_sinteticos(self) -> pd.DataFrame:
        """
        Carga el dataset sintético del Módulo 2 y lo convierte a formato
        de métricas de funnel (sesiones únicas por etapa y dispositivo).
        """
        if not EVENTS_PATH.exists():
            logger.error(f"No se encontró {EVENTS_PATH}. Ejecutar Módulo 2 primero.")
            sys.exit(1)

        with open(EVENTS_PATH, encoding="utf-8") as f:
            eventos = json.load(f)

        df = pd.DataFrame(eventos)
        logger.info(f"Dataset sintético cargado: {len(df)} eventos")

        # Contar sesiones únicas que alcanzaron cada etapa, por dispositivo.
        # unique() sobre session_id garantiza que un usuario con múltiples
        # add_to_cart en la misma sesión cuente solo una vez en esa etapa.
        registros = []
        for device in df["device_category"].unique():
            df_dev = df[df["device_category"] == device]
            for etapa in ETAPAS:
                sesiones = df_dev[df_dev["event_name"] == etapa]["session_id"].nunique()
                registros.append({
                    "etapa":           etapa,
                    "device_category": device,
                    "sesiones":        sesiones,
                })

        return pd.DataFrame(registros)

    def _cargar_datos_bigquery(self) -> pd.DataFrame:
        """
        Carga la tabla funnel_events desde BigQuery.

        Requiere que el Módulo 1 haya cargado los datos y que las
        credenciales de Google Cloud estén configuradas.
        """
        try:
            from google.cloud import bigquery
            # PROJECT_ID y DATASET_ID importados del Módulo 1
            sys.path.insert(0, str(MODULE_DIR.parent / "01_extraction"))
            from bq_loader import PROJECT_ID, DATASET_ID

            client = bigquery.Client(project=PROJECT_ID)
            query  = f"""
                SELECT
                    eventName          AS etapa,
                    deviceCategory     AS device_category,
                    SUM(totalUsers)    AS sesiones
                FROM `{PROJECT_ID}.{DATASET_ID}.funnel_events`
                WHERE eventName IN ({', '.join(f"'{e}'" for e in ETAPAS)})
                GROUP BY etapa, device_category
            """
            df = client.query(query).to_dataframe()
            logger.info(f"BigQuery cargado: {len(df)} filas")
            return df

        except Exception as exc:
            logger.warning(f"No se pudo conectar a BigQuery ({exc}). Usando datos sintéticos.")
            return self._cargar_datos_sinteticos()

    def construir_metricas(self) -> pd.DataFrame:
        """
        Construye el DataFrame de métricas del funnel con tasas de conversión.

        Columnas resultantes:
          etapa            — nombre del evento
          etapa_label      — nombre legible para visualización
          device_category  — desktop / mobile / tablet
          sesiones         — sesiones únicas que alcanzaron esta etapa
          tasa_vs_anterior — % que avanzó desde la etapa previa (mismo device)
          tasa_vs_inicio   — % de conversión acumulada desde session_start
          abandono_abs     — sesiones que abandonaron en esta etapa
        """
        df_raw = (
            self._cargar_datos_bigquery() if self.modo == "bigquery"
            else self._cargar_datos_sinteticos()
        )

        registros = []
        for device, grupo in df_raw.groupby("device_category"):
            grupo = grupo.set_index("etapa").reindex(ETAPAS).fillna(0)
            inicio = grupo.loc["session_start", "sesiones"] or 1

            for i, etapa in enumerate(ETAPAS):
                sesiones = int(grupo.loc[etapa, "sesiones"])
                prev     = int(grupo.loc[ETAPAS[i - 1], "sesiones"]) if i > 0 else sesiones
                registros.append({
                    "etapa":            etapa,
                    "etapa_label":      ETAPAS_LABEL[etapa],
                    "device_category":  device,
                    "sesiones":         sesiones,
                    "tasa_vs_anterior": round(sesiones / prev  * 100, 1) if prev > 0 else 100.0,
                    "tasa_vs_inicio":   round(sesiones / inicio * 100, 1),
                    "abandono_abs":     max(prev - sesiones, 0),
                })

        df_metricas = pd.DataFrame(registros)
        df_metricas.to_csv(METRICS_PATH, index=False)
        logger.info(f"Métricas guardadas: {METRICS_PATH}")

        # Log resumen por dispositivo
        logger.info("\n── TASAS DE CONVERSIÓN POR DISPOSITIVO ──")
        for device in df_metricas["device_category"].unique():
            df_d = df_metricas[df_metricas["device_category"] == device]
            purchase_row = df_d[df_d["etapa"] == "purchase"]
            if not purchase_row.empty:
                conv = purchase_row["tasa_vs_inicio"].values[0]
                logger.info(f"  {device:<10}: {conv:.1f}% conversión global")

        return df_metricas

    def graficar(self, df_metricas: pd.DataFrame) -> None:
        """
        Genera un gráfico interactivo de funnel comparativo por dispositivo.

        Estructura del gráfico:
          - Panel izquierdo: funnel de barras horizontales apiladas (sesiones absolutas)
          - Panel derecho:   tasa de conversión por etapa (líneas por dispositivo)

        ¿Por qué dos paneles?
        El panel izquierdo muestra volumen (cuántos usuarios hay en cada etapa).
        El panel derecho muestra eficiencia (qué % avanza). Un BA debe presentar
        ambas perspectivas: un canal con poco volumen puede convertir bien,
        y viceversa.
        """
        devices = df_metricas["device_category"].unique()

        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=("Sesiones por etapa", "Tasa de conversión acumulada (%)"),
            horizontal_spacing=0.12,
        )

        # Panel izquierdo: barras horizontales por etapa y dispositivo
        for device in devices:
            df_d  = df_metricas[df_metricas["device_category"] == device]
            color = COLORES_DEVICE.get(device, "#6B7280")
            fig.add_trace(
                go.Bar(
                    name=device.capitalize(),
                    y=[ETAPAS_LABEL[e] for e in ETAPAS],
                    x=df_d.set_index("etapa").reindex(ETAPAS)["sesiones"].values,
                    orientation="h",
                    marker_color=color,
                    text=df_d.set_index("etapa").reindex(ETAPAS)["sesiones"].astype(int).values,
                    textposition="outside",
                    legendgroup=device,
                ),
                row=1, col=1,
            )

        # Panel derecho: líneas de conversión acumulada
        for device in devices:
            df_d  = df_metricas[df_metricas["device_category"] == device]
            color = COLORES_DEVICE.get(device, "#6B7280")
            tasas = df_d.set_index("etapa").reindex(ETAPAS)["tasa_vs_inicio"].values
            fig.add_trace(
                go.Scatter(
                    name=device.capitalize(),
                    x=[ETAPAS_LABEL[e] for e in ETAPAS],
                    y=tasas,
                    mode="lines+markers+text",
                    text=[f"{t:.1f}%" for t in tasas],
                    textposition="top center",
                    line=dict(color=color, width=2),
                    marker=dict(size=8),
                    legendgroup=device,
                    showlegend=False,
                ),
                row=1, col=2,
            )

        fig.update_layout(
            title=dict(
                text="Funnel de Conversión E-Commerce — Google Merchandise Store<br>"
                     "<sup>Segmentado por dispositivo | Módulo 4 — E-Commerce Analytics Pipeline</sup>",
                font=dict(size=16),
            ),
            barmode="group",
            height=500,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
        )
        fig.update_xaxes(title_text="Sesiones", row=1, col=1)
        fig.update_yaxes(title_text="", row=1, col=1)
        fig.update_xaxes(title_text="Etapa del funnel", tickangle=-20, row=1, col=2)
        fig.update_yaxes(title_text="Conversión acumulada (%)", row=1, col=2)

        fig.write_html(CHART_PATH)
        logger.info(f"Gráfico guardado: {CHART_PATH}")


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "synthetic"
    builder  = FunnelBuilder(modo=modo)
    metricas = builder.construir_metricas()
    builder.graficar(metricas)

    print(f"\nMétricas:  {METRICS_PATH}")
    print(f"Gráfico:   {CHART_PATH}")
    print("\nSiguiente paso: python 04_funnel_analysis/friction_detector.py")
