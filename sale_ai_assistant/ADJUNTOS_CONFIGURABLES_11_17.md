# Versión 18.0.0.11.17 — Límites de adjuntos configurables por compañía

En **Ventas → Asistente IA → Conexión Vercel IA → Adjuntos — límites configurables por compañía** puedes establecer los límites sin editar ningún archivo fuente:

| Parámetro | Valor inicial al actualizar | Unidad |
|---|---:|---|
| Archivos máximos por mensaje | 5 | archivos |
| Total de adjuntos por mensaje | 30 | MiB |
| Máximo por imagen | 10 | MiB |
| Máximo por PDF | 5 | MiB |
| Máximo por TXT | 5 | MiB |
| Máximo por MP3 | 25 | MiB |
| Páginas máximas por PDF | 10 | páginas |
| Resolución máxima de la imagen original | 25 | megapíxeles |
| Lado máximo de imagen enviada a IA | 1800 | píxeles |
| Lado máximo de una vista de página PDF | 1600 | píxeles |
| Caracteres máximos extraídos por archivo | 50000 | caracteres |
| Tamaño máximo de respuesta HTTP de transcripción | 1024 | KiB |

**Todas estas casillas admiten `0` para no imponer ese límite desde el módulo.** La configuración se guarda en `ir.config_parameter` con separación por compañía; los valores preexistentes se conservan y los no definidos utilizan los valores iniciales indicados. Los números son valores iniciales editables, no máximos inamovibles. Los valores positivos se verifican antes de llamar a la API del proveedor; en el navegador se precargan desde Odoo y se vuelven a verificar siempre en servidor. Las validaciones de carácter, formato y autenticación se mantienen.

## Restricciones externas y errores

Un `0` no garantiza que un archivo se procese: los límites de los RPC de Odoo, del proxy inverso, de los decodificadores Pillow/PyMuPDF, del proveedor Vercel y del modelo elegido no son controlables por estos parámetros. La transferencia JSON/base64 incrementa el tamaño de la petición alrededor del 33 %, además de los metadatos.

- Si el módulo rechaza un adjunto, indica el límite configurado y que puedes modificarlo desde «Conexión Vercel IA».
- Si Vercel rechaza un MP3 por tamaño, la respuesta menciona **HTTP 413**, la procedencia y que puedes probar otro tamaño o modelo.
- Si el modelo rechaza un formato o parámetros, la respuesta menciona HTTP 400/404/415/422 y sugiere verificar compatibilidad; los demás errores de conectividad, cuotas y saldo mantienen su manejo previo.
- Si Odoo o el proxy rechazan el cuerpo de petición **antes de que llegue al módulo**, no podremos convertirlo en un mensaje del asistente ni superar ese límite mediante su configuración.

Los audios MP3 siguen usando el modelo de transcripción elegido por compañía y la API key de Vercel; no se instala FFmpeg ni Whisper en Odoo. Los MP4 deben convertirse externamente a MP3. PDF sigue requiriendo PyMuPDF. El modelo de descripción debe admitir imágenes para analizar imágenes y vistas de páginas PDF.

La transcripción de audio sigue siendo **síncrona** y depende de los tiempos máximos del servicio Odoo; subir un límite no aumenta por sí mismo esos tiempos. Los parámetros sin límite son adecuados únicamente cuando el administrador acepta el mayor consumo de RAM, latencia y créditos.

Actualización: sustituir la carpeta, reiniciar Odoo, actualizar el módulo desde Aplicaciones y recargar recursos del navegador. No desinstalar el módulo.

Verificación aislada: `python checks/verify_audio_11_16.py`, `python checks/verify_files.py`; no sustituye una prueba integrada con Odoo, proxy y Vercel.
