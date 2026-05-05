"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    MÓDULO 4 — FRICTION DETECTOR                            ║
║              friction_detector.py  |  E-Commerce Analytics Pipeline        ║
╚══════════════════════════════════════════════════════════════════════════════╝

¿QUÉ HACE ESTE ARCHIVO?
───────────────────────
Lee las métricas de funnel calculadas por funnel_builder.py y detecta
automáticamente los puntos de fricción: etapas donde la caída del funnel
es significativamente mayor en mobile que en desktop.

Produce dos outputs:
  - friction_insights.json: hallazgos estructurados para el dashboard
  - device_comparison.html: gráfico comparativo de brechas mobile/desktop

¿QUÉ ES UN PUNTO DE FRICCIÓN EN ANALYTICS?
────────────────────────────────────────────
Una fricción es una etapa del funnel donde la conversión cae más de lo
esperado. Hay dos tipos:

  1. FRICCIÓN ABSOLUTA: muchos usuarios abandonan en una etapa
     (ej: solo el 22% avanza de view_item a add_to_cart)

  2. FRICCIÓN RELATIVA: la caída es significativamente mayor en un
     segmento específico versus otro
     (ej: mobile convierte 3.2x menos que desktop en checkout)

El detector busca fricciones RELATIVAS entre dispositivos porque son
las más accionables: indican un problema específico de UX móvil que
puede solucionarse sin cambiar la propuesta de valor del producto.

¿POR QUÉ AUTOMATIZAR LA DETECCIÓN DE FRICCIONES?
─────────────────────────────────────────────────
En un equipo de analytics real, el BA no puede revisar el funnel
manualmente cada día buscando cambios. Un detector automático:

  1. Alerta cuando una brecha mobile/desktop se amplía (ej: una
     actualización del sitio empeoró el checkout en móvil)
  2. Documenta el hallazgo con números exactos, listos para un
     informe ejecutivo o una presentación al equipo de producto
  3. Prioriza las fricciones por impacto potencial de revenue,
     que es el lenguaje que entiende la dirección del negocio

¿CÓMO ENCAJA EN EL PIPELINE?
─────────────────────────────
  04_funnel_analysis/funnel_metrics.csv  ◄── input de funnel_builder.py
       │
       ▼
  friction_detector.py  ◄── ESTÁS AQUÍ
       │  Calcula brechas mobile vs desktop por etapa
       │  Estima impacto de revenue de cada fricción
       │  produce: friction_insights.json
       │           device_comparison.html
       ▼
  05_dashboard/bq_views.sql
        Consume friction_insights para los KPIs del dashboard
"""

import json
import logging
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

MODULE_DIR      = Path(__file__).parent
METRICS_PATH    = MODULE_DIR / "funnel_metrics.csv"
INSIGHTS_PATH   = MODULE_DIR / "friction_insights.json"
COMPARISON_PATH = MODULE_DIR / "device_comparison.html"

ETAPAS = ["session_start", "view_item", "add_to_cart", "begin_checkout", "purchase"]
TRANSICIONES = [
    ("session_start",  "view_item",      "Sesión → Vista de producto"),
    ("view_item",      "add_to_cart",    "Vista → Agregar al carrito"),
    ("add_to_cart",    "begin_checkout", "Carrito → Inicio de checkout"),
    ("begin_checkout", "purchase",       "Checkout → Compra completada"),
]
COLORES_DEVICE = {"desktop": "#2563EB", "mobile": "#DC2626", "tablet": "#D97706"}


# ─────────────────────────────────────────────────────────────────────────────
# CLASE FrictionDetector
# ─────────────────────────────────────────────────────────────────────────────

class FrictionDetector:
    """
    Detecta fricciones en el funnel comparando mobile vs desktop,
    las cuantifica en términos de sesiones perdidas y revenue potencial,
    y genera visualizaciones e insights estructurados.
    """

    def __init__(self):
        logger.info("=" * 60)
        logger.info("MÓDULO 4 — FRICTION DETECTOR")
        logger.info("=" * 60)

        if not METRICS_PATH.exists():
            raise FileNotFoundError(
                f"No se encontró {METRICS_PATH}. "
                "Ejecutar primero: python 04_funnel_analysis/funnel_builder.py"
            )

        self.df = pd.read_csv(METRICS_PATH)
        logger.info(f"Métricas cargadas: {len(self.df)} filas | {self.df['device_category'].nunique()} dispositivos")

    def _tasa(self, device: str, etapa: str) -> float:
        """Retorna la tasa_vs_anterior para un dispositivo y etapa dados."""
        fila = self.df[
            (self.df["device_category"] == device) &
            (self.df["etapa"] == etapa)
        ]
        return float(fila["tasa_vs_anterior"].values[0]) if not fila.empty else 0.0

    def _sesiones(self, device: str, etapa: str) -> int:
        """Retorna las sesiones absolutas para un dispositivo y etapa dados."""
        fila = self.df[
            (self.df["device_category"] == device) &
            (self.df["etapa"] == etapa)
        ]
        return int(fila["sesiones"].values[0]) if not fila.empty else 0

    def detectar_fricciones(self) -> list[dict]:
        """
        Identifica las transiciones del funnel donde la brecha mobile/desktop
        es más pronunciada.

        Métrica de fricción usada: "ratio de conversión desktop/mobile"
        Un ratio de 2.0 significa que desktop convierte al doble que mobile
        en esa transición específica.

        ¿Por qué ratio y no diferencia absoluta?
        Si desktop convierte 60% y mobile 58%, la diferencia es pequeña
        aunque el ratio sea ~1.03. Pero si desktop convierte 8% y mobile 4%,
        la diferencia absoluta es pequeña pero el ratio es 2.0 — mobile tiene
        el doble de abandono. El ratio captura la severidad relativa.
        """
        fricciones = []

        for etapa_origen, etapa_destino, label in TRANSICIONES:
            tasa_desktop = self._tasa("desktop", etapa_destino)
            tasa_mobile  = self._tasa("mobile",  etapa_destino)

            if tasa_mobile == 0:
                continue

            ratio           = round(tasa_desktop / tasa_mobile, 2)
            brecha_puntos   = round(tasa_desktop - tasa_mobile, 1)

            # Sesiones móviles que están en la etapa anterior (potential)
            sesiones_mobile_prev = self._sesiones("mobile", etapa_origen)
            # Si mobile tuviera la misma tasa que desktop, cuántas más avanzarían
            sesiones_mobile_reales  = self._sesiones("mobile", etapa_destino)
            sesiones_mobile_potencial = int(sesiones_mobile_prev * tasa_desktop / 100)
            sesiones_recuperables    = max(sesiones_mobile_potencial - sesiones_mobile_reales, 0)

            # Impacto estimado de revenue (ticket promedio aproximado)
            # ¿Por qué $45? Promedio del catálogo de productos simulado.
            # En un proyecto real se calcularía el AOV real desde BigQuery.
            ticket_promedio = 45.0
            revenue_potencial = round(sesiones_recuperables * ticket_promedio, 2)

            fricciones.append({
                "transicion":             label,
                "etapa_destino":          etapa_destino,
                "tasa_desktop":           tasa_desktop,
                "tasa_mobile":            tasa_mobile,
                "ratio_desktop_mobile":   ratio,
                "brecha_porcentual":      brecha_puntos,
                "sesiones_mobile_previas": sesiones_mobile_prev,
                "sesiones_recuperables":  sesiones_recuperables,
                "revenue_potencial_usd":  revenue_potencial,
                "prioridad":              "ALTA" if ratio >= 1.5 else "MEDIA" if ratio >= 1.2 else "BAJA",
            })

        # Ordenar por impacto de revenue (mayor primero)
        fricciones.sort(key=lambda x: x["revenue_potencial_usd"], reverse=True)
        return fricciones

    def generar_insights(self, fricciones: list[dict]) -> dict:
        """
        Construye el objeto de insights estructurado que el dashboard consumirá.

        ¿Por qué estructurar los insights en JSON?
        Para que el Módulo 5 (SQL + Looker Studio) pueda acceder a los
        hallazgos sin re-ejecutar el análisis. El dashboard puede mostrar
        el insight principal directamente desde este JSON como texto fijo,
        y las métricas como KPIs actualizables.

        El campo 'hallazgo_principal' replica el formato de los insights
        que un BA presentaría en un informe ejecutivo: número concreto,
        segmento afectado, comparación con benchmark.
        """
        friccion_principal = fricciones[0] if fricciones else {}

        # Conversión global por dispositivo
        conv_global = {}
        for device in self.df["device_category"].unique():
            fila = self.df[
                (self.df["device_category"] == device) &
                (self.df["etapa"] == "purchase")
            ]
            if not fila.empty:
                conv_global[device] = float(fila["tasa_vs_inicio"].values[0])

        conv_desktop = conv_global.get("desktop", 0)
        conv_mobile  = conv_global.get("mobile",  0)
        ratio_global = round(conv_desktop / conv_mobile, 1) if conv_mobile > 0 else 0

        # Abandono en la transición principal
        tasa_avance_mobile = friccion_principal.get("tasa_mobile", 0)
        abandono_mobile    = round(100 - tasa_avance_mobile, 1)

        insights = {
            "generado_en":        pd.Timestamp.utcnow().isoformat() + "Z",
            "fuente_datos":       str(METRICS_PATH),
            "conversion_global": {
                device: f"{tasa:.1f}%"
                for device, tasa in conv_global.items()
            },
            "ratio_conversion_desktop_vs_mobile": ratio_global,
            "hallazgo_principal": (
                f"El {abandono_mobile:.0f}% del abandono en el funnel de mobile ocurre "
                f"en la transición '{friccion_principal.get('transicion', '')}', "
                f"con una tasa de conversión {ratio_global}× menor que en desktop."
            ),
            "fricciones_detectadas": fricciones,
            "recomendaciones": self._generar_recomendaciones(fricciones),
        }

        with open(INSIGHTS_PATH, "w", encoding="utf-8") as f:
            json.dump(insights, f, indent=2, ensure_ascii=False)
        logger.info(f"Insights guardados: {INSIGHTS_PATH}")
        logger.info(f"Hallazgo principal: {insights['hallazgo_principal']}")

        return insights

    def _generar_recomendaciones(self, fricciones: list[dict]) -> list[dict]:
        """
        Mapea cada fricción detectada a una recomendación de CRO accionable.

        Las recomendaciones son genéricas pero específicas al tipo de fricción.
        En un engagement real, se validarían con heatmaps (Hotjar), session
        recordings y tests de usabilidad antes de implementar.
        """
        RECOMENDACIONES_POR_ETAPA = {
            "view_item": {
                "hipotesis": "Imágenes de producto de baja calidad o información insuficiente en mobile",
                "acciones": [
                    "Optimizar imágenes para carga rápida en mobile (WebP, lazy loading)",
                    "Agregar reseñas de productos visible sin scroll en mobile",
                    "Verificar que el botón 'Add to Cart' sea visible above the fold",
                ],
            },
            "add_to_cart": {
                "hipotesis": "Fricción en el proceso de selección de producto o botón poco visible",
                "acciones": [
                    "Hacer el botón 'Add to Cart' sticky (fijo al hacer scroll) en mobile",
                    "Reducir pasos para seleccionar variantes (talla, color)",
                    "Agregar indicador de stock limitado para crear urgencia",
                ],
            },
            "begin_checkout": {
                "hipotesis": "Formulario de checkout no optimizado para mobile o proceso demasiado largo",
                "acciones": [
                    "Implementar checkout de una página (one-page checkout) en mobile",
                    "Agregar Apple Pay / Google Pay para eliminar ingreso manual de tarjeta",
                    "Activar autocompletado de dirección con Google Places API",
                    "Mostrar barra de progreso de checkout para reducir abandono por incertidumbre",
                ],
            },
            "purchase": {
                "hipotesis": "Dudas de seguridad o errores técnicos en el paso final de pago",
                "acciones": [
                    "Agregar sellos de seguridad y encriptación visibles en mobile",
                    "Verificar que el teclado numérico se active automáticamente en campos de tarjeta",
                    "Implementar guardado de carrito para recuperación por email",
                ],
            },
        }

        result = []
        for f in fricciones:
            etapa  = f.get("etapa_destino", "")
            config = RECOMENDACIONES_POR_ETAPA.get(etapa, {})
            result.append({
                "transicion":        f["transicion"],
                "prioridad":         f["prioridad"],
                "revenue_potencial": f"${f['revenue_potencial_usd']:,.0f}",
                "hipotesis":         config.get("hipotesis", "Analizar con heatmaps y session recordings"),
                "acciones":          config.get("acciones", []),
            })
        return result

    def graficar_comparacion(self, fricciones: list[dict]) -> None:
        """
        Gráfico de barras agrupadas: tasa de conversión por transición y dispositivo.
        Resalta visualmente la brecha mobile/desktop en cada paso del funnel.
        """
        transiciones = [f["transicion"] for f in fricciones]
        tasas_desktop = [f["tasa_desktop"] for f in fricciones]
        tasas_mobile  = [f["tasa_mobile"]  for f in fricciones]
        ratios        = [f["ratio_desktop_mobile"] for f in fricciones]

        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=(
                "Tasa de conversión por transición (desktop vs mobile)",
                "Ratio desktop/mobile — cuántas veces más convierte desktop",
            ),
            vertical_spacing=0.18,
            row_heights=[0.65, 0.35],
        )

        # Panel superior: barras agrupadas
        fig.add_trace(go.Bar(
            name="Desktop", x=transiciones, y=tasas_desktop,
            marker_color=COLORES_DEVICE["desktop"],
            text=[f"{t:.1f}%" for t in tasas_desktop],
            textposition="outside",
        ), row=1, col=1)

        fig.add_trace(go.Bar(
            name="Mobile", x=transiciones, y=tasas_mobile,
            marker_color=COLORES_DEVICE["mobile"],
            text=[f"{t:.1f}%" for t in tasas_mobile],
            textposition="outside",
        ), row=1, col=1)

        # Panel inferior: ratio como barras de calor
        colores_ratio = [
            "#DC2626" if r >= 1.5 else "#D97706" if r >= 1.2 else "#16A34A"
            for r in ratios
        ]
        fig.add_trace(go.Bar(
            name="Ratio D/M", x=transiciones, y=ratios,
            marker_color=colores_ratio,
            text=[f"{r:.1f}×" for r in ratios],
            textposition="outside",
            showlegend=False,
        ), row=2, col=1)

        # Línea de referencia: ratio = 1 (sin fricción)
        fig.add_hline(
            y=1.0, line_dash="dash", line_color="gray",
            annotation_text="Sin fricción (ratio = 1)", row=2, col=1,
        )

        fig.update_layout(
            title=dict(
                text="Análisis de Fricción Mobile vs Desktop — E-Commerce Funnel<br>"
                     "<sup>Rojo = fricción alta (ratio ≥ 1.5) | Naranja = media | Verde = baja</sup>",
                font=dict(size=15),
            ),
            barmode="group",
            height=650,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=-0.12, xanchor="center", x=0.5),
        )
        fig.update_yaxes(title_text="Tasa de avance (%)", row=1, col=1)
        fig.update_yaxes(title_text="Ratio D/M", row=2, col=1)

        fig.write_html(COMPARISON_PATH)
        logger.info(f"Gráfico de comparación guardado: {COMPARISON_PATH}")


if __name__ == "__main__":
    detector   = FrictionDetector()
    fricciones = detector.detectar_fricciones()
    insights   = detector.generar_insights(fricciones)
    detector.graficar_comparacion(fricciones)

    print(f"\nFricciones detectadas: {len(fricciones)}")
    for f in fricciones:
        print(f"  [{f['prioridad']}] {f['transicion']} — ratio {f['ratio_desktop_mobile']}× — ${f['revenue_potencial_usd']:,.0f} potencial")

    print(f"\nInsights:   {INSIGHTS_PATH}")
    print(f"Gráfico:    {COMPARISON_PATH}")
    print("\nSiguiente paso: revisar 05_dashboard/bq_views.sql")
