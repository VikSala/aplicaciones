# Optima Delivery Pickup

Generic multi-provider pickup core for Odoo 18 ecommerce.

Current development phase:

- Generic `Punto de recogida` option is intentionally always visible.
- Product length / width / height fields in millimetres.
- Provider-neutral pickup-point snapshot stored on `sale.order`.
- Uses Odoo's standard `pickup_location_data`.
- Generic provider frontend registry.
- Generic point -> delivery carrier + price resolution hook.
- When an adapter resolves a carrier, the core uses Odoo's standard
  `sale.order.set_delivery_line()` and re-enables checkout confirmation.

Eligibility restrictions by destination, weight and dimensions are deliberately
postponed to a later phase.
