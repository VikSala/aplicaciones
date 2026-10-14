# Mural Web — Producción

La Fase 13 deja Mural Web preparado para ejecutarse como **un único servicio Docker**: el backend Node sirve `/api` y también el frontend ya compilado por Vite.

## 1. Preparar configuración

```bash
cp .env.example .env
```

Edita `.env` y rellena las credenciales de Vercel AI Gateway, Azure Speech y Google Cloud.

Coloca el JSON de la service account de Google junto al `docker-compose.yml` con el nombre `mural-chirp.json` (o cambia `GOOGLE_CREDENTIALS_FILE` en `.env`). Ese fichero se monta como secreto de Docker Compose y no se copia dentro de la imagen.

Recomendación de permisos en Ubuntu:

```bash
chmod 600 .env mural-chirp.json
```

## 2. Arrancar

```bash
docker compose up -d --build
```

Comprobar estado:

```bash
docker compose ps
curl http://127.0.0.1:3001/api/health
```

Logs:

```bash
docker compose logs -f mural
```

Actualizar una versión posterior:

```bash
docker compose up -d --build
```

El volumen `mural_usage` conserva `usage.json` aunque se sustituya el contenedor.

## 3. Reverse proxy y HTTPS

Por defecto Mural publica el puerto solo en `127.0.0.1:3001`. Es adecuado si Nginx/Apache está instalado directamente en el host.

Para Nginx Proxy Manager en Docker hay dos opciones:

1. Conectar su contenedor a la red `mural-web-network` y usar como destino `mural:3001`.
2. Cambiar `MURAL_BIND_IP=0.0.0.0` y apuntar NPM a la IP del host y puerto `3001`. En ese caso limita el acceso al puerto mediante firewall y deja el acceso público únicamente por HTTPS.

El micrófono y la instalación PWA deben publicarse mediante HTTPS cuando no se usa `localhost`.

Mural no incluye cuentas de usuario. Si el dominio va a ser accesible desde Internet, protégelo con una **Access List** del reverse proxy, VPN o equivalente. De lo contrario otra persona que conozca la URL podría utilizar tus cuotas de IA/voz.

## 4. Persistencia y copias

### Servidor

Solo es persistente en Docker el control de uso (`usage.json`). Para respaldarlo:

```bash
docker run --rm \
  -v mural-web_mural_usage:/data:ro \
  -v "$PWD":/backup \
  alpine sh -c 'tar czf /backup/mural-usage-backup.tgz -C /data .'
```

### Navegador

Conversación activa, vocabulario, memoria pedagógica, pronunciación y progreso viven en IndexedDB en cada navegador/dispositivo. No están en el volumen Docker y no se sincronizan entre dispositivos.

## 5. Desarrollo local

La configuración de desarrollo se conserva separada:

```bash
docker compose -f docker-compose.dev.yml up --build
```

Frontend: `http://localhost:5173`

## 6. Seguridad incluida

- build Docker multi-stage;
- Vite y dependencias de desarrollo no están en la imagen runtime;
- root filesystem del contenedor de solo lectura;
- proceso ejecutado como usuario `node`, no como root;
- capacidades Linux eliminadas y `no-new-privileges`;
- service account de Google montada como secret;
- `.env` y credenciales excluidos por `.dockerignore`;
- volumen independiente para `usage.json`;
- healthcheck del contenedor;
- cierre limpio con SIGTERM/SIGINT;
- cabeceras HTTP de seguridad y caché diferenciada para assets/PWA;
- `/api` y frontend comparten origen, sin CORS abierto.

## Actualizar una instalación existente

Para esta versión de interfaz se ha cambiado la etiqueta de imagen y la versión del service worker para evitar que el navegador o Docker sigan sirviendo una compilación anterior.

Desde la carpeta del proyecto:

```bash
docker compose down
docker compose build --no-cache mural
docker compose up -d --force-recreate
```

Después abre Mural de nuevo. El nuevo service worker invalida las cachés anteriores y fuerza una recarga única de las ventanas abiertas al activarse.

Si Mural estaba instalada como PWA y el launcher del móvil conserva únicamente el icono antiguo, desinstala y vuelve a instalar la PWA una vez. El código y la interfaz no requieren borrar IndexedDB, por lo que no es necesario eliminar los datos del sitio para actualizar la aplicación.
