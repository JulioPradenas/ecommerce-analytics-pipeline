# Módulo 2 — Simulación de Tagging GTM + Tracking Plan

## ¿Qué hace este módulo?

Simula lo que en un proyecto real haría Google Tag Manager: define el plan de medición (qué eventos medir, con qué parámetros y en qué condiciones), y genera eventos sintéticos que reproducen el comportamiento de usuarios en un e-commerce.

No puedes mostrar un GTM real en GitHub, pero sí demostrar que entiendes cómo funciona por dentro: el dataLayer, la estructura de eventos, los triggers y los parámetros.

---

## Archivos

| Archivo | Rol |
|---|---|
| `tag_schema.json` | Especificación de eventos, parámetros, tipos y reglas de QA |
| `gtm_events_simulator.py` | Genera el dataset sintético validado contra el schema |
| `tracking_plan.md` | Documento técnico para el equipo de desarrollo |
| `gtm_events_raw.json` | Output: eventos en formato dataLayer (generado) |
| `gtm_funnel_summary.csv` | Output: resumen por etapa del funnel (generado) |

---

## Eventos simulados

```
session_start → view_item → add_to_cart → begin_checkout → purchase
```

Cada etapa tiene tasas de avance distintas por dispositivo, produciendo la asimetría mobile/desktop que el Módulo 4 detectará como insight principal.

---

## Cómo ejecutar

```bash
cd ecommerce-analytics-pipeline/02_tagging_simulation
python gtm_events_simulator.py
```

Output esperado:
```
2026-05-04 10:00:00 [INFO] GTMSimulator | 1000 sesiones | 30 días | schema cargado: 5 eventos
2026-05-04 10:00:00 [INFO] Simulando 1000 sesiones...
2026-05-04 10:00:01 [INFO] Total eventos generados: ~3200

── RESUMEN DEL FUNNEL SIMULADO ──
Etapa                Eventos  vs anterior  vs inicio
session_start           1000       100.0%    100.0%
view_item                693        69.3%     69.3%
add_to_cart              183        26.4%     18.3%
begin_checkout            97        53.0%      9.7%
purchase                  42        43.3%      4.2%
```

---

## Decisiones de diseño

**¿Por qué el simulador lee `tag_schema.json`?**
Para que schema y output estén acoplados: si se agrega un campo obligatorio al schema, el simulador lo detecta y loggea un warning si el evento generado no lo incluye. Evita que la especificación y la implementación se desincronicen.

**¿Por qué `seed=42`?**
Con la misma semilla, `random` produce exactamente los mismos números en cualquier máquina. El dataset es reproducible: cualquiera que clone el repo obtiene los mismos resultados.

**¿Por qué JSON para los eventos raw y no CSV?**
Los eventos tienen estructura heterogénea: `purchase` tiene `transaction_id` y `revenue`; `session_start` tiene `landing_page`. JSON preserva esa estructura. El CSV pondría `NaN` en todos los campos que no aplican a cada tipo de evento.

**¿Por qué UTC en los timestamps?**
GA4 almacena todos los eventos en UTC. Usar `timezone.utc` en el simulador garantiza consistencia al comparar datos simulados vs. reales en el Módulo 4.

---

## Conexión con el resto del pipeline

| Módulo | Qué consume | Para qué |
|---|---|---|
| `03_qa` | `gtm_events_raw.json` + `tag_schema.json` | Validar calidad del dataset sintético |
| `04_funnel_analysis` | `gtm_funnel_summary.csv` | Comparar funnel simulado vs. real (GA4) |
| `docs/` | `tracking_plan.md` | Documentación técnica del proyecto |
