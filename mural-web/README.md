# Mural Web — Fase 13 · Producción

Estado actual: circuito completo de conversación por voz con **Azure Speech STT + Pronunciation Assessment → GPT-6 Luna (Vercel AI Gateway) → Google Chirp 3 HD TTS**, persistencia local, memoria pedagógica, progreso agregado, PWA y una interfaz monocromática rediseñada para Fase 12.5. Mural conserva una sola conversación activa y sustituye el historial al cambiar de tema, mientras aprendizaje, pronunciación y actividad se resumen de forma acotada.

## Fases completadas

### Fases 1–3 — Base, Core y conversación de texto
- Node 24 + Docker, React/Vite/TypeScript/Tailwind.
- `LanguageModule`, PromptBuilder, Español → Inglés y 26 temas.
- `/api/chat` con Responses API, historial multi-turno y claves solo en backend.

### Fase 4 — Providers + control de uso
- LLM desacoplado mediante provider.
- Vercel AI Gateway + `openai/gpt-6-luna` por defecto.
- `UsageManager` persistente en `data/usage.json`.
- Límites locales para Azure/Google con margen de seguridad.
- Ajustes automáticos/manuales y panel de consumo.

### Fase 5 — Azure Speech STT
- Micrófono en navegador y reconocimiento continuo.
- Transcripciones parciales/finales.
- Token STS temporal: la key de Azure nunca llega al navegador.
- Contabilización de sesión, límite máximo y fallback a texto.

### Fase 6 — Azure STT → GPT-6 Luna
- Voz y teclado usan el mismo `/api/chat`.
- Envío de voz manual o automático.
- Protección contra doble envío y conservación del último parcial.

### Fase 7 — Google Chirp 3 HD
- Endpoint backend `POST /api/tts/synthesize`.
- Autenticación OAuth de Google usando la service account configurada en `GOOGLE_APPLICATION_CREDENTIALS`.
- La clave privada de Google nunca se entrega al navegador.
- Voz por defecto: `en-US-Chirp3-HD-Charon`, configurable desde `.env`.
- El backend verifica la cuota local **antes** de sintetizar y contabiliza caracteres solo después de una síntesis correcta.
- Audio MP3 reproducido en navegador.
- El audio generado se conserva en memoria durante la conversación: `Repetir audio` no realiza otra llamada a Google y no vuelve a consumir caracteres.

### Fase 8 — Persistencia local
- IndexedDB nativo, sin añadir dependencias de persistencia al frontend.
- Se restaura al abrir la aplicación el tema activo, los mensajes y los ajustes de voz.
- Existe **una única conversación activa**: no se crea un historial infinito de sesiones.
- `Nueva conversación` elimina los mensajes actuales y empieza de cero manteniendo el tema.
- Cambiar a un tema distinto elimina la conversación anterior y crea inmediatamente una nueva para el nuevo tema.
- El audio de Chirp no se persiste; al recargar, los mensajes anteriores se muestran como texto.
- Los stores `vocabulary` y `learningEvidence` se utilizan desde Fase 9 para memoria pedagógica agregada; la Fase 8 ya dejó preparada su estructura.
- Los ajustes de voz siguen espejados en `localStorage` por compatibilidad y pasan también a IndexedDB.

### Fase 9 — Motor pedagógico inicial
- Nuevo endpoint `POST /api/learning/analyze`: después de un turno útil, GPT-6 Luna extrae señales pedagógicas compactas sin bloquear la respuesta ni el TTS.
- Las respuestas de una sola palabra se omiten del análisis para evitar consumo innecesario.
- IndexedDB usa los stores `vocabulary` y `learningEvidence` para guardar **estado agregado**, no conversaciones antiguas.
- Vocabulario: usos correctos, dificultades, introducciones, significado breve y última aparición.
- Evidencias: gramática, vocabulario, uso y ortografía con contadores y un máximo de 3 ejemplos recientes por concepto.
- Límites locales: máximo 80 elementos de vocabulario y 60 puntos de aprendizaje por idioma.
- El `PromptBuilder` recibe solo un resumen de los puntos prioritarios (máx. ~3.500 caracteres), nunca el historial completo eliminado.
- Cambiar de tema sigue borrando la conversación anterior; la memoria pedagógica compacta permanece para adaptar el nuevo tema.
- Desde Ajustes se puede borrar explícitamente la memoria pedagógica sin borrar la conversación activa.
- Los tokens del análisis pedagógico se contabilizan dentro del consumo estimado de GPT-6 Luna.

### Fase 10 — Pronunciación Azure
- Azure Pronunciation Assessment se aplica opcionalmente a la **misma sesión de micrófono** que ya utiliza STT; no se crea una segunda subida del audio.
- Modo por defecto: `Básica (Accuracy + Fluency)`. Puede desactivarse desde Ajustes.
- Evaluación no guiada: referencia vacía, escala 0–100 y granularidad de fonema.
- Se usa IPA para mostrar fonemas problemáticos de forma útil para aprendizaje.
- No se activa Prosody Assessment: queda fuera para evitar el add-on adicional de Azure.
- Al terminar de hablar se muestra un resumen del último turno: puntuación global, precisión, fluidez y palabras marcadas como débiles.
- Para palabras, Mural usa el criterio de Azure de `Mispronunciation` / AccuracyScore inferior a 60 como señal de dificultad.
- IndexedDB sube a versión 2 y añade el store `pronunciation`. Se conserva solo memoria agregada: medias, último resultado y hasta 60 palabras débiles; nunca se guarda audio.
- La memoria de pronunciación permanece al cambiar de tema, igual que la memoria pedagógica, mientras la conversación activa se elimina.
- Las palabras con dificultades repetidas se incorporan de forma compacta al contexto del profesor para que Luna pueda reciclarlas naturalmente en futuros turnos.
- Desde Ajustes se puede borrar la memoria de pronunciación de forma independiente.
- La protección de cuota sigue siendo la de Azure STT: la evaluación comparte la sesión de voz existente y Mural no añade un segundo contador de audio.


### Fase 11 — Progreso y estadísticas
- IndexedDB sube a versión 3 y añade `progressDaily`.
- La actividad no guarda conversaciones: conserva como máximo **120 días de agregados diarios**.
- Por día se registran turnos completados, origen voz/teclado, palabras del usuario, palabras de Luna, sesiones iniciadas y temas practicados.
- Nueva vista `Progreso` con actividad de 7 días, días activos, racha, vocabulario consolidado/en repaso, gramática/uso, pronunciación y prioridades de repaso.
- No existe un porcentaje global de “nivel”: se muestran únicamente métricas respaldadas por evidencia almacenada.
- Borrar actividad elimina solo agregados diarios; no borra memoria pedagógica, pronunciación ni conversación activa.

### Fase 12 — UX responsive + PWA
- Navegación principal `Conversación / Progreso / Ajustes`.
- Selector rápido de tema visible en conversación. Cambiar a otro tema sigue eliminando inmediatamente la conversación activa y conserva la memoria pedagógica agregada.
- Composer móvil mejorado, `textarea`, Enter para enviar y Shift+Enter para salto de línea.
- Autoscroll al último mensaje, estados de orb en español, mejoras de accesibilidad y soporte para `prefers-reduced-motion`.
- Indicador offline: los datos locales siguen consultables, pero Azure/Luna/Chirp quedan deshabilitados sin Internet.
- PWA con `manifest.webmanifest`, iconos 192/512 y service worker que cachea únicamente el app shell/recursos locales; `/api` nunca se cachea.
- Botón de instalación cuando el navegador expone `beforeinstallprompt`; en iOS se muestran instrucciones para “Añadir a pantalla de inicio”.
- El service worker se registra solo en build de producción/preview para no interferir con Vite/HMR durante desarrollo.
- El TTS permanece deliberadamente **sin streaming**: Luna completa todo el texto y Chirp recibe una única petición por respuesta.


### Fase 12.5 — Rediseño visual premium
- Nuevo lenguaje visual monocromático inspirado en interfaces nativas: menos ruido, más espacio, superficies suaves y controles redondeados.
- Apariencia `Automático / Claro / Oscuro`, persistida en IndexedDB. Automático sigue el esquema del sistema y actualiza también el `theme-color` del navegador.
- Navegación inferior `Talk / Themes / Words / Progress`, con Ajustes accesible desde la cabecera.
- `Themes` abre una hoja inferior dedicada; seleccionar otro tema mantiene la regla existente: conversación activa eliminada, aprendizaje agregado conservado.
- Nueva vista `Words` reutilizando la memoria pedagógica existente, sin crear otra base de datos ni historial.
- Orb reconstruido con una malla de cuadrados y animaciones orgánicas distintas para reposo, escucha, pensamiento y habla.
- Micrófono central y composer secundario: la voz vuelve a ser la acción principal sin eliminar la entrada por teclado.
- Paneles de progreso, palabras y ajustes adaptados al mismo sistema visual tanto en móvil como escritorio.
- Se mantiene `prefers-reduced-motion` y toda la lógica de Azure/Luna/Chirp permanece intacta.

## Modos de respuesta

En `Ajustes → Comportamiento de voz`:

### Listening
```text
Luna → texto oculto → Chirp → audio
```

- La respuesta del profesor queda oculta.
- `Mostrar texto` permite comprobar posteriormente lo entendido.
- `Escuchar`/`Repetir audio` reutiliza el MP3 ya generado.
- Si Chirp falla o no queda cuota, Mural revela el texto automáticamente.

### Reading
```text
Luna → texto
```

- No llama a Google Chirp.
- Por tanto no consume caracteres TTS.

### Mixto
```text
Luna → texto visible + Chirp → audio
```

### Automático
- Mientras Chirp esté configurado y quede cuota local: se comporta como **Listening**.
- Si Google no está disponible o se alcanza el límite: cambia esa respuesta a **Reading**.
- El cambio no afecta a Luna ni al resto de la conversación.

La opción `Salida → Sin audio` fuerza Reading funcional aunque el modo de respuesta estuviese en Listening/Automático.

## Decisión de TTS: sin streaming

Mural espera siempre la respuesta completa de Luna antes de llamar a Google Chirp. No se segmenta por frases ni se genera audio progresivamente.

```text
Luna → texto completo → una petición a Chirp → audio completo → reproducción
```

Esta decisión prioriza simplicidad, estabilidad y control de consumo sobre latencia mínima.

## Configuración

Ejemplo mínimo de `.env`:

```env
# LLM
LLM_PROVIDER=vercel
AI_GATEWAY_API_KEY=vck_...
LLM_BASE_URL=https://ai-gateway.vercel.sh/v1
LLM_MODEL=openai/gpt-6-luna
LLM_REASONING_EFFORT=none

# STT
AZURE_SPEECH_KEY=...
AZURE_SPEECH_FALLBACK_KEY=... # opcional
AZURE_SPEECH_REGION=francecentral
AZURE_STT_FREE_SECONDS=18000
AZURE_STT_MAX_SESSION_SECONDS=300

# TTS
GOOGLE_CLOUD_PROJECT=mural-...
GOOGLE_APPLICATION_CREDENTIALS=/app/mural-chirp.json
GOOGLE_TTS_FREE_CHARACTERS=1000000
GOOGLE_TTS_LANGUAGE=en-US
GOOGLE_TTS_VOICE=en-US-Chirp3-HD-Charon

# Protección local
USAGE_SAFETY_PERCENT=98
USAGE_DATA_FILE=/app/data/usage.json
```

El proyecto espera `mural-chirp.json` en la raíz durante desarrollo si usas la ruta `/app/mural-chirp.json`. Está excluido de Git y Vite bloquea su acceso desde navegador.

Antes de usar Chirp, el proyecto de Google debe tener habilitada Cloud Text-to-Speech y la service account debe disponer de permisos para utilizarla.

## Arranque

```bash
docker compose up --build
```

Después abre:

```text
http://localhost:5173
```

En otro dispositivo de la red local, el navegador puede exigir HTTPS para acceder al micrófono.

## Flujo completo

```text
🎙 Micrófono
     ↓
Azure Speech STT
     ↓
texto
     ↓
GPT-6 Luna
     ↓
texto
     ├──────────────→ Reading
     │
     ↓
Google Chirp 3 HD
     ↓
MP3
     ↓
🔊 Listening / Mixto
```

## Endpoints

```text
GET  /api/health
GET  /api/usage
POST /api/chat
POST /api/learning/analyze
POST /api/stt/session/start
POST /api/stt/session/finish
POST /api/tts/synthesize
```

## Protección de cuota

El `UsageManager` aplica `USAGE_SAFETY_PERCENT` tanto a Azure como a Google. Con la configuración de ejemplo:

```text
Azure STT configurado       18.000 s
Google TTS configurado     1.000.000 caracteres
Margen local                       98 %
```

Los valores son límites locales de protección configurables; el panel de Mural no sustituye los contadores oficiales de los proveedores.

Si una respuesta no cabe en los caracteres restantes, el backend devuelve bloqueo TTS y Mural muestra el texto sin audio. Los modos manuales tampoco pueden saltarse el límite.

## Seguridad

- `.env` no se sirve al navegador.
- `mural-chirp.json`, `*-service-account.json` y `*-credentials.json` están ignorados por Git y bloqueados por Vite.
- Las claves de Vercel, Azure y Google viven exclusivamente en backend.
- Azure entrega al frontend solo tokens STS temporales.
- Google se autentica desde backend; el navegador recibe únicamente el MP3 sintetizado.

## Probar la PWA localmente

`docker compose up --build` sigue usando Vite en modo desarrollo y, por seguridad, no registra service worker. Para comprobar instalación/cache PWA usa un build:

```bash
npm run build
VITE_API_PROXY_TARGET=http://localhost:3001 npm run preview
```

Con el backend ejecutándose aparte, abre `http://localhost:4173`. En producción la PWA se activará automáticamente bajo HTTPS.

## Siguiente fase

**Fase 13 — Producción**: imagen Docker final, frontend estático, proxy/HTTPS, persistencia de `usage.json`, backups y despliegue estable en Ubuntu.


## Fase 13 — Producción

- Docker multi-stage: Vite se compila en `builder` y no forma parte del runtime.
- Un único proceso Node sirve frontend compilado y `/api` desde el mismo origen.
- `docker-compose.yml` es ahora la configuración de producción; `docker-compose.dev.yml` conserva el flujo de desarrollo.
- El runtime usa usuario no-root, root filesystem de solo lectura, `cap_drop: ALL` y `no-new-privileges`.
- `usage.json` vive en un volumen Docker persistente.
- `mural-chirp.json` entra mediante Docker Compose `secrets` y nunca se copia a la imagen.
- Healthcheck, apagado limpio, cabeceras HTTP de seguridad y política de caché para assets/PWA.
- `.env.example` contiene únicamente placeholders y valores no secretos.
- Guía de despliegue en `PRODUCTION.md`.

Arranque esperado en Ubuntu:

```bash
cp .env.example .env
# completar .env y colocar mural-chirp.json
docker compose up -d --build
```
