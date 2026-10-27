# Versión 18.0.0.11.3

Parte del ZIP suministrado, cuya versión era 18.0.0.11.2.

## Cambios

- Las solicitudes de descripción y mejora de notas generan una propuesta persistente sin alterar el borrador. El plan semántico distingue proponer de guardar; no se utilizan expresiones regulares para interpretar esa intención.
- El modelo configurado como redactor produce el texto. El modelo de operaciones realiza una validación separada y registra observaciones internas; no reescribe el texto. La validación es orientativa, no una certificación técnica ni un bloqueo automático del guardado.
- Añadir a vista previa copia el texto exacto mediante las herramientas Python existentes, conservando permisos y deshacer. Una petición explícita de guardar una nota nueva puede guardarla directamente. Las notas existentes requieren aceptar la sustitución.
- Controles de mejora y descarte. Mejorar texto prepara una instrucción editable para que el usuario concrete el cambio y la envíe.
- Identificador único y huella del borrador impiden aceptar dos veces o aplicar una propuesta desactualizada. Con varias notas y sin destino inequívoco, se solicita identificar la nota.
- Estilos Breve y Equilibrado más concisos. La extensión es una instrucción al modelo, no un recorte automático que pudiera perder especificaciones.
- Consumo por modelo permite abrir un registro y consultar texto de la etapa, validación, resultados de herramientas y motivo de fallback. Los errores de proveedor pueden activar el modelo alternativo configurado; la propuesta identifica al autor efectivo.
- Las operaciones comerciales e integrales conservan el motor existente. El flujo de propuestas se aplica a turnos de redacción técnica y descripción, no sustituye toda la lógica de los turnos mixtos.

## Actualización

1. Hacer una copia de seguridad de la base de datos.
2. Sustituir la carpeta `sale_ai_assistant` dentro de la ruta de addons por la del ZIP.
3. Reiniciar Odoo y actualizar el módulo desde Aplicaciones; alternativamente ejecutar `odoo-bin -d BASE -u sale_ai_assistant --stop-after-init` con la configuración habitual del servidor.
4. Volver a iniciar Odoo si corresponde y recargar el navegador para actualizar los assets.

Es imprescindible actualizar el módulo, no solo reiniciar: se añaden campos persistentes.

## Validación realizada

- Sintaxis de 46 archivos Python, parseo de 13 XML y sintaxis del JavaScript.
- Ocho pruebas aisladas ejecutadas sobre los métodos reales de aceptación mediante dobles de ORM/herramientas: copia exacta, actualización, duplicación, borrador cambiado, propuesta antigua, descarte, error de herramienta y acción no válida.
- Pruebas de integración Odoo añadidas para separación de modelos, aceptación, guardado explícito, sustitución, persistencia, descarte y respuesta truncada. Actualizadas dos regresiones cuyo comportamiento anterior era guardar automáticamente.
- No se han ejecutado las pruebas de integración: este entorno no dispone de Odoo, PostgreSQL ni una conexión configurada a Vercel. Tampoco se ha realizado una prueba visual de OWL en Odoo.

## Prueba funcional sugerida

Con el perfil que use Gemini para redacción y estilo Breve, pedir una descripción técnica. Verificar que aparece una propuesta atribuida al redactor y que el borrador no cambia. Mejorarla, aceptar y comparar el texto con la nota guardada. Probar descarte, reapertura del chat y una sustitución de nota existente. Consultar Consumo por modelo para contrastar redacción y validación.

Comando orientativo para integración en una base de pruebas con Odoo 18:
`odoo-bin -d BASE_PRUEBAS -u sale_ai_assistant --test-enable --test-tags /sale_ai_assistant --stop-after-init`
