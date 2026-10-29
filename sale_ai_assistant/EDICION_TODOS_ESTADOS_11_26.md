# Asistente IA Ventas — Actualización en cualquier estado (18.0.0.11.26)

Partiendo de la versión 11.25, el botón de cargar/recargar presupuesto aparece en el formulario de `sale.order` de la compañía activa independientemente del campo `state`. Se permite trabajar con presupuestos en `draft`, enviados (`sent`), pedidos confirmados (`sale`) y cancelados (`cancel`), así como estados adicionales de módulos personalizados.

## Cambios

- Se elimina el filtro de estado tanto en la detección JavaScript del formulario como en la carga, validación previa y actualización definitiva del servidor.
- La vista previa no cambia `state`: únicamente se escriben los campos seleccionados y las diferencias de líneas comerciales, como antes.
- La confirmación de actualización muestra el estado actual de Odoo. Si se trata de un pedido confirmado o cancelado, avisa de revisar entregas y facturas relacionadas. **No bloquea por estado.**
- La instantánea de concurrencia registra `state`. Si cambia después de cargar la propuesta, el diálogo informa de la modificación. Si vuelve a cambiar entre preflight y guardado, la firma impide guardar sin revisar de nuevo. Las sesiones anteriores sin campo `state` en su instantánea siguen siendo compatibles.
- Se mantienen los permisos existentes de administrador de Ventas, compañía activa y sesión propia, la comprobación de firmas y el bloqueo de concurrencia. No se cambia el flujo de **crear presupuestos nuevos**, que sigue creándolos en borrador.

## Alcance real

Quitar la restricción del asistente no neutraliza las validaciones de Odoo o de otros módulos. En pedidos ya confirmados puede haber entregas, movimientos de stock, facturas, contratos o reglas adicionales. Cambiar una línea comercial no corrige necesariamente documentos posteriores. La actualización puede ser rechazada por esos módulos, y en ese caso se devuelve el error sin saltarse sus protecciones. Validar primero en entorno de test, con distintos estados y documentos relacionados.

## Pruebas

- `python checks/verify_edit_any_status_11_26.py` (verificaciones sin entorno Odoo)
- `tests/test_sale_ai_quotation_edit.py` contiene pruebas de actualización con otros estados para ejecutar en una base de pruebas Odoo 18.
