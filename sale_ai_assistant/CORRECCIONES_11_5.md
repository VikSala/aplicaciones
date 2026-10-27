# 18.0.0.11.5

Esta versión sustituye a 11.4 para las siguientes pruebas.

## Presentación adaptada a cada presupuesto
Se elimina el reconocimiento automático IE/TLMEF y su modificación de secuencias y descripción TOTAL. También se elimina la instrucción general que imponía ese orden. El asistente interpreta la presentación según cada petición y puede proponer una estructura; los cambios requieren autorización en la conversación. Se conservan las herramientas habituales de modificación de líneas.

## Contexto conservador
Se retira toda la deduplicación introducida en 11.4: no se omiten mensajes repetidos ni se sustituyen fragmentos del historial por referencias. Se conserva el modo de contexto configurado: en modo experimental se envía el historial completo; en modo acotado sigue aplicándose el límite previamente configurable, seleccionando mensajes completos.
Las nuevas confirmaciones de guardado siguen siendo breves. El texto aprobado permanece en la propuesta histórica del chat y en la nota del borrador; la confirmación nueva no vuelve a copiarlo entero.

## Estimaciones y validación
Se explicita que el precio orientativo debe proceder de datos e hipótesis y diferenciarse del precio definitivo que decida el usuario. No existe un precio objetivo impuesto.
Se conserva la revisión por el redactor cuando el validador devuelve observaciones, con una única pasada de corrección. No se modifica en esta versión su funcionamiento ni se garantiza que detecte o resuelva todos los problemas.

## Comprobaciones realizadas
- Ejecución del método real de construcción de contexto con dobles de entorno: conserva textos largos, duplicados y orden de conversación.
- Comparación AST: el método de alta de líneas coincide con el del módulo original adjunto, sin la normalización de 11.4.
- Ocho pruebas aisladas del flujo de aceptación, descarte y protección frente a cambios/duplicados.
- Sintaxis Python, XML, JavaScript e integridad del ZIP.
No se han ejecutado pruebas de integración en Odoo/PostgreSQL o llamadas a Vercel. No se ha medido una reducción de latencia.

## Actualización
Sustituir completamente la carpeta sale_ai_assistant, reiniciar Odoo, actualizar el módulo desde Aplicaciones y recargar el navegador. Si se instaló 11.4, esta actualización no revierte cambios que esa versión hubiera aplicado a presupuestos existentes.
Los documentos 11.3 y 11.4 del paquete son históricos; este documento describe las correcciones vigentes.
