# Módulo 3 — QA Automatizado de Calidad de Datos

## ¿Qué hace este módulo?

Valida automáticamente el dataset generado por el Módulo 2 en dos niveles:

- **Nivel 1 — Column Checks** (great-expectations): nulls, tipos, valores válidos columna por columna
- **Nivel 2 — Cross-Event Checks** (pandas): reglas de negocio entre eventos de una misma sesión

Produce un reporte detallado y un resumen ejecutivo que el Módulo 4 usa para decidir si continuar el pipeline.

---

## Archivos

| Archivo | Rol |
|---|---|
| `data_quality_checks.py` | Script principal de QA |
| `qa_report.csv` | Output: detalle de cada check (generado) |
| `qa_summary.json` | Output: resumen PASS/FAIL con flag `passed` (generado) |
| `qa.log` | Log de ejecución (generado) |

---

## Checks implementados

### Nivel 1 — Column Checks (great-expectations)

| Check | Evento | Qué detecta |
|---|---|---|
| `event_name` in set válido | todos | Eventos no definidos en el tracking plan |
| `session_id` not null | todos | Pérdida del identificador de sesión |
| `user_pseudo_id` not null | todos | Pérdida del identificador de usuario |
| `timestamp_ms` not null | todos | Eventos sin timestamp |
| `device_category` in {desktop, mobile, tablet} | todos | Valores de dispositivo no estándar |
| `price` > 0 | view_item | Productos con precio incorrecto |
| `currency` = USD | view_item | Moneda incorrecta |
| `quantity` >= 1 | add_to_cart | Cantidades inválidas |
| `cart_value` > 0 | begin_checkout | Checkout con carrito vacío |
| `revenue` > 0 | purchase | Transacciones sin ingresos |
| `transaction_id` not null | purchase | Compras sin ID de transacción |

### Nivel 2 — Cross-Event Checks (pandas)

| Check | Qué detecta |
|---|---|
| `transaction_id` único en purchase | Doble conteo de revenue por recarga de página |
| Timestamps en orden lógico por sesión | Bug en el clock del cliente o trigger mal configurado |
| `purchase` tiene `begin_checkout` previo | Tag disparado en página incorrecta |
| `begin_checkout` tiene `add_to_cart` previo | Flujo de checkout iniciado sin producto en carrito |
| `revenue = cart_value + shipping + tax` | Cálculo de revenue incorrecto en GTM |
| Todos los eventos del funnel presentes | Dataset incompleto para análisis |

---

## Cómo ejecutar

```bash
# Requiere que el Módulo 2 haya generado gtm_events_raw.json
cd ecommerce-analytics-pipeline
python 02_tagging_simulation/gtm_events_simulator.py
python 03_qa/data_quality_checks.py
```

Output esperado (dataset limpio):
```
2026-05-04 10:00:00 [INFO] MÓDULO 3 — QA DE DATOS
2026-05-04 10:00:00 [INFO] Dataset cargado: 3241 eventos | 5 tipos
2026-05-04 10:00:01 [INFO] ── Nivel 1: Column Checks (great-expectations) ──
2026-05-04 10:00:02 [INFO] ── Nivel 2: Cross-Event Checks (pandas) ──
2026-05-04 10:00:02 [INFO] ══════════════════════════
2026-05-04 10:00:02 [INFO] RESUMEN DE CALIDAD DE DATOS
2026-05-04 10:00:02 [INFO]   Total checks:  17
2026-05-04 10:00:02 [INFO]   PASS:          17
2026-05-04 10:00:02 [INFO]   FAIL:          0
2026-05-04 10:00:02 [INFO]   Estado global: ✅ APROBADO
```

**Exit code 0** si todos los checks pasan. **Exit code 1** si hay algún FAIL — permite integrar el script en pipelines de CI/CD.

---

## Outputs

### `qa_report.csv`

Una fila por check:

| nivel | evento | check | estado | detalle |
|---|---|---|---|---|
| column | todos | session_id not null | PASS | 0 nulls |
| cross_event | purchase | transaction_id único | PASS | 0 duplicados |

### `qa_summary.json`

```json
{
  "timestamp": "2026-05-04T10:00:02Z",
  "total_eventos": 3241,
  "total_checks": 17,
  "total_pass": 17,
  "total_fail": 0,
  "passed": true,
  "checks_criticos_fallidos": [],
  "por_nivel": {
    "column": { "pass": 11, "fail": 0 },
    "cross_event": { "pass": 6, "fail": 0 }
  }
}
```

El campo `passed` es el que el Módulo 4 lee para decidir si proceder con el análisis.

---

## Decisiones de diseño

**¿Por qué `ge.from_pandas()` y no el DataContext completo de GE?**
El DataContext requiere inicializar un proyecto GE con estructura de directorios, stores y checkpoints. Para un script standalone de portafolio, `ge.from_pandas()` demuestra el mismo conocimiento de la librería con menos overhead. En un proyecto en producción con Airflow, se usaría el DataContext completo con Data Docs.

**¿Por qué `sys.exit(1)` si hay FAILs?**
Para que el script sea integrable en pipelines de CI/CD (GitHub Actions, Airflow). Un proceso que termina con código 1 detiene automáticamente el pipeline, evitando que datos corruptos lleguen al dashboard.

**¿Por qué los cross-event checks no usan GE?**
great-expectations opera sobre columnas de un DataFrame plano. No tiene mecanismo nativo para comparar valores entre filas de distintos eventos dentro de una misma sesión. Pandas con `groupby("session_id")` es la herramienta correcta para esa clase de validaciones.

---

## Conexión con el pipeline

```
02_tagging_simulation/gtm_events_raw.json  →  fuente de datos validada
02_tagging_simulation/tag_schema.json      →  referencia de qa_checks
03_qa/qa_summary.json                      →  leído por 04_funnel_analysis
```
