# Iteración C (18.0.0.10.0) — Calidad técnica y comercial

**Base**: Iteración B `18.0.0.9.0`. La interfaz, botones, permisos, herramientas
actuales, control de consumo y creación de `sale.order` en estado `draft` se conservan.
No se recuperan las reglas comerciales rígidas de `18.0.0.7.1`.

## 1. Asistente con iniciativa y distinción entre hipótesis y decisiones

Se revisaron `SYSTEM_PROMPT` y `PLANNING_PROMPT` para que el modelo:

- Ofrezca descripciones técnicas completas a partir de apuntes del usuario,
  distinguiendo lo confirmado de lo que aún debe revisarse.
- Cuando el usuario **confirma** nueva información relevante (p. ej., que los
  motores serán trifásicos o que el subcuadro incorporará protecciones),
  consulte el borrador, actualice la nota técnica afectada y no la duplique.
  Las consultas hipotéticas («¿qué pasaría si…?») **no** autorizan editar.
- Ante datos incompletos, plantee alternativas y valoraciones orientativas
  condicionadas, sin atribuir a la instalación calibres/protecciones definitivas
  o cumplimiento normativo sin las verificaciones correspondientes.
- En valoraciones comerciales diferencie: desglose de referencia, precio de
  venta recomendado y cifra elegida por el usuario. Puede explicar ajustes
  por alcance, materiales auxiliares o imprevistos, pero no aplica un margen
  arbitrario ni cambia unilateralmente los importes del borrador.
- Evite solicitar repetidamente información que solo se necesita para el
  dimensionamiento definitivo si el usuario ha pedido una **estimación**.

Las decisiones del agente siguen dependiendo del modelo y de la calidad del
contexto. Estas reglas son instrucciones, **no validación técnica automática**.
No hay certeza de que Gemini las cumpla en todos los casos.

## 2. Revisión de coherencia antes de crear un presupuesto

Al pulsar **Finalizar y crear presupuesto**, `assistant_panel_quotation_preflight`
realiza primero sus validaciones originales de Odoo y, adicionalmente, una
revisión de solo lectura utilizando el modelo seleccionado. La revisión:

1. Contrasta las decisiones explícitas de la conversación con el borrador actual.
2. Devuelve hasta seis advertencias breves basadas en evidencias: omisiones,
   inconsistencias y pendientes de revisión técnica o económica.
3. Presenta los hallazgos **antes** de confirmar la creación; NO modifica
   líneas, precios, productos ni clientes.
4. En caso de timeout, errores de Vercel o modelo sin herramientas,
   deja una advertencia y permite continuar con la revisión humana.

El sistema de revisión **no ejecuta** `sale.order.create`. La creación efectiva
continúa protegida por la firma del borrador y la confirmación explícita del
usuario y **no vuelve a invocar el modelo**.

El revisor envía a Vercel la conversación actual y la estructura completa del
borrador. Esto puede incrementar el consumo y el tiempo de abrir la confirmación,
particularmente en el modo experimental de contexto completo. No se envía
el historial de otras conversaciones.

## 3. Pruebas en Odoo

1. **Redacción inicial**: describe tres motores, materiales y las horas previstas.
   Comprueba si el agente produce una nota técnica clara y señaliza hipótesis.
2. **Cambio confirmado**: indica que los motores son trifásicos y que habrá
   protecciones en el subcuadro. Debe revisar la nota existente, sin duplicarla,
   y señalar datos de placa/condiciones pendientes para el dimensionamiento.
3. **Consulta hipotética**: pregunta «¿qué pasaría si fueran monofásicos?».
   No debe cambiar las líneas confirmadas.
4. **Valoración**: indica 2 operarios, 6 h, 40 €/h y materiales. Debe calcular
   480 EUR de mano de obra y una valoración orientativa de materiales, además
   de una recomendación comercial explicada cuando se solicite. No debe forzar
   un precio de referencia histórico como valor definitivo.
5. **Revisión final**: deja deliberadamente obsoleta una nota y pulsa
   «Finalizar y crear presupuesto» (con cliente y partida comercial válidos).
   Comprueba que se presentan advertencias antes de confirmar.
6. **Fallo Vercel**: desconecta o fuerza un error del proveedor durante la
   revisión final; el usuario aún puede finalizar la creación del presupuesto
   en borrador y recibe un aviso claro de revisión manual.
7. **Permisos**: solo Administradores de Ventas acceden a la operación.
   La sesión permanece separada por usuario y compañía.

## 4. Límites y seguridad

- Sin cambios en los valores de `Conexión Vercel IA`; se siguen utilizando
  el timeout y máximo de tokens configurados también para la revisión previa.
- No se realizan nuevos diseños eléctricos certificados ni verificaciones
  normativas. La selección definitiva de protecciones exige un técnico competente
  y datos adecuados.
- No se confirma la venta, ni se crean facturas o movimientos de almacén.
- Los ensayos en `tests/test_sale_ai_agent_iteration_c.py` están preparados
  para Odoo 18 y emplean respuestas simuladas del proveedor; **no** prueban la
  calidad semántica de Gemini ni llamadas reales a Vercel/Tavily.
