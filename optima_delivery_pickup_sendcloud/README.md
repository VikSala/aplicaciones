# Optima Delivery Pickup - Sendcloud

Sendcloud adapter for `optima_delivery_pickup`.

Current development phase (18.0.0.6.4):

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


## 18.0.0.4.3
- Corrige la validación de puntos para transportistas zonales enviando país y códigos postales al endpoint `shipping_methods`.
- Tolera respuestas de `shipping_methods` en formato paginado o lista.
- Evita falsos negativos por IDs volátiles de Sendcloud usando coincidencia exacta y no ambigua por nombre cuando los dos endpoints no comparten ID.
- Mantiene la validación fail-closed: nunca acepta un método solo por compartir transportista.

## 18.0.0.4.4

- La validación de Fase 1 usa una única consulta acotada a Shipping Products para peso/dimensiones.
- El método remoto debe mapearse a un PUDO sincronizado del mismo transportista que el punto seleccionado.
- Se evitan las consultas encadenadas al endpoint `shipping_methods` que podían alargar el checkout y provocar cortes de conexión.

## 18.0.0.5.1 — Fase 4

- Sincroniza el punto Sendcloud seleccionado en website con el albarán de salida
  creado al confirmar el pedido.
- Conserva un snapshot del payload del Service Point y del Post Number en el
  albarán.
- Si la versión instalada de `delivery_sendcloud_oca` expone sus campos de
  Service Point en `stock.picking`, los rellena de forma compatible sin
  redefinirlos.
- Repite la sincronización justo antes de `send_to_shipper` y bloquea el envío
  si el carrier dejó de ser Sendcloud, falta el payload o el ID del punto no
  coincide con el pedido confirmado.
- La creación de parcel, etiqueta, tracking y cancelación sigue usando el flujo
  nativo de `delivery_sendcloud_oca`.


## 18.0.0.6.0 — Fase 5

- Añade búsqueda server-side de Service Points mediante la API v2 de Sendcloud.
- Devuelve al mapa únicamente datos públicos y normalizados del punto; la clave
  secreta nunca sale de Odoo.
- Filtra carriers del mapa contra los métodos compatibles con el peso y
  dimensiones del bulto usando una única consulta de Shipping Products.
- Añade al resultado distancia, horario, tipo de punto, carrier, precio
  orientativo desde la tarifa sincronizada y `lead_time_hours` cuando Sendcloud
  lo informa.
- La selección final sigue pasando por la validación exacta existente; el precio
  del mapa es informativo y nunca sustituye la tarifa definitiva del checkout.
- Conserva el picker alojado Sendcloud como fallback si la interfaz unificada no
  pudiera abrirse.


## 18.0.0.6.1 — Fase 5 mejorada

- La búsqueda del mapa hace una sola petición remota a Service Points; elimina la consulta previa a Shipping Products que podía duplicar la latencia y provocar cortes de `/search_points`.
- El precio orientativo del mapa se obtiene de las rutas/tarifas ya sincronizadas en Odoo y la validación dimensional exacta sigue ejecutándose al elegir el punto.
- Añade un token de caché ligado a dirección + perfil logístico para que el frontend pueda reutilizar resultados sin conservar datos obsoletos.
- Añade iconos visuales por transportista (InPost, Correos, Correos Express, UPS, GLS, FedEx, DHL, DPD y fallback genérico).
- Reduce el timeout de lectura de Service Points para evitar que una búsqueda lenta bloquee el checkout durante demasiado tiempo.


## 18.0.0.6.2
- El mapa ya no oculta puntos que no tengan tarifa orientativa local; la validación exacta sigue al seleccionar.
- Alias robustos para InPost ES / Mondial Relay.
- Caché temporal por carrier + CP + bulto + dirección para evitar repetir Shipping Products al cambiar entre puntos equivalentes.
- Fallback de precio mediante Shipping Price API cuando la ruta sincronizada no contiene una tarifa utilizable (caso de carriers zonales como Correos).

## 18.0.0.6.3

- La búsqueda Sendcloud del mapa usa directamente desde el navegador el `access_token` público de la integración.
- Evita el salto navegador -> Odoo -> Sendcloud para la exploración del mapa y mantiene el resolver exacto de precio en servidor al seleccionar el punto.
- Si la búsqueda directa no está disponible, el core conserva el endpoint Odoo como fallback.

## 18.0.0.6.4

- Separa la caché de `shipping-products` del transportista: para el mismo CP, dirección y bulto, Correos, Correos Express e InPost reutilizan una única validación base de Sendcloud.
- Añade precalentamiento de compatibilidad y tarifa mientras el cliente examina/previsualiza el punto en el mapa.
- Las escrituras de caché del precálculo se acumulan en memoria y se fusionan al final con un bloqueo de fila corto, evitando mantener el pedido bloqueado durante llamadas remotas.
- El precálculo omite el fallback pesado `rate_shipment`; si ruta sincronizada y `shipping-price` no bastan, `set_point` conserva el fallback autoritativo existente.

