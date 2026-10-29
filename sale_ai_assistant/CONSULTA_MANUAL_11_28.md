# Versión 11.28 — consulta de costes únicamente bajo demanda

- Eliminada la tarea programada `ir_cron_sale_ai_cost_refresh` del contenido instalable.
- Quitada la referencia `data/sale_ai_cost_refresh.xml` de `__manifest__.py`; no se incluye el XML de cron.
- La consulta de importes pendientes se ejecuta **solo** al pulsar **Consultar costes pendientes en Vercel** en **Ventas → Asistente IA → Consumo por modelo**.
- Se mantienen el enrutamiento por modelo, el proveedor efectivo, el identificador de generación y los estados pendiente/confirmado/no disponible.
- El envío de mensajes de chat no activa una consulta secundaria de costes; conserva el importe si Vercel lo incluye en la respuesta.
- Esta versión se prepara para instalar sobre 11.26. No incluye rutinas de desinstalación ni de borrado de tareas anteriores.
- La obtención de importes reales sigue dependiendo de que Vercel exponga la generación correspondiente.
