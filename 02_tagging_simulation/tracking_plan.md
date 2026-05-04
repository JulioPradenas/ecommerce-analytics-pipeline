# Tracking Plan — E-Commerce Analytics Pipeline

**Versión:** 1.0.0 | **Propiedad GA4:** 213025502 | **Fecha:** 2026-05-04

---

## ¿Qué es un Tracking Plan?

Documento técnico que especifica exactamente qué medir, cómo medirlo y quién es responsable de implementarlo. Es el contrato entre el BA y el equipo de desarrollo: el BA lo define, desarrollo lo implementa, el BA hace el QA.

La especificación completa de parámetros y tipos vive en `tag_schema.json`. Este documento es la versión legible para equipos mixtos (técnicos y no técnicos).

---

## Resumen de eventos

| Evento | Trigger GTM | Responsable | Prioridad |
|---|---|---|---|
| `session_start` | Page View — All Pages | Automático GA4 | Alta |
| `view_item` | Page View — URL contiene `/product/` | Dev Frontend | Alta |
| `add_to_cart` | Custom Event dataLayer | Dev Frontend | Alta |
| `begin_checkout` | Page View — URL contiene `/checkout` | Dev Frontend | Alta |
| `purchase` | Page View — URL contiene `/order-confirmation` | Dev Frontend | Crítica |

---

## Parámetros obligatorios en todos los eventos

| Parámetro | Tipo | Fuente |
|---|---|---|
| `session_id` | string | Cookie `_ga` |
| `user_pseudo_id` | string | Cookie `_ga` |
| `device_category` | string | `navigator.userAgent` |
| `timestamp_ms` | integer | `Date.now()` |

---

## Implementación requerida por el equipo de desarrollo

### 1. Snippet GTM en el `<head>` (todas las páginas)

```html
<script>
  window.dataLayer = window.dataLayer || [];
</script>

<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer','GTM-XXXXXXX');</script>
<!-- Reemplazar GTM-XXXXXXX con el Container ID del workspace -->
```

### 2. Push para `add_to_cart`

Disparar cuando el usuario hace click en "Add to Cart":

```javascript
window.dataLayer.push({
  event: 'add_to_cart',
  ecommerce: {
    currency: 'USD',
    items: [{
      item_id:       producto.id,
      item_name:     producto.nombre,
      item_category: producto.categoria,
      price:         producto.precio,
      quantity:      cantidad
    }]
  }
});
```

### 3. Push para `purchase`

Disparar **una sola vez** en la página de confirmación de orden. Implementar deduplicación por `transaction_id` para evitar doble conteo en recargas de página:

```javascript
// Verificar que no se haya disparado ya para este transaction_id
if (!sessionStorage.getItem('purchase_fired_' + orden.id)) {
  window.dataLayer.push({
    event: 'purchase',
    ecommerce: {
      transaction_id: orden.id,
      value:          orden.total,
      tax:            orden.impuesto,
      shipping:       orden.envio,
      currency:       'USD',
      items:          orden.items
    }
  });
  sessionStorage.setItem('purchase_fired_' + orden.id, '1');
}
```

---

## Parámetro crítico: `device_category`

La segmentación por dispositivo es prioritaria en este proyecto. El análisis de funnel (Módulo 4) muestra que mobile tiene una tasa de conversión 3.2× menor que desktop, concentrada entre `add_to_cart` y `begin_checkout`.

Valores válidos: `desktop` | `mobile` | `tablet`

---

## QA Checklist (responsabilidad BA)

- [ ] `session_start` se dispara exactamente una vez por sesión
- [ ] `view_item` incluye `price > 0` en todas las páginas de producto
- [ ] `add_to_cart` tiene `quantity >= 1` siempre
- [ ] `begin_checkout` tiene `cart_value > 0`
- [ ] `purchase`: `transaction_id` es único (sin duplicados en el dataset)
- [ ] `purchase`: `revenue = cart_value + shipping + tax`
- [ ] Orden de timestamps correcto en todas las sesiones
- [ ] `device_category` es uno de los tres valores válidos en todos los eventos
- [ ] Los eventos llegan a GA4 DebugView sin errores de schema

---

## Conexión con el pipeline

```
tracking_plan.md  →  referencia humana (este documento)
tag_schema.json   →  especificación técnica para validación automatizada
gtm_events_raw.json → dataset sintético generado por gtm_events_simulator.py
                       └── validado por 03_qa/data_quality_checks.py
                       └── analizado por 04_funnel_analysis/funnel_builder.py
```
