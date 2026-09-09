# Optima Delivery Pickup - Sendcloud

Sendcloud adapter for `optima_delivery_pickup`.

Current development phase (18.0.0.4.0):

- Opens Sendcloud's hosted Service Point Picker.
- Normalizes and persists the selected service point.
- Keeps `delivery_sendcloud_oca`'s `sendcloud_service_point_address` in sync.
- Validates the one-parcel weight and dimensions against Sendcloud's
  `shipping-products` API with `last_mile=service_point`.
- Intersects those dimension-compatible methods with the methods Sendcloud
  says are valid for the exact selected `service_point_id`.
- Maps the resulting remote method to the synchronized technical Odoo PUDO
  carrier before applying the synchronized route price.
- API errors and ambiguous method mapping fail closed: checkout confirmation
  remains blocked rather than accepting an unvalidated shipment.

## 18.0.0.4.0

- Adds real Sendcloud weight/dimension compatibility validation.
- Adds exact selected-service-point compatibility validation.
- Prevents selecting a local PUDO method unless it maps to a compatible
  Sendcloud remote shipping method.


## 18.0.0.4.2
- Guarda en el pedido los límites del método Sendcloud finalmente seleccionado.
- Normaliza peso máximo/mínimo y dimensiones máximas del Shipping Products API a kg/mm.
- El snapshot queda asociado al método técnico de Odoo usado para la expedición.
