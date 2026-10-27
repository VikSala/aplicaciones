# Fase 6 — v18.0.0.7.3 · Delimitación literal mediante comillas

Partimos de la **v18.0.0.7.2**, sin recuperar reglas comerciales ni perfiles automáticos. Los botones continúan insertando `Producto:`, `Sección:` o `Nota:`; el chat libre y la creación confirmada de presupuestos de la Fase 6 siguen igual.

## Producto: campos explícitos

```
Producto: nombre "material electrico" precio 1290 descripcion "TOTAL"
Producto: sku IE cantidad 1 precio 0
Producto:
sku IE precio 0 descripcion "Instalación eléctrica"
sku TLMEF precio 1290 descripcion "TOTAL"
```

- **`nombre` y `descripcion` deben ir entre comillas** (`"..."`, `'...'`, `«...»` o `“...”`). Cada bloque es un valor literal completo: la palabra `precio`, `sku` o `cantidad` dentro de esas comillas no se interpreta como otro campo.
- El **`sku` puede ir sin comillas** (referencia exacta), o entre comillas si contiene espacios. Nunca se inventa un SKU.
- **`precio` y `cantidad` son numéricos y van sin comillas**, con `,` o `.` como separadores habituales. Cantidad por defecto: **1**.
- Los campos pueden estar en diferente orden. Cada producto se separa con salto de línea o `;` **fuera de comillas**; saltos de línea, signos de puntuación y `;` dentro de una descripción entrecomillada permanecen en su texto.
- Busca SKU exacto o nombre coincidente de manera no ambigua. Si hay varios productos, solicita el SKU antes de guardar; ningún producto ficticio se crea. En un comando múltiple, todos se validan antes de guardar.
- Si falta cerrar una comilla o se envía `nombre`/`descripcion` sin comillas, muestra un error útil, **sin crear líneas**.

## Sección y Nota: comillas = literal; sin comillas = IA

```
Nota: "Comprobar el paso por la canalización existente."
Sección: "Materiales"
Nota: Redacta una nota técnica de la instalación con los materiales de esta conversación.
Sección: Propón un encabezado para el apartado de materiales.
Nota: Redacta una descripción e incluye exactamente "Protecciones pendientes de dimensionar".
```

- Cuando **todo el cuerpo** es un único texto entrecomillado, se guarda ese contenido **sin consulta al modelo**.
- En cualquier otro caso, se envía como **instrucción al modelo configurado**, con algo de contexto acotado de la **misma conversación**. Si aparecen fragmentos entrecomillados dentro de la instrucción, se solicita que se respeten literalmente.
- Sección generada por IA: título breve de una línea. Nota generada: texto técnico sin datos inventados.
- No se guarda nada si el proveedor falla o si el texto generado no pasa la validación.

## Vista previa / Deshacer

Cada modificación del borrador continúa abriendo la vista previa de manera automática (al finalizar el envío). El botón Deshacer revierte el último cambio del borrador, sin borrar la conversación. Nada crea un `sale.order` salvo el flujo separado de **Finalizar y crear presupuesto**, con confirmación explícita.

## Instalación y verificación

Sustituir la carpeta del módulo, reiniciar Odoo y **actualizar** `sale_ai_assistant` en Aplicaciones. Recargar la interfaz (`Ctrl+Shift+R`). No se modifican modelos SQL ni se reintroducen reglas comerciales.

La sintaxis del código y el parser se pueden verificar fuera de Odoo; los tests de integración `tests/test_sale_ai_chat_commands.py` y el comportamiento real necesitan ejecutarse en Odoo 18.
