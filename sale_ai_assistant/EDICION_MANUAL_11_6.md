# 18.0.0.11.6 — Edición directa de propuestas

La tarjeta de propuesta permite editar el texto en un área multilínea.
- Guardar edición conserva la propuesta modificada sin alterar la vista previa ni llamar a IA.
- Añadir / Sustituir guarda directamente el texto editado en el borrador.
- Mejorar texto guarda primero la edición y prepara la petición para IA. La petición solo se envía cuando el usuario la envía.
- Descartar elimina la propuesta pendiente.

Los cambios escritos deben guardarse antes de cerrar o cambiar de conversación. No hay autoguardado. Se admite texto plano (no editor visual de formato); se conservan saltos interiores y se recortan espacios de los extremos, como en las herramientas existentes.

Las ediciones persistidas se registran como mensajes del usuario. La tarjeta identifica que el texto ha sido editado manualmente; no se atribuye la versión modificada exclusivamente al modelo. Se renueva el identificador de propuesta para impedir sobrescrituras desde otra pestaña y se mantiene la huella del borrador para no aceptar una versión desactualizada. Guardar y aceptar se realizan dentro de la misma transacción cuando corresponde.

## Tiempos observados en el registro aportado
Productos: 15 y 14,9 segundos; cliente: 0,75 segundos; redacción: 50 segundos; actualización: 58 segundos; valoración inicial: 37,5 segundos; revaloración: 13,5 segundos.
La ruta de cliente es directa. Las frases naturales de alta de productos usadas en esa prueba recorren el agente. En la primera aparece además un rechazo por parámetros de precio. No se puede repartir el tiempo entre modelos, red, Odoo y búsquedas con estos datos agregados.
Ya existe una ruta explícita sin IA para productos, por ejemplo:
producto: sku TLMEF precio 1290 descripcion "TOTAL"
La versión 11.6 no modifica la interpretación de peticiones naturales ni los modelos o límites. Su mejora de rapidez es evitar llamadas IA para correcciones manuales.

## Validación e instalación
Se ejecutaron ocho pruebas aisladas previas de aceptación y comprobaciones aisladas del método real de edición: nuevo token, conservación de huella, texto exacto, no-op y entradas inválidas. Se añadieron tres pruebas Odoo de edición/aceptación sin gateway y rechazo de texto vacío; no ejecutadas por ausencia de Odoo/PostgreSQL. Sintaxis Python, XML, JavaScript e integridad del ZIP verificadas. La interfaz OWL no se ha probado en un navegador con Odoo.
Sustituir carpeta, reiniciar Odoo, actualizar módulo y recargar navegador. Probar editar, guardar, reabrir la conversación y aceptar.
