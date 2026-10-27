# Fase 6.1 — Estructuras comerciales inteligentes (18.0.0.7.1)

Actualización del módulo **sale_ai_assistant** para Odoo 18 Community.

## Instalación

Sustituye la carpeta del módulo existente, reinicia Odoo y actualiza **Asistente IA para Ventas** desde Aplicaciones. No desinstales el módulo, ni borres la base de datos ni las conversaciones.

## Configuración inicial

1. En **Ventas → Asistente IA → Reglas de presupuestación** abre la regla compartida **Instalaciones eléctricas — partida global**.
2. Puedes mantener las referencias internas `IE` y `TLMEF` si corresponden **exactamente** a un único producto vendible de la compañía activa.
3. Si hay ambigüedad, usa **Personalizar para esta compañía** y selecciona los productos reales en los campos **Producto principal** y **Producto importe global**. El botón crea una regla específica para la compañía activa. No se hace ninguna selección ambigua.
4. Edita la lista de expresiones, prioridad y estructura si procede. Puedes crear reglas adicionales desde el mismo menú.
5. Usa un modelo de Vercel con **Admite herramientas** activado. Si no admite llamadas a funciones, la IA no podrá modificar la vista previa.

## Resultado de la regla de instalaciones eléctricas

- `product_id` del producto `IE`, **cantidad 1**, **precio unitario 0**.
- **Nota técnica de Odoo** (`display_type='line_note'`), con la descripción del trabajo y materiales. No es una línea facturable.
- `product_id` del producto `TLMEF`, **cantidad 1**, descripción `TOTAL` y **precio de la valoración comercial aceptada**.

La valoración de mano de obra y materiales queda en **Cálculo interno orientativo**. Los impuestos y condiciones definitivos solo los calculará Odoo al crear el presupuesto, tras confirmación humana.

La regla NO fija márgenes ni aplica un porcentaje comercial automático. En una consulta de valoración, el asistente muestra una propuesta orientativa y sus advertencias, sin alterar el borrador. Solo cuando el usuario ordena actualizar o crear las líneas provisionales puede aplicar la regla.

## Históricos

La herramienta `get_historical_line_patterns` puede consultar un máximo de cinco presupuestos **relevantes** de la compañía, limitados además por **Máximo históricos** en Ajustes. Devuelve únicamente tipos de línea y referencias de productos; no arrastra notas completas ni precios antiguos.

Las reglas tienen prioridad sobre los patrones históricos. Una instrucción expresa del usuario («quiero partidas separadas») tiene prioridad sobre las reglas.

## Prueba rápida

1. Nueva conversación: **Necesito una descripción técnica para la instalación eléctrica de tres motores, con cable 2,5 mm², tubo de 25 mm, tres cajas estancas y mano de obra de dos operarios. Añádela a la vista previa.**
2. Comprobar el producto principal `IE` (0 €), la nota técnica y una partida `TLMEF` inicialmente sin valoración si aún no se ha aceptado precio.
3. Solicitar valoración orientativa: **Calcula materiales y 2 instaladores × 6 h × 40 €/h. No modifiques todavía el borrador.**
4. **Traslada un importe global de 1.290 € a la vista previa.** Comprobar que `TLMEF` vale 1.290 €, sin líneas desglosadas duplicadas.
5. **Amplía la nota con las protecciones trifásicas, pendientes de dimensionar.** Comprobar que se conserva la nota anterior.
6. **Deshaz el último cambio.** Comprobar que vuelve a la estructura inmediatamente anterior.
7. Asignar cliente real y pulsar **Finalizar y crear presupuesto**. Revisar Odoo: las tres líneas aparecen en el orden correcto, y `sale.order.state == 'draft'`.

### Restricciones

- Si no se encuentran referencias internas únicas, no se aplica la regla automáticamente. El chat señalará la configuración pendiente y mantendrá el borrador existente.
- No se realizan búsquedas de productos por parecido de nombre en esta operación.
- No se crean/confirmar pedidos sin la acción humana de finalización y confirmación.
- En esta entrega no se ha ejecutado el módulo dentro de un servidor Odoo 18. Se incluyen pruebas de regresión para ejecutarlas en una instancia Odoo.
