# Optima Ecommerce Financial Risk

Extensión para Odoo 18 destinada al Odoo de Instalaciones.

## Objetivo

Mantener intacta la lógica de `account_financial_risk` y mostrar, a nivel
informativo, el riesgo calculado en el Odoo Ecommerce.

## Campos añadidos en `res.partner`

- `ecommerce_risk_synced`: importe editable que debe recibir el riesgo local del Ecommerce.
- `total_risk_synced`: suma informativa de `risk_total` (OCA) + `ecommerce_risk_synced`.
- `ecommerce_risk_sync_date`: fecha/hora de la última actualización del riesgo Ecommerce.

## Sin bucles de sincronización

Desde Instalaciones hacia Ecommerce debe sincronizarse el `risk_total` oficial
de OCA, no `total_risk_synced`.

Desde Ecommerce hacia Instalaciones debe sincronizarse únicamente su riesgo
local hacia `ecommerce_risk_synced`.

## Fecha de sincronización

Cuando se escribe `ecommerce_risk_synced`, el módulo actualiza automáticamente
`ecommerce_risk_sync_date`, salvo que el propio sincronizador envíe explícitamente
una fecha en esa misma escritura.
