# Corrección 18.0.0.11.21 — OwlError `Service router is not available`

La versión 11.20 llamaba a `useService("router")` en `SaleAIChat.setup()`.
En algunas instalaciones del cliente web de Odoo 18, ese servicio no está registrado en el entorno de los componentes principales y provoca un OwlError al iniciar el chat (la pantalla puede quedar bloqueada y el mensaje desaparecer al refrescar).

Esta versión:

- Elimina la dependencia del servicio `router`.
- Identifica el registro abierto usando `this.action.currentController`, API expuesta por el servicio `action` de Odoo 18. Comprueba `ir.actions.act_window`, modelo `sale.order`, vista `form` e ID válido.
- Da preferencia a `currentState.resId` (registro actual cuando se navega dentro del formulario) sobre `props.resId`.
- Escucha además `ACTION_MANAGER:UI-UPDATED` para detectar el formulario cuando Odoo termina de montarlo tras cambiar de pantalla.
- Continúa comprobando `state = 'draft'` en el servidor antes de mostrar el botón; las comprobaciones de permisos y estado del servidor de la versión 11.20 siguen vigentes.

## Instalación

1. Sustituye la carpeta `sale_ai_assistant` por la nueva versión en el addons_path.
2. Reinicia Odoo y actualiza el módulo desde Aplicaciones (o con `-u sale_ai_assistant`).
3. Realiza una recarga completa en el navegador, preferentemente con `?debug=assets` si hay activos en caché.
4. Comprueba que abre el panel del asistente y luego el formulario de un presupuesto en borrador: debe mostrarse el icono de cargar PV, que no debería estar presente en vista de lista ni en otro modelo.

## Validación

`node checks/verify_router_11_21.cjs` comprueba que no se usa `useService("router")` y ejecuta `getCurrentPVId` del archivo real en varios escenarios simulados.

No se ha ejecutado una prueba contra el navegador/Odoo real del usuario.
