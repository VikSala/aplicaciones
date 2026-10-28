# 18.0.0.11.19 — Diagnóstico HTTP 400 en MP3 con Vercel AI Gateway

## Contexto

La versión 11.18 devolvía "Vercel o el proveedor ha rechazado el MP3 o el modelo de transcripción (HTTP 400)" para distintos errores del proveedor. El mensaje real (`error.message`) se descartaba aunque se recibiera en la respuesta JSON, impidiendo determinar si el fallo era de formato de audio, cabeceras, modelo o parámetros.

## Revisión del protocolo

El transporte Python se ha contrastado con el código fuente oficial del SDK de Vercel, `packages/gateway/src/gateway-provider.ts` y `packages/gateway/src/gateway-transcription-model.ts`.

Se añaden las dos cabeceras que emite el SDK y faltaban en nuestra petición a `POST https://ai-gateway.vercel.sh/v4/ai/transcription-model`:

- `ai-gateway-protocol-version: 0.0.1`
- `ai-gateway-auth-method: api-key`

Se mantienen el modelo seleccionado por compañía, `ai-model-id`, `ai-transcription-model-specification-version: 4`, `audio` (base64) y `mediaType: audio/mpeg`. La API key sigue confinada al servidor Odoo.

## Diagnóstico seguro

Ante un fallo HTTP del proveedor, el backend examina **solo** los campos estructurados `error.code`, `error.type` y `error.message` de la respuesta JSON (hasta 8 KiB). Si la respuesta permite obtener un detalle, se muestra al usuario sin el body bruto: se eliminan saltos de línea, etiquetas HTML, la API key utilizada, tokens y cadenas largas codificadas, y se recorta el texto a 300 caracteres. No se registra ni el audio ni la respuesta sin depurar.

El texto del mensaje y los MP3 seleccionados se conservan tras el rechazo, según la recuperación implementada en la 11.18.

## Alcance

No contamos con los archivos MP3 ni con las credenciales del servidor del usuario, por lo que **no se ha probado** el resultado con su solicitud real a Vercel. Esta revisión corrige una discrepancia verificable con el SDK y mejora el diagnóstico. Es posible que el HTTP 400 original se deba a otra razón, como un MP3 incompatible. La siguiente prueba debe realizarse primero con **un MP3** y el modelo ya seleccionado (`microsoft/mai-transcribe-2`).

## Comprobaciones

- Prueba simulada de solicitud: URI, body, clave, ID del modelo y las cuatro cabeceras de protocolo.
- HTTP 400 JSON: el detalle del proveedor es visible, pero la API key no lo es.
- HTTP 400 HTML/no JSON: el body no aparece en el mensaje.
- HTTP 413 y demás códigos preservados.
- Compilación Python y verificaciones anteriores de adjuntos, preservación del mensaje y del navegador.
