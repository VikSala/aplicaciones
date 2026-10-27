# Iteración multimodelo — 18.0.0.11.0

Actualización directa del `sale_ai_assistant` aportado por el usuario (10.1); no desinstalar.

## Configuración

1. En Ventas > Asistente IA > Modelos IA comprueba que los modelos individuales
   existen y tienen los identificadores exactos de Vercel, tarifas y capacidades correctos.
2. Crea uno nuevo con **Tipo = Perfil multimodelo**. No necesita identificador propio.
3. Configura las seis funciones usando solo modelos individuales activos.
   Ejemplo: GLM para redacción y síntesis de precios; DeepSeek para operaciones,
   propuesta comercial, revisión y fallback.
4. Selecciona el estilo **Breve / Equilibrado / Detallado**.
5. Marca **Modelo por defecto** para tu compañía o selecciónalo en el chat.
6. En Ventas > Asistente IA > Consumo por modelo puedes revisar cada llamada,
   etapa, tokens y costes estimados; nunca se guardan prompts ni respuestas de herramientas.

## Comportamiento

- El modelo asignado a **operaciones** planifica el turno y llama herramientas
  de Odoo. Solo el backend ejecuta las escrituras y valida permisos.
- Para una nota técnica, el modelo de **redacción** prepara texto sin herramientas;
  el modelo de operaciones verifica y guarda la nota en el borrador.
- Para valoraciones de mercado, el modelo de operaciones consulta las fuentes
  y el modelo de **síntesis de búsquedas** redacta la respuesta basada en resultados.
- El modelo **comercial** sirve para la recomendación final y el de **revisión**
  comprueba coherencia antes de crear el presupuesto.
- Si una llamada falla, se puede recurrir al fallback sin reiniciar operaciones
  ya ejecutadas. Si una respuesta HTTP omite herramientas imprescindibles,
  se reintenta únicamente esa llamada con el modelo de respaldo.
- Los límites de tokens, herramientas y tiempo siguen siendo los configurados
  en Conexión Vercel IA y los soportados por cada proveedor.

## Compatibilidad / límites

- Los modelos individuales y sesiones anteriores permanecen disponibles.
- Los perfiles comparten el contexto de la conversación, no crean chats secundarios.
- Los importes de mercado siguen siendo orientativos, no cotizaciones.
- El coste del perfil es la suma por llamada de los modelos reales; si las tarifas
  de los modelos individuales están vacías, el coste calculado NO es fiable.
- La prueba dentro de un servidor Odoo 18 y las llamadas reales a Vercel deben
  validarse en la instancia del usuario antes de producción.
