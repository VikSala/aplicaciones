> Documento histórico de 11.4. La versión 11.5 retira la ordenación automática y la deduplicación descritas aquí. Consultar CORRECCIONES_11_5.md.

# 18.0.0.11.4 — Coherencia y presentación comercial

## Cambios
- Criterios compartidos entre conversación, redactor, validador y revisión final: alcance confirmado, alternativas separadas, ausencia de calibres definitivos sin datos, respeto a referencias y ofertas a precio cerrado. Se prohíbe asumir exclusiones o duplicar conceptos en la justificación comercial.
- Cuando la validación produce observaciones, el propio modelo redactor realiza una corrección antes de presentar la propuesta. El texto corregido sigue sujeto a aceptación. La corrección tiene una sola pasada para evitar bucles; no constituye una certificación técnica. Si falta tiempo o la respuesta está incompleta, no se guarda.
- El validador recibe también el estado del borrador, además de la conversación.
- Al añadir líneas, se reconoce exclusivamente el patrón de tres líneas del proyecto: IE a cero y cantidad uno, una nota, TLMEF con precio positivo y cantidad uno. Se ordenan como referencia, nota y TOTAL. Solo se sustituye la descripción de TLMEF si coincide con la referencia, el nombre por defecto o TOTAL; se preservan descripciones comerciales personalizadas. El ajuste queda dentro de la misma operación de deshacer. Otros presupuestos conservan su estructura.
- Las confirmaciones nuevas dejan de repetir la nota entera. El contexto elimina mensajes de asistente exactamente duplicados y sustituye copias largas del texto ya disponible en el estado actual por una referencia. Se conservan las instrucciones del usuario. No se recorta arbitrariamente el historial.

## Rendimiento
La reducción de contexto evita parte del procesamiento repetido. No se promete una reducción concreta de segundos: no se ha medido con Vercel. Los turnos con observaciones requieren una llamada adicional de corrección y pueden tardar más. La prioridad de esos turnos es resolver los problemas detectados.

## Validación
Sintaxis Python, XML y JavaScript comprobada. Doce pruebas aisladas ejecutadas: ocho sobre aceptación y cuatro sobre estructura comercial y preservación de otros presupuestos. No se dispone de Odoo/PostgreSQL ni Vercel para ejecutar integración o medir latencia. Las instrucciones a modelos necesitan validarse con conversaciones reales; no son garantías deterministas de calidad.

## Instalación y prueba
Sustituir la carpeta sale_ai_assistant, reiniciar Odoo, actualizar el módulo desde Aplicaciones y recargar el navegador. Probar en una base de pruebas antes de producción.
Repetir el ejemplo adjunto: descripción, protecciones dentro del subcuadro, valoración y productos IE/TLMEF. Comprobar que la envolvente se trata como alternativa pendiente si no está confirmada, que no se presentan calibres provisionales como definitivos y que la estructura final queda referencia → nota → TOTAL. Confirmar que Deshacer revierte también los cambios de orden.
