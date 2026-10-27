# Fase 6 — Creación real de presupuestos (18.0.0.7.0)

Versión acumulativa, actualizable desde `18.0.0.6.2`, para Odoo 18 Community.

## Funcionalidad

- Botón **Finalizar y crear presupuesto** en el pie del chat y en la vista previa móvil.
- Precomprobación **solo lectura**: conversación activa, administrador de Ventas, propietario, compañía activa, cliente real, tarifa y moneda, al menos una línea comercial, productos disponibles, cantidades y precios válidos.
- Resumen previo y confirmación explícita del usuario. La precomprobación devuelve una huella SHA-256 del estado económico y comercial exacto. El servidor vuelve a calcularla inmediatamente antes de crear.
- Bloqueo transaccional de la sesión para evitar doble creación en dos pestañas.
- Creación mediante ORM de `sale.order` con estado `draft`, conservando orden de líneas, productos válidos, notas, secciones, textos y precios explícitos.
- Cálculo de impuestos por Odoo desde cliente, posición fiscal y productos. La base estimada del chat no pretende representar los impuestos del documento final.
- Si una línea económica no tiene producto, se conserva como línea descriptiva valorada, con una advertencia clara de que habrá que revisar la asociación al catálogo antes de procesos posteriores.
- Tras crearse, el chat se cierra y queda en historial, con enlace directo al presupuesto. Al iniciar otra conversación, el contexto estará limpio.
- La IA no puede crear ni confirmar pedidos mediante herramientas. Una instrucción en lenguaje natural «crear presupuesto» informa de la acción manual necesaria.

## Condiciones importantes

- **Un cliente es obligatorio** antes de crear el presupuesto. Si el cliente no existe en Odoo, hay que crearlo mediante el flujo estándar (no mediante IA).
- Debe haber **alguna línea comercial**. Las notas y secciones por sí solas no son un presupuesto comercial.
- Las monedas de la tarifa aplicable y el borrador deben coincidir. En caso contrario, la creación se detiene para evitar cambios de valor silenciosos.
- Las **líneas sin producto** podrían no ser facturables/entregables hasta asociarlas a un producto del catálogo. La fiscalidad de estas líneas puede no estar completa.
- El responsable debe revisar descuentos, IVA, condiciones de pago, cifras estimadas y otros ajustes comerciales en Odoo antes de utilizar el documento.
- No se ejecuta nunca `action_confirm`, ni se generan facturas, ni expediciones.
- Los mensajes permanecen en la sesión finalizada y no alimentan las conversaciones nuevas.

## Instalación

1. Copiar/sustituir la carpeta `sale_ai_assistant` completa dentro de tu `addons_path`.
2. Reiniciar el servidor Odoo 18.
3. Actualizar el módulo desde Aplicaciones (no desinstalar).
4. Recargar Ventas con Ctrl + Shift + R para renovar los assets OWL.

## Pruebas recomendadas

1. Intentar crear una conversación sin cliente: debe avisar sin crear `sale.order`.
2. Asignar un cliente real, crear una nota técnica y una partida de 1.290 €, pulsar **Finalizar y crear presupuesto**, revisar el resumen y confirmar.
3. Verificar en Ventas que se creó **un solo presupuesto en estado Borrador** con las líneas y descripciones ordenadas.
4. Verificar que el chat desaparece, aparece en el historial y permite abrir el presupuesto sin modificar la conversación.
5. Abrir una conversación nueva y comprobar que no contiene mensajes del presupuesto anterior.
6. Intentar crear dos veces el mismo presupuesto: debe quedar bloqueado.
7. Cambiar el importe en otra pestaña entre el resumen y la confirmación: la operación debe abortarse por huella obsoleta.
8. Probar una partida con producto real y otra sin referencia. Revisar posibles límites fiscales de las líneas sin producto.

## Validación realizada

Sintaxis Python y JavaScript, lectura de XML y empaquetado ZIP. Pruebas de `odoo.tests` incluidas pero **sin ejecución contra una instancia Odoo 18 real**. Realizar las primeras pruebas en una base de test.
