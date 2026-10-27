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

