**Nota:** el comportamiento actualizado de las comillas está documentado en `FASE6_7_3_COMILLAS_LITERALES.md`.

# Fase 6 — Comandos opcionales de líneas (18.0.0.7.2)

Base: **18.0.0.7.0** suministrada por el usuario. NO incluye las reglas de presupuestación ni los perfiles de la 18.0.0.7.1.

El usuario puede seguir conversando libremente. Los botones **Producto**, **Sección** y **Nota** preparan únicamente un prefijo del campo de entrada, sin enviar mensajes automáticamente. La acción **Deshacer** revierte directamente el último cambio provisional y registra la operación en el historial del chat.

## Ejemplos

- `Producto: sku TLMEF precio 1290 descripcion "TOTAL"`
- `Producto: nombre "material electrico" precio 1290 descripcion "TOTAL"`
- `Producto: sku IE cantidad 1 precio 0`
- Varios productos en un mensaje, separados por salto de línea o `;`:

  ```
  Producto:
  sku IE precio 0
  sku TLMEF precio 1290 descripcion "TOTAL"
  ```

- `Sección: Mano de obra`
- `Nota: Comprobar canalización en obra.` (texto literal)
- `Nota: Necesito texto descriptivo técnico para presupuesto de la siguiente instalación: ...` (IA redacta y guarda una nota)
- Botón ↶ **Deshacer último cambio** (no borra lo que se esté escribiendo)

### Reglas de interpretación explícitas

- `sku` busca coincidencia **exacta** en `product.product.default_code` y en productos vendibles de la compañía activa.
- `nombre` busca por palabras en `product.product.name`, tolerando tildes y orden diferente. **Si hay varios candidatos**, no elige ninguno y pide el SKU.
- `precio`, `cantidad`, `descripcion` (también `descripción`) son opcionales. `cantidad` predeterminada: **1**.
- Si el usuario indica un `precio`, se registra con origen `user` (no precio de mercado). Si no lo indica, se usa la tarifa del cliente asignado cuando existe; si no, el precio de lista Odoo.
- Las partidas de producto **siempre** requieren una referencia real de catálogo. No se inventa un producto.
- Las nuevas líneas se añaden al **borrador provisional**, no a `sale.order`. Para crear el presupuesto real se exige el flujo de confirmación humana de la Fase 6.
- Para un comando de producto múltiple, la validación es atómica: si falla una línea, **ninguna** se guarda.
- Nota literal se guarda tal cual. Una instrucción claramente redactora (`Necesito texto...`, `Redacta...`, `Genera...`) pide una versión profesional al modelo y guarda el texto resultante. Si falla el proveedor, no se añade una nota vacía.
- El botón Deshacer utiliza el mecanismo de instantánea del borrador ya existente. Solo revierte el **último cambio**, no toda la conversación.
- Si el asistente guarda líneas o cambia el borrador, la vista previa se abre automáticamente; en móviles pasa a la vista de presupuesto.

## Actualización

Sustituir carpeta `sale_ai_assistant` de la versión 18.0.0.7.0 por esta. Reiniciar Odoo, actualizar módulo en Aplicaciones y recargar backend (`Ctrl+Shift+R`).

Los comandos se ejecutan con ORM y permisos de administrador de Ventas ya existentes. No cambian la estructura SQL ni el flujo de creación del presupuesto. Si actualizas desde la 18.0.0.7.1, se desactiva el menú antiguo de Reglas de presupuestación sin borrar los presupuestos ni los datos existentes. Los perfiles de reglas ya no se cargan ni se utilizan. Se incluye `tests/test_sale_ai_chat_commands.py` para ejecutar dentro de Odoo 18 con `--test-enable`.

## Verificación

Comprobación estática Python y XML, sintaxis JS y tests aislados del parser sin servidor. **La instalación funcional y los tests de Odoo aún deben probarse en la instancia del usuario**.
