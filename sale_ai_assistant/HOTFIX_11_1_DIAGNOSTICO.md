# 18.0.0.11.1 — protección del envío y diagnóstico

Se mantiene la versión multimodelo, sus herramientas, la configuración y los datos existentes.

- **Nueva protección en el envío**: las excepciones Python inesperadas del agente se aíslan en un `cr.savepoint()`. El mensaje del usuario se conserva y se devuelve un aviso normal al chat, sin dejar el RPC en error.
- **Reintento protegido**: la misma protección se aplica a `assistant_panel_retry`, sin reenviar el mensaje del usuario.
- **Registro de consumo no bloqueante**: si falla el guardado de las estadísticas de llamadas por modelo, se revierte esa escritura auxiliar y se conserva la conversación. El error se registra completo en el log del servidor; puede perderse ese registro de consumo.
- **Diagnóstico**: buscar `sale_ai_assistant: unhandled AI generation error` o `sale_ai_assistant: metering failed` en el log de Odoo y recuperar el traceback completo que sigue.

## Importante

El mensaje `RPC_ERROR` del navegador por sí solo no identifica la excepción original.
Esta entrega protege el canal de envío y facilita el diagnóstico, pero NO demuestra
que la causa sea necesariamente el registro de consumo. Si vuelve a fallar, enviar
el traceback de Odoo/Python generado en el servidor. No compartir claves API.

## Prueba rápida

1. Sustituir la carpeta del módulo, reiniciar Odoo, actualizar a 18.0.0.11.1 y recargar los assets.
2. Abrir el mismo perfil multimodelo y enviar la petición técnica inicial.
3. Si el agente devuelve un error, el mensaje debe quedar guardado para `Reintentar` sin duplicarlo.
4. Comprobar el log del servidor y remitir la excepción si sigue fallando.

Tests de regresión: `test_sale_ai_multimodel_recovery.py` (requieren Odoo 18 para su ejecución).
