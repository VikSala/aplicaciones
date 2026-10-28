# 18.0.0.11.15 — Transcripción de MP3 por Vercel AI Gateway

El asistente admite archivos **MP3** (audio ya extraído manualmente). El modelo de
transcripción predeterminado es `microsoft/mai-transcribe-1.5`. Se utiliza la **misma
API key por compañía de Vercel AI Gateway** ya configurada para el asistente.
DeepSeek sigue procesando los textos y creando los presupuestos; **no recibe el
MP3** sino el texto de la transcripción.

No requiere instalar FFmpeg, ffprobe, faster-whisper, Hugging Face, modelos locales,
ni un SDK Python adicional. La petición sale de Odoo por HTTPS al endpoint propio
para transcripciones de AI Gateway.

## Cómo utilizarlo

1. Convertir el MP4 a MP3 con la herramienta habitual fuera de Odoo.
2. Abrir el asistente de ventas, añadir el MP3 con el botón «+» y escribir la petición.
3. Enviar. Se transcribe el audio y el texto se incorpora al mensaje de la sesión.
   El MP3 original y un TXT privado `nombre.mp3.transcripcion.txt` se adjuntan a la
   sesión Odoo, como sucedía con la implementación anterior.

Formatos admitidos en el selector: TXT, PDF, PNG, JPG, JPEG, WebP, MP3. **Los vídeos
MP4/MOV/M4V/WebM dejan de admitirse**: el objetivo de esta iteración es evitar la
extracción local de audio. Sigue existiendo el límite de **3 adjuntos por mensaje**,
**25 MB por MP3** y **5 MB por documento/imagen**. La duración del MP3 no se mide
localmente; comenzar con audio de 15–120 segundos por latencia y control de coste.

## Configuración y privacidad

No se añade ninguna opción obligatoria: basta tener activa la clave habitual de
Vercel AI Gateway en Odoo y saldo suficiente. La comunicación usa el protocolo
nativo de transcripción de AI Gateway (`/v4/ai/transcription-model`), modelo
`microsoft/mai-transcribe-1.5`. El audio se envía a Vercel y a su proveedor de
transcripción (Microsoft); tener en cuenta sus políticas de tratamiento de datos.
El texto resultante se envía después al modelo conversacional configurado.

Esta transcripción genera consumo facturable en Vercel. El coste de la transcripción
puede consultarse en el panel de Vercel; **no se añade al registro de tokens del chat
en Odoo**, ya que el uso de audio se factura por duración.

## Instalación

Reemplazar la carpeta `sale_ai_assistant`, reiniciar Odoo, actualizar el módulo desde
Aplicaciones y recargar la página con los assets actualizados. La actualización no
requiere dependencias adicionales para los audios. La lectura de PDF sigue
requiriendo PyMuPDF, como en 11.13.

## Limitaciones y validación

El flujo sigue siendo **síncrono**: mientras Vercel transcribe, el usuario espera
la respuesta de Odoo. El tiempo máximo de espera HTTP por transcripción usa el
ajuste ya existente de «Tiempo máximo de espera por llamada», limitado entre 15 y
180 segundos. También aplican los límites del servidor y proxy. Los cambios
no se han ejecutado contra el Odoo real ni contra una API key del usuario.
Se han preparado pruebas de petición, respuesta, validación y errores con simulación
local de la API. Antes del uso real, probar con un MP3 corto.

Fuentes del protocolo:
https://github.com/vercel/ai/blob/main/packages/gateway/src/gateway-transcription-model.ts
https://vercel.com/ai-gateway/models/mai-transcribe-1.5
