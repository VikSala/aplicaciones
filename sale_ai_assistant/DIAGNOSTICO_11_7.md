# Versión 18.0.0.11.7 — diagnóstico de fallos del agente

## Cambios

- Cada ejecución del agente tiene una referencia única, compartida por sus llamadas.
- Los errores capturados durante planificación, redacción, validación y ejecución
  incluyen esa referencia en el chat, también cuando ya hay cambios provisionales.
- En Ventas → Asistente IA → Consumo por modelo se puede buscar la referencia.
  Se muestran etapa, modelo, operación, tipo de excepción y duración.
- Se distinguen registros de llamada y fallo del turno. El fallo del turno tiene
  su propio tiempo transcurrido; su latencia de llamada es cero para no duplicar
  las duraciones. Un fallo de turno no representa otra petición ni otro coste.
- Los intentos fallidos registran el tiempo medido, aunque no haya tokens de uso.
  Tokens y coste cero en un intento fallido significan que no se recibieron esos
  datos; no garantizan que el proveedor no lo haya facturado.
- El servidor registra los fallos a nivel ERROR con traceback y referencia.
  Las llamadas correctas se registran a nivel INFO con duración y referencia.
  No se añaden prompts, cabeceras ni cuerpos HTTP al registro diagnóstico.
  El traceback puede contener el mensaje de la excepción: revisar antes de compartir.
- Antes de cada intento, incluido el modelo alternativo, se recalcula el tiempo
  restante y se acota el timeout. No se añaden reintentos nuevos.

## Instalación y prueba en Odoo 18

1. Sustituir la carpeta sale_ai_assistant, reiniciar Odoo y actualizar el módulo
   desde Aplicaciones. La actualización es necesaria por los campos nuevos.
2. Recargar el navegador y repetir la consulta en una conversación de prueba.
3. Si falla, copiar la referencia del chat. Buscarla en Consumo por modelo
   (el menú requiere permisos de responsable de Ventas).
4. Abrir el registro «Fallo del turno» y las llamadas con la misma referencia.
   Compartir etapa, operación, modelo, tipo de excepción y tiempos.
5. Para el detalle técnico, buscar la referencia en el registro del proceso Odoo
   (archivo, contenedor o servicio según el despliegue). El traceback completo
   está en el servidor, no en el chat ni en los campos de Consumo por modelo.

## Interpretación y límites

La etapa y el modelo son el contexto del fallo, no una atribución de culpa.
«Procesamiento de respuesta» indica que la llamada regresó y se estaba
interpretando el resultado. «Ejecución de herramienta» identifica una operación
posterior. Una llamada fallida puede deberse a red, rechazo o incompatibilidad;
el diagnóstico concreto debe leerse junto con la excepción.

Esta versión instrumenta la ruta del agente existente y no demuestra ni corrige
por sí sola la causa del fallo intermitente de la captura. Errores anteriores al
inicio del agente, pérdida de conexión del navegador, caída del trabajador o
fallos fuera del bloque protegido pueden impedir que aparezca la referencia.
Si falla la escritura del consumo, se conserva el registro del servidor como
alternativa; no se garantiza persistencia en una transacción que luego se revierta.
El timeout de red no es un corte estricto del tiempo total de pared.
No se han cambiado modelos, prompts de calidad, historial ni editor de propuestas.

## Validación realizada

- Seis pruebas aisladas ejecutando las funciones reales extraídas del motor:
  medición correcta, fallback con tiempo restante, agotamiento de tiempo,
  excepción inesperada sin reintento, fallo de procesamiento y fallo de ambos modelos.
- Ocho pruebas aisladas existentes del guardado de propuestas.
- Comprobaciones existentes del editor de propuestas.
- Sintaxis Python y XML de todo el módulo.

No se dispone aquí de una instancia Odoo 18 ni de acceso a los servicios del
usuario. La actualización de vistas, permisos, persistencia e integración real
con Vercel quedan pendientes de prueba en ese entorno.
