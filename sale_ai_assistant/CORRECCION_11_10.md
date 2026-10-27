# Versión 18.0.0.11.10 — aviso concreto y comprobación previa de la nota

## Cambios

Los UserError de Odoo capturados durante el turno del agente se muestran con su
mensaje concreto y la referencia del diagnóstico. Las excepciones inesperadas
siguen mostrando un aviso genérico; el detalle técnico continúa en el servidor.

El registro «Fallo del turno» de Consumo por modelo incorpora «Mensaje del error»
para UserError y GatewayError. Abrir el registro permite leer el motivo sin
necesidad de acceder al log del servidor. No se reconstruyen mensajes de fallos
anteriores a esta versión.

Tras la planificación y antes de llamar al redactor se comprueba:
- que el borrador se pueda editar;
- que el identificador sea válido y corresponda a una nota del borrador;
- si no se indica destino, que no haya varias notas entre las que elegir.

Se reutiliza la misma comprobación al guardar. No se elimina la protección ni se
elige arbitrariamente una nota. Se conserva el comportamiento existente: con una
sola nota y destino cero se propone sustituir esa nota; sin notas se propone una
nueva. Cuando hay varias notas sin destino, se pide indicar cuál revisar.

El diagnóstico marca esta fase como «comprobación del destino de la nota». En un
fallo previo a la redacción, el modelo asociado es el último utilizado para
planificar, no evidencia de una llamada al redactor. La planificación sigue siendo
necesaria; lo que se evita en esos casos es la llamada posterior de redacción.

Se mantienen los tres botones de la 11.9 y la generación sin revisión ni corrección
automáticas. No se cambian modelos, precios ni límites de tiempo.

## Actualización

Sustituir sale_ai_assistant, reiniciar Odoo, actualizar el módulo desde Aplicaciones
y recargar el navegador. Es necesario actualizar por el nuevo campo de diagnóstico.

## Comprobaciones y límites

Han pasado ocho comprobaciones aisladas nuevas del destino y tratamiento de errores,
seis de diagnóstico, seis de acciones de propuesta, ocho de aceptación existentes
y las comprobaciones del editor. Sintaxis Python/XML validada.

No se dispone de una instancia Odoo/Vercel para verificar la integración. El cambio
no identifica retrospectivamente cuál de los UserError produjo la captura: el
mensaje concreto quedará disponible si vuelve a ocurrir. Las restricciones del
borrador se conservan; un aviso de varias notas seguirá requiriendo aclarar destino.
