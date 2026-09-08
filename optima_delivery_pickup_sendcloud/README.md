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
