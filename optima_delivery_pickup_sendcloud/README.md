# Optima Delivery Pickup - Sendcloud

Sendcloud adapter for `optima_delivery_pickup`.

Current development phase:

- Opens Sendcloud's hosted Service Point Picker.
- Normalizes and persists the selected service point.
- Keeps `delivery_sendcloud_oca`'s `sendcloud_service_point_address` in sync.
- Matches the selected point carrier (Correos, InPost, ...) against technical
  Sendcloud PUDO delivery methods.
- Calls Odoo's standard `delivery.carrier.rate_shipment(order)` for matching
  methods and selects the lowest valid returned rate.
- The core then creates the real delivery line and enables checkout.

Product-dimension eligibility rules are not applied yet.


## 18.0.0.3.1

- Resolve Sendcloud pickup pricing from the synchronized country-route price before falling back to `rate_shipment`.
- Match the technical Sendcloud method by carrier, origin/destination and weight bracket, avoiding unrelated 0.00 methods.


### 18.0.0.3.2
- No muestra el aviso falso de Service Point cuando el punto Sendcloud ya está guardado.
