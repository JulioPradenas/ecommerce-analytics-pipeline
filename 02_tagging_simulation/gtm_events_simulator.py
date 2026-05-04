"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    MÓDULO 2 — GTM EVENTS SIMULATOR                         ║
║              gtm_events_simulator.py  |  E-Commerce Analytics Pipeline     ║
╚══════════════════════════════════════════════════════════════════════════════╝

¿QUÉ HACE ESTE ARCHIVO?
───────────────────────
Simula el flujo de eventos que Google Tag Manager generaría en un e-commerce
real. Produce un dataset sintético con la estructura exacta del dataLayer de
GTM, incluyendo fricciones realistas en el funnel (usuarios que abandonan
en distintas etapas).

¿POR QUÉ SIMULAR EVENTOS Y NO USAR SOLO LOS DATOS REALES DE GA4?
─────────────────────────────────────────────────────────────────
Dos razones clave:

  1. DEMOSTRACIÓN TÉCNICA: muestra que entiendes la estructura interna de
     GTM (dataLayer, triggers, variables), no solo que sabes leer reportes.
     Un BA que puede especificar y simular un dataLayer demuestra que puede
     coordinar con el equipo de desarrollo para implementarlo correctamente.

  2. CONTROL DE FRICCIONES: los datos reales de GA4 muestran lo que pasó.
     Los datos simulados permiten diseñar escenarios específicos: qué pasa
     si el 40% abandona en mobile en el checkout, o si un evento deja de
     dispararse (simula un bug de tracking).

¿QUÉ ES EL DATALAYER?
──────────────────────
El dataLayer es un array JavaScript que vive en el navegador del usuario.
Es el canal de comunicación entre el sitio web y GTM:

  window.dataLayer = [];   // inicializado en el <head> del sitio

Cuando ocurre algo relevante (click en "Add to Cart"), el sitio hace:
  window.dataLayer.push({
    event: 'add_to_cart',
    ecommerce: {
      items: [{ item_id: 'ABC123', price: 19.99 }]
    }
  });

GTM "escucha" ese push y dispara el tag correspondiente (GA4, Meta Pixel, etc.)
Este script Python reproduce esa lógica: genera los mismos objetos JSON
que el dataLayer produciría en un browser real.

¿CÓMO ENCAJA EN EL PIPELINE?
─────────────────────────────
  tag_schema.json  →  define la especificación (qué campos, tipos, reglas QA)
       │
       ▼
  gtm_events_simulator.py  ◄── ESTÁS AQUÍ
       │  lee el schema para validar cada evento generado
       │  produce: gtm_events_raw.json     (todos los eventos)
       │           gtm_funnel_summary.csv  (resumen por etapa)
       ▼
  03_qa/data_quality_checks.py
       │  valida el dataset contra las reglas de qa_checks del schema
       ▼
  04_funnel_analysis/funnel_builder.py
       │  puede usar este dataset como alternativa a los datos reales
       ▼
  05_dashboard/
        visualiza tanto datos reales como simulados
"""

import json
import random
import uuid
import pandas as pd
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Path relativo al archivo, no al directorio de ejecución.
# Así el script funciona independientemente de desde dónde se llame.
OUTPUT_DIR = Path(__file__).parent


# ─────────────────────────────────────────────────────────────────────────────
# CATÁLOGO DE PRODUCTOS
# item_id únicos consistentes con el Google Merchandise Store real.
# Un mismo item_id tiene siempre el mismo precio — coherencia entre eventos.
# ─────────────────────────────────────────────────────────────────────────────

PRODUCTOS = [
    {"item_id": "GGOEGOAQ012899", "item_name": "Google Sunglasses",         "item_category": "Apparel",     "price": 19.99},
    {"item_id": "GGOEGAAX0104",   "item_name": "Google Men's T-Shirt",      "item_category": "Apparel",     "price": 22.99},
    {"item_id": "GGOEGFKQ020399", "item_name": "Google Laptop Backpack",    "item_category": "Bags",        "price": 99.99},
    {"item_id": "GGOEGHPB003410", "item_name": "Google Hard Cover Journal", "item_category": "Stationery",  "price": 12.99},
    {"item_id": "GGOEYDHJ056099", "item_name": "Google Snapback Hat",       "item_category": "Accessories", "price": 18.99},
    {"item_id": "GGOEGAAX0358",   "item_name": "Google Women's Hoodie",     "item_category": "Apparel",     "price": 49.99},
    {"item_id": "GGOEADHH073999", "item_name": "Google Water Bottle",       "item_category": "Drinkware",   "price": 14.99},
    {"item_id": "GGOEWXXX0827",   "item_name": "Google USB-C Charging Kit", "item_category": "Electronics", "price": 34.99},
]

# Canales de adquisición — mismos valores que sessionDefaultChannelGroup en GA4
# para que el Módulo 4 pueda comparar datos reales vs. simulados sin conversión.
CANALES = {
    "Organic Search": 0.35,
    "Direct":         0.25,
    "Paid Search":    0.15,
    "Email":          0.12,
    "Referral":       0.08,
    "Social":         0.05,
}

DISPOSITIVOS = {
    "mobile":  0.58,
    "desktop": 0.35,
    "tablet":  0.07,
}

# Tasas de avance por etapa del funnel, segmentadas por dispositivo.
# Mobile convierte significativamente menos en cart→checkout y checkout→purchase.
# Este es el patrón que el Módulo 4 detectará como insight principal.
CONVERSION_RATES = {
    "desktop": {
        "session_to_view":      0.72,
        "view_to_cart":         0.35,
        "cart_to_checkout":     0.58,
        "checkout_to_purchase": 0.62,
    },
    "mobile": {
        "session_to_view":      0.68,
        "view_to_cart":         0.22,
        "cart_to_checkout":     0.45,
        "checkout_to_purchase": 0.38,
    },
    "tablet": {
        "session_to_view":      0.70,
        "view_to_cart":         0.28,
        "cart_to_checkout":     0.52,
        "checkout_to_purchase": 0.51,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# CLASE GTMSimulator
# ─────────────────────────────────────────────────────────────────────────────

class GTMSimulator:
    """
    Simula sesiones de usuario y genera eventos con estructura de dataLayer GTM.

    El simulador carga tag_schema.json al inicializarse y valida cada evento
    generado contra los campos obligatorios definidos en el schema. Esto
    garantiza consistencia entre la especificación (tag_schema.json) y el
    output (gtm_events_raw.json).
    """

    def __init__(self, n_sesiones: int = 1000, dias: int = 30, seed: int = 42):
        """
        seed=42 garantiza reproducibilidad: cualquiera que clone el repo
        obtiene exactamente el mismo dataset.
        """
        self.n_sesiones  = n_sesiones
        self.dias        = dias
        random.seed(seed)
        self.fecha_inicio = datetime.now(tz=timezone.utc) - timedelta(days=dias)

        # Cargar schema y construir índice por event_name para validación O(1)
        schema_path = OUTPUT_DIR / "tag_schema.json"
        with open(schema_path, encoding="utf-8") as f:
            raw_schema = json.load(f)
        self.schema: dict = {ev["event_name"]: ev for ev in raw_schema["eventos"]}

        logger.info(f"GTMSimulator | {n_sesiones} sesiones | {dias} días | schema cargado: {len(self.schema)} eventos")

    def _validate_event(self, event: dict) -> bool:
        """
        Valida que el evento tenga todos los campos obligatorios según el schema.

        Solo valida presencia de campos requeridos — la validación de reglas
        cruzadas entre eventos (ej: "add_to_cart antes de begin_checkout")
        es responsabilidad del Módulo 3 (QA), que opera sobre el dataset completo.

        Retorna False y loggea warning si falta algún campo obligatorio.
        """
        event_schema = self.schema.get(event.get("event_name"))
        if not event_schema:
            return True  # evento no definido en schema — dejar pasar

        for param_name, param_def in event_schema["parametros"].items():
            if param_def.get("obligatorio") and event.get(param_name) is None:
                logger.warning(
                    f"Campo obligatorio faltante: '{param_name}' en evento '{event['event_name']}'"
                )
                return False
        return True

    def _generar_ids(self) -> tuple[str, str]:
        session_id     = str(uuid.uuid4())[:8]
        user_pseudo_id = "user_" + str(uuid.uuid4())[:6]
        return session_id, user_pseudo_id

    def _siguiente_timestamp(self, base_ts: int, min_seg: int = 5, max_seg: int = 300) -> int:
        """
        Genera el timestamp del siguiente evento, siempre posterior al anterior.

        El orden cronológico de timestamps es un invariante que el QA del
        Módulo 3 validará. El simulador lo garantiza aquí para que el
        dataset sea internamente consistente.
        """
        return base_ts + random.randint(min_seg * 1000, max_seg * 1000)

    def _evento_base(self, event_name: str, session_id: str,
                     user_pseudo_id: str, device: str,
                     canal: str, timestamp_ms: int) -> dict:
        """
        Campos comunes a todos los eventos. Centralizar aquí evita
        inconsistencias de nombres entre etapas del funnel.

        Usa UTC explícito para alinearse con GA4, que almacena timestamps en UTC.
        """
        return {
            "event_name":      event_name,
            "session_id":      session_id,
            "user_pseudo_id":  user_pseudo_id,
            "device_category": device,
            "traffic_source":  canal,
            "timestamp_ms":    timestamp_ms,
            "fecha":           datetime.fromtimestamp(
                                   timestamp_ms / 1000, tz=timezone.utc
                               ).strftime("%Y-%m-%d"),
        }

    def simular_sesion(self) -> list[dict]:
        """
        Simula una sesión completa con su secuencia de eventos GTM.

        En cada etapa del funnel, una probabilidad (distinta por dispositivo)
        determina si el usuario avanza o abandona. Esto produce la asimetría
        mobile/desktop que es el insight central del proyecto.
        """
        session_id, user_pseudo_id = self._generar_ids()

        device = random.choices(list(DISPOSITIVOS), weights=list(DISPOSITIVOS.values()))[0]
        canal  = random.choices(list(CANALES),      weights=list(CANALES.values()))[0]
        rates  = CONVERSION_RATES[device]
        eventos: list[dict] = []

        ts = int((self.fecha_inicio + timedelta(
            seconds=random.randint(0, self.dias * 86400)
        )).timestamp() * 1000)

        # ── session_start (siempre ocurre) ────────────────────────────────
        ev = self._evento_base("session_start", session_id, user_pseudo_id, device, canal, ts)
        ev["landing_page"] = random.choice(["/", "/sale", "/new-arrivals", "/collections"])
        self._validate_event(ev)
        eventos.append(ev)

        # ── view_item ─────────────────────────────────────────────────────
        if random.random() > rates["session_to_view"]:
            return eventos

        producto = random.choice(PRODUCTOS)
        ts = self._siguiente_timestamp(ts, 10, 120)
        ev = self._evento_base("view_item", session_id, user_pseudo_id, device, canal, ts)
        ev.update({
            "item_id":       producto["item_id"],
            "item_name":     producto["item_name"],
            "item_category": producto["item_category"],
            "price":         producto["price"],
            "currency":      "USD",
        })
        self._validate_event(ev)
        eventos.append(ev)

        # ── add_to_cart ───────────────────────────────────────────────────
        if random.random() > rates["view_to_cart"]:
            return eventos

        ts = self._siguiente_timestamp(ts, 15, 180)
        quantity = random.choices([1, 2, 3], weights=[0.75, 0.20, 0.05])[0]
        ev = self._evento_base("add_to_cart", session_id, user_pseudo_id, device, canal, ts)
        ev.update({
            "item_id":       producto["item_id"],
            "item_name":     producto["item_name"],
            "item_category": producto["item_category"],
            "price":         producto["price"],
            "quantity":      quantity,
            "currency":      "USD",
        })
        self._validate_event(ev)
        eventos.append(ev)

        # ── begin_checkout ────────────────────────────────────────────────
        if random.random() > rates["cart_to_checkout"]:
            return eventos

        ts = self._siguiente_timestamp(ts, 30, 300)
        cart_value = round(producto["price"] * quantity, 2)
        ev = self._evento_base("begin_checkout", session_id, user_pseudo_id, device, canal, ts)
        ev.update({
            "cart_value":       cart_value,
            "cart_items_count": quantity,
            "currency":         "USD",
        })
        self._validate_event(ev)
        eventos.append(ev)

        # ── purchase ──────────────────────────────────────────────────────
        if random.random() > rates["checkout_to_purchase"]:
            return eventos

        ts = self._siguiente_timestamp(ts, 60, 600)
        shipping = round(random.uniform(5.0, 15.0), 2)
        tax      = round(cart_value * 0.08, 2)
        revenue  = round(cart_value + shipping + tax, 2)
        ev = self._evento_base("purchase", session_id, user_pseudo_id, device, canal, ts)
        ev.update({
            "transaction_id": f"T-{datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}",
            "revenue":        revenue,
            "cart_value":     cart_value,
            "shipping":       shipping,
            "tax":            tax,
            "currency":       "USD",
            "payment_method": random.choices(
                ["credit_card", "debit_card", "paypal", "apple_pay"],
                weights=[0.45, 0.25, 0.20, 0.10]
            )[0],
        })
        self._validate_event(ev)
        eventos.append(ev)

        return eventos

    def generar_dataset(self) -> tuple[list, pd.DataFrame]:
        """
        Ejecuta la simulación completa y persiste los resultados.

        Outputs:
          gtm_events_raw.json    — estructura JSON fiel al dataLayer de GTM
          gtm_funnel_summary.csv — resumen con tasa por etapa y conversión global
        """
        todos_los_eventos: list[dict] = []

        logger.info(f"Simulando {self.n_sesiones} sesiones...")
        for _ in range(self.n_sesiones):
            todos_los_eventos.extend(self.simular_sesion())

        logger.info(f"Total eventos generados: {len(todos_los_eventos)}")

        # JSON raw preserva la estructura heterogénea por evento.
        # Un CSV pondría NaN en campos que no aplican a cada tipo de evento.
        json_path = OUTPUT_DIR / "gtm_events_raw.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(todos_los_eventos, f, indent=2, default=str)
        logger.info(f"JSON guardado: {json_path}")

        # ── Resumen del funnel ─────────────────────────────────────────────
        df      = pd.DataFrame(todos_los_eventos)
        conteos = df["event_name"].value_counts()
        etapas  = ["session_start", "view_item", "add_to_cart", "begin_checkout", "purchase"]

        sesiones_totales = conteos.get("session_start", 1)
        resumen = []
        for i, etapa in enumerate(etapas):
            count    = int(conteos.get(etapa, 0))
            prev     = resumen[i - 1]["count"] if i > 0 else count
            resumen.append({
                "etapa":            etapa,
                "count":            count,
                "tasa_vs_anterior": round(count / prev * 100, 1) if prev > 0 else 100.0,
                "tasa_vs_inicio":   round(count / sesiones_totales * 100, 1),
            })

        df_resumen = pd.DataFrame(resumen)
        csv_path   = OUTPUT_DIR / "gtm_funnel_summary.csv"
        df_resumen.to_csv(csv_path, index=False)

        logger.info("\n── RESUMEN DEL FUNNEL SIMULADO ──")
        logger.info(f"{'Etapa':<20} {'Eventos':>8} {'vs anterior':>12} {'vs inicio':>10}")
        logger.info("-" * 55)
        for _, row in df_resumen.iterrows():
            logger.info(
                f"{row['etapa']:<20} {int(row['count']):>8} "
                f"{row['tasa_vs_anterior']:>11.1f}% {row['tasa_vs_inicio']:>9.1f}%"
            )

        return todos_los_eventos, df_resumen


if __name__ == "__main__":
    simulator = GTMSimulator(n_sesiones=1000, dias=30, seed=42)
    eventos, resumen = simulator.generar_dataset()

    print(f"\nEventos generados: {len(eventos)}")
    print(f"Archivos en {OUTPUT_DIR}/:")
    print("  - gtm_events_raw.json    (dataLayer events)")
    print("  - gtm_funnel_summary.csv (resumen por etapa)")
    print("\nSiguiente paso: python 03_qa/data_quality_checks.py")
