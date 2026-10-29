# Versión 11.28 — enrutamiento y consulta manual de costes reales de Vercel

## Configuración
En **Ventas → Asistente IA → Modelos IA**, abre cada modelo individual y elige:
- **Priorizar menor coste** (inicial): `providerOptions.gateway.sort = "cost"`. Ordena por precio de **entrada**; no garantiza el menor total, y puede usar otro proveedor si el preferido falla.
- **Automático de Vercel**: no envía selección de proveedor.
- **Menor latencia** (`ttft`) o **mayor velocidad** (`tps`).
- **Proveedor específico**: `providerOptions.gateway.only = [slug]`. Sin fallback a otros proveedores.

El comportamiento se configura **por modelo individual**, también dentro de perfiles multimodelo. Las tarifas manuales antiguas quedan en base de datos exclusivamente para compatibilidad; no se solicitan, no se calculan y no aparecen en el coste del chat.

## Costes reales
- Cada llamada al endpoint de chat guarda el ID de generación, proveedor cuando se conoce, tokens y estado de coste.
- Si viene el coste en la respuesta, se registra como confirmado. En otro caso queda **pendiente**, nunca como `0` estimado.
- **No se crean tareas programadas ni se consultan costes periódicamente.** Los importes pendientes se recuperan exclusivamente al pulsar «Consultar costes pendientes en Vercel» en **Ventas → Asistente IA → Consumo por modelo**.
- Cada pulsación consulta hasta 12 generaciones pendientes mediante `GET /v1/generation?id=...`, con un timeout de 5 s por consulta. Tras 36 consultas fallidas de una generación, se indica **No disponible**. No hacen falta paquetes Python nuevos.
- En la lista de consumo se muestran el proveedor, identificador de generación, estado y coste confirmado; los registros nuevos quedan pendientes hasta la consulta manual, salvo que Vercel indique el coste en la respuesta inicial.
- La conversación muestra la suma **confirmada** cuando todas sus llamadas asociadas tienen precio. Si falta alguna muestra Pendiente o No disponible, sin simular total final de 0.
- No se recontabilizan costes anteriores cuyos ID de generación no se guardaron en versiones anteriores.
- Si utilizas BYOK, la contabilidad del proveedor externo puede ser diferente de los créditos de Vercel.

## Validaciones pendientes
Las pruebas locales usan respuestas HTTP simuladas; la consulta real requiere la API key y una generación en tu cuenta Vercel. El coste de las transcripciones MP3 todavía no se integra en Consumo por modelo; esta entrega contabiliza las llamadas de texto/visión a Chat Completions. No se exponen claves a la interfaz ni a registros.
