# 18.0.0.11.18 — Errores MP3 y alineación del botón «+»

## Problema reproducido en la interfaz anterior

La versión 11.17 vaciaba el texto antes de la llamada RPC. Si fallaba `assistant_panel_send` durante la preparación del adjunto (incluida la transcripción de un MP3), el cliente intentaba refrescar la conversación y dejaba el campo de escritura vacío, aunque el envío se hubiese cancelado. El usuario solo veía el cuadro genérico de «Odoo Server Error» y una notificación imprecisa. Esta pérdida del borrador es verificable en el código anterior, con independencia del error original del proveedor.

## Cambios

- El servidor contiene las excepciones de procesamiento de adjuntos dentro de un `savepoint` y responde normalmente con `file_error`; la transacción cancela adjuntos y metadatos parciales de ese intento, no guarda el mensaje y no inicia la redacción.
- El cliente presenta el motivo del error junto al campo de escritura y en una notificación. Conserva **el texto y la cola de archivos** para reintentar. Solo limpia los archivos si el servidor confirma un envío correcto.
- También conserva el borrador cuando el error se produce antes de llegar a nuestro módulo, por ejemplo por la red, proxy u Odoo. En esos casos no siempre se puede conocer la causa del servidor; se recomienda revisar los logs de Odoo, buscando `sale_ai_assistant` o el traceback de la llamada `assistant_panel_send`.
- El identificador del modelo de transcripción por compañía permanece editable, con compatibilidad con `microsoft/mai-transcribe-2`. El protocolo REST nativo de transcripción se ha contrastado con el SDK de Vercel. No se modifica el modelo de redacción.
- Se elimina una comprobación local de cabeceras MP3 que descartaba audios por no comenzar con ID3/sincronización MPEG. El archivo se entrega a Vercel como `audio/mpeg`, y corresponde al proveedor detectar si realmente lo puede decodificar. No se instalan decodificadores en Odoo.
- El botón «+» utiliza un icono FontAwesome con centrado flex horizontal y vertical; la caja del compositor vuelve a `align-items: center` para mantenerlo alineado también en mensajes de varias líneas.

## Limitaciones y pruebas

Esta revisión **no permite conocer de forma retrospectiva la causa original** del RPC_ERROR de la captura: no se dispone del traceback Python del servidor ni de los MP3 de prueba. Si Vercel rechaza un MP3, la interfaz mostrará un HTTP 400/413/415/422/etc. según el caso. Si es un error interno, el servidor registrará el traceback con `sale_ai_assistant` y el ID de sesión. Ante un HTTP 413 del proxy antes de Odoo, no es posible recuperar el diagnóstico desde Python.

Verificado con tests locales simulados: errores del proveedor, formulario conservado cuando se devuelve `file_error`, conservación del mensaje cuando el RPC lanza excepción, envío correcto, esquema Vercel y SCSS/XML/JS. **Pendiente prueba en Odoo 18 real y con credenciales Vercel reales.**

Para actualizar: reemplazar la carpeta `sale_ai_assistant` por la nueva, reiniciar el servicio Odoo, actualizar el módulo desde Aplicaciones y refrescar los recursos del navegador (recarga completa). No desinstalar el módulo.
