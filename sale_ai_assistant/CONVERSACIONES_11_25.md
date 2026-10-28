# Versión 11.25 — Elección al reemplazar conversaciones

- **Cargar o recargar un presupuesto:** al existir trabajo, el diálogo ofrece **Archivar y cargar** a la izquierda y **Descartar y cargar** a la derecha. Se ha eliminado «Cancelar»: la X cierra el diálogo sin modificar la conversación.
- **Iniciar una conversación nueva:** cuando existe trabajo, ofrece **Archivar y empezar** o **Descartar y empezar**, tanto en sesiones de edición como en conversaciones normales.
- **Sin trabajo real:** abrir una nueva conversación no presenta ningún diálogo y elimina la sesión sin añadirla al historial.
- **Backend:** `assistant_panel_new` acepta `replace_mode` (`auto`, `archive`, `discard`). El modo por defecto mantiene compatibilidad con llamadas antiguas; `archive` conserva solo sesiones con trabajo, `discard` elimina la sesión activa. Ninguna operación modifica presupuestos reales ni el historial previo.
- Si existen adjuntos o texto sin enviar, se advierte que se perderán al archivar o descartar.
