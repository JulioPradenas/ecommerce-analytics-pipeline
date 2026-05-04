"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                          MÓDULO 1 — BQ LOADER                              ║
║                   bq_loader.py  |  E-Commerce Analytics Pipeline           ║
╚══════════════════════════════════════════════════════════════════════════════╝

¿QUÉ HACE ESTE ARCHIVO?
───────────────────────
Toma los DataFrames producidos por ga4_extractor.py y los carga como tablas
en Google BigQuery. Es el puente entre la extracción de datos y el almacén
donde vivirán permanentemente para ser consultados por SQL, Looker Studio
y los módulos de análisis del pipeline.

¿POR QUÉ BIGQUERY Y NO UNA BASE DE DATOS TRADICIONAL (MySQL, PostgreSQL)?
──────────────────────────────────────────────────────────────────────────
BigQuery es un Data Warehouse columnar serverless de Google. Esto significa:

  1. COLUMNAR: guarda los datos por columna, no por fila. Cuando haces
     SELECT revenue FROM tabla, solo lee la columna revenue, no toda la fila.
     Esto lo hace extremadamente rápido para queries analíticas.

  2. SERVERLESS: no hay servidor que administrar. No necesitas instalar
     nada, hacer backups ni escalar manualmente. Google lo gestiona todo.

  3. INTEGRACIÓN NATIVA CON GA4: Google exporta datos de GA4 directamente
     a BigQuery. Es el stack estándar en Digital Analytics empresarial.

  4. LOOKER STUDIO: conecta nativamente con BigQuery. Las vistas SQL que
     crearemos en el Módulo 5 alimentarán el dashboard directamente.

¿CÓMO ENCAJA EN EL PIPELINE?
─────────────────────────────
  ga4_extractor.py
     │  Produce: dict de DataFrames
     │
     ▼
  bq_loader.py  ◄─── ESTÁS AQUÍ
     │  Crea dataset en BigQuery (si no existe)
     │  Crea/reemplaza tablas con los DataFrames
     │  Genera schema documentation
     ▼
  03_qa/data_quality_checks.py
     │  Lee las tablas desde BigQuery para validarlas
     ▼
  04_funnel_analysis/funnel_builder.py
     │  Consulta BigQuery con SQL para construir el funnel
     ▼
  05_dashboard/bq_views.sql
        Crea vistas sobre estas tablas para Looker Studio
"""

# ─────────────────────────────────────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────────────────────────────────────

from google.cloud import bigquery
from google.cloud.exceptions import NotFound
# ↑ google-cloud-bigquery: SDK oficial para interactuar con BigQuery.
#   Permite crear datasets, tablas, cargar datos y ejecutar SQL
#   directamente desde Python.
#   NotFound: excepción que se lanza cuando un dataset o tabla no existe.

import pandas as pd
import logging
import json
from datetime import datetime
from pathlib import Path

# Importamos la función de extracción del módulo anterior
# ¿Por qué importar y no copiar el código?
# Principio DRY (Don't Repeat Yourself): si ga4_extractor.py cambia,
# bq_loader.py se beneficia automáticamente sin necesidad de actualizar
# el código en dos lugares. Esto reduce errores y facilita el mantenimiento.
from ga4_extractor import extract_all, PROPERTY_ID, DATE_START, DATE_END

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("01_extraction/loader.log")
    ]
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE BIGQUERY
# ─────────────────────────────────────────────────────────────────────────────

# ¿Qué es un PROJECT_ID en Google Cloud?
# Cada recurso en Google Cloud (BigQuery, GA4, etc.) vive dentro de un
# "proyecto". Es el contenedor de facturación y permisos. En el tier
# gratuito de Google Cloud, puedes crear un proyecto sin costo.
PROJECT_ID = "tu-proyecto-gcp"          # ← reemplazar con tu Project ID
DATASET_ID = "ecommerce_analytics"      # nombre del dataset en BigQuery
LOCATION   = "US"
# ↑ ¿Por qué US? BigQuery tiene regiones. US es la más económica y donde
#   viven la mayoría de los datasets públicos de Google Analytics demo.

# Configuración de carga
# ¿Qué es WRITE_TRUNCATE?
# Define qué pasa cuando la tabla ya existe:
#   WRITE_TRUNCATE:  borra todo y recarga (ideal para datos históricos estáticos)
#   WRITE_APPEND:    agrega filas nuevas (ideal para datos incrementales)
#   WRITE_EMPTY:     falla si la tabla ya tiene datos
# Usamos TRUNCATE porque en cada extracción queremos el período completo
# de 90 días actualizado, no filas duplicadas.
WRITE_DISPOSITION = bigquery.WriteDisposition.WRITE_TRUNCATE


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMAS DE BIGQUERY
# ¿Por qué definir schemas explícitamente?
# ─────────────────────────────────────────────────────────────────────────────
# BigQuery puede inferir el schema automáticamente (autodetect), pero en
# producción siempre se define explícitamente porque:
#   1. Evita que BigQuery infiera mal los tipos (ej: "20240115" como string
#      en vez de DATE, o "1.5" como float en vez de NUMERIC).
#   2. Documenta la estructura de los datos para el equipo.
#   3. Permite agregar descripciones a cada campo (documentación inline).
# En un entorno de Digital Analytics, los schemas son parte de la
# "especificación de medición" que el BA entrega al equipo de desarrollo.

SCHEMAS = {
    "funnel_events": [
        bigquery.SchemaField("eventName",                    "STRING",  description="Nombre del evento GA4 (add_to_cart, purchase, etc.)"),
        bigquery.SchemaField("sessionDefaultChannelGroup",   "STRING",  description="Canal de adquisición (Organic, Paid, Direct, etc.)"),
        bigquery.SchemaField("deviceCategory",               "STRING",  description="Tipo de dispositivo (desktop, mobile, tablet)"),
        bigquery.SchemaField("eventCount",                   "INTEGER", description="Total de veces que ocurrió el evento"),
        bigquery.SchemaField("totalUsers",                   "INTEGER", description="Usuarios únicos que dispararon el evento"),
        bigquery.SchemaField("extraction_date",              "DATE",    description="Fecha de extracción del dato"),
        bigquery.SchemaField("date_range_start",             "DATE",    description="Inicio del período analizado"),
        bigquery.SchemaField("date_range_end",               "DATE",    description="Fin del período analizado"),
    ],
    "session_overview": [
        bigquery.SchemaField("sessionDefaultChannelGroup",   "STRING",  description="Canal de adquisición"),
        bigquery.SchemaField("deviceCategory",               "STRING",  description="Tipo de dispositivo"),
        bigquery.SchemaField("sessions",                     "INTEGER", description="Total de sesiones"),
        bigquery.SchemaField("totalUsers",                   "INTEGER", description="Usuarios únicos"),
        bigquery.SchemaField("bounceRate",                   "FLOAT",   description="Tasa de rebote (0-1)"),
        bigquery.SchemaField("averageSessionDuration",       "FLOAT",   description="Duración promedio de sesión en segundos"),
        bigquery.SchemaField("conversions",                  "INTEGER", description="Total de conversiones"),
        bigquery.SchemaField("totalRevenue",                 "FLOAT",   description="Ingresos totales en USD"),
        bigquery.SchemaField("extraction_date",              "DATE",    description="Fecha de extracción"),
    ],
    "daily_revenue": [
        bigquery.SchemaField("date",                         "DATE",    description="Fecha (YYYY-MM-DD)"),
        bigquery.SchemaField("totalRevenue",                 "FLOAT",   description="Ingresos totales del día en USD"),
        bigquery.SchemaField("transactions",                 "INTEGER", description="Número de transacciones completadas"),
        bigquery.SchemaField("averagePurchaseRevenue",       "FLOAT",   description="Ticket promedio por transacción"),
        bigquery.SchemaField("extraction_date",              "DATE",    description="Fecha de extracción"),
    ],
    "device_breakdown": [
        bigquery.SchemaField("deviceCategory",               "STRING",  description="Tipo de dispositivo"),
        bigquery.SchemaField("operatingSystem",              "STRING",  description="Sistema operativo (iOS, Android, Windows, etc.)"),
        bigquery.SchemaField("sessions",                     "INTEGER", description="Total de sesiones"),
        bigquery.SchemaField("engagedSessions",              "INTEGER", description="Sesiones con engagement (>10s o conversión)"),
        bigquery.SchemaField("conversions",                  "INTEGER", description="Total de conversiones"),
        bigquery.SchemaField("totalRevenue",                 "FLOAT",   description="Ingresos totales"),
        bigquery.SchemaField("bounceRate",                   "FLOAT",   description="Tasa de rebote"),
        bigquery.SchemaField("conversion_rate",              "FLOAT",   description="Tasa de conversión calculada (conversions/sessions*100)"),
        bigquery.SchemaField("extraction_date",              "DATE",    description="Fecha de extracción"),
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# CLASE BQLoader
# ─────────────────────────────────────────────────────────────────────────────

class BQLoader:
    """
    Carga DataFrames de pandas en tablas de BigQuery.

    ¿Por qué una clase separada de GA4Extractor?
    Principio de Responsabilidad Única (SRP): cada clase hace una sola cosa.
      - GA4Extractor:  sabe hablar con GA4
      - BQLoader:      sabe hablar con BigQuery

    Esto facilita el testing (puedes probar cada parte por separado)
    y el mantenimiento (si cambia la API de BigQuery, solo tocas esta clase).
    """

    def __init__(self, project_id: str, dataset_id: str, location: str = "US"):
        self.project_id  = project_id
        self.dataset_id  = dataset_id
        self.location    = location
        self.client      = bigquery.Client(project=project_id)
        # ↑ bigquery.Client: establece la conexión autenticada con BigQuery.
        #   Usa las mismas credenciales que GA4Extractor (GOOGLE_APPLICATION_CREDENTIALS).
        logger.info(f"BQLoader inicializado | Project: {project_id} | Dataset: {dataset_id}")

    def crear_dataset(self):
        """
        Crea el dataset en BigQuery si no existe.

        ¿Qué es un dataset en BigQuery?
        Es el contenedor de tablas, análogo a una "base de datos" en SQL
        tradicional o a una "carpeta" que agrupa tablas relacionadas.

        Estructura en BigQuery:
          Proyecto (tu-proyecto-gcp)
            └── Dataset (ecommerce_analytics)
                  ├── Tabla: funnel_events
                  ├── Tabla: session_overview
                  ├── Tabla: daily_revenue
                  └── Tabla: device_breakdown

        El try/except verifica si el dataset ya existe para no sobrescribirlo
        en ejecuciones posteriores del pipeline.
        """
        dataset_ref = f"{self.project_id}.{self.dataset_id}"
        try:
            self.client.get_dataset(dataset_ref)
            logger.info(f"Dataset ya existe: {dataset_ref}")
        except NotFound:
            dataset = bigquery.Dataset(dataset_ref)
            dataset.location = self.location
            dataset.description = (
                "Pipeline de Digital Analytics e-Commerce. "
                "Datos extraídos desde GA4 Google Merchandise Store. "
                f"Última actualización: {datetime.today().strftime('%Y-%m-%d')}"
            )
            self.client.create_dataset(dataset)
            logger.info(f"Dataset creado: {dataset_ref} | Región: {self.location}")

    def cargar_tabla(self, df: pd.DataFrame, tabla: str,
                     schema: list = None,
                     write_disposition = WRITE_DISPOSITION):
        """
        Carga un DataFrame como tabla en BigQuery.

        ¿Qué hace internamente load_table_from_dataframe?
        1. Serializa el DataFrame a formato Parquet (binario columnar)
        2. Sube el archivo al Google Cloud Storage de BigQuery (temporal)
        3. Crea o reemplaza la tabla con los datos
        4. Elimina el archivo temporal

        ¿Por qué Parquet y no CSV?
        Parquet es el formato de transferencia estándar entre pandas y BigQuery
        porque preserva los tipos de datos (int, float, date) sin ambigüedad.
        Un CSV perdería la distinción entre "1.0" (float) y "1" (int).

        Parámetros:
          df:                DataFrame a cargar
          tabla:             nombre de la tabla destino en BigQuery
          schema:            lista de SchemaField (si None, autodetect)
          write_disposition: qué hacer si la tabla ya existe
        """
        tabla_ref = f"{self.project_id}.{self.dataset_id}.{tabla}"

        job_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=write_disposition,
            # autodetect solo si no hay schema explícito
            autodetect=(schema is None),
        )

        logger.info(f"Cargando tabla: {tabla_ref} | {len(df)} filas")

        job = self.client.load_table_from_dataframe(df, tabla_ref, job_config=job_config)
        # ↑ load_table_from_dataframe devuelve un "job" (trabajo asíncrono).
        #   job.result() espera a que el job termine antes de continuar.
        #   Sin esto, el script podría terminar antes de que los datos se carguen.
        job.result()

        # Verificar que la tabla se creó correctamente
        tabla_bq = self.client.get_table(tabla_ref)
        logger.info(
            f"✅ Tabla cargada: {tabla_ref} | "
            f"Filas en BQ: {tabla_bq.num_rows} | "
            f"Tamaño: {tabla_bq.num_bytes / 1024:.1f} KB"
        )

    def cargar_todo(self, dataframes: dict):
        """
        Carga todos los DataFrames del pipeline en sus respectivas tablas.

        ¿Por qué iterar sobre el diccionario y no llamar cargar_tabla()
        cuatro veces manualmente?
        Si el día de mañana se agrega un quinto reporte, solo hay que
        agregarlo en ga4_extractor.py y en SCHEMAS. Este método se
        adapta automáticamente sin modificaciones.

        Esto es lo que se llama código "escalable": diseñado para crecer
        sin reescribirse.
        """
        self.crear_dataset()

        resultados = {}
        for nombre, df in dataframes.items():
            schema = SCHEMAS.get(nombre)
            self.cargar_tabla(df, tabla=nombre, schema=schema)
            resultados[nombre] = len(df)

        # Guardar metadata de la carga para trazabilidad
        # ¿Para qué sirve este archivo?
        # El Módulo 3 (QA) lo lee para saber cuántas filas se esperaban
        # en cada tabla y comparar contra lo que realmente está en BigQuery.
        metadata = {
            "load_timestamp": datetime.now().isoformat(),
            "project_id":     self.project_id,
            "dataset_id":     self.dataset_id,
            "tablas":         resultados,
            "total_filas":    sum(resultados.values())
        }
        Path("01_extraction/load_metadata.json").write_text(
            json.dumps(metadata, indent=2)
        )

        logger.info("=" * 60)
        logger.info("CARGA A BIGQUERY COMPLETADA")
        for tabla, filas in resultados.items():
            logger.info(f"  {tabla:<20} → {filas:>5} filas")
        logger.info(f"  Total: {sum(resultados.values())} filas cargadas")
        logger.info("=" * 60)
        logger.info("🚀 Siguiente paso: ejecutar 03_qa/data_quality_checks.py")

        return resultados


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # PASO 1: Extraer datos desde GA4
    # ¿Por qué llamar extract_all() aquí?
    # bq_loader.py es el orquestador del Módulo 1: primero extrae, luego carga.
    # Puedes también importar bq_loader desde un orquestador mayor (pipeline.py)
    # que coordine todos los módulos del proyecto.
    logger.info("MÓDULO 1 — PIPELINE COMPLETO: EXTRACCIÓN + CARGA")
    dataframes = extract_all(
        property_id=PROPERTY_ID,
        date_start=DATE_START,
        date_end=DATE_END
    )

    # PASO 2: Cargar a BigQuery
    loader = BQLoader(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        location=LOCATION
    )
    loader.cargar_todo(dataframes)

    print("\n✅ Módulo 1 completado.")
    print(f"   Dataset: {PROJECT_ID}.{DATASET_ID}")
    print("   Tablas creadas:")
    for tabla in SCHEMAS.keys():
        print(f"     - {tabla}")
    print("\n🚀 Siguiente paso: python 03_qa/data_quality_checks.py")
