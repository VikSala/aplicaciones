# Optima Delivery Pickup

Generic multi-provider pickup core for Odoo 18 ecommerce.

Current development phase (18.0.0.8.2):

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


## 18.0.0.6.0 — Fase 3

- Revalida automáticamente el punto ya elegido cuando cambia un producto o una cantidad física del carrito.
- Si el mismo punto sigue siendo compatible, recalcula y conserva método/precio; si deja de serlo, conserva el punto visible pero invalida método/precio y bloquea Confirmar.
- Al cambiar o editar la dirección de entrega, elimina el punto anterior y mantiene el modo pickup activo para obligar a seleccionar un punto adecuado a la nueva dirección.
- Guarda huellas internas de dirección y perfil logístico validados y las comprueba de nuevo al renderizar checkout y antes del pago, protegiendo frente a cambios hechos por otros módulos o escrituras directas.
- Un fallo temporal del proveedor durante una modificación del carrito no impide editar el carrito: deja pickup pendiente con diagnóstico y Confirmar bloqueado.

## 18.0.0.7.0 — Fase 4

- Añade una protección local final antes de confirmar un pedido pickup: punto,
  método, huellas logística/dirección y `pickup_location_data` deben seguir
  coincidiendo con lo validado en checkout, sin volver a llamar a la API durante
  el callback de pago.
- Copia al albarán de salida un snapshot operativo del método, embalaje esperado,
  límites y punto seleccionado.
- Añade la pestaña **Método de entrega** al albarán para que almacén vea la misma
  información con la que se confirmó el pedido.
- Antes de `send_to_shipper`, bloquea una expedición pickup si el método o el
  destino ya no coinciden con el snapshot confirmado.
- La creación real de envío, etiqueta y tracking sigue delegada al conector del
  transportista instalado (por ejemplo `delivery_sendcloud_oca`).


## 18.0.0.8.0 — Fase 5

- Sustituye la dependencia funcional del picker alojado por un **mapa unificado**
  propiedad del core, preparado para mezclar puntos de varios proveedores.
- Añade `/shop/optima_pickup/search_points` y un hook backend genérico para que
  cada adaptador aporte puntos normalizados sin exponer credenciales al navegador.
- El cliente puede buscar por dirección/CP, ampliar radio (5/10/20/50 km) y
  ordenar por distancia, precio estimado o plazo.
- La lista funciona incluso si el mapa Leaflet no carga; el selector alojado del
  proveedor se conserva como fallback de emergencia.
- Al elegir un marcador se mantiene el flujo estable de Fases 1-4: spinner,
  validación exacta del punto, precio definitivo, total y Confirmar.


## 18.0.0.8.1
- Corrige la compilación SCSS de Odoo 18 evitando `min()` entre unidades `px` y `vw/vh` en el modal del mapa unificado.
- Mantiene el mismo tamaño visual mediante `width/height` + `max-width/max-height`.


## 18.0.0.8.2 — Fase 5 mejorada

- El mapa abre por defecto con radio de 5 km y usa el CP del cliente como búsqueda inicial.
- Oculta la vista nacional durante la primera carga y centra/encuadra el mapa sobre los puntos realmente encontrados.
- Cambia a cartografía CARTO Voyager sobre OpenStreetMap para una lectura más moderna a corta distancia.
- Mueve la lista de puntos a la izquierda, añade filtros por transportista y soporta logos proporcionados por cada adaptador.
- Persiste durante 15 minutos búsqueda, radio, filtros, resultados y posición del mapa en `sessionStorage`, invalidando la caché cuando cambian dirección o bulto.
- Si una actualización falla, conserva los últimos resultados en vez de vaciar el mapa; añade un reintento y fallback al selector oficial.


## 18.0.0.8.3
- Mapa base OpenStreetMap sin API key ni marcas de agua de proveedor.


## 18.0.0.8.4
- Marcadores de mapa específicos para Correos, Correos Express e InPost.
- Los marcadores de otras compañías conservan el fallback genérico.
- Eliminado el aviso inferior sobre precio orientativo del selector de puntos.
