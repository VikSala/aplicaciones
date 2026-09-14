Optima Delivery Pickup - GLS
============================

Adapter between ``optima_delivery_pickup`` and ``delivery_gls_asm``.

* Adds GLS ParcelShops returned by ``GetParcelShopProximosV3`` to the unified
  Optima checkout map.
* Only GLS carriers configured with Shipping Time ``19 - ParcelShop`` are
  exposed as pickup delivery methods.
* Search stays server-side and runs in parallel with browser-side providers.
* The exact GLS point is verified server-side from a short-lived canonical cache
  (with a GLS re-query fallback) before storing it on the sale order.
* Delivery price is obtained from the configured GLS ParcelShop carrier's normal
  Odoo rating method. The GLS locator itself does not publish rates.

This adapter deliberately does not alter the GLS shipment XML yet. The original
``delivery_gls_asm`` module still needs the final ParcelShop shipment handoff
(``Horario=19`` + ``Destinatario/Codigo``) in the next integration step.
