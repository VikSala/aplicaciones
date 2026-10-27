## Actualización 18.0.0.7.5 — Notas técnicas completas

- `Nota:` sin comillas sigue generando la nota con la IA. La generación de notas recibe un presupuesto específico de 2.400 a 3.200 tokens, separado del límite ordinario del chat (habitualmente 900), para evitar cortar descripciones largas. Esto puede incrementar ligeramente el consumo de una nota.
- El transporte guarda ahora `finish_reason` de Vercel. Si el modelo finaliza por límite de tokens, **no crea una nota truncada**; muestra un aviso y conserva el borrador anterior. Se contempla también un proveedor que omita `finish_reason` pero declare un consumo de salida casi igual al límite.
- Las notas ya guardadas no se reescriben automáticamente; para generar una versión nueva completa utiliza de nuevo `Nota:` y, si lo necesitas, `Deshacer:` para quitar una nota anterior.
- No hay cambios en los comandos Producto, Sección, literal entre comillas, creación de presupuestos o ajustes de acceso.

---

## Actualización 18.0.0.7.2 — Comandos opcionales de líneas

La versión está basada en la **18.0.0.7.0**. No incluye reglas comerciales ni perfiles.
En el chat aparecen botones **Producto / Sección / Nota / Deshacer**.
Al usarlos puedes controlar exactamente la estructura del borrador.
La vista previa se abre sola si el asistente guarda cambios.
Consulta `FASE6_7_2_COMANDOS_FLEXIBLES.md` para ejemplos y requisitos.

---

# Actualización Fase 5 — 18.0.0.6.2 (búsqueda relevante y valoración sin edición)

Esta versión **actualiza** la 18.0.0.6.1. Sustituir la carpeta completa del módulo,
reiniciar Odoo, actualizar Aplicaciones → Asistente IA y recargar el navegador.
No desinstalar, no borrar sesiones, no ejecutar SQL. No introduce columnas nuevas.

## Qué cambia

1. **Valoración ≠ edición:** peticiones como «plantea un presupuesto orientativo» o
   «calcula los materiales» generan una respuesta con estimaciones pero **no**
   modifican `sale.ai.draft` ni alteran importes que ya has fijado. Para trasladar
   los resultados al borrador, pedir «actualiza la vista previa con...». Las
   instrucciones explícitas de edición siguen activando las herramientas de escritura.
   Se retiran además las herramientas de escritura del esquema enviado al modelo
   durante una valoración y se bloquean en servidor si el proveedor las solicita
   a pesar de ello.
2. **Tavily por material:** consultas genéricas («precio», «precios medios») o
   mezclas de varios materiales no se envían. Se buscan referencias concretas
   por material y dimensión. Se eliminan diccionarios, traductores y resultados
   sin coincidencia de material o dimensiones (p. ej. cable 1,5 mm² solicitado
   como 2,5 mm²). Se añade exclusión de sitios irrelevantes a Tavily.
3. **Evidencia honesta:** se devuelven como máximo 4 enlaces filtrados por
   respuesta. Sólo se extrae un texto de precio cuando el fragmento indica
   explícitamente una unidad (€/m, €/ud, etc.). NO se declara precio verificado,
   ni se normalizan lotes si no se conoce su contenido. Cotejar siempre IVA,
   unidades, fecha y disponibilidad en la web del proveedor.
4. **Cálculo sin depender de la búsqueda:** la herramienta aritmética sigue
   disponible aunque no haya resultados web. Se prioriza su ejecución antes de
   responder y se presenta el desglose calculado por Python. Si un modelo omite
   la llamada, se recupera *solo* la mano de obra cuando operarios, horas y tarifa
   constan explícitamente en la petición o el borrador activo, sin inventar datos.
5. **Menos consumo de tokens:** prompt de sistema más corto, historial reciente
   abreviado, resumen limitado de la nota técnica, máximo 2 rondas con herramientas
   durante valoración y reducción de la carga de resultados recuperados. El coste
   real depende del modelo y de las decisiones de tool calling; no se garantiza
   una cifra concreta.

## Prueba manual recomendada

- En una conversación con partida existente de **1.290 €**, solicitar:
  «En base a 40 €/h por instalador (6 horas cada uno), y a los precios medios
  de materiales eléctricos en España, plantéame una valoración orientativa».
  Debe devolver una valoración; no debe alterar la partida de 1.290 €.
- La búsqueda «precio» se rechaza antes de contactar con Tavily.
  «tubo corrugado 25 mm» puede consultar Tavily; se eliminan diccionarios.
- Después decir «actualiza la vista previa con esta valoración»: esta **sí**
  es una orden de edición. Debe cambiar la vista previa según las líneas
  propuestas, sin crear `sale.order`.
- Con Tavily deshabilitado, debe calcular la mano de obra y marcar el resto
  de materiales como estimación o pendiente de precio contrastado.

## Límites

La búsqueda Tavily sigue aportando **fragmentos**, no lectura/validación completa
 de fichas de proveedor. No garantiza precios actuales ni cálculo fiscal. La
 ejecución de tests automatizados requiere un servidor Odoo 18; este ZIP se
 valida estáticamente fuera del servidor y debe probarse en una instancia de test.

---

# Asistente IA para Ventas — Odoo 18 Community

## Fase 5 · v18.0.0.6.0

Actualización compatible con la Fase 3 v18.0.0.4.1: mantener el nombre técnico
`sale_ai_assistant`, sustituir la carpeta completa, reiniciar Odoo y ejecutar
**Actualizar** (NO desinstalar). Si faltan assets, usar `?debug=assets` y recarga
forzada. Probado estáticamente; requiere validación funcional en una instancia
Odoo 18 con acceso a Vercel.

### Qué hace

- Los administradores de Ventas (`sales_team.group_sale_manager`) pueden
  conversar con un modelo Vercel compatible con tool calling.
- La IA dispone de las 6 herramientas de lectura anteriores y, desde ahora,
  de `get_current_draft`, `set_draft_header`, `add_draft_lines`,
  `update_draft_line`, `remove_draft_line`, `undo_last_draft_change`.
- La vista previa puede abrirse en paralelo en escritorio o en la pantalla
  estrecha, y se actualiza al terminar cada turno o reintento del modelo.
- Las líneas del borrador aceptan partidas, secciones y notas técnicas
  multilínea, con cantidad, descuento, importe orientativo y origen del precio.
- Se guardan el cálculo interno (distinto de líneas de cara al cliente),
  hipótesis pendientes y la fuente de precio. *Nunca se calcula IVA en esta fase*.
- No se crea ni modifica NINGÚN `sale.order`: el borrador está en
  `sale.ai.draft` y `sale.ai.draft.line`, y permanece sujeto a revisión humana.
- La X oculta el chat; comenzar otra conversación descarta el borrador activo
  y sus mensajes. El historial finalizado continúa siendo informativo.

### Activación

En **Ventas → Asistente IA → Modelos IA** marca *Admite herramientas* solo
para los modelos que lo soporten. En **Conexión Vercel IA** configura la API
key y modelo. Los modelos sin tool calling siguen conversando sin fingir
que han modificado el borrador. Para notas largas quizá necesites incrementar
la salida máxima a ~2000 tokens: más tokens implican más consumo.

### Reglas de seguridad

- El modelo solo puede modificar la propuesta perteneciente a la sesión activa
  del usuario y a la compañía actual; todo pasa por los permisos del ORM.
- Se permite como máximo 40 líneas y 8 altas por llamada; textos y argumentos
  acotados. Nunca se concede `sudo` para productos, clientes o pedidos.
- `price_source=odoo` obliga a un producto real, lee su precio de lista en el
  servidor y **no** equivale a una tarifa de cliente ni a un precio de mercado.
- `price_source=history` requiere ID de un pedido histórico accesible en la
  compañía. Sin verificación externa no se puede marcar una cifra como `external`.
- `undo_last_draft_change` restaura el estado anterior al último cambio
  realizado por la IA, siempre que nadie lo haya modificado desde entonces.
- Los resultados de las herramientas no se incorporan al historial como mensajes
  separados; el contexto se limita y pertenece exclusivamente a esta sesión.
- Un fallo posterior a una escritura no ofrece un reintento que duplicaría líneas:
  el asistente informa de los cambios guardados para que el usuario los revise.

### Pruebas manuales prioritarias

1. "Prepara una propuesta para una instalación eléctrica de tres motores;
   crea una nota técnica y una partida global de 1.100 €, marcada como estimación".
   Comprobar la vista previa sin ningún registro nuevo de `sale.order`.
2. "Aumenta la partida de 1.100 a 1.290 €, es una cifra decidida por mí".
   Debe **editar** la línea previa en vez de duplicarla.
3. "Añade una sección y una nota sobre las protecciones pendientes".
   La sección y nota carecerán de cantidad e importe.
4. "Deshaz el último cambio". Debe restaurar el borrador anterior.
5. Cerrar el panel con la X y reabrir: persiste el borrador. Nueva
   conversación: borrador distinto, sin transportar contexto.
6. Probar con otro administrador, con un usuario vendedor NO administrador
   y con una compañía distinta: no deben acceder a los datos de otra sesión.
7. Probar un modelo con *Admite herramientas* desactivado: responde en modo
   conversacional sin modificar la propuesta.

### Alcance posterior

Fase 5: lógica económica y comercial más avanzada, cálculo de tarifas real,
criterios de mercado con **fuentes externas verificables** y reglas fiscales.
Fase 6: confirmación humana y creación de `sale.order` en estado `draft`.
Los adjuntos PDF, imágenes y TXT quedan pendientes.



### Corrección 18.0.0.5.1 — vista previa OWL

- Solucionado `TypeError: ctx.Number is not a function` al abrir la vista previa.
- La conversión y el formato de importes se ejecutan en un método JavaScript
  del componente, en lugar de usar `Number()` dentro de la plantilla OWL.
- También se aplica el formato seguro a los costes por mensaje.
- Sin cambios en modelos de datos, operaciones del chat o borradores
  existentes; basta con sustituir la carpeta, reiniciar Odoo y actualizar
  el módulo para reconstruir los assets.


## Fase 5 — investigación de precios y valoración comercial

Actualiza **sobre 18.0.0.5.3** sin desinstalar y sin modificar datos previos.
No se crea ni confirma ningún `sale.order`.

- `get_customer_pricelist_price`: consulta la lista de precios real asociada
  al cliente de Odoo, con cantidad y moneda, sin elevar permisos y sin
  calcular impuestos. Una línea provisional puede usar
  `price_source=pricelist`, que fuerza el recálculo de servidor al añadir
  la línea y no acepta una cifra arbitraria de la IA.
- Calculadora `calculate_cost_breakdown`: materiales (hasta 15 conceptos), cantidad,
  precio unitario de referencia, fuente, operarios, horas, tarifa, extras y recargo.
  Devuelve subtotales exactos redondeados a 2 decimales. **No calcula impuestos**.
  El resultado de la calculadora no modifica el borrador: la IA lo transfiere
  a `estimate_details` y genera/modifica las líneas comerciales por separado.
- Consulta `search_market_prices`: **opcional** con Tavily y API key distinta de
  Vercel. En `Ventas → Asistente IA → Conexión Vercel IA` activar la búsqueda
  web, guardar clave y ajustar límites. Sin activar, ningún dato sale a Tavily.
  Requiere conectividad saliente HTTPS a `api.tavily.com` y un modelo con
  *Admite herramientas* activo. No necesita instalar un SDK nuevo: utiliza
  `requests`, incluida en las dependencias habituales de Odoo.
- Límites predeterminados: 2 búsquedas por respuesta, 4 por conversación,
  60 por compañía/mes y 4 resultados por búsqueda. Tiempo máximo por
  búsqueda de 9 s. Cuotas protegidas frente a accesos simultáneos mediante
  bloqueo transaccional sobre la compañía. Solo se guarda un hash de la
  consulta, compañía, usuario, fecha y número de resultados; nunca los textos
  devueltos ni la API key en el historial de consumo.
- Tavily devuelve **fragmentos de buscador con enlaces**, no presupuestos de
  proveedores, no confirmación de stock y no clasificación fiable de precios
  con/sin IVA. El asistente no debe dar una cifra como verificada por ver un
  fragmento. El usuario debe abrir y comprobar cada fuente; etiquetas
  `estimate` y `user` se mantienen en las líneas. El origen `external`
  continúa bloqueado para impedir afirmar verificación sin inspección real.
- Cuotas/costes Tavily son **independientes** del saldo de Vercel AI Gateway.
  Tavily ofrece un plan Researcher gratuito bajo sus condiciones vigentes:
  consultar https://www.tavily.com/pricing antes de contratar.
- No enviar al buscador datos personales de clientes, direcciones ni secretos.
  La búsqueda rechaza emails, URLs y ciertos identificadores; solo se deben
  formular términos genéricos de materiales y medidas.
- La valoración y la estructura comercial siguen sujetas a revisión humana.
  La Fase 6 implementará la creación autorizada de un presupuesto Odoo real.

**Ejemplos de prueba**

1. Con la búsqueda desactivada, solicitar precios actuales de cable 2,5 mm:
   se debe explicar la limitación, sin atribuir importes a Internet.
2. Activar Tavily y solicitar referencias de cable, tubo y cajas estancas
   en España: deben aparecer URLs auténticas, nunca fuentes inventadas.
3. «2 operarios, 6 h cada uno a 40 €/h»: subtotal mano de obra 480 €
   sin IVA; añadir materiales identificados con su origen y crear el cálculo
   interno y las líneas provisionales. Verificar que ningún pedido real aparece.
4. Con un modelo sin tool calling, debe informar que no tiene herramientas.
5. Al superar el cupo de búsquedas, el agente debe declararlo y trabajar
   únicamente con datos Odoo/estimaciones claramente etiquetados.

**Limitaciones:** no hay extracción de precios estructurados de páginas,
no hay scraping, no hay búsqueda semántica ni adjuntos. Las cifras de Internet
son referencias para la revisión del usuario, no datos certificados.

## Fase 6 (18.0.0.7.0) — Presupuestos reales en borrador

Se añade la creación controlada de `sale.order` tras precomprobación y confirmación explícita del usuario. La IA no puede confirmar operaciones comerciales. Ver `FASE6_7_0_CREACION_PRESUPUESTOS.md` para límites, instalación y pruebas.


## Corrección 18.0.0.7.5: cliente y vista previa

Consulta `FASE6_7_5_CLIENTES_PREVIEW.md`.


## Iteración A — Motor experimental (18.0.0.8.0)

El modo de contexto por defecto es **Experimental: conversación completa**. El agente
recibe todos los mensajes de su **propia sesión** sin cortar mensajes, además del
estado actual del borrador. No se mezclan sesiones. El tamaño permitido por el
proveedor/modelo puede ser inferior al contexto enviado: en ese caso la solicitud
fallará con un error del proveedor; no se silencian ni recortan mensajes.

En **Ventas → Asistente IA → Conexión Vercel IA** se configuran por compañía:
modo completo/acotado, presupuesto de contexto en modo acotado, máximo de tokens
por salida, timeout por llamada, rondas de herramientas, número de herramientas,
caracteres de resultados de herramientas y segundos totales por turno.
La configuración de búsqueda Tavily incluye el máximo por respuesta, sesión y mes.

El valor de **Máximo de tokens de respuesta** se envía tal cual a Vercel,
incluidas las notas y secciones. No hay límites privados de 1100, 2400 o 3200
tokens. No significa que el proveedor garantice utilizar todos esos tokens:
puede finalizar antes o imponer un máximo menor. Los modelos con tokens de
razonamiento pueden contar estos tokens dentro de su salida total.

**Actualización:** se respetan los ajustes ya guardados de cada compañía,
incluido por ejemplo un máximo de 2000 tokens configurado previamente.
Los nuevos ajustes arrancan en modo experimental con valores altos: 10 rondas,
30 llamadas, 64000 caracteres de resultados y 110 segundos por turno.
Para una instancia recién instalada el máximo de salida sugerido es 8192;
si deseas 8192 en tu instancia actual, configúralo expresamente.

**Precauciones:** Vercel cobra por entrada y salida; enviar el historial íntegro
aumenta el consumo en conversaciones largas. El servidor Odoo puede necesitar
`limit_time_real` suficiente para turnos extensos. La Iteración B ampliará
la verificación de objetivos multi-herramienta; esta iteración sustituye el
clasificador rígido por decisiones del modelo y verifica las operaciones
individuales ya realizadas.

## Iteración A.1 — Ejecución verificable (18.0.0.8.1)

Se evita aceptar respuestas como «voy a buscar precios» cuando el modelo
no ha llamado a las herramientas. Una primera llamada estructurada hace que
el **propio modelo** establezca si necesita búsquedas, cálculo u operaciones
de borrador. El motor exige las herramientas seleccionadas antes de cerrar
el turno y muestra qué se ejecutó realmente.

No se incorporan reglas comerciales rígidas por palabras. La planificación
consume una llamada adicional al proveedor por turno cuando el modelo admite
herramientas. Se respetan los ajustes de tokens, tiempos y límites operativos
de **Conexión Vercel IA**. Para funciones de búsqueda externa debe estar Tavily
configurado y activado. Consulta `ITERACION_A_8_1_EJECUCION_HERRAMIENTAS.md`.

## Iteración C — Calidad técnica, estimaciones y revisión del borrador (18.0.0.10.0)

Se conserva el agente de la Iteración B. Se han ampliado las instrucciones para
mejorar las notas técnicas a medida que evoluciona la conversación, proponer
hipótesis orientativas cuando faltan datos y ofrecer valoraciones comerciales
razonadas sin imponer precios ni alterar importes fijados por el usuario.
Al pulsar **Finalizar y crear presupuesto**, una revisión IA **de solo lectura**
compara el borrador con las decisiones de la conversación y muestra advertencias
antes de confirmar. Si falla Vercel, el usuario puede continuar con la revisión
humana y crear exclusivamente un `sale.order` en estado `draft`.

Consulta `ITERACION_C_10_0_CALIDAD.md` para alcance y pruebas.


## Perfiles multimodelo (18.0.0.11.0)

Consulta [PERFILES_MULTIMODELO_11_0.md](PERFILES_MULTIMODELO_11_0.md). Los modelos individuales siguen funcionando.
