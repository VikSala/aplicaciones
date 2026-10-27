# 18.0.0.10.1 — Separación de consulta y modificaciones

## Regresión observada (conversación de motores de ventilación)

- La solicitud de texto técnico solo se respondía en el chat; no creaba `line_note`.
- La valoración de protecciones creaba cuatro líneas sin producto, pese a que el usuario
  únicamente había comunicado información técnica y pedido estimaciones.
- Se interpretaba «instalado **en** el subcuadro» como suministro de un subcuadro nuevo.

## Cambio en el agente

El planificador de Gemini declara explícitamente el propósito de cada turno con
`write_scope`: `read_only`, `technical_note`, `commercial_lines`, `header_only`,
`full_draft` o `undo`. No se deduce el propósito mediante un detector rígido de
palabras clave; **la IA clasifica**, y el servidor limita las herramientas a ese
propósito antes de ofrecérselas. Cada llamada se vuelve a validar en Python.

- Un texto técnico para presupuesto crea nota si no existe o modifica la nota del
  mismo trabajo. Se requiere una herramienta real y no basta con responder texto.
- Una valoración económica puede buscar y calcular, pero no tocar el borrador.
- Una confirmación técnica puede actualizar la nota, pero no incorporar
  automáticamente equipos y precios a líneas facturables.
- Para crear una partida libre sin producto se necesita petición expresa del
  usuario, también aunque el modelo marque `allow_unlinked=true`.
- Para un producto real sigue siendo obligatorio localizar y comprobar su ID.

No se alteran `sale.order`, la confirmación explícita, el Deshacer multinivel,
las preferencias experimentales, el proveedor de IA ni los límites visibles.

## Casos de prueba

1. Nueva conversación: solicita descripción técnica de los tres motores.
   Debe aparecer una **Nota** completa en vista previa, sin partidas económicas.
2. Solicita valoración de materiales y 2 instaladores x 6 horas a 40 €/h.
   Debe recibir desglose; el total comercial de la vista previa no debe cambiar.
3. Añade información de motores trifásicos y protecciones en el subcuadro.
   Debe actualizar la nota existente cuando sea decisión confirmada; no crear
   «Subcuadro nuevo», «Guardamotor» o «Diferencial» como partidas económicas.
4. Pide explícitamente «añade el producto de catálogo TLMEF por 1.290 €».
   Debe buscar el producto real y usar su product_id.
5. Pide explícitamente una partida libre sin producto: se permite cuando se
   solicita así; de lo contrario, la operación es rechazada.

Las pruebas automatizadas de Odoo se incluyen, pero requieren ejecutarse en una
instancia Odoo 18 real para confirmar el funcionamiento con Vercel/Gemini.
