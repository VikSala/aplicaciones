# Optima Ecommerce Credit (Odoo 18)

Sistema propio de riesgo financiero para el Odoo Ecommerce y forma de pago **Pago a Crédito**.

## 1. Riesgo Ecommerce

- `sale.order.is_ecommerce` es `False` por defecto.
- Los pedidos creados realmente por `website_sale` se marcan automáticamente como Ecommerce.
- Los pedidos históricos/importados desde Instalaciones quedan fuera del riesgo mientras
  `is_ecommerce = False`.
- Las facturas creadas desde pedidos Ecommerce heredan `is_ecommerce = True`.
- Las notas de crédito/reversiones conservan la marca Ecommerce.
- El riesgo del pedido solo incluye la parte todavía no facturada.
- Al crear una factura, el riesgo pasa de pedido a factura para evitar doble conteo.
- Las facturas publicadas consumen su saldo residual y dejan de consumir riesgo al cobrarse.

El riesgo global es:

`Riesgo Instalaciones sincronizado + Riesgo Ecommerce local`

### Sincronización

Instalaciones -> Ecommerce:

- `optima_installations_risk_synced`
- `optima_installations_risk_exception`
- `optima_installations_risk_sync_date`

Ecommerce -> Instalaciones:

- `optima_ecommerce_risk_total`

Nunca debe sincronizarse como entrada el riesgo global combinado.

## 2. Pago a Crédito

Se instala un proveedor/medio de pago llamado **Pago a Crédito**.

Solo se muestra para un pedido Ecommerce cuando se cumplen todas estas condiciones:

- `optima_credit_payment_enabled = True`.
- El cliente tiene `credit_limit > 0`.
- No existe `optima_risk_exception`.
- El crédito disponible es mayor o igual al importe total del pedido.

En el checkout se muestra junto al medio de pago:

`Disponible X,XX € | <condición de pago del pedido>`

El importe disponible se convierte a la moneda del pedido cuando sea necesario.

### Seguridad de la validación

La condición no se comprueba únicamente al dibujar el checkout:

1. Se filtra el proveedor antes de mostrarlo.
2. Se vuelve a validar en backend al crear la transacción.
3. Se valida nuevamente justo antes de confirmar el pedido.
4. La validación final bloquea la fila del cliente comercial en PostgreSQL (`FOR UPDATE`)
   para serializar dos checkouts simultáneos del mismo cliente y reducir el riesgo de que
   ambos consuman el mismo crédito disponible.

Cuando el pago a crédito es válido:

- se confirma el pedido;
- la transacción queda en estado `pending`, ya que no existe un cobro online inmediato;
- el pedido confirmado empieza a consumir automáticamente riesgo Ecommerce.

## Campos principales del contacto

- `optima_credit_payment_enabled`
- `optima_installations_risk_synced`
- `optima_installations_risk_exception`
- `optima_ecommerce_sale_risk`
- `optima_ecommerce_invoice_draft_risk`
- `optima_ecommerce_invoice_open_risk`
- `optima_ecommerce_invoice_unpaid_risk`
- `optima_ecommerce_risk_total`
- `optima_risk_total`
- `optima_risk_remaining_value`
- `optima_risk_remaining_percentage`
- `optima_risk_exception`

Se reutiliza `res.partner.credit_limit` como crédito concedido.

## 18.0.2.1.0 - Corrección tránsito PV → factura → cobro

- La detección de facturas Ecommerce ya no depende únicamente del booleano `account.move.is_ecommerce`: también usa la relación real `invoice_line_ids.sale_line_ids.order_id.is_ecommerce`.
- Autocorrección de `is_ecommerce` al crear/publicar facturas ligadas a pedidos Ecommerce.
- El riesgo pendiente de los PV se calcula en vivo desde las líneas de factura enlazadas, evitando que el pedido permanezca consumiendo riesgo por una recomputación/caché pendiente de `qty_invoiced`.
- Una factura en borrador traslada el importe desde "Pedidos Ecommerce pendientes" a "Facturas Ecommerce borrador"; al publicarla pasa a abierta/vencida; al cobrarla y quedar su residual a cero deja de consumir riesgo.
