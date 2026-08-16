# Odoo AI Chat Citas — Fase 7 final

Módulo autónomo para Odoo 18 construido a partir de la plantilla `odoo_ai_chat_base`.
`odoo_ai_chat_base` no es una dependencia del addon.

## Incluido hasta Fase 7

- Widget Web y configuración visual.
- Servicios reservables y relación servicio -> departamentos -> empleados activos.
- Sesiones persistentes Web/WhatsApp.
- Motor de disponibilidad basado en jornada efectiva, ausencias, fecha/hora actual,
  asistencias ocupadas, duración, granularidad y preferencias.
- Máquina de estados Python-first y parser contextual/incremental.
- Integración Web mediante `sessionId` persistente y reanudación tras recarga.
- Integración con Open WhatsApp Connector mediante `discuss.channel`, sin duplicar histórico.
- Revalidación y creación real de `hr.attendance` al confirmar una cita.
- Protección por empleado frente a confirmaciones simultáneas del chatbot.
- Fallback n8n/IA solo cuando Python devuelve `fallback=True`.
- Prompt controlado por Odoo para impedir que la IA invente funcionamiento del negocio.

## Filosofía definitiva

1. Python/Odoo intenta interpretar siempre primero.
2. Si Python entiende el mensaje, n8n no interviene.
3. Si Python no lo entiende, Odoo construye un prompt contextual para n8n.
4. La IA conversa y reconduce, pero no ejecuta la reserva.
5. El siguiente mensaje vuelve a pasar primero por Python.
6. Si n8n falla, se usa la aclaración determinista de Python.

## Prompt controlado de Fase 7.4

El webhook ya no recibe el texto crudo del usuario como `message` principal.

Ahora:

- `message`: prompt completo construido por Odoo;
- `prompt`: el mismo prompt, por compatibilidad con workflows que prefieran ese nombre;
- `userMessage`: frase original escrita por el usuario;
- `odooContext`: estado estructurado y datos de diagnóstico.

Esto permite que un workflow n8n existente que ya use `{{$json.body.message}}` empiece a recibir
el prompt seguro sin tener que cambiar el nodo que alimenta al agente.

El prompt cambia según el estado actual de la reserva:

- `waiting_service`: obtener un servicio realmente configurado;
- `waiting_booking_mode`: elegir profesional o primera disponibilidad;
- `waiting_employee`: obtener un profesional compatible real;
- `waiting_time_preference`: obtener una fecha/hora suficientemente concreta;
- `slot_proposed`: aclarar si acepta, rechaza o quiere cambiar la propuesta;
- `waiting_customer_name`: obtener nombre y apellidos.

La IA recibe además los datos que Odoo conoce realmente y reglas explícitas para no inventar:

- disponibilidad;
- horarios;
- profesionales;
- servicios;
- precios;
- tratamientos;
- teléfonos o direcciones;
- páginas/secciones de la web;
- formas de contacto;
- operaciones ejecutadas.

La respuesta de la IA **no está atada a una frase fija ni a una plantilla fija**. El prompt le pide
redactar de forma natural y breve según la situación. Tampoco se exige JSON: el módulo acepta texto
plano y sigue entendiendo respuestas habituales de n8n como `output`, `reply`, `response`, `answer`,
`text`, `message`, `content`, etc.

Ejemplo de fallback en `waiting_time_preference`:

Usuario:

`Normalmente después de recoger a los niños, aunque esta semana voy un poco justo`

La IA recibe un prompt que le indica que falta una preferencia horaria objetiva y que no puede
inventarla. Una respuesta válida y natural podría ser:

`Entiendo. ¿A partir de qué hora aproximadamente sueles poder después de recoger a los niños?`

Después, si el usuario responde `a partir de las 17`, Python vuelve a tomar el control y consulta el
motor de disponibilidad.

## Contrato resumido Odoo -> n8n

```json
{
  "message": "<PROMPT CONTROLADO GENERADO POR ODOO>",
  "prompt": "<PROMPT CONTROLADO GENERADO POR ODOO>",
  "userMessage": "Normalmente después de recoger a los niños...",
  "sessionId": "web-...",
  "channel": "web",
  "mode": "conversational_fallback",
  "odooContext": {
    "appointmentSession": {
      "state": "waiting_time_preference",
      "service": "Fisioterapia",
      "bookingMode": "first_available"
    },
    "currentObjective": {},
    "pythonParser": {
      "handled": false,
      "fallback": true
    }
  }
}
```

En WhatsApp el prompt incorpora además hasta 12 mensajes recientes recuperados directamente de
`discuss.channel` / `mail.message`.

## Configuración

La URL del webhook se configura en **Ajustes -> AI Chat Citas**.

También puede definirse mediante:

- `ODOO_AI_CHAT_APPOINTMENTS_WEBHOOK_URL`
- fallback compatible: `ODOO_AI_CHAT_WEBHOOK_URL`

Una URL HTTP(S) válida habilita el fallback. Sin URL, el chatbot continúa funcionando solo con Python.

## Seguridad funcional de la IA

Aunque n8n devolviese campos extra como `action`, `state`, `employee`, `slot` o similares, este módulo
solo extrae texto visible. La lógica de reserva continúa siendo responsabilidad de Python/Odoo.

## Prueba recomendada

1. Flujo conocido por Python: `Quiero fisioterapia con Pablo el lunes a las 16`.
   n8n no debe ejecutarse.
2. En preferencia horaria: `Normalmente después de recoger a los niños, aunque esta semana voy un poco justo`.
   Debe ejecutarse n8n con el prompt controlado.
3. La respuesta IA debe pedir una aclaración realista y no inventar secciones web, teléfonos,
   disponibilidad ni acciones.
4. Responder `a partir de las 17`.
   Python debe retomar el flujo y buscar disponibilidad.
5. Detener n8n y repetir un mensaje ambiguo.
   Debe mostrarse la aclaración Python y el chatbot debe seguir operativo.

## Pendiente para Fase 8

- casos límite y cambios de intención más complejos;
- expiración/recuperación avanzada de sesiones;
- cancelación/modificación de citas ya confirmadas;
- telemetría y logs avanzados;
- robustez de integraciones externas;
- validación end-to-end de WhatsApp con número real.
