# Versión 18.0.0.11.12

## Comentarios

La vista previa muestra COMENTARIOS. El campo interno description del borrador se
conserva por compatibilidad y ahora admite texto multilínea (hasta 5000 caracteres
cuando lo modifica el asistente). Al crear el presupuesto se copia a
sale.order.x_comentarios, sin rellenar client_order_ref con ese texto.

Se utiliza el campo custom existente; el módulo no crea ni redefine x_comentarios.
Si hay comentarios y ese campo falta, no es Char/Text o es un cálculo sin inversa,
se muestra un error antes de crear el presupuesto. Los comentarios no se descartan
silenciosamente. Si está vacío no se exige el campo ni se sobrescribe su valor
predeterminado. Los borradores anteriores conservan su texto, ahora bajo Comentarios.
Los presupuestos ya creados no se modifican retrospectivamente.

## Vista previa

Se retiran de cada producto las dos filas de origen/evidencia del precio, incluidos
«Precio de lista Odoo» y su explicación orientativa. Los datos siguen guardados y
disponibles para la lógica interna; cantidades, unidades, importes y descuentos
siguen visibles.

## Botones y mensaje

Producto, Sección, Nota, Deshacer y Crear presupuesto comparten una sola fila.
El botón verde es compacto y conserva la revisión/confirmación existente antes
de crear el presupuesto. La fila no se parte; si no cabe en una pantalla muy
estrecha permite desplazamiento horizontal.

El mensaje crece y se contrae con su contenido. Límite: 240 píxeles o el 35 % de
la altura de la ventana si resulta menor, con un mínimo de 60 píxeles para ese
límite. Al superarlo aparece desplazamiento vertical. Se ajusta al escribir/pegar,
al actualizar el componente, al cambiar el ancho del panel y al redimensionar la
ventana. Se mantiene el envío y el atajo de salto de línea existentes.

Se mantienen los tres botones de propuesta y la redacción sin revisión/corrección
automáticas.

## Actualización

Sustituir sale_ai_assistant, reiniciar Odoo, actualizar desde Aplicaciones y
recargar el navegador (recarga completa para renovar JS/CSS). La actualización
incluye el cambio del campo del borrador a texto.

## Verificación

Seis pruebas aisladas de comentarios, seis de acciones de propuesta, comprobación
estructural de los cinco botones en una fila y pruebas de la función real de
expansión con medidas DOM simuladas. Sintaxis Python, XML y JavaScript validada.
No ha sido posible ejecutar una prueba visual en navegador por falta del binario
de Chromium en este entorno. Falta probar interfaz, compilación SCSS por Odoo,
actualización de la base de datos y creación con x_comentarios en la instalación real.
