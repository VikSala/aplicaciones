# 18.0.0.11.22 — Ajustes de navegación y botones

- Botón de cargar presupuesto (icono actualizar): margen derecho del icono de 1 px, evitando el desplazamiento del centrado generado por la regla general de accesos rápidos.
- En una conversación del historial, el pie del panel mantiene el botón «Volver a conversación» y lo conecta a la carga de la sesión activa (`returnToActive`). No depende de desplazar el scroll al principio.
- En la lista del historial, el botón inferior también recupera explícitamente la conversación activa.
- El retorno desde la vista previa móvil mantiene el comportamiento `showChat`.
- El encabezado de conversación archivada dispone el botón de retorno y el título en líneas separadas con espaciado consistente.
- El enlace inferior se presenta visualmente como un botón accesible, con estados hover, focus y disabled.
- Sin cambios en modelos Python, permisos o conectividad Vercel.
