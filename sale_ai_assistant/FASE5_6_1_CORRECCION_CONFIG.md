# Fase 5 — corrección de guardado, versión 18.0.0.6.1

## Problema corregido
Al guardar «Conexión Vercel IA», el wizard de configuración de búsqueda opcional podía recibir valores 0 (campos aún sin inicializar después de la actualización a Fase 5), provocando «Límite de búsqueda web inválido: market_queries_per_session».  El problema no proviene de Tavily ni de la clave API.

## Comportamiento ahora
* Las cuatro opciones de búsqueda con valor 0 se normalizan a sus valores predeterminados: por conversación 4, por mes 60, resultados 4, espera 9 s. Un valor 0 **no** significa búsquedas ilimitadas.
* Al reabrir la configuración, los parámetros persistidos vacíos o fuera de rango también muestran valores seguros.
* Los valores no nulos fuera de rango siguen provocando una validación clara y con el rango permitido.
* La búsqueda web sigue siendo **opt-in**. Si se activa, se exige una clave Tavily.
* No se cambian campos de base de datos, permisos ni comportamiento del asistente de Fases 1–4.

## Actualización
Sustituir carpeta de módulo, reiniciar Odoo y actualizar desde Aplicaciones. Volver a abrir el asistente de configuración y guardar. No desinstalar ni alterar los datos de conversaciones.

## Comprobación
Tests de regresión `tests/test_sale_ai_phase_five.py`. Sintaxis y XML verificados. Validación funcional en una instancia Odoo 18 pendiente.
