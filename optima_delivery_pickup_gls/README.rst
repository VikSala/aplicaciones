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

18.0.0.1.1
------------
* Usa el marker corporativo GLS/ASM en el mapa unificado y en las tarjetas laterales.


18.0.0.1.2
------------

* GLS ParcelShops now honour the 5/10/20/50 km radius selected in the unified
  pickup map. ``GetParcelShopProximosV3`` has no radius argument, so the module
  uses GLS' returned ``Distancia`` value directly as metres and filters locally.
* GLS points now expose a real ``distance_m`` value and therefore sort correctly
  together with Sendcloud points.
* The technical GLS ParcelShop carrier remains published but is hidden from the
  standard checkout delivery-method list by ``optima_delivery_pickup``.

Version 18.0.0.1.3
------------------

* ``Distancia`` from ``GetParcelShopProximosV3`` is treated directly as metres.
  The previous metres/km inference has been removed.
* The selected 5/10/20/50 km map radius is now an exact numeric comparison
  against the distance calculated and returned by GLS.
