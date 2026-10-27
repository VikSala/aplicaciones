# Fase 4 — disponibilidad de Vercel y transparencia de precios externos (18.0.0.5.3)

Actualización sobre 18.0.0.5.2, sin reinstalación y sin modificar el esquema de base de datos.

## Correcciones

- Se distingue el error HTTP 503 (servicio Vercel/proveedor temporalmente no disponible) de la carencia de herramientas de búsqueda web. El panel mantiene el mensaje original y permite reintentar sin duplicar el mensaje del usuario cuando no hubo modificaciones guardadas.
- Para errores 502/504 se devuelve un diagnóstico de disponibilidad más específico.
- Ante solicitudes de precios actuales o precios medios del mercado, se muestra una advertencia explícita: **no hay búsqueda en Internet implementada en este módulo**. El asistente puede consultar Odoo o estimar con supuestos señalados, pero no afirmar que verificó precios externos.
- La advertencia se añade desde el backend a la respuesta final incluso cuando la confirmación de cambios del borrador sustituye al texto libre del modelo.
- No se implementa acceso web ni se incrementa el número de llamadas a proveedores; la integración de fuentes externas se evaluará en una fase posterior.

## Pruebas

- La solicitud de precios medios del mercado recibe advertencia aunque el ORM haya guardado una partida provisional.
- El HTTP 503 no se presenta como prueba de una incapacidad para navegar.
- Un fallo del proveedor conserva el mensaje del usuario y comunica separadamente los límites de búsqueda web.

No hay cambios en `sale.order`; la Fase 4 sigue usando exclusivamente borradores provisionales.
