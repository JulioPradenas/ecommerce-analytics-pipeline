"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                         MÓDULO 1 — GA4 EXTRACTOR                           ║
║                  ga4_extractor.py  |  E-Commerce Analytics Pipeline        ║
╚══════════════════════════════════════════════════════════════════════════════╝

¿QUÉ HACE ESTE ARCHIVO?
───────────────────────
Extrae datos de comportamiento de usuarios desde Google Analytics 4 (GA4)
usando su API oficial, y los convierte en DataFrames de pandas listos para
ser cargados a BigQuery en el siguiente paso (bq_loader.py).

¿POR QUÉ PYTHON Y NO OTRO LENGUAJE?
────────────────────────────────────
Python es el estándar de facto en Data Analytics por tres razones concretas:

  1. Ecosistema: las librerías google-analytics-data y google-cloud-bigquery
     son mantenidas por Google directamente. En Java existen equivalentes
     pero son más verbosas y con menos documentación para analytics.

  2. Pandas: la librería de manipulación de datos más usada en el mundo.
     Permite transformar, limpiar y estructurar datos en pocas líneas.

  3. Legibilidad: un BA (Business Analyst) necesita código que pueda
     ser revisado y entendido por perfiles mixtos (técnicos y no técnicos).
     Python es el lenguaje más cercano a pseudocódigo.

¿POR QUÉ GA4 DATA API Y NO EXPORTAR UN CSV DESDE LA UI?
────────────────────────────────────────────────────────
  - La UI de GA4 tiene límites de filas y no es automatizable.
  - La API permite programar extracciones periódicas (diarias, hourly).
  - Es la misma conexión que usaría un equipo de Digital Analytics real.
  - Demuestra dominio técnico: el reclutador ve que sabes conectarte
    a fuentes de datos, no solo descargar archivos manualmente.

¿CÓMO ENCAJA EN EL PIPELINE COMPLETO?
──────────────────────────────────────
  GA4 (fuente)
     │
     ▼
  ga4_extractor.py  ◄─── ESTÁS AQUÍ
     │  Extrae métricas y dimensiones via API
     │  Devuelve DataFrames limpios
     ▼
  bq_loader.py
     │  Carga los DataFrames a tablas en BigQuery
     ▼
  03_qa/data_quality_checks.py
     │  Valida que los datos sean consistentes
     ▼
  04_funnel_analysis/funnel_builder.py
     │  Construye el funnel de conversión
     ▼
  05_dashboard/bq_views.sql
        Alimenta el dashboard en Looker Studio

DATOS USADOS: Google Merchandise Store (Demo Account de Google)
  - Es una tienda e-commerce real operada por Google para demos.
  - Property ID pública: 213025502
  - No requiere credenciales propias para leer (modo demo).
  - Contiene datos reales de sesiones, eventos, conversiones y revenue.
  - URL: https://shop.googlemerchandisestore.com
"""

# ─────────────────────────────────────────────────────────────────────────────
# IMPORTS — ¿por qué cada uno?
# ─────────────────────────────────────────────────────────────────────────────

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    DateRange,
    Dimension,
    Metric,
    OrderBy,
    Filter,
    FilterExpression,
)
# ↑ google-analytics-data: SDK oficial de Google para GA4 Data API.
#   Versión "beta" porque GA4 aún mantiene algunos endpoints en beta,
#   pero es la versión que se usa en producción. Abstrae toda la
#   comunicación HTTP/REST con los servidores de Google.

import pandas as pd
# ↑ pandas: la librería central de manipulación de datos en Python.
#   Convierte las respuestas de la API (objetos JSON anidados) en
#   tablas planas (DataFrames) que BigQuery puede ingerir directamente.
#   Un DataFrame es esencialmente una tabla Excel en memoria.

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
# ↑ Librerías estándar de Python (no requieren instalación):
#   - os: leer variables de entorno (credenciales, IDs)
#   - json: serializar/deserializar configuraciones
#   - logging: registrar qué hizo el script (esencial para QA y debugging)
#   - datetime: calcular rangos de fechas dinámicamente
#   - pathlib: manejar rutas de archivos de forma cross-platform

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE LOGGING
# ¿Por qué logging y no print()?
# ─────────────────────────────────────────────────────────────────────────────
# print() no registra timestamps ni niveles de severidad.
# logging permite clasificar mensajes como INFO, WARNING o ERROR,
# y redirigirlos a archivos o sistemas de monitoreo.
# En un entorno profesional, los logs son la primera fuente de diagnóstico
# cuando algo falla en producción.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),                          # consola
        logging.FileHandler("01_extraction/extractor.log")  # archivo
    ]
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES DE CONFIGURACIÓN
# ¿Por qué definirlas aquí y no hardcodearlas?
# ─────────────────────────────────────────────────────────────────────────────
# Centralizar la configuración permite cambiar el Property ID, las fechas
# o las métricas sin tocar la lógica del código. Esto es una práctica
# estándar llamada "separación de configuración y lógica".

PROPERTY_ID = "213025502"
# ↑ ID de la propiedad GA4 del Google Merchandise Store (demo pública).
#   En un proyecto real, este valor vendría de una variable de entorno:
#   PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID")

# Rango de fechas: últimos 90 días desde hoy
# ¿Por qué 90 días? Suficiente para ver tendencias semanales y estacionalidad,
# sin exceder los límites de la API demo ni generar datasets enormes.
DATE_END   = datetime.today().strftime("%Y-%m-%d")
DATE_START = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")

# Directorio de salida para CSVs intermedios
# ¿Para qué guardar CSVs si después cargamos a BigQuery?
# Como respaldo (backup) y para poder inspeccionar los datos visualmente
# antes de cargarlos. También útil si BigQuery no está disponible.
OUTPUT_DIR = Path("01_extraction/raw_data")
OUTPUT_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# CLASE GA4Extractor
# ¿Por qué usar una clase y no funciones sueltas?
# ─────────────────────────────────────────────────────────────────────────────
# Una clase agrupa el cliente de la API y todos los métodos de extracción
# en un solo objeto. Esto evita pasar el cliente como argumento en cada
# función y hace el código más organizado y reutilizable.
# En términos de analítica: es como tener un "conector" que sabe hablar
# con GA4, al que le puedes pedir distintos tipos de reportes.

class GA4Extractor:
    """
    Extrae datos de GA4 via Data API y los devuelve como DataFrames de pandas.

    Reportes disponibles:
      - funnel_events():     eventos del funnel de conversión e-commerce
      - session_overview():  sesiones, usuarios, bounce rate por canal
      - device_breakdown():  comportamiento por tipo de dispositivo
      - daily_revenue():     revenue y transacciones diarias

    Cada reporte alimenta una tabla diferente en BigQuery, que a su vez
    es consultada por una vista SQL específica en el Módulo 5.
    """

    def __init__(self, property_id: str):
        """
        Inicializa el cliente de GA4.

        ¿Qué hace BetaAnalyticsDataClient()?
        Establece la conexión autenticada con los servidores de GA4.
        Busca credenciales en este orden:
          1. Variable de entorno GOOGLE_APPLICATION_CREDENTIALS
             (apunta a un archivo JSON de Service Account)
          2. Application Default Credentials (gcloud auth)
          3. Si ninguna está configurada, usa acceso anónimo (solo demo)

        En un proyecto real de empresa, siempre se usa una Service Account:
        un usuario de sistema (no humano) con permisos mínimos necesarios.
        """
        self.property_id = f"properties/{property_id}"
        self.client = BetaAnalyticsDataClient()
        logger.info(f"GA4Extractor inicializado | Property: {property_id}")

    def _run_report(self, dimensions: list, metrics: list,
                    date_start: str, date_end: str,
                    dimension_filter=None) -> pd.DataFrame:
        """
        Método privado que ejecuta cualquier reporte en GA4.

        ¿Por qué "_" al inicio del nombre?
        Convención Python: indica que es un método interno de la clase,
        no pensado para ser llamado directamente desde afuera.
        Los métodos públicos (funnel_events, session_overview, etc.)
        llaman a este método pasándole sus parámetros específicos.

        ¿Qué es un RunReportRequest?
        Es el objeto que le dice a la API exactamente qué quieres:
          - dimensions: las "filas" de tu reporte (ej: nombre del evento)
          - metrics:    los "valores" numéricos (ej: cantidad de eventos)
          - dateRanges: el período de tiempo a consultar

        Analogía con SQL:
          SELECT {dimensions}, {metrics}
          FROM ga4_data
          WHERE date BETWEEN {date_start} AND {date_end}
        """
        request = RunReportRequest(
            property=self.property_id,
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=[DateRange(start_date=date_start, end_date=date_end)],
            dimension_filter=dimension_filter,
        )

        logger.info(f"Ejecutando reporte | dims={dimensions} | metrics={metrics}")
        response = self.client.run_report(request)

        # Convertir la respuesta de la API a un DataFrame de pandas
        # ¿Por qué esta conversión es necesaria?
        # La API devuelve un objeto protobuf (formato binario de Google),
        # no una tabla. Debemos extraer manualmente las filas y columnas.
        rows = []
        for row in response.rows:
            row_data = {}
            for i, dim in enumerate(dimensions):
                row_data[dim] = row.dimension_values[i].value
            for i, met in enumerate(metrics):
                row_data[met] = row.metric_values[i].value
            rows.append(row_data)

        df = pd.DataFrame(rows)
        logger.info(f"Reporte completado | {len(df)} filas extraídas")
        return df

    # ─────────────────────────────────────────────────────────────────────────
    # REPORTE 1: EVENTOS DEL FUNNEL DE CONVERSIÓN
    # ─────────────────────────────────────────────────────────────────────────
    def funnel_events(self, date_start: str, date_end: str) -> pd.DataFrame:
        """
        Extrae los eventos clave del funnel e-commerce.

        ¿Qué es un funnel de conversión?
        Es la secuencia de pasos que un usuario recorre desde que llega
        al sitio hasta que compra. Cada paso es un "evento" en GA4:

          session_start → view_item → add_to_cart → begin_checkout → purchase

        ¿Por qué estos eventos específicos?
        Son los eventos de e-commerce estándar de GA4 (enhanced ecommerce).
        La oferta de BC Tecnología pide explícitamente analizar el funnel
        de compra en e-commerce. Estos son exactamente los eventos que
        se implementarían via GTM en el Módulo 2.

        ¿Cómo se relaciona con el resto del pipeline?
          → Los datos de este reporte alimentan funnel_builder.py (Módulo 4)
          → El funnel_builder calcula las tasas de caída entre etapas
          → Las visualizaciones resultantes van al dashboard (Módulo 5)

        Dimensiones extraídas:
          - eventName:       nombre del evento (add_to_cart, purchase, etc.)
          - sessionDefaultChannelGroup: canal de adquisición (Organic, Paid, etc.)
          - deviceCategory:  desktop / mobile / tablet

        Métricas extraídas:
          - eventCount:      cuántas veces ocurrió el evento
          - totalUsers:      usuarios únicos que dispararon el evento
        """
        # Filtro: solo queremos los eventos del funnel, no todos los eventos
        # ¿Por qué filtrar aquí y no en pandas después?
        # Filtrar en la API reduce el volumen de datos transferidos,
        # lo que acelera la extracción y reduce costos en producción.
        funnel_events_list = [
            "session_start", "view_item", "add_to_cart",
            "begin_checkout", "purchase"
        ]

        dimension_filter = FilterExpression(
            filter=Filter(
                field_name="eventName",
                in_list_filter=Filter.InListFilter(values=funnel_events_list)
            )
        )

        df = self._run_report(
            dimensions=["eventName", "sessionDefaultChannelGroup", "deviceCategory"],
            metrics=["eventCount", "totalUsers"],
            date_start=date_start,
            date_end=date_end,
            dimension_filter=dimension_filter
        )

        # Conversión de tipos
        # ¿Por qué es necesario esto?
        # La API devuelve TODOS los valores como strings (texto).
        # Si no convertimos a número, no podemos hacer cálculos matemáticos
        # como tasas de conversión o comparaciones entre etapas.
        df["eventCount"] = pd.to_numeric(df["eventCount"])
        df["totalUsers"] = pd.to_numeric(df["totalUsers"])

        # Agregar metadatos de extracción
        # ¿Para qué sirven estos campos?
        # Para trazabilidad: saber cuándo se extrajeron los datos.
        # En BigQuery, si re-ejecutamos el pipeline, podemos identificar
        # qué datos son nuevos vs. cuáles ya existían.
        df["extraction_date"] = datetime.today().strftime("%Y-%m-%d")
        df["date_range_start"] = date_start
        df["date_range_end"] = date_end

        return df

    # ─────────────────────────────────────────────────────────────────────────
    # REPORTE 2: RESUMEN DE SESIONES POR CANAL
    # ─────────────────────────────────────────────────────────────────────────
    def session_overview(self, date_start: str, date_end: str) -> pd.DataFrame:
        """
        Extrae métricas de sesiones segmentadas por canal de adquisición.

        ¿Qué es un canal de adquisición?
        Es la "puerta de entrada" del usuario al sitio:
          - Organic Search: vino por Google/Bing sin pagar
          - Paid Search:    vino por un anuncio de búsqueda
          - Direct:         escribió la URL directamente
          - Email:          vino desde una campaña de email
          - Referral:       vino desde otro sitio web

        ¿Por qué este reporte importa para el rol?
        La oferta menciona "optimizar inversión publicitaria" y
        "análisis de comportamiento en canales digitales". Este reporte
        es la base para detectar qué canales convierten mejor y cuáles
        están desperdiciando presupuesto.

        ¿Cómo se relaciona con el pipeline?
          → Alimenta la vista SQL channel_performance en Módulo 5
          → El dashboard mostrará revenue y conversión por canal
          → Permite comparar costo vs. conversión (si se cruza con datos de pauta)

        Métricas:
          - sessions:            número de sesiones totales
          - totalUsers:          usuarios únicos
          - bounceRate:          % de usuarios que se van sin interactuar
          - averageSessionDuration: tiempo promedio en el sitio
          - conversions:         eventos marcados como conversión en GA4
          - totalRevenue:        ingresos generados
        """
        df = self._run_report(
            dimensions=["sessionDefaultChannelGroup", "deviceCategory"],
            metrics=[
                "sessions", "totalUsers", "bounceRate",
                "averageSessionDuration", "conversions", "totalRevenue"
            ],
            date_start=date_start,
            date_end=date_end
        )

        numeric_cols = [
            "sessions", "totalUsers", "bounceRate",
            "averageSessionDuration", "conversions", "totalRevenue"
        ]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric)
        df["extraction_date"] = datetime.today().strftime("%Y-%m-%d")

        return df

    # ─────────────────────────────────────────────────────────────────────────
    # REPORTE 3: REVENUE DIARIO
    # ─────────────────────────────────────────────────────────────────────────
    def daily_revenue(self, date_start: str, date_end: str) -> pd.DataFrame:
        """
        Extrae revenue y transacciones día a día.

        ¿Por qué un reporte separado para revenue diario?
        Para análisis de tendencias temporales: ver si el revenue
        crece semana a semana, detectar estacionalidad (fines de semana,
        fechas especiales) y medir el impacto de cambios en el sitio.

        ¿Cómo se relaciona con el pipeline?
          → Alimenta el gráfico de línea temporal en el dashboard (Módulo 5)
          → Permite correlacionar cambios de tagging/tracking con variaciones
            de revenue (si un evento dejó de dispararse, el revenue baja)
          → El QA del Módulo 3 usa este reporte para detectar días con
            datos anómalos (ej: revenue = 0 en un día normal indica error)

        La dimensión "date" en GA4 devuelve formato YYYYMMDD,
        que convertimos a datetime para ordenamiento correcto.
        """
        df = self._run_report(
            dimensions=["date"],
            metrics=["totalRevenue", "transactions", "averagePurchaseRevenue"],
            date_start=date_start,
            date_end=date_end
        )

        # Convertir fecha de YYYYMMDD a formato estándar YYYY-MM-DD
        # ¿Por qué? BigQuery y Looker Studio esperan fechas en ISO 8601.
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        df[["totalRevenue", "transactions", "averagePurchaseRevenue"]] = \
            df[["totalRevenue", "transactions", "averagePurchaseRevenue"]].apply(pd.to_numeric)
        df = df.sort_values("date").reset_index(drop=True)
        df["extraction_date"] = datetime.today().strftime("%Y-%m-%d")

        return df

    # ─────────────────────────────────────────────────────────────────────────
    # REPORTE 4: BREAKDOWN POR DISPOSITIVO
    # ─────────────────────────────────────────────────────────────────────────
    def device_breakdown(self, date_start: str, date_end: str) -> pd.DataFrame:
        """
        Extrae métricas de conversión segmentadas por dispositivo.

        ¿Por qué es crítico este reporte para CRO?
        La mayoría de las fricciones en el funnel ocurren en mobile.
        Si la tasa de conversión en desktop es 3% y en mobile es 0.8%,
        hay una fricción específica en la experiencia móvil (formularios
        difíciles, botones pequeños, carga lenta, etc.).

        Este reporte permite hacer exactamente lo que pide la oferta:
        "detectar fricciones en el funnel de conversión, proponiendo
        mejoras orientadas a aumentar conversión y calidad de UX".

        ¿Cómo se relaciona con el pipeline?
          → El friction_detector.py (Módulo 4) usa este reporte para
            segmentar caídas del funnel por dispositivo
          → Si desktop convierte bien y mobile no, la hipótesis de mejora
            es diferente a si ambos convierten mal
        """
        df = self._run_report(
            dimensions=["deviceCategory", "operatingSystem"],
            metrics=[
                "sessions", "engagedSessions", "conversions",
                "totalRevenue", "bounceRate"
            ],
            date_start=date_start,
            date_end=date_end
        )

        numeric_cols = ["sessions", "engagedSessions", "conversions",
                        "totalRevenue", "bounceRate"]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric)

        # Calcular tasa de conversión directamente aquí
        # conversion_rate = conversiones / sesiones * 100
        # ¿Por qué calcularlo en Python y no en SQL después?
        # Para tener la métrica disponible tanto en el CSV de respaldo
        # como en BigQuery, y para validarla en el QA del Módulo 3.
        df["conversion_rate"] = (
            df["conversions"] / df["sessions"].replace(0, pd.NA) * 100
        ).round(2)

        df["extraction_date"] = datetime.today().strftime("%Y-%m-%d")
        return df


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL DE EXTRACCIÓN
# ─────────────────────────────────────────────────────────────────────────────

def extract_all(property_id: str = PROPERTY_ID,
                date_start: str = DATE_START,
                date_end: str = DATE_END) -> dict:
    """
    Ejecuta todos los reportes y guarda CSVs de respaldo.

    ¿Por qué devolver un diccionario de DataFrames?
    Para que bq_loader.py pueda recibir todos los DataFrames de una vez
    y cargarlos a BigQuery en un solo flujo, sin necesidad de leer los
    CSVs desde disco (aunque estos existen como respaldo).

    Flujo:
      extract_all()  →  dict{"funnel": df, "sessions": df, ...}
                              │
                              ▼
                       bq_loader.py  →  BigQuery (una tabla por DataFrame)
    """
    extractor = GA4Extractor(property_id)

    logger.info("=" * 60)
    logger.info("INICIANDO EXTRACCIÓN COMPLETA")
    logger.info(f"Período: {date_start} → {date_end}")
    logger.info("=" * 60)

    reportes = {
        "funnel_events":    extractor.funnel_events(date_start, date_end),
        "session_overview": extractor.session_overview(date_start, date_end),
        "daily_revenue":    extractor.daily_revenue(date_start, date_end),
        "device_breakdown": extractor.device_breakdown(date_start, date_end),
    }

    # Guardar CSVs de respaldo
    # ¿Por qué guardar en CSV si BigQuery es el destino final?
    # 1. Respaldo: si algo falla en la carga a BigQuery, no hay que
    #    volver a llamar a la API (que tiene rate limits).
    # 2. Inspección rápida: puedes abrir el CSV en Excel para revisar
    #    que los datos tienen sentido antes de cargar.
    # 3. Documentación: los CSVs en el repositorio de GitHub muestran
    #    exactamente qué estructura tienen los datos del pipeline.
    for nombre, df in reportes.items():
        ruta = OUTPUT_DIR / f"{nombre}_{date_end}.csv"
        df.to_csv(ruta, index=False)
        logger.info(f"CSV guardado: {ruta} | {len(df)} filas | {len(df.columns)} columnas")

    # Resumen de extracción
    logger.info("=" * 60)
    logger.info("EXTRACCIÓN COMPLETADA")
    for nombre, df in reportes.items():
        logger.info(f"  {nombre:<20} → {len(df):>5} filas")
    logger.info("=" * 60)

    return reportes


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ¿Qué es if __name__ == "__main__"?
# ─────────────────────────────────────────────────────────────────────────────
# Esta condición permite que el archivo funcione de dos formas:
#   1. Ejecutado directamente: python ga4_extractor.py  → corre extract_all()
#   2. Importado como módulo: from ga4_extractor import extract_all
#      → NO corre extract_all() automáticamente
#
# bq_loader.py importa este archivo como módulo (opción 2), por eso
# esta separación es importante. Sin ella, cada vez que bq_loader.py
# importara ga4_extractor.py, lanzaría una extracción no deseada.

if __name__ == "__main__":
    datos = extract_all()
    print("\n✅ Extracción completada. DataFrames disponibles:")
    for nombre, df in datos.items():
        print(f"   {nombre}: {df.shape[0]} filas × {df.shape[1]} columnas")
    print(f"\n📁 CSVs guardados en: {OUTPUT_DIR.resolve()}")
    print("🚀 Siguiente paso: ejecutar bq_loader.py para cargar a BigQuery")
