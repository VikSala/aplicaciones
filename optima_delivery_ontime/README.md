# Optima Delivery OnTime — versión final Mensaglobal

Versión: **18.0.9.0.0**

Integración de OnTime para Odoo 18 utilizando la API v1 de Mensaglobal facilitada por la oficina de OnTime.

## Modos

- **Simulated (local only)**: no realiza llamadas externas.
- **API Test (Test Pruebas)**: utiliza la misma URL/token confirmados por OnTime, pero sustituye exclusivamente el nombre del destinatario enviado a Mensaglobal por `Test Pruebas`. El contacto de Odoo no se modifica.
- **Production**: utiliza la misma API y envía el destinatario real.

La URL actualmente confirmada por OnTime es `https://preproduccion.mensaglobal.com/api`. Aunque el hostname contiene `preproduccion`, OnTime ha indicado que la URL y el token entregados corresponden al acceso que debe utilizarse en producción.

## Servicios API

- XS Economy 48/72: código `72`.
- Fallback 19Horas XS: código `24`.

El cliente nunca selecciona el servicio. El módulo resuelve internamente la tarifa y el código API.

## Funcionalidad

- Tarifas contractuales importadas desde PDF.
- Zonificación Provincial / Regional / Iberia y destinos especiales.
- Peso real y volumétrico.
- Dimensiones de producto reutilizando `shipping_length_mm`, `shipping_width_mm` y `shipping_height_mm`.
- Validación por bulto y uso prioritario de paquetes reales de Odoo.
- Creación de expediciones en Mensaglobal.
- Etiquetas PDF.
- Tracking y URL pública de seguimiento.
- POD mediante `urlPOD` devuelta por Mensaglobal.
- Anulación mediante `PUT /v1/envios/{codigoExpedicion}/anular`.
- Control de `anuladoEnRed`.
- Protección contra duplicados, concurrencia y resultados inciertos.
- Reintentos automáticos únicamente en operaciones de lectura seguras.
- Aislamiento multicompañía cuando existe más de una compañía.
- Uso automático de la única compañía cuando la base es monocompañía.

## IVA / impuestos del transporte

Odoo no debe recibir una tarifa con el IVA sumado manualmente. La línea de transporte usa los impuestos configurados en el producto de envío del transportista y después aplica la posición fiscal del pedido.

En esta versión, si el producto de envío de OnTime no tiene ningún impuesto de venta para la compañía, el módulo le asigna automáticamente el **impuesto de venta por defecto de la compañía**. En una configuración española estándar normalmente será el 21 %, pero no se fuerza un porcentaje concreto: se respeta la configuración fiscal real de Odoo.

El impuesto puede revisarse directamente desde la pestaña OnTime mediante **Shipping Sales Taxes / Impuestos de venta del envío**.

Tras actualizar desde una versión anterior, si ya existía una línea de transporte sin IVA en un presupuesto abierto, conviene volver a calcular/eliminar y añadir el método de envío para que Odoo regenere la línea con sus impuestos actuales.

## API Mensaglobal

- Creación: `POST /v1/envios`
- Etiquetas: `GET /v1/envios/etiquetas/{reference}`
- Tracking: `GET /v1/envios/localizar/{reference}`
- Cancelación: `PUT /v1/envios/{reference}/anular`

La autenticación se realiza con `Authorization: Bearer <token>`.

## Seguridad operativa

Las escrituras no se reintentan automáticamente. Si una creación o cancelación queda en estado incierto por timeout/conexión/5xx, el albarán se bloquea para evitar duplicados y requiere reconciliación manual. Las lecturas sí admiten reintentos configurables.

El token no se incluye en URLs externas de documentos ni se almacena en logs del módulo.

## Validación final recomendada

Antes de cambiar a Producción, ejecutar en modo **API Test (Test Pruebas)** al menos un ciclo completo:

1. Probar conexión Mensaglobal.
2. Crear expedición código 72.
3. Descargar etiqueta.
4. Consultar tracking.
5. Probar POD cuando exista.
6. Anular la expedición y comprobar `anuladoEnRed`.
7. Probar un caso de fallback código 24.
8. Probar varios bultos si el flujo operativo los utiliza.

Las tarifas actualmente cargadas deben sustituirse por las tarifas vigentes cuando OnTime las facilite.
