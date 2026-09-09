# Optima Delivery Pickup

Generic multi-provider pickup core for Odoo 18 ecommerce.

Current development phase (18.0.0.4.5):

- Generic `Punto de recogida` option remains intentionally always visible.
- Product length / width / height fields in millimetres.
- Builds a conservative **single-parcel** logistics profile from the cart:
  total weight plus estimated L × W × H, without using volume.
- Missing weight or dimensions fail closed after point selection and keep
  checkout confirmation blocked with a clear diagnostic.
- Provider-neutral pickup-point snapshot stored on `sale.order`.
- Uses Odoo's standard `pickup_location_data`.
- Generic provider frontend registry and package-validation hook.
- Generic point -> delivery carrier + price resolution hook.
- When an adapter resolves a carrier, the core uses Odoo's standard
  `sale.order.set_delivery_line()` and re-enables checkout confirmation.

Visibility restrictions are deliberately postponed: pickup is shown even when
validation will later reject the current cart.

## 18.0.0.4.0

- Adds conservative one-parcel weight/dimension calculation.
- Adds generic provider package validation before carrier/price resolution.
- Shows the calculated logistics profile on the sale order pickup tab.


## 18.0.0.4.1

- Homogeneous quantities now use an exhaustive rectangular rows/columns/layers
  search across all unit orientations, minimizing the parcel's longest side,
  then second and third sides.
- Mixed carts optimize each homogeneous product block first and then combine
  those blocks conservatively without assuming that different products can
  interlock.
- The sale order pickup tab shows which packing strategy was used.


## 18.0.0.4.2
- La pestaña del pedido pasa a llamarse **Método de entrega** y se muestra en cualquier presupuesto.
- Añade resumen genérico del método seleccionado, embalaje sugerido y límites del método.
- Los límites se conservan como snapshot asociado al transportista que los proporcionó.


## 18.0.0.4.4

- Pickup selection is persisted and rendered before slow provider rating starts.
- Adds a visible circular loading spinner while the point method/price is resolving.
- Checkout confirmation is disabled both in the UI and server-side until pickup is resolved.
- Pending pickup mode no longer allows Odoo to auto-select the first standard carrier.
- Preserves native `pickup_location_data` while delivery lines are recalculated.
- Automatically resumes a pending stored point resolution after a checkout reload.


## 18.0.0.4.5

- Keeps the 0.4.4 immediate point preview and circular loading spinner.
- Restores the proven 0.3.2 single-request pricing flow: `set_point` now stores
  the point and resolves the concrete carrier/price atomically.
- Removes the frontend dependency on `/shop/optima_pickup/resolve`, avoiding the
  interrupted-connection regression introduced by the two-request flow.
- Preserves provider callback extras during validation/rating instead of losing
  them between requests.
- Checkout confirmation remains blocked until the same request returns a valid
  carrier and price.

## 18.0.0.4.6

- Limpia la selección pickup cuando el carrito se queda sin productos entregables, evitando heredar punto/precio al reutilizar el mismo presupuesto web.
- La sustitución de punto se aplica de forma atómica: primero valida/resuelve y solo después reemplaza la línea de transporte.
- El checkout recupera el estado real del servidor y reintenta una vez ante una interrupción de red de `/shop/optima_pickup/set_point`.
