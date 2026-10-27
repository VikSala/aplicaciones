# Versión 18.0.0.11.8 — revisión opcional de descripciones

## Uso

La redacción normal deja de llamar automáticamente al validador y de ejecutar
la posterior corrección. En la ruta habitual de una descripción quedan la
planificación y la redacción. Se mantienen el modelo redactor, sus instrucciones,
la comprobación de texto vacío/truncado y las protecciones de aceptación.
Los reintentos y el modelo de respaldo existentes pueden añadir llamadas.
No se garantiza una reducción concreta de segundos sin medir en Odoo/Vercel.

La propuesta incorpora el botón **Revisar con IA**:

1. Guarda primero las ediciones manuales del texto, sin tocar el presupuesto.
2. Solicita una revisión al modelo de **Planificación y operaciones de Odoo**.
   No utiliza el campo «Revisión antes de crear presupuesto», que mantiene su
   función anterior. Si el perfil usa el mismo modelo para redactar y operar,
   será una segunda consulta al mismo modelo, esta vez por decisión del usuario.
3. Muestra las observaciones y el nombre del modelo que realmente respondió.
   No pasa por planificación ni reescribe automáticamente. Una revisión normal
   requiere una llamada; un fallo puede activar el respaldo ya configurado.
4. Conserva el texto, su autor, la línea de destino y la huella del borrador.
   El usuario puede editarlo, pedir una mejora o aceptarlo tal como está.

La revisión distingue errores que requieren corrección de comprobaciones técnicas
pendientes. No garantiza exactitud técnica ni sustituye la aceptación del usuario.
Si se cambia el texto, las observaciones anteriores dejan de mostrarse como
vigentes; al guardar la edición se eliminan de la propuesta. El historial conserva
la revisión anterior como parte de lo ocurrido en la conversación.

El botón rechaza propuestas de otra versión/pestaña o cuyo borrador haya cambiado.
Si la revisión falla, conserva las ediciones guardadas y muestra un aviso; los
fallos capturados por el agente mantienen la referencia diagnóstica de la 11.7.
Se puede volver a pulsar Revisar con IA. El error no dispara automáticamente
una nueva redacción ni la aceptación de la propuesta.

## Actualización

Sustituir la carpeta sale_ai_assistant, reiniciar Odoo, actualizar el módulo desde
Aplicaciones y recargar el navegador para renovar los recursos de interfaz.

## Validación

Ejecutadas ocho comprobaciones aisladas de revisión opcional: texto editado,
una sola llamada de revisión, preservación del contenido/destino/huella,
invalidez por edición, conservación si no cambia el texto, bloqueo de versiones
antiguas/borradores cambiados, fallo y respuesta vacía/truncada. Incluyen una
comprobación estructural de que la rama de redacción solo invoca al redactor.
También pasaron las seis pruebas aisladas de diagnóstico, ocho del guardado
existente, comprobaciones del editor y sintaxis de Python, XML y JavaScript.

Se actualizan y amplían las pruebas de integración Odoo para exigir dos llamadas
(planificación + redacción) y una llamada de revisión opcional. Esas pruebas no
se han ejecutado aquí porque no hay una instancia Odoo disponible.
Queda pendiente comprobar instalación, interfaz y funcionamiento con Vercel.
