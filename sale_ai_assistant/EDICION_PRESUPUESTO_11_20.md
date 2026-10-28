# Asistente IA de Ventas · Edición de presupuestos (18.0.0.11.20)

## Alcance

- Se mantiene el flujo de **Crear presupuesto** de las versiones anteriores.
- En la ficha de un `sale.order` con `state = draft`, el panel del asistente presenta un botón circular **Actualizar / cargar PV** (icono de recarga), situado entre **Deshacer** y **Crear/Actualizar presupuesto**.
- **Solo** pueden utilizarlo administradores de Ventas (`sales_team.group_sale_manager`), como el resto del asistente. La petición se valida de nuevo en Odoo, para la compañía activa y con los accesos ORM existentes.
- **No** está disponible para presupuestos enviados (`sent`), pedidos confirmados (`sale`) o cancelados (`cancel`).
- Al cargar un PV, se copia su cliente, tarifa, moneda, campo `x_comentarios` si existe y sus líneas/secciones/notas al **borrador provisional IA**. Todavía no cambia nada en `sale.order`.
- El botón final pasa a **Actualizar presupuesto**. La IA modifica siempre el borrador provisional: solo el usuario confirma la escritura de datos reales.

## Conversación actual y recarga

- Si hay un chat con trabajo previo, el navegador pide confirmación antes de cambiar de PV. Se **archiva** la sesión con su historial, en lugar de borrarla.
- Los mensajes sin enviar y adjuntos todavía seleccionados se avisan y se descartan **solo al confirmar** el cambio.
- Un chat vacío puede descartarse automáticamente.
- Si se pulsa la recarga estando ya en la edición de ese PV, se ofrece **archivar la edición y recargar desde Odoo**; al cancelar no se modifica ni el borrador ni el presupuesto.
- El botón para una conversación nueva también archiva (en vez de destruir) una sesión de edición.

## Qué se guarda

- En `sale.ai.session`: `edit_order_id` y `edit_baseline_json` (instantánea original).
- En `sale.ai.draft.line`: `source_sale_line_id` (identificador **entero** de la línea Odoo, estable incluso si otro usuario elimina el registro).
- El historial Deshacer del borrador incluye esa relación de origen.
- Las actualizaciones se calculan por diferencia de campos del cliente, tarifa, comentarios y de cada línea. Las líneas sin cambios conservan su ID de `sale.order.line`.
- Las líneas nuevas se crean y solo las retiradas explícitamente del borrador se eliminan. No se borran y recrean todas las líneas.
- **No** se alteran explícitamente otros campos de `sale.order` como fecha, direcciones, condiciones de pago, comerciales, referencias, etc. Odoo puede recalcular dependencias como impuestos al cambiar cliente/producto.
- No se convierte en otro tipo una línea existente: para ello se debe eliminar la línea provisional y añadir otra.

## Cambios concurrentes

1. El asistente guarda una instantánea original al cargar el PV.
2. Al pulsar Actualizar, compara esa instantánea con Odoo y con los cambios de la vista previa; muestra los campos en conflicto (antes, ahora, propuesta) y los cambios ajenos que preservará.
3. Si se acepta **Sobrescribir mis campos**, solo los campos comerciales modificados expresamente prevalecen. Las líneas añadidas por otras personas se preservan.
4. La operación final obtiene un bloqueo SQL sobre el presupuesto y sus líneas, vuelve a validar su estado y las dos firmas de revisión y aplica un parche en una única transacción.
5. Si el presupuesto ha cambiado entre revisión y confirmación, se cancela el guardado. Si una línea que se quiere modificar fue eliminada en Odoo, se exige recargar; no se recrea en silencio.
6. Los cambios guardados pasan a ser la nueva base de la misma sesión, que **permanece activa** y permite revisiones sucesivas.
7. Si la **moneda** del presupuesto cambia después de cargarlo, es obligatorio recargarlo antes de escribir precios.

## Instalación / validación

1. Usar primero en una **base de pruebas**, con copia de seguridad.
2. Sustituir carpeta `sale_ai_assistant` por la de este ZIP y actualizar el módulo desde Odoo 18 (reiniciar el servicio / actualizar apps si es necesario).
3. Recargar activos JS del navegador (recarga completa).
4. Probar crear PV nuevo como antes; abrir una ficha de PV en `draft`, pulsar el icono de recarga, editar la cantidad y actualizar tras revisar el resumen.
5. Probar recarga del mismo PV y otro PV con conversación empezada.
6. Probar concurrentemente con dos administradores editando el mismo PV y comprobar el aviso de conflicto. Probar cambiar su estado a `sent` y confirmar que la actualización se bloquea.
7. Probar añadir, eliminar y conservar líneas, `x_comentarios` y Deshacer provisional.

### Comprobaciones incluidas

- `python checks/verify_quote_edit_11_20.py` (comparación y conflictos, sin arrancar Odoo)
- Tests Odoo (`tests/test_sale_ai_quotation_edit.py`, etiqueta `post_install`) para ejecutarse con base de datos de test.
- Se ejecutaron comprobaciones de sintaxis de Python/JS y XML, junto a los verificadores standalone heredados.

**No se ha ejecutado una prueba de integración contra la base de datos Odoo real del usuario**. Antes de producción conviene verificar las recalculaciones específicas de la instalación y de otros módulos sobre `sale.order`/`sale.order.line`.

> Corrección de compatibilidad Odoo 18: consultar `HOTFIX_11_21_ODOO_18.md`.
