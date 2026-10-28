# Asistente IA 18.0.0.11.16 — Límites y modelo MP3 configurable

## Configuración de transcripción

En **Ventas → Asistente IA → Conexión Vercel IA**, bajo el apartado
**Transcripción de MP3 (Vercel AI Gateway)**, indica el slug completo del modelo
con formato `proveedor/modelo`. Ejemplos disponibles en el catálogo público
(consultar disponibilidad actual, políticas, límites y tarifas):

- `microsoft/mai-transcribe-2`
- `microsoft/mai-transcribe-1.5`
- `openai/whisper-1`
- `openai/gpt-4o-mini-transcribe`

**Guardar configuración** persiste el identificador por compañía. La API key
es la de Vercel ya utilizada para el chat. El modelo de transcripción **no**
es el modelo de conversación DeepSeek: la primera petición procesa el audio,
y luego se envía la transcripción al asistente. No se instala FFmpeg ni Whisper
local. La configuración anterior se conserva: al actualizar, si no existe un
modelo de transcripción guardado, se usa `microsoft/mai-transcribe-1.5`.

El formulario permite escribir el ID completo, sin lista cerrada: los modelos
se pueden cambiar sin actualizar Python. Se comprueba el formato del slug,
**no** si ese proveedor lo admite; incompatibilidades y límites reales se
notifican desde Vercel. `microsoft/mai-transcribe-2-streaming` es de transmisión
en tiempo real y no se debe utilizar para esta ruta síncrona de archivos.

## Restricciones de adjuntos del módulo

| Tipo | Tamaño máximo individual |
|---|---|
| MP3 | 25 MiB |
| Imagen PNG/JPG/JPEG/WebP | 10 MiB |
| Documento PDF/TXT | 5 MiB |

Máximo **cinco archivos** y **30 MiB combinados** por mensaje; tanto navegador
como servidor verifican estos límites, el servidor vuelve a validar.
Son **salvaguardas propias del módulo**, no límites certificados por Vercel:
varían según proveedor, modelo y operación. Se reciben por RPC de Odoo en
base64 (aumenta el tamaño aproximadamente un tercio). El MP3 no tiene control
local de duración. Los MP4 no se admiten: convierte primero a MP3.

Las imágenes se convierten a PNG redimensionado a como máximo 1800×1800 píxeles
para interpretación, y se rechazan originales con más de 25 megapíxeles.
Ampliar 5 a 10 MiB no cambia esta reducción; las medidas o letras pequeñas
requieren comprobación. Los PDF siguen limitados a diez páginas y 50.000
caracteres; PyMuPDF sigue siendo necesario para PDF, no para MP3.

## Actualización, seguridad y validación

Reemplazar carpeta, reiniciar Odoo, actualizar módulo en Aplicaciones y
recargar assets del navegador. No desinstalar ni borrar datos. Las claves
permanecen en servidor. Las transcripciones se adjuntan como TXT privados
al historial y el MP3 original también se guarda como adjunto privado.

Los rechazos por tamaño se realizan antes de enviar ningún archivo a Vercel:
esto evita cargos por subir varios adjuntos si uno de ellos supera el máximo.
La transcripción es **síncrona** y puede agotar el timeout de Odoo/proxy.

Pruebas locales sin Odoo y Vercel realizadas con
`python checks/verify_audio_11_16.py`. Pendiente de validar audio real y
los nuevos límites de carga en el Odoo del usuario.

Referencias públicas: https://vercel.com/ai-gateway/models/mai-transcribe-2
https://vercel.com/i/multimodal-ai
