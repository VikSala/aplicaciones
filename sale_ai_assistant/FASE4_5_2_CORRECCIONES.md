# Fase 4 — corrección de ejecución de herramientas (18.0.0.5.2)

Esta actualización se instala sobre 18.0.0.5.1; no requiere desinstalar el módulo ni borrar conversaciones.

## Problema corregido

La IA podía contestar que actualizaría el borrador sin ejecutar herramientas ORM. El backend aceptaba esa respuesta de texto como si la petición hubiera concluido, aunque la vista previa no se hubiera modificado.

## Cambios

- Primer intento con herramientas en modo automático, manteniendo compatibilidad con modelos anteriores.
- Si el usuario solicita expresamente un cambio y el ORM no lo registra, el motor vuelve a pedir una herramienta, usando `tool_choice=required` en intentos acotados.
- El motor comprueba los cambios reales, una cantidad global fijada por el usuario y la actualización de notas técnicas cuando se solicita expresamente.
- Nueva herramienta `append_draft_line_text` para ampliar una nota técnica existente sin reemplazar su texto ni duplicar el párrafo.
- Respuestas de confirmación generadas a partir de operaciones realmente guardadas; si faltan cambios, se indican como pendientes.
- Detección de cambios en contenido de líneas para impedir el reintento inseguro tras una interrupción del proveedor.
- No se crea `sale.order`; solo se editan los modelos provisionales del chat.

## Prueba recomendada en Odoo

1. Abrir una conversación activa existente con nota técnica y base provisional 0 €.
2. Solicitar: `Añade una partida económica orientativa de 1.100 € al presupuesto provisional`.
3. Comprobar en vista previa que existe una línea económica y la base se actualiza.
4. Solicitar: `Añade las protecciones eléctricas y actualiza la descripción técnica. Cambia el importe global a 1.290 €.`
5. Comprobar que la nota anterior se conserva con las protecciones añadidas, que no se duplican líneas y que la base muestra 1.290 €.
6. Probar un modelo incompatible con herramientas obligatorias: el asistente no debe afirmar que guardó cambios inexistentes.

**Validación realizada**: sintaxis Python, XML y ZIP, y pruebas de lógica de detección. Las pruebas ORM automatizadas quedan incluidas, pero requieren ejecutarse en un servidor Odoo 18 con `--test-enable`. No se han ejecutado en este entorno.
