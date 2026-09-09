# Optima Delivery Pickup

Generic multi-provider pickup core for Odoo 18 ecommerce.

Current development phase (18.0.0.4.1):

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
