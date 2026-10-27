# Iteración B — 18.0.0.9.0

Esta entrega parte de 18.0.0.8.1; conserva los ajustes visibles de Vercel.

- El agente debe ejecutar una consulta real a `search_products` o `get_product_details` antes de asociar por primera vez un producto al borrador. Los IDs verificados viven solo en esa ejecución; nunca se inventan.
- Las partidas libres requieren `allow_unlinked=true` y una petición explícita del usuario; no son una alternativa silenciosa a una búsqueda fallida.
- El modelo sigue siendo quien planifica; ante errores de herramientas puede recuperarse mediante otras consultas y, si hay ambigüedad, debe solicitar el SKU.
- Deshacer multinivel: cada cambio provisional guarda una instantánea en `sale.ai.draft.change` con usuario y compañía. Al deshacer, se recalcula la huella del estado restaurado para permitir repetir la acción.
- Se mantiene compatibilidad con el `undo_snapshot` de versiones anteriores para el primer deshacer pendiente; los nuevos cambios se registran exclusivamente en el historial multinivel.
- La respuesta final ya no muestra listados de nombres de herramientas y se confirma solo una vez el estado real de Odoo.
- Ninguna de estas herramientas crea ni confirma `sale.order`.

## Casos de prueba

1. «Añade material eléctrico»: debe buscar productos Odoo; si hay coincidencias ambiguas, debe pedir la referencia y no crear una partida sin catálogo.
2. «Añade el SKU TLMEF»: debe buscar y asociar el ID de producto real; la vista previa mostrará su referencia.
3. Crea una nota, una sección, un producto y asigna un cliente. Pulsa Deshacer cuatro veces y comprueba que se recupera el estado anterior en cada ocasión, incluso tras cerrar y reabrir el panel.
4. Verifica que finalizar crea `sale.order` solo tras confirmación explícita.

No se ha probado esta entrega contra un Odoo 18 de producción ni un modelo Vercel real.
