# Odoo AI Chat Base

Plantilla mínima para Odoo 18 orientada a reutilizar la infraestructura de un chatbot sin lógica de ecommerce.

## Qué conserva

- Widget flotante en frontend.
- Activación por páginas de `website.page`.
- Configuración de webhook, título y saludo.
- Envío asíncrono del mensaje desde Odoo al webhook con rutas `start/result`.
- Normalización de respuestas habituales de n8n/AI (`reply`, `output`, `text`, etc.).
- `sessionId`, URL y título de la página como contexto básico.

## Qué se ha eliminado

- Productos, categorías, precios, stock e inventario.
- Carrito y `website_sale`.
- Pedidos de venta y compras.
- Clientes, usuarios portal y alta de cuentas.
- Acciones administrativas desde IA.
- Historiales y filtros del backend.
- Flujos guiados específicos de producto.
- Adjuntos específicos de imágenes de producto.
- Dependencias `website_sale`, `sale`, `purchase`, `stock` y `portal`.

## Extensión para variantes

El controlador `OdooAIChatBaseController` contiene tres hooks principales:

- `_try_handle_local_message(data)`: resolver acciones en Odoo sin llamar a IA.
- `_build_variant_context(data)`: añadir contexto estructurado al payload.
- `_build_n8n_payload(data)`: reemplazar o ampliar por completo el payload enviado al webhook.
- `_response_payload_from_job(job)`: enriquecer la respuesta que recibe el navegador.

Una variante de citas o reservas puede depender de `odoo_ai_chat_base`, heredar el controlador y añadir sus propios modelos, rutas y lógica sin duplicar el widget base.

## Payload base enviado al webhook

```json
{
  "message": "mensaje del usuario",
  "userMessage": "mensaje del usuario",
  "sessionId": "web-...",
  "pageUrl": "https://...",
  "pageTitle": "...",
  "odooContext": {},
  "source": "odoo_ai_chat_base",
  "expectedResponseField": "reply"
}
```

## Nota sobre el modo asíncrono

La plantilla conserva el almacenamiento temporal de jobs en memoria porque replica el patrón del módulo de origen y mantiene el núcleo sencillo. En una instalación Odoo con varios workers, conviene sustituir ese almacén por un modelo persistente o una cola compartida para que `start` y `result` no dependan de caer en el mismo proceso.
