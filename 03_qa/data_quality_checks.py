"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                      MÓDULO 3 — DATA QUALITY CHECKS                        ║
║            data_quality_checks.py  |  E-Commerce Analytics Pipeline        ║
╚══════════════════════════════════════════════════════════════════════════════╝

¿QUÉ HACE ESTE ARCHIVO?
───────────────────────
Valida automáticamente la calidad del dataset sintético generado por el
Módulo 2 (gtm_events_raw.json). Detecta problemas que en producción
indicarían bugs en la implementación de GTM: campos nulos, tipos incorrectos,
violaciones de reglas de negocio y anomalías en el orden del funnel.

¿POR QUÉ QA AUTOMATIZADO Y NO REVISAR LOS DATOS MANUALMENTE?
─────────────────────────────────────────────────────────────
En un e-commerce real, el pipeline corre diariamente. Revisar manualmente
miles de eventos cada día es inviable. El QA automatizado:

  1. Detecta regresiones: si el evento 'purchase' deja de llegar con
     transaction_id, el pipeline lo detecta en la siguiente ejecución.
  2. Documenta los contratos de datos: las expectativas son la versión
     ejecutable del tracking plan. Si el código pasa el QA, los datos
     cumplen el contrato.
  3. Habilita confianza en el dashboard: un BA que entrega datos validados
     automáticamente es más valioso que uno que entrega datos "a ojo".

¿POR QUÉ GREAT-EXPECTATIONS?
─────────────────────────────
great-expectations es el estándar de facto para QA de datos en Python:
  - Vocabulario declarativo: expect_column_values_to_not_be_null() describe
    QUÉ se espera, no CÓMO verificarlo.
  - Reporte reproducible: los resultados son objetos estructurados, no prints.
  - Integrable con pipelines: retorna True/False, usable en Airflow, CI/CD.
  - Documentación automática: puede generar "Data Docs" en HTML.

¿DOS NIVELES DE VALIDACIÓN?
────────────────────────────
Este módulo opera en dos niveles complementarios:

  NIVEL 1 — Column Checks (great-expectations):
    Valida columna por columna dentro de cada tipo de evento.
    Ejemplos: price > 0, currency = USD, device_category en {desktop, mobile, tablet}
    → Detecta errores en la implementación de parámetros individuales.

  NIVEL 2 — Cross-Event Checks (pandas):
    Valida relaciones entre eventos de una misma sesión.
    Ejemplos: timestamps en orden, purchase solo si hubo begin_checkout previo
    → Detecta bugs en la lógica del funnel (eventos disparados fuera de orden).
    great-expectations no maneja esta clase de validaciones multi-fila
    porque opera sobre columnas, no sobre secuencias de eventos.

¿CÓMO ENCAJA EN EL PIPELINE?
─────────────────────────────
  02_tagging_simulation/
       │  gtm_events_raw.json  (dataset sintético)
       │  tag_schema.json      (especificación de eventos)
       ▼
  data_quality_checks.py  ◄── ESTÁS AQUÍ
       │  Nivel 1: column checks con great-expectations
       │  Nivel 2: cross-event checks con pandas
       │  produce: qa_report.csv   (detalle por check)
       │           qa_summary.json (resumen ejecutivo)
       ▼
  04_funnel_analysis/funnel_builder.py
       │  Solo procesa si el QA pasó (lee qa_summary.json)
       ▼
  05_dashboard/
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import great_expectations as ge
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "qa.log"),
    ],
)
logger = logging.getLogger(__name__)

# Rutas relativas al archivo — independiente del directorio de ejecución
MODULE_DIR   = Path(__file__).parent
EVENTS_PATH  = MODULE_DIR.parent / "02_tagging_simulation" / "gtm_events_raw.json"
SCHEMA_PATH  = MODULE_DIR.parent / "02_tagging_simulation" / "tag_schema.json"
REPORT_PATH  = MODULE_DIR / "qa_report.csv"
SUMMARY_PATH = MODULE_DIR / "qa_summary.json"

EVENTOS_VALIDOS = ["session_start", "view_item", "add_to_cart", "begin_checkout", "purchase"]
DEVICES_VALIDOS = ["desktop", "mobile", "tablet"]


# ─────────────────────────────────────────────────────────────────────────────
# CLASE QAChecker
# ─────────────────────────────────────────────────────────────────────────────

class QAChecker:
    """
    Orquesta los dos niveles de validación y consolida los resultados.

    Diseño:
      - _column_checks():      great-expectations, un check por expectation
      - _cross_event_checks(): pandas, un check por regla de negocio
      - generar_reporte():     agrega resultados y escribe archivos de salida
    """

    def __init__(self):
        logger.info("=" * 60)
        logger.info("MÓDULO 3 — QA DE DATOS")
        logger.info("=" * 60)

        # Cargar dataset sintético
        if not EVENTS_PATH.exists():
            logger.error(
                f"No se encontró {EVENTS_PATH}. "
                "Ejecutar primero: python 02_tagging_simulation/gtm_events_simulator.py"
            )
            sys.exit(1)

        with open(EVENTS_PATH, encoding="utf-8") as f:
            eventos = json.load(f)

        self.df = pd.DataFrame(eventos)
        logger.info(f"Dataset cargado: {len(self.df)} eventos | {self.df['event_name'].nunique()} tipos")

        # Cargar schema para referencia (qa_checks documentados)
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            raw_schema = json.load(f)
        self.schema = {ev["event_name"]: ev for ev in raw_schema["eventos"]}

        self.resultados: list[dict] = []

    def _registrar(self, nivel: str, check: str, evento: str,
                   passed: bool, detalle: str = "") -> None:
        """
        Registra el resultado de un check individual.

        Todos los checks pasan por aquí para garantizar estructura uniforme
        en el reporte final. Un check = una fila en qa_report.csv.
        """
        estado = "PASS" if passed else "FAIL"
        if not passed:
            logger.warning(f"[{estado}] {nivel} | {evento} | {check} | {detalle}")
        self.resultados.append({
            "nivel":   nivel,
            "evento":  evento,
            "check":   check,
            "estado":  estado,
            "detalle": detalle,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # NIVEL 1: COLUMN CHECKS CON GREAT-EXPECTATIONS
    # ─────────────────────────────────────────────────────────────────────────

    def _column_checks(self) -> None:
        """
        Validaciones de columna usando great-expectations sobre el dataset completo
        y sobre subsets por tipo de evento.

        ¿Por qué ge.from_pandas()?
        Convierte un DataFrame en un PandasDataset de GE, que expone los métodos
        expect_*. Cada expect_* retorna un dict con 'success' (bool) y estadísticas
        de cuántos valores fallaron — sin necesidad de iterar manualmente.

        ¿Por qué no usar el DataContext completo de GE?
        El DataContext requiere configurar un proyecto GE con directorios, stores
        y checkpoints. Para un script standalone de portafolio, ge.from_pandas()
        demuestra el conocimiento de la librería con menos overhead operativo.
        """
        logger.info("── Nivel 1: Column Checks (great-expectations) ──")
        df_ge = ge.from_pandas(self.df)

        # ── Checks sobre el dataset completo ──────────────────────────────

        # event_name debe ser uno de los 5 eventos del funnel
        r = df_ge.expect_column_values_to_be_in_set("event_name", EVENTOS_VALIDOS)
        self._registrar(
            "column", "event_name in set válido", "todos",
            r["success"],
            f"{r['result'].get('unexpected_count', 0)} valores inesperados"
        )

        # session_id nunca debe ser null
        r = df_ge.expect_column_values_to_not_be_null("session_id")
        self._registrar(
            "column", "session_id not null", "todos",
            r["success"],
            f"{r['result'].get('unexpected_count', 0)} nulls"
        )

        # user_pseudo_id nunca debe ser null
        r = df_ge.expect_column_values_to_not_be_null("user_pseudo_id")
        self._registrar(
            "column", "user_pseudo_id not null", "todos",
            r["success"],
            f"{r['result'].get('unexpected_count', 0)} nulls"
        )

        # timestamp_ms debe ser numérico positivo
        r = df_ge.expect_column_values_to_not_be_null("timestamp_ms")
        self._registrar(
            "column", "timestamp_ms not null", "todos",
            r["success"],
            f"{r['result'].get('unexpected_count', 0)} nulls"
        )

        # device_category debe ser uno de los tres valores válidos
        r = df_ge.expect_column_values_to_be_in_set("device_category", DEVICES_VALIDOS)
        self._registrar(
            "column", "device_category in {desktop, mobile, tablet}", "todos",
            r["success"],
            f"{r['result'].get('unexpected_count', 0)} valores inesperados"
        )

        # ── Checks por tipo de evento ──────────────────────────────────────

        # view_item: price debe ser positivo
        df_view = self.df[self.df["event_name"] == "view_item"].copy()
        if not df_view.empty:
            df_view["price"] = pd.to_numeric(df_view["price"], errors="coerce")
            ge_view = ge.from_pandas(df_view)
            r = ge_view.expect_column_values_to_be_between("price", min_value=0.01)
            self._registrar(
                "column", "view_item: price > 0", "view_item",
                r["success"],
                f"{r['result'].get('unexpected_count', 0)} eventos con price <= 0"
            )

            # currency debe ser USD
            r = ge_view.expect_column_values_to_be_in_set("currency", ["USD"])
            self._registrar(
                "column", "view_item: currency = USD", "view_item",
                r["success"],
                f"{r['result'].get('unexpected_count', 0)} eventos con currency != USD"
            )

        # add_to_cart: quantity >= 1
        df_cart = self.df[self.df["event_name"] == "add_to_cart"].copy()
        if not df_cart.empty:
            df_cart["quantity"] = pd.to_numeric(df_cart["quantity"], errors="coerce")
            ge_cart = ge.from_pandas(df_cart)
            r = ge_cart.expect_column_values_to_be_between("quantity", min_value=1)
            self._registrar(
                "column", "add_to_cart: quantity >= 1", "add_to_cart",
                r["success"],
                f"{r['result'].get('unexpected_count', 0)} eventos con quantity < 1"
            )

        # begin_checkout: cart_value > 0
        df_checkout = self.df[self.df["event_name"] == "begin_checkout"].copy()
        if not df_checkout.empty:
            df_checkout["cart_value"] = pd.to_numeric(df_checkout["cart_value"], errors="coerce")
            ge_checkout = ge.from_pandas(df_checkout)
            r = ge_checkout.expect_column_values_to_be_between("cart_value", min_value=0.01)
            self._registrar(
                "column", "begin_checkout: cart_value > 0", "begin_checkout",
                r["success"],
                f"{r['result'].get('unexpected_count', 0)} eventos con cart_value <= 0"
            )

        # purchase: revenue > 0
        df_purchase = self.df[self.df["event_name"] == "purchase"].copy()
        if not df_purchase.empty:
            df_purchase["revenue"] = pd.to_numeric(df_purchase["revenue"], errors="coerce")
            ge_purchase = ge.from_pandas(df_purchase)
            r = ge_purchase.expect_column_values_to_be_between("revenue", min_value=0.01)
            self._registrar(
                "column", "purchase: revenue > 0", "purchase",
                r["success"],
                f"{r['result'].get('unexpected_count', 0)} eventos con revenue <= 0"
            )

            # transaction_id no debe ser null
            r = ge_purchase.expect_column_values_to_not_be_null("transaction_id")
            self._registrar(
                "column", "purchase: transaction_id not null", "purchase",
                r["success"],
                f"{r['result'].get('unexpected_count', 0)} nulls"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # NIVEL 2: CROSS-EVENT CHECKS CON PANDAS
    # ─────────────────────────────────────────────────────────────────────────

    def _cross_event_checks(self) -> None:
        """
        Validaciones que requieren comparar múltiples eventos dentro de una sesión.

        great-expectations opera sobre columnas de un DataFrame plano.
        No puede comparar valores entre filas de distintos eventos en la misma
        sesión (ej: verificar que el timestamp de purchase sea mayor al de
        begin_checkout). Para eso usamos pandas con groupby + apply.

        Estas validaciones replican exactamente los qa_checks definidos en
        tag_schema.json que involucran más de un evento.
        """
        logger.info("── Nivel 2: Cross-Event Checks (pandas) ──")

        df = self.df.copy()
        df["timestamp_ms"] = pd.to_numeric(df["timestamp_ms"], errors="coerce")

        # ── Check 1: transaction_id único en purchase ──────────────────────
        # Si aparece duplicado, hay doble conteo de revenue en el dashboard.
        # En producción esto ocurre cuando la página de confirmación se recarga
        # y GTM dispara el evento 'purchase' dos veces.
        df_purchase = df[df["event_name"] == "purchase"]
        ids = df_purchase["transaction_id"].dropna()
        duplicados = ids[ids.duplicated()].nunique()
        self._registrar(
            "cross_event", "purchase: transaction_id único", "purchase",
            duplicados == 0,
            f"{duplicados} transaction_id(s) duplicados"
        )

        # ── Check 2: orden de timestamps dentro de cada sesión ─────────────
        # En un funnel correcto: ts(session_start) < ts(view_item) < ts(add_to_cart)
        # < ts(begin_checkout) < ts(purchase). Si el orden está invertido,
        # hay un bug en el clock del cliente o en la implementación del dataLayer.
        orden_esperado = {ev: i for i, ev in enumerate(EVENTOS_VALIDOS)}
        sesiones_con_error = 0

        for session_id, grupo in df.groupby("session_id"):
            grupo_ord = grupo.sort_values("timestamp_ms")
            eventos_sesion = grupo_ord["event_name"].tolist()
            posiciones = [orden_esperado.get(e, -1) for e in eventos_sesion]
            if posiciones != sorted(posiciones):
                sesiones_con_error += 1

        self._registrar(
            "cross_event", "timestamps en orden lógico por sesión", "todos",
            sesiones_con_error == 0,
            f"{sesiones_con_error} sesiones con orden incorrecto"
        )

        # ── Check 3: purchase solo si existe begin_checkout previo ─────────
        # Un purchase sin begin_checkout previo indica que GTM está disparando
        # el evento en la página incorrecta, o que el trigger está mal configurado.
        sesiones_purchase    = set(df[df["event_name"] == "purchase"]["session_id"])
        sesiones_checkout    = set(df[df["event_name"] == "begin_checkout"]["session_id"])
        purchase_sin_checkout = sesiones_purchase - sesiones_checkout
        self._registrar(
            "cross_event", "purchase tiene begin_checkout previo", "purchase",
            len(purchase_sin_checkout) == 0,
            f"{len(purchase_sin_checkout)} sesiones con purchase sin checkout previo"
        )

        # ── Check 4: begin_checkout solo si existe add_to_cart previo ───────
        sesiones_cart        = set(df[df["event_name"] == "add_to_cart"]["session_id"])
        sesiones_checkout_all = set(df[df["event_name"] == "begin_checkout"]["session_id"])
        checkout_sin_cart    = sesiones_checkout_all - sesiones_cart
        self._registrar(
            "cross_event", "begin_checkout tiene add_to_cart previo", "begin_checkout",
            len(checkout_sin_cart) == 0,
            f"{len(checkout_sin_cart)} sesiones con checkout sin add_to_cart previo"
        )

        # ── Check 5: revenue = cart_value + shipping + tax ─────────────────
        # En producción, una discrepancia aquí indica que el tag de GTM está
        # calculando revenue incorrectamente (ej: usando el precio sin impuestos).
        df_p = df[df["event_name"] == "purchase"].copy()
        for col in ["revenue", "cart_value", "shipping", "tax"]:
            df_p[col] = pd.to_numeric(df_p[col], errors="coerce").fillna(0)

        df_p["revenue_esperado"] = (df_p["cart_value"] + df_p["shipping"] + df_p["tax"]).round(2)
        df_p["revenue_real"]     = df_p["revenue"].round(2)
        discrepancias = (df_p["revenue_real"] != df_p["revenue_esperado"]).sum()
        self._registrar(
            "cross_event", "purchase: revenue = cart_value + shipping + tax", "purchase",
            discrepancias == 0,
            f"{discrepancias} eventos con revenue incorrecto"
        )

        # ── Check 6: cobertura mínima del funnel ──────────────────────────
        # Verifica que el dataset tiene al menos un evento de cada tipo.
        # Si falta un tipo de evento, el análisis del Módulo 4 será incompleto.
        eventos_presentes = set(df["event_name"].unique())
        eventos_faltantes = set(EVENTOS_VALIDOS) - eventos_presentes
        self._registrar(
            "cross_event", "todos los eventos del funnel presentes", "todos",
            len(eventos_faltantes) == 0,
            f"Eventos faltantes: {eventos_faltantes}" if eventos_faltantes else ""
        )

    # ─────────────────────────────────────────────────────────────────────────
    # GENERACIÓN DE REPORTE
    # ─────────────────────────────────────────────────────────────────────────

    def generar_reporte(self) -> dict:
        """
        Ejecuta ambos niveles de validación y persiste los resultados.

        Outputs:
          qa_report.csv   — detalle fila por fila de cada check
          qa_summary.json — resumen ejecutivo: total PASS/FAIL por nivel

        ¿Por qué dos formatos de output?
          - CSV: para el Módulo 4, que puede filtrar los checks fallidos
            y omitir el análisis si hay problemas críticos.
          - JSON: para integración con pipelines (Airflow, GitHub Actions)
            que esperan un objeto estructurado con un campo 'passed' bool.

        Retorna el dict del summary para que el llamador pueda decidir si
        continuar el pipeline o detenerlo (exit code 1).
        """
        self._column_checks()
        self._cross_event_checks()

        df_report = pd.DataFrame(self.resultados)
        df_report.to_csv(REPORT_PATH, index=False)
        logger.info(f"Reporte detallado guardado: {REPORT_PATH}")

        # Resumen por nivel
        totales      = df_report.groupby("nivel")["estado"].value_counts().unstack(fill_value=0)
        total_pass   = (df_report["estado"] == "PASS").sum()
        total_fail   = (df_report["estado"] == "FAIL").sum()
        checks_criticos_fallidos = df_report[
            (df_report["estado"] == "FAIL") &
            (df_report["check"].str.contains("null|único|revenue", case=False))
        ]["check"].tolist()

        summary = {
            "timestamp":               datetime.utcnow().isoformat() + "Z",
            "dataset":                 str(EVENTS_PATH),
            "total_eventos":           len(self.df),
            "total_checks":            len(self.resultados),
            "total_pass":              int(total_pass),
            "total_fail":              int(total_fail),
            "passed":                  total_fail == 0,
            "checks_criticos_fallidos": checks_criticos_fallidos,
            "por_nivel": {
                nivel: {
                    "pass": int(totales.loc[nivel, "PASS"]) if nivel in totales.index else 0,
                    "fail": int(totales.loc[nivel, "FAIL"]) if nivel in totales.index and "FAIL" in totales.columns else 0,
                }
                for nivel in ["column", "cross_event"]
            },
        }

        with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        logger.info(f"Resumen guardado: {SUMMARY_PATH}")

        # ── Log del resumen final ──────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("RESUMEN DE CALIDAD DE DATOS")
        logger.info("=" * 60)
        logger.info(f"  Total checks:  {len(self.resultados)}")
        logger.info(f"  PASS:          {total_pass}")
        logger.info(f"  FAIL:          {total_fail}")
        logger.info(f"  Estado global: {'✅ APROBADO' if summary['passed'] else '❌ FALLIDO'}")
        if checks_criticos_fallidos:
            logger.warning("  Checks críticos fallidos:")
            for check in checks_criticos_fallidos:
                logger.warning(f"    - {check}")
        logger.info("=" * 60)

        return summary


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    checker = QAChecker()
    summary = checker.generar_reporte()

    print(f"\nChecks ejecutados: {summary['total_checks']}")
    print(f"PASS: {summary['total_pass']} | FAIL: {summary['total_fail']}")
    print(f"Archivos generados:")
    print(f"  - {REPORT_PATH}")
    print(f"  - {SUMMARY_PATH}")

    if not summary["passed"]:
        print("\nHay checks fallidos. Revisar qa_report.csv para detalle.")
        sys.exit(1)

    print("\nSiguiente paso: python 04_funnel_analysis/funnel_builder.py")
    sys.exit(0)
