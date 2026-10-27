# Versión 18.0.0.11.9

Retirados los botones Guardar edición y Revisar con IA, las acciones de servidor
save/review y la ruta de revisión opcional de la descripción. Una interfaz antigua
que intente esas acciones recibirá «Acción de propuesta no válida».

Se mantienen tres botones:
- Añadir a vista previa (Sustituir nota en vista previa si corresponde): incorpora
  exactamente la versión editada, con los controles de aceptación existentes.
- Mejorar texto: conserva las ediciones como punto de partida y prepara el campo
  de mensaje para que indiques la mejora. La IA se llama al enviar ese mensaje.
- Descartar: elimina la propuesta pendiente sin cambiar el presupuesto.

Se mantiene el editor de texto. No hay autoguardado ni acción independiente para
guardar una edición. Antes de salir, utiliza Añadir/Sustituir o Mejorar texto si
quieres conservar lo editado. Las propuestas e historiales de versiones anteriores
no se borran; el panel ya no muestra observaciones de la revisión retirada.

La generación normal de descripciones sigue SIN revisión ni corrección automáticas.
En la ruta habitual se realizan planificación y redacción; los mecanismos de
respaldo existentes pueden añadir llamadas. La revisión anterior a la creación
del presupuesto, que es un paso distinto, no se modifica.

## Actualización
Sustituir la carpeta sale_ai_assistant, reiniciar Odoo, actualizar el módulo desde
Aplicaciones y recargar el navegador para renovar los recursos de interfaz.

## Comprobaciones
Pasaron seis comprobaciones aisladas de las acciones/botones, seis de diagnóstico,
ocho del guardado existente, las comprobaciones del editor y la sintaxis Python,
XML y JavaScript. Se actualizaron las pruebas Odoo de propuestas, pero no se han
podido ejecutar sin una instancia Odoo. Pendiente verificar la interfaz y la
integración real con Vercel en el entorno del usuario.
