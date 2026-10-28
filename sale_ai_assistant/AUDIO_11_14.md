**DOCUMENTO HISTÓRICO (11.14): el procedimiento local ya no se usa en la versión 11.15.**

Consulta `AUDIO_11_15.md` para el flujo actual basado en MP3 y Vercel.

---

# 18.0.0.11.14 — botón + y audio de vídeos

El selector nativo desaparece. El botón + a la izquierda del campo de mensaje abre
la selección; los adjuntos seleccionados aparecen como etiquetas con botón quitar.
Permite añadir archivos en varias selecciones, hasta tres en total.

Vídeos MP4/MOV/M4V/WebM: máximo 25 MB y 120 segundos. Solo se extrae la primera
pista de audio; no se analizan fotogramas. TXT, imágenes y PDF conservan sus límites
de 5 MB. Escribe la petición antes de enviar los archivos.

La transcripción se realiza localmente con faster-whisper (CPU int8, dos hilos).
Se guarda un TXT privado vinculado a la sesión, además del original, y el texto se
incorpora al mensaje para que DeepSeek trabaje con él. El TXT no tiene todavía un
botón de descarga en el chat; está en los adjuntos de la sesión de Odoo. Incluye
marcas temporales y una indicación heurística de baja confianza. No garantiza
reconocer correctamente referencias y cantidades: revisar el texto.

## Preparación del servidor (necesaria para vídeo)

Instalar FFmpeg y ffprobe, por ejemplo en Debian/Ubuntu:

    sudo apt-get install ffmpeg

En el entorno Python de Odoo:

    python -m pip install faster-whisper

Descargar previamente el modelo multilingual small (requiere acceso a Hugging Face):

    python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', local_dir='/opt/odoo/models/whisper-small')"

Configurar en el servicio Odoo la variable de entorno:

    SALE_AI_WHISPER_MODEL=/opt/odoo/models/whisper-small

La carpeta debe ser legible por el usuario de Odoo. Durante una solicitud no se
descargan modelos ni se envía el audio a un servicio de transcripción. El texto
transcrito sí se envía al modelo del chat por Vercel como contexto de la petición.
PDF sigue requiriendo PyMuPDF como en la versión anterior.

Actualizar módulo, reiniciar servicio y recargar completamente el navegador.

## Rendimiento y límites

Procesamiento síncrono: puede tardar y ocupa un trabajador de Odoo. Los subprocesos
se limitan a 15 s de inspección, 30 s de extracción y 180 s de transcripción por
vídeo. Los límites del proxy/Odoo pueden interrumpir antes la petición; comenzar
con clips de 15–30 segundos. No se ha implementado cola de trabajos en segundo plano.
Varios vídeos se procesan consecutivamente. La transcripción local consume RAM/CPU;
no se registra como consumo de tokens de Vercel. El modelo se carga por cada vídeo.
Los temporales se eliminan al terminar o fallar el procesamiento.

## Validación

FFmpeg/ffprobe probados realmente con un MP4 de audio sintético y otro sin audio.
Verificados WAV mono, creación del TXT privado y rechazo de vídeo sin audio. La
transcripción en esta prueba se simuló: no hay pesos faster-whisper instalados aquí.
Pasaron pruebas previas de TXT/rechazos y sintaxis Python/XML/JS. Pendientes prueba
visual, reconocimiento con voz real e integración Odoo en el servidor del usuario.

Referencia de la librería: https://github.com/SYSTRAN/faster-whisper
