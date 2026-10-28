# Adjuntos 18.0.0.11.13

Selecciona hasta tres archivos (5 MB cada uno), escribe qué necesitas y envía.
Formatos: TXT UTF-8, PNG/JPG/WebP y PDF sin contraseña de hasta diez páginas.
No incluye vídeo ni audio. Cada TXT/PDF admite hasta 50.000 caracteres extraídos.

Para PDF instala PyMuPDF en el mismo entorno Python que ejecuta Odoo:
`python -m pip install PyMuPDF`
La lectura de imágenes utiliza Pillow, normalmente disponible en Odoo.

Los documentos visuales se interpretan con el modelo de Redacción técnica del
perfil, o con el modelo individual seleccionado. Activa Admite imágenes si el
proveedor soporta visión; DeepSeek V4.1 Flash se reconoce por su identificador.
No se usa el modelo alternativo para interpretar archivos automáticamente.
Los PDF se procesan mediante texto y páginas renderizadas para conservar gráficos.
Se reducen imágenes a 1800 px y páginas a aproximadamente 1600 px; el detalle pequeño
puede perder legibilidad. Si la lectura sale truncada se pide reducir el documento.

Los originales se guardan como adjuntos privados de la sesión; su contenido
extraído se incorpora al mensaje del usuario. No hay descarga de originales desde
el nuevo control de chat. Las lecturas se conservan en el historial y siguen el
modo de contexto configurado (el modo acotado puede excluir mensajes antiguos).
La IA usa esa lectura textual en turnos posteriores, no reexamina automáticamente
los originales. La lectura visual añade llamadas, latencia y coste; figura en
Consumo por modelo. No equivale a la revisión automática de descripciones retirada.

La preparación es síncrona. Tres PDF grandes pueden superar límites del servidor;
para empezar, prueba un documento corto por envío. Si la preparación falla antes
de crear el mensaje, la operación se revierte y se pueden reenviar los archivos.
Una llamada externa que ya se haya realizado puede haber sido facturada aunque
la transacción se revierta. No se promete OCR exacto: revisar medidas/referencias.

Actualizar módulo, reiniciar Odoo y recargar navegador tras instalar dependencias.
Comprobadas sintaxis Python/XML/JS y pruebas aisladas de TXT y rechazos. No hay
instancia Odoo/Vercel aquí: pendientes pruebas reales de carga, permisos, imagen,
PDF, consumo y continuidad de conversación. No declarar producción validada.
