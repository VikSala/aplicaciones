# Hotfix 18.0.0.11.2 — Traducciones del agente multimodelo

## Fallo corregido

`UnboundLocalError: cannot access local variable '_' where it is not associated with a value` en `models/sale_ai_engine.py`, método `_ai_generate_for`.

Python trataba `_` como variable local por dos asignaciones a resultados de `invoke()`, ocultando la función de traducción `odoo._` utilizada para construir los mensajes de éxito y error.

## Cambios

- Renombrados los dos destinos `_` como `_market_model_used` y `_synthesis_model_used`.
- Conservada la función `_()` de traducción para avisos de operación verificada y errores.
- Añadidas pruebas contra regresiones de sombreado y para recuperar errores inesperados del proveedor sin volver a fallar en las traducciones.
- Sin cambios de esquema, permisos, configuración, herramientas, perfil o interfaz.

## Instalación y prueba

Actualizar el módulo desde 18.0.0.11.1 a 18.0.0.11.2 sin desinstalar; reiniciar Odoo. Volver a la conversación afectada y comprobar la vista previa antes de pulsar «Reintentar respuesta». El mensaje original debe seguir guardado.

Comprobaciones estáticas realizadas fuera de Odoo; la validación funcional requiere Odoo 18 y conexión a Vercel.
