# Guía de Configuración — Dashboard en Looker Studio

## Conexión a BigQuery

1. Abrir [Looker Studio](https://lookerstudio.google.com) → **Crear** → **Informe**
2. Elegir fuente: **BigQuery**
3. Seleccionar proyecto → dataset `ecommerce_analytics`
4. Agregar las 5 vistas como fuentes de datos separadas

> Cada página del dashboard usa una vista distinta. Agregar todas al inicio evita cambiar de fuente mientras se construye el informe.

---

## Estructura del dashboard: 4 páginas

### Página 1 — Resumen Ejecutivo

**Fuente:** `v_executive_summary`

| Chart | Tipo | Campo(s) |
|---|---|---|
| Revenue total | Big Number | `revenue_total_usd` |
| Transacciones | Big Number | `transacciones_totales` |
| Sesiones | Big Number | `sesiones_totales` |
| Conversión global | Big Number | `conversion_global_pct` |
| Ticket promedio | Big Number | `ticket_promedio_usd` |
| Conversión desktop vs mobile | Scorecard doble | `conversion_desktop_pct` / `conversion_mobile_pct` |
| Ratio D/M | Big Number con color | `ratio_desktop_vs_mobile` (rojo si > 2.0) |
| Última actualización | Text widget | `ultima_actualizacion` |

**Configuración del ratio con color condicional:**
- Campo calculado: `ratio_desktop_vs_mobile`
- Regla de color: rojo si ≥ 2.0, naranja si 1.5–2.0, verde si < 1.5

---

### Página 2 — Funnel de Conversión

**Fuente:** `v_funnel_conversion`

| Chart | Tipo | Dimensiones | Métricas |
|---|---|---|---|
| Funnel por dispositivo | Gráfico de barras apiladas | `etapa_orden`, `dispositivo` | `usuarios` |
| Tasa de conversión acumulada | Gráfico de líneas | `etapa_orden` | `tasa_conversion_acumulada_pct` |
| Tabla detalle | Tabla | `etapa`, `dispositivo`, `canal` | `usuarios`, `tasa_conversion_acumulada_pct` |

**Configuración del funnel de barras:**
- Ordenar por: `etapa_orden` ascendente
- Paleta de colores por `dispositivo`: azul=desktop, rojo=mobile, naranja=tablet
- Deshabilitar leyenda automática y agregar una manual con los colores

**Filtro de página:** agregar selector de `canal` para poder ver el funnel por canal de adquisición

---

### Página 3 — Rendimiento por Canal

**Fuente:** `v_channel_performance`

| Chart | Tipo | Dimensiones | Métricas |
|---|---|---|---|
| Revenue por canal | Barras horizontales | `canal` | `revenue_usd` |
| Revenue share | Gráfico de torta | `canal` | `revenue_share_pct` |
| Conversión por canal | Barras agrupadas | `canal`, `dispositivo` | `tasa_conversion_pct` |
| Tabla de performance | Tabla ordenable | `canal`, `dispositivo` | `sesiones`, `revenue_usd`, `tasa_conversion_pct`, `bounce_rate_pct`, `revenue_por_sesion` |

**Campo calculado útil en Looker Studio:**
```
# Revenue por usuario (eficiencia del canal)
revenue_usd / usuarios
```

**Ordenar la tabla por:** `revenue_usd` descendente por defecto

---

### Página 4 — Análisis Mobile vs Desktop

**Fuente principal:** `v_device_kpis` | **Fuente secundaria:** `v_daily_revenue`

| Chart | Tipo | Dimensiones | Métricas |
|---|---|---|---|
| KPIs por dispositivo | Tabla con barras de datos | `dispositivo` | `sesiones`, `tasa_conversion_pct`, `revenue`, `ticket_promedio`, `ratio_vs_desktop` |
| Tendencia de revenue | Gráfico de líneas + promedio móvil | `fecha` | `revenue`, `revenue_media_7d` |
| Anomalías de revenue | Gráfico de dispersión con color | `fecha` | `revenue` (color: `posible_anomalia`) |
| Insight principal | Text box fijo | — | — |

**Text box del insight principal** (copiar y personalizar con los valores reales):
```
HALLAZGO CLAVE: Mobile convierte 3.2× menos que desktop.
El mayor punto de abandono está en Carrito → Checkout.
Recomendación: implementar one-page checkout + Apple Pay en mobile.
Impacto estimado: +8 puntos de conversión en mobile.
```

**Configuración de la tendencia de revenue:**
- Serie 1: `revenue` → línea delgada, color gris
- Serie 2: `revenue_media_7d` → línea gruesa, color azul oscuro
- Eje Y: desde 0 para no distorsionar la percepción de la variación

---

## Paleta de colores recomendada

| Elemento | Color | Hex |
|---|---|---|
| Desktop | Azul | `#2563EB` |
| Mobile | Rojo | `#DC2626` |
| Tablet | Naranja | `#D97706` |
| Positive / PASS | Verde | `#16A34A` |
| Negative / FAIL | Rojo oscuro | `#991B1B` |
| Fondo | Blanco | `#FFFFFF` |
| Texto principal | Gris oscuro | `#111827` |
| Texto secundario | Gris medio | `#6B7280` |

---

## Filtros globales recomendados

Agregar en la barra superior del informe (aplican a todas las páginas):

| Filtro | Campo | Tipo |
|---|---|---|
| Período | `fecha` / `extraction_date` | Selector de fechas |
| Dispositivo | `dispositivo` | Lista desplegable |
| Canal | `canal` | Lista desplegable |

---

## Compartir el dashboard

1. **Compartir con enlace:** Archivo → Compartir → Cualquier persona con el enlace puede ver
2. **Publicar como reporte:** para incluir en el README del repositorio
3. **Captura para el README:** hacer screenshot de la página de Resumen Ejecutivo y guardarlo como `docs/dashboard_preview.png`

---

## Checklist antes de publicar

- [ ] Todas las Big Numbers muestran datos (no `-` o `null`)
- [ ] El funnel está ordenado de session_start a purchase
- [ ] El ratio desktop/mobile aparece en el scorecard con color correcto
- [ ] El selector de fechas funciona en todas las páginas
- [ ] La fecha de `ultima_actualizacion` es reciente
- [ ] El enlace de compartir está activo y sin restricciones de dominio
