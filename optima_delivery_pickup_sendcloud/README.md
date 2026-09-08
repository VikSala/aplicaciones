# Optima Delivery Pickup - Sendcloud

Adaptador Sendcloud para `optima_delivery_pickup`.

- Detecta los `delivery.carrier` de `delivery_sendcloud_oca` que requieren Service Point.
- Aporta la Public Key/configuración del checkout.
- En esta primera fase reutiliza el Hosted Service Point Picker oficial de Sendcloud.
- Normaliza el punto al formato genérico/estándar de Odoo.
- Sincroniza también `sendcloud_service_point_address` y `postNumber` para mantener compatibilidad con OCA.

El cálculo de precio, validación dimensional y asignación del carrier real se implementarán en la siguiente fase.


## 18.0.0.2.1

- El descubrimiento de Sendcloud PUDO ya no depende de `sale.order._get_delivery_methods()`.
- Los métodos técnicos Service Point pueden permanecer ocultos del checkout estándar; el adaptador los descubre directamente y los agrupa bajo la opción genérica `Punto de recogida`.
