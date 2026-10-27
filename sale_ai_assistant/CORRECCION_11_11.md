# Versión 18.0.0.11.11 — productos, notas y orden de incorporación

## Destino de las descripciones

El planificador recibe en note_line_id únicamente 0 y los IDs de notas reales del
borrador, mediante enum. Los IDs de productos y secciones quedan fuera. Las
instrucciones distinguen la descripción comercial de un producto de una nota.

Si el proveedor incumple el enum y devuelve un ID positivo cuando no existe ninguna
nota, la operación se trata como creación de una nota nueva. No se modifica el
producto ni su descripción. Cuando sí hay notas y el destino es inválido, se
mantiene el rechazo con un mensaje específico, sin escoger otra nota por suposición.

El destino 0 significa siempre nota nueva. Se elimina la conversión automática
que sustituía la única nota existente. Para sustituir una nota se necesita su ID
explícito, seleccionado por el planificador conforme a la petición. Al mejorar
una propuesta pendiente se le indica conservar su destino, incluido 0.

## Orden

La vista previa muestra sequence/id, no una agrupación fija por producto/nota.
Antes, add_draft_lines aceptaba una sequence elegida por el modelo: podía insertar
un producto por delante de una nota ya incorporada. Ahora las altas se añaden al
final, manteniendo el orden del lote. El esquema de alta ya no ofrece sequence;
si un proveedor antiguo la envía, se omite. Se conserva sequence en
update_draft_line para cambios de posición pedidos por el usuario.

Pedir una descripción genera una propuesta pendiente, no una línea del borrador.
El orden de incorporación se establece al aceptar la propuesta. Por tanto:
- Producto incorporado y después nota aceptada: producto → nota.
- Nota aceptada y después producto incorporado: nota → producto.
- Propuesta aún pendiente y producto incorporado: solo el producto existe todavía
  en la vista previa. Los controles de propuesta desactualizada siguen vigentes;
  si cambió el borrador desde su generación, hay que regenerarla antes de aceptar.

No se reordenan retrospectivamente presupuestos ni se imponen nombres «TOTAL» o
reglas basadas en códigos. Se mantienen tres botones y la redacción sin validación
ni corrección automáticas.

## Instalación

Sustituir la carpeta sale_ai_assistant, reiniciar Odoo, actualizar el módulo desde
Aplicaciones y recargar el navegador.

## Validación

Pasaron tres pruebas aisladas nuevas de ambas secuencias de incorporación, altas
en lote y recuperación del ID de producto cuando no hay notas; nueve de destino
incluyendo creación sin sustituir notas existentes; seis de diagnóstico; seis de
acciones; ocho de aceptación existentes y las comprobaciones del editor. Python y
XML validados. Las pruebas aisladas usan dobles de ORM, no una instancia Odoo.

Se amplían las pruebas Odoo con producto primero y creación de nota nueva junto a
una existente. No se han ejecutado aquí. Pendiente probar ambos recorridos en Odoo
con el proveedor real. No se ha observado el JSON original del incidente: se corrige
la ruta que admite esa confusión y el control del orden, sin atribuir retrospectivamente
un identificador concreto al fallo de la captura.
