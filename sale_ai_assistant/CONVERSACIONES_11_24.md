# 18.0.0.11.24 — Sustitución de conversación y detección de actividad real

## Al cargar un presupuesto en borrador

Cuando existe trabajo real en la conversación activa, Odoo muestra **tres opciones**:

- **Archivar y cargar**: guarda la sesión anterior en el historial (con sus mensajes y vista previa) y carga el PV elegido.
- **Descartar y cargar**: elimina únicamente la sesión activa anterior, con su borrador provisional y mensajes; no altera el PV real ni las conversaciones archivadas anteriormente.
- **Cancelar**: conserva la conversación actual y sus datos.

Los mensajes escritos que todavía no se han enviado y los adjuntos pendientes se pierden al cargar en cualquiera de los dos modos; el modal lo advierte.

## Cuando solo se ha cargado el PV

Una vista previa que se limita a reproducir el PV original **no equivale a trabajo hecho**. Si no hay mensajes, propuestas técnicas, notas nuevas, historial de modificaciones o diferencias comerciales con la instantánea inicial, **Nuevo chat** o **Cargar otro PV** pueden descartar esa sesión temporal directamente, sin pedir confirmación y sin archivarla.

La detección se hace tanto en cliente como en servidor. El servidor compara los valores de la propuesta con la instantánea comercial original del PV; nunca toma las líneas precargadas como señal de actividad. En caso de error al leer o comparar la instantánea, la sesión se trata conservadoramente como actividad existente para evitar perder trabajo.

## Invariantes

- Se conserva la restricción: solo presupuestos en estado `draft`.
- Se conserva el acceso por administrador de Ventas y compañía activa.
- Estas operaciones nunca modifican `sale.order` ni sus líneas.
- Las llamadas RPC que sustituyen una conversación activa bloquean la sesión y se hacen dentro de una transacción.
- Las funciones de chat, archivos, Vercel y edición existentes no cambian.

## Pruebas

- `node checks/verify_replace_11_24.cjs`
- `python checks/verify_pristine_edit_11_24.py`
- Casos adicionales en `tests/test_sale_ai_quotation_edit.py`, ejecutables en una base de datos de test Odoo 18.
