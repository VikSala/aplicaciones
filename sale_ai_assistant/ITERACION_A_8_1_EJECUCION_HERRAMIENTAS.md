# Iteración A — 18.0.0.8.1: ejecución de herramientas

## Error corregido

Con `tool_choice=auto`, Gemini podía responder «voy a buscar precios» y terminar el
turno sin llamar a ninguna herramienta. Era un resultado permitido por la API,
pero insuficiente para la tarea comercial.

## Qué cambia

- Primera decisión estructurada a través de `plan_turn` con `tool_choice=required`
  **solo si el modelo tiene herramientas habilitadas**.
- El propio modelo determina si necesita búsquedas, cálculo o modificaciones. El
  servidor no infiere la intención mediante palabras o expresiones regulares.
- Si el plan exige herramientas, las llamadas se solicitan con `tool_choice=required`
  hasta que se ejecuten o se agoten los límites configurados.
- La ejecución nunca se sustituye por frases futuras. Si falta una herramienta,
  hay errores del proveedor o vence el presupuesto, el chat lo comunica.
- Se cuentan los tokens de planificación y ejecución en el consumo de la respuesta.
- Se muestran los nombres y el número de herramientas realmente invocadas.
- Búsqueda Tavily sigue siendo **opcional** y requiere clave, habilitación y cuota.
  Ante falta de precios concretos, el asistente puede dar estimaciones identificadas
  como tales sin presentarlas como fuentes verificadas.
- No se ha cambiado la lógica de creación final de `sale.order`: requiere
  confirmación explícita del usuario y crea únicamente `draft`.

## Configuración

Se respetan los límites visibles en **Ventas → Asistente IA → Conexión Vercel IA**.
La primera planificación añade una llamada al modelo que consume tokens/tiempo;
no se introducen límites ocultos de salida. Se requiere un modelo compatible con
`tool_choice=required` y marcado como «Admite herramientas».

## Pruebas manuales

1. Con Gemini 2.5 Flash, Tavily activo y saldo, iniciar conversación y describir
   materiales, cantidades y operarios.
2. Pedir «búscame precios de los materiales y propón una valoración económica».
   Deben verse `search_market_prices` y `calculate_cost_breakdown` en la traza
   de herramientas si ambas están disponibles. Las cifras deben aparecer en
   la respuesta, no quedar pendientes.
3. Sin Tavily, repetir: debe estimar honestamente y no atribuir precios a la web.
4. Probar «adelante» tras una instrucción pendiente: debe continuar el objetivo
   real de la conversación.
5. Confirmar que las consultas informativas no modifican el borrador.

Se ha ejecutado un simulacro aislado del flujo de planificación → búsqueda →
calculadora → respuesta. **La prueba real contra Vercel/Odoo sigue pendiente.**
