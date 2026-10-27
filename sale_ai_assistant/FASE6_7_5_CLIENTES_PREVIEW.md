# Fase 6 · 18.0.0.7.5: selección de cliente confirmada en Odoo

## Por qué se produce el fallo

Antes, mensajes como `cliente segalca` se enviaban a la IA sin obligarla a
llamar a `set_draft_header`. La IA podía decir que el cliente estaba asignado
cuando el campo `sale.ai.draft.partner_id` continuaba vacío. El texto de la
respuesta no equivale a una escritura real en Odoo.

## Corrección

- `cliente Segalca` y `Cliente: "Segalca Rehabilitación y Construcción, S.L."`
  se resuelven directamente mediante el ORM de Odoo sin una llamada a Vercel.
- Se admite `asigna el cliente Segalca`, `pon el cliente Segalca` y
  `el cliente es Segalca` como atajos explícitos.
- Solo se elige automáticamente un resultado inequívoco; coincidencias de
  contactos de una misma entidad comercial se agrupan en su matriz.
- Si hay varias empresas posibles, el asistente solicita un nombre o una
  referencia más precisa, sin elegir un cliente al azar.
- Se registra la operación para **Deshacer**, se comprueba el `partner_id`
  realmente almacenado y se devuelve en el payload de la vista previa.
- El resto del chat, modelos, Producto/Nota/Sección y creación de
  presupuestos permanece sin cambios.

## Prueba en Odoo

1. Inicia una conversación nueva y envía `cliente segalca`.
2. Comprueba que el asistente confirma el nombre completo **solo si se ha
   guardado** y que en la vista previa deja de figurar «Pendiente de asignar».
3. Si hay varias coincidencias, escribe `Cliente: "nombre completo"`.
4. Pulsa **Deshacer**: el borrador recuperará el cliente anterior.
5. Cierra y reabre el panel: el cliente debe persistir en la misma sesión.

El ZIP no se ha ejecutado contra una instancia real de Odoo 18 en este entorno.
